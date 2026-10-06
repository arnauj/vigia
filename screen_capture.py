"""
VIGIA — Captura de pantalla multiplataforma y multisesión (X11 / Wayland / Windows).

Kubuntu 26.04+ usa Wayland como única sesión por defecto y `mss` (XGetImage)
solo ve las ventanas XWayland, no el escritorio real. Este módulo abstrae la
captura con varios backends, en orden de preferencia según la sesión:

  X11 / Windows : mss                       (rápido, ~30 fps)
  Wayland KDE   : spectacle -b -n -f -o …   (sin diálogos, ~1-3 fps)
  Wayland otros : grim / gnome-screenshot   (sin diálogos, ~1-3 fps)

Las importaciones de mss/PIL son perezosas para que los tests puedan
mockearlas antes de importar client.py.

Todos los backends aceptan `grab(max_age=segundos)` / `grab_raw(max_age=…)`:
si el último frame capturado es más reciente que `max_age` se reutiliza en
lugar de pedir otro al compositor. Así las miniaturas (1 fps) aprovechan el
frame que acaba de tirar WebRTC en vez de duplicar la captura.
"""

import itertools
import os
import sys
import shutil
import subprocess
import tempfile
import threading
import time
from desktop_session import ensure_session_env


class CaptureError(Exception):
    """No hay ningún backend de captura funcional."""


def session_type():
    """Devuelve 'windows', 'wayland', 'x11' o 'unknown'."""
    if sys.platform == 'win32':
        return 'windows'
    ensure_session_env()
    if os.environ.get('WAYLAND_DISPLAY') or \
       os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland':
        return 'wayland'
    if os.environ.get('DISPLAY'):
        return 'x11'
    return 'unknown'


def is_wayland():
    return session_type() == 'wayland'


# Fijar WAYLAND_DISPLAY/XDG_RUNTIME_DIR al importar, para que cualquier
# subprocess lanzado luego (spectacle, ydotool) herede el entorno correcto.
ensure_session_env()


# ── Backend mss (X11 / Windows) ──────────────────────────────────────────────

class MssBackend:
    name = 'mss'

    def __init__(self):
        import mss
        self._sct = mss.mss()
        self.index = 1   # 0 = espacio virtual completo, 1..n = monitores
        self._cache = None      # (data, w, h, stride) del último grab
        self._cache_idx = None
        self._cache_ts = 0.0
        # Validar que realmente puede capturar (lanza si no hay DISPLAY)
        cap = self._sct.grab(self._sct.monitors[1])
        # Guarda anti-pantalla-negra: en Wayland, mss lee el root VACÍO de
        # XWayland y devuelve un frame TODO negro sin lanzar excepción. Si el
        # frame de prueba es íntegramente negro en Linux, rechazamos este
        # backend para que create_capturer caiga a spectacle/grim (que sí ven
        # el escritorio Wayland real).
        if sys.platform.startswith('linux'):
            raw = bytes(cap.rgb)
            if raw and raw.count(0) == len(raw):
                raise CaptureError(
                    'mss devolvió un frame completamente negro '
                    '(probable XWayland en sesión Wayland)')

    def set_monitor(self, index):
        if 0 <= int(index) < len(self._sct.monitors):
            self.index = int(index)

    def monitors(self):
        """Lista de monitores disponibles (formato mss)."""
        return list(self._sct.monitors)

    def monitor(self):
        m = self._sct.monitors[self.index]
        return {'left': m.get('left', 0), 'top': m.get('top', 0),
                'width': m['width'], 'height': m['height']}

    def grab(self, max_age=0.0):
        """Devuelve una PIL.Image RGB del monitor seleccionado."""
        from PIL import Image
        data, w, h, stride = self.grab_raw(max_age=max_age)
        return Image.frombuffer('RGB', (w, h), data, 'raw', 'BGRX', stride, 1)

    def grab_raw(self, max_age=0.0):
        """Frame crudo BGRA sin PIL: (data, w, h, stride_bytes).
        Vía rápida para WebRTC (conversión/escala vía swscale).

        `max_age` reutiliza el último frame si aún es reciente: evita una
        segunda captura cuando miniaturas y WebRTC coinciden en el tiempo."""
        if max_age > 0 and self._cache is not None and \
                self._cache_idx == self.index and \
                (time.monotonic() - self._cache_ts) <= max_age:
            return self._cache
        cap = self._sct.grab(self._sct.monitors[self.index])
        w, h = cap.size
        self._cache = (cap.bgra, w, h, w * 4)
        self._cache_idx = self.index
        self._cache_ts = time.monotonic()
        return self._cache

    def close(self):
        try:
            self._sct.close()
        except Exception:
            pass


# ── Backends CLI (Wayland) ───────────────────────────────────────────────────

class CliBackend:
    """Captura vía herramienta externa que escribe un PNG a disco."""

    # nombre → plantilla de argumentos ({out} = fichero destino)
    TOOLS = {
        'spectacle':        ['spectacle', '-b', '-n', '-f', '-o', '{out}'],
        'grim':             ['grim', '{out}'],
        'gnome-screenshot': ['gnome-screenshot', '-f', '{out}'],
    }

    # Serializa las capturas CLI de TODO el proceso: dos spectacle/grim en
    # paralelo (miniaturas + WebRTC) compiten por la herramienta y producen
    # frames corruptos o negros.
    _GRAB_LOCK = threading.Lock()
    _SEQ = itertools.count()

    def __init__(self, tool):
        self.name = tool
        self.index = 0          # 0 = todas las pantallas, 1..n = un monitor
        self._mons = None       # geometrías lógicas (wayland_monitors)
        self._cmd = self.TOOLS[tool]
        self._path = shutil.which(tool)
        if not self._path:
            raise CaptureError(f'{tool} no encontrado')
        # Fichero temporal único por INSTANCIA: el cliente usa dos capturadores
        # simultáneos (miniaturas y WebRTC) y no pueden compartir el mismo PNG.
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f'vigia_cap_{os.getpid()}_{next(self._SEQ)}.png')
        self._geom = None
        self._cache = None      # última PIL.Image capturada
        self._cache_ts = 0.0
        # Captura de prueba: valida permisos/entorno en el constructor
        self.grab()

    def monitor(self):
        if self._geom is None:
            self.grab()
        return self._geom

    def monitors(self):
        """[todas, monitor 1, …] en coordenadas lógicas, como mss."""
        if self._mons is None:
            self._mons = wayland_monitors()
        mons = self._mons
        if not mons:
            return []
        x0 = min(m['left'] for m in mons); y0 = min(m['top'] for m in mons)
        x1 = max(m['left'] + m['width'] for m in mons)
        y1 = max(m['top'] + m['height'] for m in mons)
        return [{'left': x0, 'top': y0, 'width': x1 - x0, 'height': y1 - y0}] + mons

    def set_monitor(self, index):
        """La herramienta solo captura el escritorio entero: un monitor
        concreto se recorta de esa imagen (ver _recortar)."""
        self._mons = wayland_monitors()   # releer por si cambió la disposición
        index = int(index)
        self.index = index if 0 < index <= len(self._mons) else 0
        self._geom = None

    def _recortar(self, img):
        mons = self.monitors()
        if not self.index or self.index >= len(mons):
            return img
        todo, m = mons[0], mons[self.index]
        # spectacle/grim devuelven el escritorio en píxeles físicos: escalar
        # las coordenadas lógicas al tamaño real de la imagen (HiDPI).
        fx = img.width / todo['width']
        fy = img.height / todo['height']
        caja = (round((m['left'] - todo['left']) * fx),
                round((m['top'] - todo['top']) * fy),
                round((m['left'] - todo['left'] + m['width']) * fx),
                round((m['top'] - todo['top'] + m['height']) * fy))
        caja = (max(0, caja[0]), max(0, caja[1]),
                min(img.width, caja[2]), min(img.height, caja[3]))
        if caja[2] - caja[0] < 2 or caja[3] - caja[1] < 2:
            return img
        return img.crop(caja)

    def grab(self, max_age=0.0):
        img = self._grab_full(max_age)
        if self.index:
            img = self._recortar(img)
            self._geom = {'left': 0, 'top': 0,
                          'width': img.width, 'height': img.height}
        return img

    def _grab_full(self, max_age=0.0):
        from PIL import Image
        # spectacle/grim lanzan un proceso y escriben un PNG (~0,5 s): compartir
        # el último frame entre miniaturas y observación en vivo evita duplicar
        # ese coste (y la espera en _GRAB_LOCK) cuando ambos coinciden.
        if max_age > 0 and self._cache is not None and \
                (time.monotonic() - self._cache_ts) <= max_age:
            return self._cache
        with self._GRAB_LOCK:
            try:
                os.remove(self._tmp)
            except OSError:
                pass
            args = [a.format(out=self._tmp) if '{out}' in a else a
                    for a in self._cmd]
            args[0] = self._path
            r = subprocess.run(args, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, text=True, errors='replace', timeout=10)
            if r.returncode != 0 or not os.path.isfile(self._tmp):
                detail = ' '.join((r.stderr or '').split())[-600:]
                raise CaptureError(f'{self.name} devolvió {r.returncode}: {detail}')
            img = Image.open(self._tmp).convert('RGB')
            if img.width < 2 or img.height < 2:
                raise CaptureError(f'{self.name} produjo una imagen vacía')
        self._geom = {'left': 0, 'top': 0,
                      'width': img.width, 'height': img.height}
        self._cache = img
        self._cache_ts = time.monotonic()
        return img

    def close(self):
        try:
            os.remove(self._tmp)
        except OSError:
            pass


# ── Monitores en Wayland ─────────────────────────────────────────────────────

def _monitores_kscreen():
    """Geometría lógica de las salidas activas según kscreen-doctor (KDE)."""
    import json
    exe = shutil.which('kscreen-doctor')
    if not exe:
        return []
    r = subprocess.run([exe, '-j'], capture_output=True, text=True,
                       errors='replace', timeout=5)
    if r.returncode != 0:
        return []
    salidas = json.loads(r.stdout or '{}').get('outputs', [])
    mons = []
    for o in salidas:
        if not (o.get('enabled') and o.get('connected', True)):
            continue
        size = o.get('size') or {}
        if not size.get('width'):
            for mode in o.get('modes', []):
                if str(mode.get('id')) == str(o.get('currentModeId')):
                    size = mode.get('size') or {}
        w, h = size.get('width'), size.get('height')
        if not w or not h:
            continue
        if o.get('rotation') in (2, 8):          # girada 90°/270°
            w, h = h, w
        scale = float(o.get('scale') or 1) or 1.0
        pos = o.get('pos') or {}
        mons.append({'left': int(pos.get('x', 0)), 'top': int(pos.get('y', 0)),
                     'width': round(w / scale), 'height': round(h / scale),
                     'name': o.get('name', ''), 'primary': o.get('priority') == 1})
    return mons


def _monitores_xrandr():
    """Respaldo: monitores tal como los ve XWayland (también vale en X11)."""
    import re
    exe = shutil.which('xrandr')
    if not exe or not os.environ.get('DISPLAY'):
        return []
    r = subprocess.run([exe, '--listmonitors'], capture_output=True, text=True,
                       errors='replace', timeout=5)
    mons = []
    for linea in r.stdout.splitlines() if r.returncode == 0 else []:
        m = re.search(r'(\*?)(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)\s+(\S+)\s*$', linea)
        if m:
            mons.append({'left': int(m.group(4)), 'top': int(m.group(5)),
                         'width': int(m.group(2)), 'height': int(m.group(3)),
                         'name': m.group(6), 'primary': '*' in linea})
    return mons


def wayland_monitors():
    """Lista de monitores (coordenadas lógicas, de izquierda a derecha).

    spectacle/grim solo capturan el escritorio completo; esta geometría permite
    al profesor elegir UNA pantalla y recortarla, como hace el selector de
    Chrome. Lista vacía si no se puede saber (se comparte todo)."""
    for fuente in (_monitores_kscreen, _monitores_xrandr):
        try:
            mons = fuente()
        except Exception:
            mons = []
        if mons:
            return sorted(mons, key=lambda m: (m['left'], m['top']))
    return []


# ── Backend PipeWire (Wayland fluido, vía portal ScreenCast) ──────────────────
# Un único stream del portal compartido por todos los consumidores (miniaturas y
# WebRTC): así solo hay UNA sesión de screencast y UN diálogo de permiso (la 1ª
# vez; luego silencioso por restore_token). Refcount para no cerrarlo hasta que
# el último consumidor llame a close().

_pw_backend = None
_pw_refcount = 0
_pw_ref_lock = threading.Lock()
_pw_grab_lock = threading.Lock()
_pw_disabled = False   # True si el portal falló/denegó: no reintentar este proceso


class _SharedPipeWire:
    """Vista con refcount sobre el PipeWireBackend único del proceso."""
    name = 'pipewire'

    def __init__(self, backend):
        self._b = backend
        self._closed = False

    def monitor(self):
        with _pw_grab_lock:
            return self._b.monitor()

    def grab(self, max_age=0.0):
        with _pw_grab_lock:
            return self._b.grab(max_age=max_age)

    def grab_raw(self, max_age=0.0):
        with _pw_grab_lock:
            return self._b.grab_raw(max_age=max_age)

    def close(self):
        if self._closed:
            return
        self._closed = True
        _release_pipewire()


def _acquire_pipewire():
    """Devuelve un _SharedPipeWire o lanza si el portal no está disponible."""
    global _pw_backend, _pw_refcount, _pw_disabled
    with _pw_ref_lock:
        if _pw_disabled:
            raise CaptureError('pipewire deshabilitado tras fallo previo')
        if _pw_backend is None:
            try:
                import pipewire_capture
                _pw_backend = pipewire_capture.create_backend(timeout=30)
            except Exception as e:
                _pw_disabled = True
                raise CaptureError(f'pipewire no disponible: {e}')
        _pw_refcount += 1
        return _SharedPipeWire(_pw_backend)


def _release_pipewire():
    global _pw_backend, _pw_refcount
    with _pw_ref_lock:
        _pw_refcount -= 1
        if _pw_refcount <= 0 and _pw_backend is not None:
            try:
                _pw_backend.close()
            except Exception:
                pass
            _pw_backend = None
            _pw_refcount = 0


# ── Fábrica ──────────────────────────────────────────────────────────────────

def _cli_tool_order():
    """Orden de prueba de herramientas CLI según el escritorio."""
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
    if 'kde' in desktop or 'plasma' in desktop:
        return ['spectacle', 'grim', 'gnome-screenshot']
    if 'gnome' in desktop:
        return ['gnome-screenshot', 'grim', 'spectacle']
    return ['grim', 'spectacle', 'gnome-screenshot']


def create_capturer(verbose=True, *, allow_portal=True):
    """Devuelve el primer backend de captura funcional.

    allow_portal=False usa las herramientas directas del escritorio, sin abrir
    el selector ScreenCast. Lo usa la captura compatible del profesor: listar
    sus pantallas no debe pedir permisos ni crear una sesión PipeWire.
    Lanza CaptureError con un mensaje orientativo si ninguno funciona.
    """
    sess = session_type()
    if sess == 'unknown':
        raise CaptureError(
            'No se encuentra una sesión gráfica de este usuario. Abre VIGIA desde '
            'el menú de aplicaciones y comprueba que se ejecuta con el mismo '
            'usuario de tu escritorio.')
    errors = []

    # En Wayland, intentar PRIMERO PipeWire (portal ScreenCast): captura fluida
    # a 30-60 fps. Si el portal no está, falla o se deniega, se cae a spectacle.
    if sess == 'wayland' and allow_portal:
        try:
            backend = _acquire_pipewire()
            if verbose:
                print("  [✓] Captura de pantalla: backend 'pipewire' "
                      "(Wayland, portal ScreenCast)")
            return backend
        except Exception as e:
            errors.append(f'pipewire: {e}')

    if sess in ('x11', 'windows', 'unknown'):
        order = ['mss'] + _cli_tool_order()
    else:  # wayland: mss solo vería XWayland → probar CLI primero
        order = _cli_tool_order() + ['mss']

    for tool in order:
        try:
            backend = MssBackend() if tool == 'mss' else CliBackend(tool)
            if verbose:
                print(f"  [✓] Captura de pantalla: backend '{backend.name}' "
                      f"(sesión {sess})")
            return backend
        except Exception as e:
            errors.append(f'{tool}: {e}')

    raise CaptureError(
        'Ningún backend de captura disponible (sesión {}):\n  {}\n'
        'En Wayland instala spectacle (KDE) o gnome-screenshot/grim; '
        'en X11 instala mss (pip install mss).'.format(
            sess, '\n  '.join(errors)))


def grab_shared(cap, max_age=0.0):
    """`cap.grab(max_age=…)` tolerante con backends que no acepten el parámetro.

    Permite reutilizar el último frame capturado (por ejemplo el que acaba de
    tirar WebRTC) en vez de pedir otro al compositor.
    """
    if max_age > 0:
        try:
            return cap.grab(max_age=max_age)
        except TypeError:
            pass
    return cap.grab()


def get_monitor_geometry(default=(1920, 1080)):
    """Geometría del monitor principal sin mantener un capturador abierto."""
    try:
        cap = create_capturer(verbose=False)
        try:
            return cap.monitor()
        finally:
            cap.close()
    except Exception:
        return {'left': 0, 'top': 0, 'width': default[0], 'height': default[1]}
