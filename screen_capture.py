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

    def grab(self, max_age=0.0):
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
