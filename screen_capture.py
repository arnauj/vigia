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
"""

import itertools
import os
import sys
import shutil
import subprocess
import tempfile
import threading
import time


class CaptureError(Exception):
    """No hay ningún backend de captura funcional."""


def session_type():
    """Devuelve 'windows', 'wayland', 'x11' o 'unknown'."""
    if sys.platform == 'win32':
        return 'windows'
    if os.environ.get('WAYLAND_DISPLAY') or \
       os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland':
        return 'wayland'
    if os.environ.get('DISPLAY'):
        return 'x11'
    return 'unknown'


def is_wayland():
    return session_type() == 'wayland'


# ── Backend mss (X11 / Windows) ──────────────────────────────────────────────

class MssBackend:
    name = 'mss'

    def __init__(self):
        import mss
        self._sct = mss.mss()
        self.index = 1   # 0 = espacio virtual completo, 1..n = monitores
        # Validar que realmente puede capturar (lanza si no hay DISPLAY)
        self._sct.grab(self._sct.monitors[1])

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

    def grab(self):
        """Devuelve una PIL.Image RGB del monitor seleccionado."""
        from PIL import Image
        cap = self._sct.grab(self._sct.monitors[self.index])
        return Image.frombytes('RGB', cap.size, cap.bgra, 'raw', 'BGRX')

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
        # Captura de prueba: valida permisos/entorno en el constructor
        self.grab()

    def monitor(self):
        if self._geom is None:
            self.grab()
        return self._geom

    def grab(self):
        from PIL import Image
        with self._GRAB_LOCK:
            try:
                os.remove(self._tmp)
            except OSError:
                pass
            args = [a.format(out=self._tmp) if '{out}' in a else a
                    for a in self._cmd]
            args[0] = self._path
            r = subprocess.run(args, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=10)
            if r.returncode != 0 or not os.path.isfile(self._tmp):
                raise CaptureError(f'{self.name} devolvió {r.returncode}')
            img = Image.open(self._tmp).convert('RGB')
            if img.width < 2 or img.height < 2:
                raise CaptureError(f'{self.name} produjo una imagen vacía')
        self._geom = {'left': 0, 'top': 0,
                      'width': img.width, 'height': img.height}
        return img

    def close(self):
        try:
            os.remove(self._tmp)
        except OSError:
            pass


# ── Fábrica ──────────────────────────────────────────────────────────────────

def _cli_tool_order():
    """Orden de prueba de herramientas CLI según el escritorio."""
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
    if 'kde' in desktop or 'plasma' in desktop:
        return ['spectacle', 'grim', 'gnome-screenshot']
    if 'gnome' in desktop:
        return ['gnome-screenshot', 'grim', 'spectacle']
    return ['grim', 'spectacle', 'gnome-screenshot']


def create_capturer(verbose=True):
    """Devuelve el primer backend de captura funcional.

    Lanza CaptureError con un mensaje orientativo si ninguno funciona.
    """
    sess = session_type()
    errors = []

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
