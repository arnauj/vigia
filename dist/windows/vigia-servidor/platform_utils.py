"""
VIGIA - Utilidades multiplataforma (Linux / Windows)
Centraliza todas las diferencias de sistema operativo para que el resto
del código pueda llamar funciones limpias sin condicionales dispersos.
"""

import sys
import os
import subprocess
import shutil
import pathlib
import ctypes
import ctypes.util
import tempfile

# ── Constantes de plataforma ─────────────────────────────────────────────────
IS_WINDOWS = sys.platform == 'win32'
IS_LINUX   = sys.platform.startswith('linux')


# ── Abrir archivo con la aplicación predeterminada ───────────────────────────
def open_file(path):
    """Abre un archivo con la aplicación predeterminada del OS."""
    path = str(path)
    try:
        if IS_WINDOWS:
            os.startfile(path)
        else:
            subprocess.Popen(['xdg-open', path])
    except Exception:
        pass


# ── Portapapeles ─────────────────────────────────────────────────────────────
def get_clipboard_text(xdo_env=None):
    """Obtiene el texto del portapapeles del sistema.
    En Linux usa xclip/xsel con el entorno xdo_env (necesita DISPLAY).
    En Windows usa la API Win32 via ctypes.
    Retorna cadena vacía si falla.
    """
    if IS_WINDOWS:
        return _get_clipboard_win32()
    return _get_clipboard_linux(xdo_env)


def _get_clipboard_linux(xdo_env):
    for cmd in [
        ['xclip', '-o', '-selection', 'clipboard'],
        ['xsel',  '--clipboard', '--output'],
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=2, env=xdo_env)
            if r.returncode == 0:
                return r.stdout
        except Exception:
            continue
    return ''


def _get_clipboard_win32():
    try:
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        CF_UNICODETEXT = 13
        if not u32.OpenClipboard(0):
            return ''
        try:
            h = u32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return ''
            k32.GlobalLock.restype = ctypes.c_void_p
            ptr = k32.GlobalLock(h)
            if not ptr:
                return ''
            try:
                return ctypes.wstring_at(ptr)
            finally:
                k32.GlobalUnlock(h)
        finally:
            u32.CloseClipboard()
    except Exception:
        return ''


# ── Directorio de descargas ──────────────────────────────────────────────────
def get_downloads_dir():
    """Devuelve el directorio de descargas del usuario."""
    if IS_WINDOWS:
        return _get_downloads_dir_win32()
    # Linux: ~/Descargas → ~/Downloads → ~
    home = pathlib.Path.home()
    for name in ('Descargas', 'Downloads'):
        d = home / name
        if d.exists():
            return d
    return home


def _get_downloads_dir_win32():
    try:
        import ctypes.wintypes
        FOLDERID_Downloads = ctypes.c_char_p(
            b'\xe3\x9c\x87\x37\x4b\xc8\x64\x43\xba\x46\x64\x7e\x03\x45\x89\x6c'
        )
        SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
        SHGetKnownFolderPath.argtypes = [
            ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_wchar_p)
        ]
        SHGetKnownFolderPath.restype = ctypes.c_long
        path_ptr = ctypes.c_wchar_p()
        hr = SHGetKnownFolderPath(FOLDERID_Downloads, 0, None, ctypes.byref(path_ptr))
        if hr == 0 and path_ptr.value:
            result = pathlib.Path(path_ptr.value)
            ctypes.windll.ole32.CoTaskMemFree(path_ptr)
            return result
    except Exception:
        pass
    # Fallback
    return pathlib.Path.home() / 'Downloads'


# ── Ruta de configuración ────────────────────────────────────────────────────
def get_config_path():
    """Devuelve la ruta del archivo de configuración del cliente."""
    if IS_WINDOWS:
        appdata = os.environ.get('APPDATA', os.path.expanduser('~'))
        return os.path.join(appdata, 'vigia', 'client.conf')
    return '/etc/vigia/client.conf'


# ── Ruta temporal ────────────────────────────────────────────────────────────
def get_temp_path(name):
    """Devuelve una ruta temporal para el archivo dado."""
    if IS_WINDOWS:
        return os.path.join(tempfile.gettempdir(), name)
    return f'/tmp/{name}'


# ── Apagar el sistema ────────────────────────────────────────────────────────
def shutdown_system():
    """Apaga el equipo."""
    try:
        if IS_WINDOWS:
            subprocess.run(['shutdown', '/s', '/t', '0'], check=False, timeout=5)
        else:
            subprocess.run(['sudo', 'shutdown', '-h', 'now'], check=False, timeout=5)
    except Exception:
        os._exit(0)


# ── Nombre de usuario ────────────────────────────────────────────────────────
def get_username(default='alumno'):
    """Devuelve el nombre de usuario del sistema."""
    if IS_WINDOWS:
        return os.environ.get('USERNAME', default)
    return os.environ.get('USER', default)


# ── Ejecución de comandos shell ──────────────────────────────────────────────
def run_shell(cmd, cwd, env=None, timeout=60):
    """Ejecuta un comando en el shell del OS y devuelve (stdout, stderr, returncode, new_cwd).
    Envuelve el comando para capturar el directorio de trabajo resultante.
    """
    marker = '__VIGIA_PWD_7f3a9b2c__'

    if env is None:
        env = dict(os.environ)

    if IS_WINDOWS:
        env.setdefault('TERM', 'dumb')
        wrapped = f'cd /d {cwd} 2>nul & {cmd} & echo {marker}:%CD%'
    else:
        env.setdefault('DEBIAN_FRONTEND', 'noninteractive')
        env.setdefault('TERM', 'xterm')
        wrapped = f'cd {cwd!r} 2>/dev/null; {cmd}; echo "{marker}:$(pwd)"'

    try:
        result = subprocess.run(
            wrapped, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout, env=env
        )
        stdout = result.stdout
        new_cwd = cwd
        lines = stdout.split('\n')
        clean_lines = []
        for line in lines:
            if line.startswith(f'{marker}:'):
                candidate = line[len(f'{marker}:'):]
                if os.path.isdir(candidate):
                    new_cwd = candidate
            else:
                clean_lines.append(line)
        clean_stdout = '\n'.join(clean_lines).rstrip('\n')
        return clean_stdout, result.stderr, result.returncode, new_cwd
    except subprocess.TimeoutExpired:
        return '', f'Timeout ({timeout}s): el comando tardó demasiado.', -1, cwd
    except Exception as e:
        return '', str(e), -1, cwd


# ── Click-through de ventana ─────────────────────────────────────────────────
def set_clickthrough(window_id):
    """Hace una ventana transparente al input (click-through).
    window_id: int — en Linux es el XID, en Windows es el HWND.
    Retorna True si tuvo éxito.
    """
    if IS_WINDOWS:
        return _set_clickthrough_win32(window_id)
    return _set_clickthrough_x11(window_id)


def _set_clickthrough_x11(window_id):
    try:
        x11_path = ctypes.util.find_library('X11')
        fix_path = ctypes.util.find_library('Xfixes')
        if not x11_path or not fix_path:
            return False
        x11  = ctypes.cdll.LoadLibrary(x11_path)
        xfix = ctypes.cdll.LoadLibrary(fix_path)

        x11.XOpenDisplay.argtypes  = [ctypes.c_char_p]
        x11.XOpenDisplay.restype   = ctypes.c_void_p
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.restype  = ctypes.c_int
        x11.XFlush.argtypes        = [ctypes.c_void_p]
        x11.XFlush.restype         = ctypes.c_int

        xfix.XFixesCreateRegion.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        xfix.XFixesCreateRegion.restype  = ctypes.c_ulong
        xfix.XFixesSetWindowShapeRegion.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_ulong
        ]
        xfix.XFixesDestroyRegion.argtypes = [ctypes.c_void_p, ctypes.c_ulong]

        dpy = x11.XOpenDisplay(None)
        if not dpy:
            return False
        try:
            empty_region = xfix.XFixesCreateRegion(dpy, None, 0)
            ShapeInput = 2
            xfix.XFixesSetWindowShapeRegion(
                dpy, ctypes.c_ulong(window_id), ShapeInput, 0, 0, empty_region
            )
            xfix.XFixesDestroyRegion(dpy, empty_region)
            x11.XFlush(dpy)
            return True
        finally:
            x11.XCloseDisplay(dpy)
    except Exception:
        return False


def _set_clickthrough_win32(hwnd):
    try:
        u32 = ctypes.windll.user32
        GWL_EXSTYLE      = -20
        WS_EX_LAYERED    = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        style = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        return True
    except Exception:
        return False


# ── Enumeración de ventanas (para server.py) ─────────────────────────────────
def get_window_list():
    """Devuelve lista de ventanas visibles con título y geometría.
    Cada elemento: {'wid': str|int, 'x': int, 'y': int, 'w': int, 'h': int, 'title': str}
    """
    if IS_WINDOWS:
        return _get_window_list_win32()
    return _get_window_list_linux()


def _get_window_list_linux():
    """Usa xprop + xdotool (implementación original de server.py)."""
    import re as _re
    try:
        r = subprocess.run(['xprop', '-root', '-notype', '_NET_CLIENT_LIST'],
                           capture_output=True, text=True, timeout=3)
        if r.returncode != 0 or '_NET_CLIENT_LIST' not in r.stdout:
            return []
        wids = _re.findall(r'0x[0-9a-fA-F]+', r.stdout.split(':', 1)[1])
        windows = []
        for wid in wids:
            state_r = subprocess.run(['xprop', '-id', wid, '-notype', '_NET_WM_STATE'],
                                     capture_output=True, text=True, timeout=1)
            if '_NET_WM_STATE_HIDDEN' in state_r.stdout:
                continue
            nr = subprocess.run(['xprop', '-id', wid, '-notype', '_NET_WM_NAME', 'WM_NAME'],
                                capture_output=True, text=True, timeout=1)
            title = ''
            for line in nr.stdout.splitlines():
                if '_NET_WM_NAME' in line and '=' in line:
                    title = line.split('=', 1)[1].strip().strip('"')
                    break
                if 'WM_NAME' in line and '=' in line and not title:
                    title = line.split('=', 1)[1].strip().strip('"')
            if not title or 'VIGIA' in title:
                continue
            gr = subprocess.run(['xdotool', 'getwindowgeometry', '--shell', wid],
                                capture_output=True, text=True, timeout=1)
            geom = dict(kv.split('=', 1) for kv in gr.stdout.splitlines() if '=' in kv)
            w, h = int(geom.get('WIDTH', 0)), int(geom.get('HEIGHT', 0))
            if w < 100 or h < 100:
                continue
            windows.append({
                'wid': wid,
                'x': int(geom.get('X', 0)), 'y': int(geom.get('Y', 0)),
                'w': w, 'h': h, 'title': title,
            })
        return windows
    except Exception:
        return []


def _get_window_list_win32():
    """Enumera ventanas visibles usando Win32 API via ctypes."""
    try:
        u32 = ctypes.windll.user32
        windows = []

        def _enum_callback(hwnd, _lparam):
            if not u32.IsWindowVisible(hwnd):
                return True
            length = u32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            u32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if not title or 'VIGIA' in title:
                return True
            # Obtener geometría
            class RECT(ctypes.Structure):
                _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                            ('right', ctypes.c_long), ('bottom', ctypes.c_long)]
            rect = RECT()
            u32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w < 100 or h < 100:
                return True
            windows.append({
                'wid': hwnd,
                'x': rect.left, 'y': rect.top,
                'w': w, 'h': h, 'title': title,
            })
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
        u32.EnumWindows(WNDENUMPROC(_enum_callback), 0)
        return windows
    except Exception:
        return []


def get_window_region(wid):
    """Devuelve la región actual de una ventana: {'left', 'top', 'width', 'height'} o None."""
    if IS_WINDOWS:
        return _get_window_region_win32(wid)
    return _get_window_region_linux(wid)


def _get_window_region_linux(wid):
    try:
        gr = subprocess.run(['xdotool', 'getwindowgeometry', '--shell', str(wid)],
                            capture_output=True, text=True, timeout=2)
        geom = dict(kv.split('=', 1) for kv in gr.stdout.splitlines() if '=' in kv)
        if 'WIDTH' in geom:
            return {'left': int(geom['X']), 'top': int(geom['Y']),
                    'width': int(geom['WIDTH']), 'height': int(geom['HEIGHT'])}
    except Exception:
        pass
    return None


def _get_window_region_win32(hwnd):
    try:
        class RECT(ctypes.Structure):
            _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                        ('right', ctypes.c_long), ('bottom', ctypes.c_long)]
        rect = RECT()
        ctypes.windll.user32.GetWindowRect(int(hwnd), ctypes.byref(rect))
        return {'left': rect.left, 'top': rect.top,
                'width': rect.right - rect.left, 'height': rect.bottom - rect.top}
    except Exception:
        return None


# ── DPI awareness (Windows) ─────────────────────────────────────────────────
def set_dpi_aware():
    """Activa DPI awareness en Windows para coordenadas correctas."""
    if IS_WINDOWS:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
