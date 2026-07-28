#!/usr/bin/env python3
"""
VIGIA - Cliente del Alumno (v1.6)
Captura la pantalla y la envía al servidor del profesor.
Uso: python client.py [ip_servidor] [puerto]
"""

import sys
import os
import io
import re
import json

# ---------------------------------------------------------------------------
# Windows: ejecutar SIEMPRE sin ventana de consola visible.
# Paso 1: Desconectar la consola heredada (FreeConsole) inmediatamente.
# Paso 2: Si se lanzó con python.exe (no pythonw ni .exe frozen),
#          re-lanzar con pythonw.exe mediante un .vbs para cero destello.
# Paso 3: Redirigir stdout/stderr a log (son None sin consola).
# ---------------------------------------------------------------------------
if sys.platform == 'win32':
    import ctypes as _ct
    # Paso 1: OCULTAR la ventana de consola inmediatamente (antes de cualquier otra cosa).
    # GetConsoleWindow + ShowWindow(SW_HIDE) cierra visualmente la ventana al instante,
    # incluso si FreeConsole no la cierra (p.ej. si fue creada por el shell de Windows).
    try:
        _hwnd = _ct.windll.kernel32.GetConsoleWindow()
        if _hwnd:
            _ct.windll.user32.ShowWindow(_hwnd, 0)  # SW_HIDE = 0
    except Exception:
        pass
    # Paso 2: desconectar la consola del proceso
    try:
        _ct.windll.kernel32.FreeConsole()
    except Exception:
        pass
    # Paso 3: si nos lanzaron con python.exe, re-lanzar con pythonw (sin consola)
    _exe = os.path.basename(sys.executable).lower()
    if _exe in ('python.exe', 'python3.exe') and not os.environ.get('VIGIA_NO_RELAUNCH'):
        _pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
        if os.path.isfile(_pythonw):
            import subprocess as _sp, tempfile
            _vbs = os.path.join(tempfile.gettempdir(), 'vigia_client_launch.vbs')
            _cmd = f'"{_pythonw}" ' + ' '.join(f'"{a}"' for a in sys.argv)
            with open(_vbs, 'w') as _f:
                _f.write(f'CreateObject("WScript.Shell").Run "{_cmd}", 0, False\n')
            os.startfile(_vbs)
            sys.exit(0)
    # Paso 4: redirigir stdout/stderr a log
    _log_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'vigia')
    os.makedirs(_log_dir, exist_ok=True)
    _log_file = open(os.path.join(_log_dir, 'client.log'), 'a', encoding='utf-8', errors='replace')
    if sys.stdout is None:
        sys.stdout = _log_file
    if sys.stderr is None:
        sys.stderr = _log_file

# Forzar salida UTF-8 en Windows (cp1252 no soporta emojis/símbolos Unicode)
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
import time
import socket
import threading
import queue
import base64
import shutil
import subprocess
import ctypes
import ctypes.util
import platform_utils
import screen_capture

# ── Importaciones ────────────────────────────────────────────────────────────

def _pip_disponible():
    _kw = {'creationflags': subprocess.CREATE_NO_WINDOW} if platform_utils.IS_WINDOWS else {}
    try:
        if subprocess.run([sys.executable, '-m', 'pip', '--version'],
                          capture_output=True, timeout=2, **_kw).returncode == 0:
            return [sys.executable, '-m', 'pip']
    except Exception: pass
    if shutil.which('pip3'): return ['pip3']
    if shutil.which('pip'): return ['pip']
    return None

def _instalar(paquete):
    print(f"  [VIGIA] Instalando {paquete}...")
    import importlib
    pip_cmd = _pip_disponible()
    if not pip_cmd:
        if platform_utils.IS_LINUX:
            os.system('sudo apt-get update -qq 2>/dev/null && sudo apt-get install -y python3-pip -qq 2>/dev/null')
        pip_cmd = _pip_disponible()
    if pip_cmd:
        _kw = {'creationflags': subprocess.CREATE_NO_WINDOW} if platform_utils.IS_WINDOWS else {}
        try:
            res = subprocess.run(pip_cmd + ['install', '--user', '--break-system-packages', '-q'] + paquete.split(), timeout=60, **_kw)
            if res.returncode == 0:
                importlib.invalidate_caches()
                return True
        except Exception: pass
    importlib.invalidate_caches()
    return False

# Cargar dependencias
try:
    import socketio as sio_module
except ImportError:
    _instalar("python-socketio[client] websocket-client")
    import socketio as sio_module

try:
    import mss
except ImportError:
    _instalar("mss")
    try:
        import mss
    except ImportError:
        # En Wayland (Kubuntu 25.10+/26.04) la captura usa spectacle/grim,
        # así que mss no es imprescindible para arrancar.
        mss = None
        print("  [!] mss no disponible — se usará captura Wayland si existe.")

try:
    from PIL import Image
except ImportError:
    # Pillow es una librería NATIVA: en Linux SIEMPRE por apt (un wheel pip
    # para otro Python falla con "No matching distribution found for Pillow").
    if platform_utils.IS_LINUX:
        os.system('sudo apt-get install -y python3-pil python3-pil.imagetk -qq 2>/dev/null')
    else:
        _instalar("Pillow")
    from PIL import Image

try:
    import tkinter as tk
    TK_OK = True
except Exception:
    TK_OK = False

if TK_OK:
    try:
        from PIL import ImageTk
        IMGTK_OK = True
    except ImportError:
        print("  [*] Falta ImageTk (PIL). Intentando instalar dependencias de sistema...")
        if platform_utils.IS_LINUX:
            os.system('sudo apt-get update -qq 2>/dev/null && sudo apt-get install -y python3-pil.imagetk -qq 2>/dev/null')
        try:
            from PIL import ImageTk
            IMGTK_OK = True
        except ImportError:
            if platform_utils.IS_LINUX:
                # En Linux NO reinstalar Pillow con pip (librería nativa: solo apt).
                print("  [!] ImageTk no disponible. Instala: sudo apt install python3-pil.imagetk")
                IMGTK_OK = False
            else:
                print("  [*] No se pudo cargar ImageTk. Reinstalando Pillow...")
                _instalar("--force-reinstall Pillow")
                try:
                    # Forzar relectura de PIL
                    for _k in list(sys.modules.keys()):
                        if _k == 'PIL' or _k.startswith('PIL.'): del sys.modules[_k]
                    from PIL import Image, ImageTk
                    IMGTK_OK = True
                except ImportError:
                    print("  [!] Error crítico: No se pudo cargar ImageTk.")
                    IMGTK_OK = False
else:
    ImageTk = None; IMGTK_OK = False

# ── WebRTC con aiortc (opcional, instalado via apt en instalar_cliente.sh) ───
WEBRTC_OK = False
WEBRTC_H264 = False   # True si se pudo preferir H.264 (x264) sobre VP8
try:
    import asyncio, fractions
    import numpy as np
    from concurrent.futures import ThreadPoolExecutor
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
    import av
    WEBRTC_OK = True
    print("  [✓] aiortc disponible — WebRTC habilitado.")
    # aiortc capa el encoder a 1.5 Mbps (MAX_BITRATE): a 1080p la imagen sale
    # borrosa y el control de tasa hunde los fps. Se elevan los topes al rango
    # que usa RustDesk en LAN; el REMB del navegador sigue autorregulando el
    # bitrate real según el ancho de banda disponible.
    # OJO: en aiortc ≥1.x el encoder VP8 vive en `aiortc.codecs.vpx`
    # (`aiortc.codecs.vp8` NO existe y el parche se perdía en silencio: el vídeo
    # seguía capado a 1.5 Mbps). Se prueban ambos nombres.
    import importlib
    _patched = []
    for _codec_mod in ('vpx', 'vp8', 'h264'):
        try:
            _cm = importlib.import_module(f'aiortc.codecs.{_codec_mod}')
        except Exception:
            continue
        if not hasattr(_cm, 'MAX_BITRATE'):
            continue
        _cm.DEFAULT_BITRATE = 3_000_000
        _cm.MIN_BITRATE     = 500_000
        _cm.MAX_BITRATE     = 8_000_000
        _patched.append(_codec_mod)
    if _patched:
        print(f"  [✓] Bitrate WebRTC elevado a 8 Mbps ({', '.join(_patched)}).")
    else:
        print("  [!] No se pudo elevar el tope de bitrate de aiortc "
              "(la imagen puede verse borrosa a 1080p).")

    # libvpx en tiempo real es de un solo hilo salvo que se le diga lo
    # contrario: aiortc reparte hilos con `number_of_threads()`, que en un PC de
    # aula de 4 núcleos deja el encoder VP8 de 1080p con SOLO 2 hilos (~15 fps).
    # Se sustituye por un reparto que usa todos los núcleos disponibles (libvpx
    # admite hasta 8 y no rinde más allá), sin tocar el resto del encoder.
    try:
        _vpx = importlib.import_module('aiortc.codecs.vpx')

        def _vigia_threads(pixels, cpus):
            if pixels > 1280 * 720:
                return max(1, min(8, cpus))
            if pixels > 640 * 480:
                return max(1, min(4, cpus))
            return max(1, min(2, cpus))

        if hasattr(_vpx, 'number_of_threads'):
            _vpx.number_of_threads = _vigia_threads
            import multiprocessing as _mp
            print(f"  [✓] Encoder VP8 multihilo ({_mp.cpu_count()} núcleos).")
    except Exception:
        pass

    # ── H.264 en vez de VP8 ──────────────────────────────────────────────────
    # x264 con preset ultrafast + tune zerolatency codifica 1080p de escritorio
    # en ~3 ms/frame; libvpx-VP8 en tiempo real necesita ~9 ms con los mismos
    # hilos (medido). aiortc, sin embargo: (a) deja que el navegador imponga el
    # orden de códecs —y Chrome pone VP8 primero—, y (b) crea el x264 SIN
    # preset, es decir con «medium», que es de codificación offline.
    # Aquí se corrigen las dos cosas, pero solo si libx264 existe de verdad en
    # el libavcodec del equipo: si no, se sigue con VP8 (nunca vídeo negro).
    try:
        import aiortc.codecs as _codecs
        from aiortc.codecs.h264 import H264Encoder as _H264Base, MAX_FRAME_RATE as _H264_FPS
        av.CodecContext.create('libx264', 'w')   # lanza si no está compilado

        class _H264EncoderRapido(_H264Base):
            """H264Encoder de aiortc con preset de tiempo real y multihilo."""

            def _encode_frame(self, frame, force_keyframe):
                # Misma condición de invalidación que la clase base: si se
                # adelanta aquí, la base encuentra el códec ya creado (con
                # NUESTRAS opciones) y no lo rehace con las suyas.
                if self.codec is not None and (
                        frame.width != self.codec.width
                        or frame.height != self.codec.height
                        or abs(self.target_bitrate - self.codec.bit_rate)
                        / self.codec.bit_rate > 0.1):
                    self.buffer_data = b""
                    self.buffer_pts = None
                    self.codec = None
                if self.codec is None:
                    c = av.CodecContext.create('libx264', 'w')
                    c.width, c.height = frame.width, frame.height
                    c.bit_rate = self.target_bitrate
                    c.pix_fmt = 'yuv420p'
                    c.framerate = fractions.Fraction(_H264_FPS, 1)
                    c.time_base = fractions.Fraction(1, _H264_FPS)
                    c.thread_count = max(1, min(8, os.cpu_count() or 1))
                    # Sin 'level': x264 elige el que corresponda a la
                    # resolución (el 3.1 fijo de aiortc se queda corto a 1080p).
                    c.options = {'preset': 'ultrafast', 'tune': 'zerolatency'}
                    c.profile = 'Baseline'
                    self.codec = c
                return super()._encode_frame(frame, force_keyframe)

        _codecs.H264Encoder = _H264EncoderRapido
        WEBRTC_H264 = True
        print("  [✓] Encoder H.264 (x264 ultrafast) preferido sobre VP8.")
    except Exception as _e:
        print(f"  [*] H.264 no disponible ({_e}); se usará VP8.")
except ImportError:
    print("  [!] aiortc no instalado — usando fallback JPEG.")

# ── Descodificador de la pantalla del profesor (vídeo comprimido) ────────────
# El panel del profesor codifica su pantalla UNA vez con WebCodecs (H.264/VP8)
# y el servidor reparte los trozos. Aquí se descodifican con PyAV (el mismo
# libavcodec que ya usa aiortc), que es C y va sobrado: un fotograma 1600p
# cuesta ~3 ms frente a los ~150-250 KB de JPEG por fotograma que llegaban
# antes por la red para CADA alumno.
try:
    import av as _av
    _AV_OK = True
except Exception:
    _av = None
    _AV_OK = False

# ── Control remoto (Pynput + Xdotool en X11, ydotool en Wayland) ──────────────
_mouse_ctrl = None
_kbd_ctrl   = None
_PBtn       = None
_XDO_CMD    = shutil.which('xdotool') if platform_utils.IS_LINUX else None
_YDO_CMD    = None   # ydotool (Wayland) — se detecta en _init_input
_YDO_TYPE_ARGS = []  # flags extra para `ydotool type` (p.ej. --key-delay 0)
_ydo_env    = None   # entorno con YDOTOOL_SOCKET resuelto
_xdo_env    = None   # entorno precalculado para xdotool (evita copiar os.environ en cada evento)
_mon_left   = 0      # offset X del monitor capturado en el espacio virtual X11
_mon_top    = 0      # offset Y del monitor capturado en el espacio virtual X11
_mon_width  = 1920   # ancho del monitor capturado (para normalizar coords abs)
_mon_height = 1080   # alto  del monitor capturado (para normalizar coords abs)
_mon_valido = False  # True cuando la geometría viene de una captura real

# Inyección de input absoluto en Wayland vía demonio uinput root (vigia_input).
# Resuelve el bug del ratón pegado en la esquina (ydotool no tiene eje absoluto).
_VIGIA_INPUT = None
_VI_ABS_MAX  = 32767
_VI_TECLADO  = False   # True si el demonio acepta teclas (evita ydotool por tecla)
_VI_KB_PROBE = 0.0     # último saludo al demonio buscando soporte de teclado
_ES_WAYLAND  = False   # se resuelve en _init_input()

# ── Terminal remoto: directorio de trabajo persistente ────────────────────────
_term_cwd = os.path.expanduser('~')   # cwd actual del terminal del profesor

# ── Pizarra overlay (subproceso GTK+Cairo) ────────────────────────────────────
_overlay_proc = None   # subprocess.Popen del proceso vigia_overlay.py

def _send_overlay_cmd(cmd: dict):
    """Envía un comando JSON al subproceso de la pizarra vía stdin."""
    global _overlay_proc
    if _overlay_proc is None or _overlay_proc.poll() is not None:
        return
    try:
        _overlay_proc.stdin.write(json.dumps(cmd) + '\n')
        _overlay_proc.stdin.flush()
    except Exception:
        _overlay_proc = None

def _start_overlay_proc() -> bool:
    """Inicia vigia_overlay.py si no está ya corriendo. Retorna True si OK."""
    global _overlay_proc
    if _overlay_proc and _overlay_proc.poll() is None:
        return True
    mon = screen_capture.get_monitor_geometry()
    l = mon.get('left', 0); t = mon.get('top', 0)
    w = mon['width'];       h = mon['height']
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vigia_overlay.py')
    if not os.path.exists(script):
        print(f"  [!] vigia_overlay.py no encontrado en {script}")
        return False
    env = dict(os.environ)
    if platform_utils.IS_LINUX:
        env.setdefault('DISPLAY', ':0')
    if platform_utils.IS_WINDOWS:
        # En Windows no se usa el overlay GTK; se usa _VentanaPizarra tkinter inline
        print("  [*] Overlay GTK no disponible en Windows; usando pizarra tkinter.")
        return False
    try:
        _overlay_proc = subprocess.Popen(
            [sys.executable, script, str(l), str(t), str(w), str(h)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=open(platform_utils.get_temp_path('vigia_pizarra.log'), 'w'),
            text=True,
            env=env,
        )
        print(f"  [✓] Pizarra GTK iniciada (pid {_overlay_proc.pid}).")
        return True
    except Exception as e:
        print(f"  [!] No se pudo iniciar pizarra: {e}")
        return False

def _stop_overlay_proc():
    """Cierra el subproceso de la pizarra si está corriendo."""
    global _overlay_proc
    if _overlay_proc and _overlay_proc.poll() is None:
        try:
            _overlay_proc.stdin.close()
        except Exception:
            pass
    _overlay_proc = None
# ─────────────────────────────────────────────────────────────────────────────

def _xdo_sync(*args):
    """Ejecuta xdotool de forma síncrona (bloqueante). Usar solo desde el hilo de entrada."""
    try:
        subprocess.run([_XDO_CMD] + [str(a) for a in args],
                       env=_xdo_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=2)
    except Exception as e:
        print(f"  [!] xdotool {args}: {e}")

def _ydo_sync(*args):
    """Ejecuta ydotool de forma síncrona. Usar solo desde el hilo de entrada."""
    global _ydo_env
    # Re-resolver el socket si aún no se encontró o desapareció: ydotoold
    # puede arrancar DESPUÉS que el cliente (carrera en el login de sesión).
    sock = (_ydo_env or {}).get('YDOTOOL_SOCKET')
    if not sock or not os.path.exists(sock):
        _ydo_env = _ydo_resolver_socket()
    try:
        subprocess.run([_YDO_CMD] + [str(a) for a in args],
                       env=_ydo_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=2)
    except Exception as e:
        print(f"  [!] ydotool {args}: {e}")

def _detectar_ydo_type_args():
    """Añade `--key-delay 0` a `ydotool type` si esa versión lo admite.

    Por defecto ydotool espera ~12-20 ms ENTRE cada tecla: escribir «hola» por
    control remoto costaba casi 100 ms de más. Se prueba con una cadena vacía
    (no escribe nada) y solo se usa el flag si el comando termina bien.
    """
    global _YDO_TYPE_ARGS
    try:
        r = subprocess.run([_YDO_CMD, 'type', '--key-delay', '0', '--', ''],
                           env=_ydo_env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=3)
        if r.returncode == 0:
            _YDO_TYPE_ARGS = ['--key-delay', '0']
    except Exception:
        pass

def _ydo_resolver_socket():
    """Devuelve un entorno con YDOTOOL_SOCKET apuntando al socket de ydotoold."""
    env = dict(os.environ)
    if 'YDOTOOL_SOCKET' not in env:
        candidatos = [
            '/run/ydotoold/socket',                      # vigia-ydotoold.service (root)
            f"/run/user/{os.getuid()}/.ydotool_socket",  # ydotoold de usuario
            '/tmp/.ydotool_socket',                      # ydotoold lanzado a mano
        ]
        for cand in candidatos:
            if os.path.exists(cand):
                env['YDOTOOL_SOCKET'] = cand
                break
    return env

def _init_input():
    global _mouse_ctrl, _kbd_ctrl, _PBtn, _XDO_CMD, _xdo_env, _YDO_CMD, _ydo_env
    global _ES_WAYLAND
    _ES_WAYLAND = platform_utils.IS_LINUX and screen_capture.is_wayland()
    # 1. pynput
    try:
        from pynput.mouse import Controller as MouseController, Button
        from pynput.keyboard import Controller as KbdController
        _mouse_ctrl = MouseController()
        _kbd_ctrl = KbdController()
        _PBtn = Button
        print("  [✓] pynput inicializado.")
    except Exception as e:
        print(f"  [!] pynput no disponible: {e}")
        import traceback; traceback.print_exc()

    # 2. xdotool (solo Linux)
    if platform_utils.IS_LINUX:
        if not _XDO_CMD:
            _XDO_CMD = shutil.which('xdotool')
        if not _XDO_CMD and os.path.exists('/usr/bin/xdotool'):
            _XDO_CMD = '/usr/bin/xdotool'

    if _XDO_CMD:
        print(f"  [✓] xdotool detectado en {_XDO_CMD}.")
    else:
        print("  [!] xdotool no detectado — pynput manejará todo el control remoto.")

    # 3. ydotool (Wayland): xdotool/pynput solo inyectan en XWayland, no en el
    #    escritorio Wayland real. ydotool usa uinput y funciona en ambos.
    if platform_utils.IS_LINUX and screen_capture.is_wayland():
        _YDO_CMD = shutil.which('ydotool')
        if _YDO_CMD:
            _ydo_env = _ydo_resolver_socket()
            _detectar_ydo_type_args()
            print(f"  [✓] Sesión Wayland: control remoto vía ydotool ({_YDO_CMD}).")
        else:
            print("  [!] Sesión Wayland sin ydotool: el control remoto solo "
                  "afectará a apps XWayland. Instala 'ydotool' y habilita su "
                  "servicio para control completo.")

    # 4. vigia_input (Wayland): dispositivo uinput ABSOLUTO propio (demonio root).
    #    Es el ÚNICO que posiciona el ratón correctamente en Wayland; ydotool no
    #    tiene eje absoluto y deja el cursor pegado en la esquina. El puntero y el
    #    bloqueo (EVIOCGRAB) van por aquí; el teclado sigue por ydotool.
    global _VIGIA_INPUT, _VI_TECLADO
    if platform_utils.IS_LINUX:
        try:
            import vigia_input
            vi = vigia_input.VigiaInput()
            _VIGIA_INPUT = vi
            global _VI_ABS_MAX
            _VI_ABS_MAX = vigia_input.ABS_MAX
            if vi.available():
                # Si el demonio anuncia 'kb', el teclado también va por uinput:
                # una escritura en el socket (~0,05 ms) en lugar de un proceso
                # ydotool por pulsación (~20-30 ms de fork+exec). Solo en
                # Wayland: en X11 xdotool ya inyecta bien y con --clearmodifiers.
                _VI_TECLADO = _ES_WAYLAND and 'kb' in vi.features()
                print("  [✓] Control de ratón vía vigia_input (uinput absoluto)"
                      + (" + teclado." if _VI_TECLADO else "."))
            else:
                print("  [!] vigia_input aún sin demonio (se reintenta al usarlo).")
        except Exception as e:
            print(f"  [!] vigia_input no disponible: {e}")

    # Precalcular entorno para xdotool (se reutiliza en cada evento)
    _xdo_env = dict(os.environ)
    if platform_utils.IS_LINUX and 'DISPLAY' not in _xdo_env:
        _xdo_env['DISPLAY'] = ':0'

    return ((_mouse_ctrl is not None) or (_XDO_CMD is not None)
            or (_YDO_CMD is not None) or (_VIGIA_INPUT is not None))

INPUT_OK = _init_input()

_XDO_KEY_MAP = {
    'space': 'space', 'enter': 'Return', 'esc': 'Escape', 'tab': 'Tab',
    'backspace': 'BackSpace', 'delete': 'Delete', 'insert': 'Insert',
    'home': 'Home', 'end': 'End', 'pageup': 'Page_Up', 'pagedown': 'Page_Down',
    'left': 'Left', 'right': 'Right', 'up': 'Up', 'down': 'Down',
    'ctrl': 'Control_L', 'alt': 'Alt_L', 'shift': 'Shift_L', 'win': 'Super_L'
}
_BTN_MAP_XDO = {'left': 1, 'middle': 2, 'right': 3}

# ── Mapas ydotool (códigos de tecla del kernel: linux/input-event-codes.h) ────
_YDO_KEY_MAP = {
    'esc': 1, '1': 2, '2': 3, '3': 4, '4': 5, '5': 6, '6': 7, '7': 8,
    '8': 9, '9': 10, '0': 11, 'minus': 12, 'equal': 13, 'backspace': 14,
    'tab': 15, 'q': 16, 'w': 17, 'e': 18, 'r': 19, 't': 20, 'y': 21,
    'u': 22, 'i': 23, 'o': 24, 'p': 25, 'enter': 28, 'ctrl': 29,
    'a': 30, 's': 31, 'd': 32, 'f': 33, 'g': 34, 'h': 35, 'j': 36,
    'k': 37, 'l': 38, 'shift': 42, 'z': 44, 'x': 45, 'c': 46, 'v': 47,
    'b': 48, 'n': 49, 'm': 50, 'alt': 56, 'space': 57,
    'f1': 59, 'f2': 60, 'f3': 61, 'f4': 62, 'f5': 63, 'f6': 64,
    'f7': 65, 'f8': 66, 'f9': 67, 'f10': 68, 'f11': 87, 'f12': 88,
    'home': 102, 'up': 103, 'pageup': 104, 'left': 105, 'right': 106,
    'end': 107, 'down': 108, 'pagedown': 109, 'insert': 110, 'delete': 111,
    'win': 125,
}
# Botones de ratón ydotool: código base | 0x40 (down) / 0x80 (up)
_BTN_MAP_YDO = {'left': 0x00, 'right': 0x01, 'middle': 0x02}

# ── Cola de entrada dedicada ───────────────────────────────────────────────────
# Todos los eventos de ratón/teclado pasan por esta cola y son procesados
# en orden estricto por un único hilo. Esto evita:
#   - Ejecuciones paralelas de xdotool que llegan fuera de orden
#   - Race conditions en pynput (controladores Xlib no thread-safe entre hilos)
#   - Movimientos de ratón estancados por HOL blocking en el DataChannel
_input_q: queue.Queue = queue.Queue(maxsize=400)

def _input_worker():
    """Hilo dedicado: ejecuta eventos de entrada uno a uno, en orden."""
    pendiente = None
    while True:
        data = pendiente if pendiente is not None else _input_q.get()
        pendiente = None
        try:
            tipo = data.get('type')
            # Coalescing de mousemove: si hay más moves en cola, descartar los
            # viejos y ejecutar solo el más reciente.
            if tipo == 'mousemove':
                while True:
                    try:
                        nxt = _input_q.get_nowait()
                    except queue.Empty:
                        break
                    if nxt.get('type') == 'mousemove':
                        data = nxt          # descartar move viejo, usar el más reciente
                    else:
                        pendiente = nxt     # se procesará en la vuelta siguiente
                        break
            # Escritura: agrupar los caracteres consecutivos en una sola
            # llamada. Al escribir rápido se acumulan varios eventos 'type' y
            # cada uno costaba un proceso ydotool/xdotool completo.
            elif tipo == 'type':
                chars = [data.get('char', '')]
                while sum(len(c) for c in chars) < 64:
                    try:
                        nxt = _input_q.get_nowait()
                    except queue.Empty:
                        break
                    if nxt.get('type') == 'type':
                        chars.append(nxt.get('char', ''))
                    else:
                        pendiente = nxt
                        break
                if len(chars) > 1:
                    data = dict(data, char=''.join(chars))
            _procesar_input(data)
        except Exception:
            pass

threading.Thread(target=_input_worker, daemon=True, name='vigia-input').start()

def _get_pynput_key(key):
    try:
        from pynput.keyboard import Key
        m = {
            'enter': Key.enter, 'esc': Key.esc, 'tab': Key.tab, 'space': Key.space,
            'backspace': Key.backspace, 'delete': Key.delete, 'insert': Key.insert,
            'home': Key.home, 'end': Key.end, 'pageup': Key.page_up, 'pagedown': Key.page_down,
            'left': Key.left, 'right': Key.right, 'up': Key.up, 'down': Key.down,
            'ctrl': Key.ctrl, 'alt': Key.alt, 'shift': Key.shift, 'win': Key.cmd
        }
        return m.get(key.lower(), key)
    except: return key

# ── Configuración (valores por defecto, ajustables desde el dashboard) ───────
# Las miniaturas se ven en tarjetas de ~280 px (y en el modal a ~900 px): 960 px
# sobra para ambas y recorta ~45% de los bytes que cada alumno envía cada
# segundo — con 30 alumnos es lo que hacía ir a tirones la rejilla del panel.
ANCHO_IMAGEN      = 960
CALIDAD_JPEG      = 55
INTERVALO_SEG     = 1.0
REINTENTOS_ESPERA = 5
_LIVE_FPS_SLEEP   = 0.05     # ~20 fps JPEG fallback
_LIVE_QUALITY     = 70       # calidad JPEG en modo observación
_WEBRTC_FPS       = 30       # FPS objetivo WebRTC

# ── Estado ───────────────────────────────────────────────────────────────────
sio = sio_module.Client(reconnection=True, reconnection_attempts=0)
_cola_profesor      = queue.Queue(maxsize=2)
_cola_bloqueo       = queue.Queue(maxsize=10)
_cola_mensajes      = queue.Queue(maxsize=20)
_cola_clipboard_req = queue.Queue(maxsize=1)
_cola_clipboard_res = queue.Queue(maxsize=1)
_cola_overlay       = queue.Queue(maxsize=300)
_en_observacion = False
_webrtc_loop   = None   # event loop asyncio dedicado
_webrtc_pc     = None   # RTCPeerConnection activa
_webrtc_track  = None   # ScreenStreamTrack activo (cerrarlo libera la captura)
_webrtc_prof   = None   # prof_sid del profesor conectado
_webrtc_activo = False  # True cuando P2P establecido
_pending_ice   = []     # ICE candidates recibidos antes del offer

def _b64(jpeg: bytes) -> str:
    return 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode()


# ── Pantalla del profesor recibida como vídeo ────────────────────────────────
_cola_stream  = queue.Queue(maxsize=12)   # trozos codificados por descodificar
_stream_perdido = False                   # se descartó algo: esperar al próximo key
_prof_destino = [0, 0]                    # tamaño útil de la ventana del alumno


def _poner_profesor(item):
    """Encola un fotograma para la ventana del profesor, descartando el viejo."""
    try:
        _cola_profesor.put_nowait(item)
    except queue.Full:
        try:
            _cola_profesor.get_nowait()
            _cola_profesor.put_nowait(item)
        except Exception:
            pass


def _stream_put(item):
    global _stream_perdido
    try:
        _cola_stream.put_nowait(item)
    except queue.Full:
        # Perder un trozo rompe la cadena de fotogramas diferenciales: se marca
        # y el descodificador espera al siguiente fotograma clave (≤2 s) en vez
        # de pintar basura.
        _stream_perdido = True


def _bucle_stream_profesor():
    """Descodifica el vídeo de la pantalla del profesor y lo pasa a la ventana."""
    global _stream_perdido
    dec = None
    codec = 'h264'
    while True:
        item = _cola_stream.get()
        try:
            tipo = item[0]
            if tipo == 'start':
                codec = item[1]
                dec = None
                _stream_perdido = False
                continue
            if tipo == 'stop':
                dec = None
                _poner_profesor({'activa': False})
                continue

            _, datos, es_clave = item
            if es_clave:
                _stream_perdido = False
            elif dec is None or _stream_perdido:
                continue          # sin clave todavía: no hay nada que pintar
            if dec is None:
                dec = _av.CodecContext.create(codec, 'r')
                dec.thread_count = max(1, min(4, os.cpu_count() or 1))
            for frame in dec.decode(_av.Packet(datos)):
                ancho, alto = _prof_destino
                if ancho and alto and frame.width > ancho:
                    # swscale escala y convierte en una pasada; hacerlo aquí
                    # evita que PIL redimensione después en el hilo de Tk.
                    escala = min(ancho / frame.width, alto / frame.height)
                    frame = frame.reformat(
                        max(2, int(frame.width * escala)),
                        max(2, int(frame.height * escala)), 'rgb24')
                _poner_profesor({'activa': True, 'pil': frame.to_image()})
        except Exception as e:
            print(f"  [!] Vídeo del profesor: {e}")
            dec = None
            _stream_perdido = True


if _AV_OK:
    threading.Thread(target=_bucle_stream_profesor, daemon=True,
                     name='vigia-stream').start()

if WEBRTC_OK:
    class ScreenStreamTrack(VideoStreamTrack):
        kind = "video"
        _CLOCK_RATE = 90000
        _MAX_W      = 1920   # tope de anchura codificada (1080p)
        # Escalones de anchura para la adaptación automática. Si el equipo del
        # alumno no da abasto (captura + codificación más lentas que el objetivo
        # de fps), se baja un escalón: es preferible 1280p fluido a 1080p a
        # tirones. Al recuperar holgura se vuelve a subir.
        _ESCALONES  = (1920, 1600, 1280, 1024, 800)
        _BAJAR_SEG  = 4.0    # espera mínima antes de bajar un escalón
        _SUBIR_SEG  = 15.0   # subir cuesta más: evita el sube-y-baja constante
        _MUESTRAS   = 30     # frames de rodaje antes de hacer caso a la media
        _CONGELAR   = 60.0   # pausa de la adaptación cuando bajar no sirve

        @property
        def _TARGET_FPS(self):
            return max(1, _WEBRTC_FPS)

        def __init__(self):
            super().__init__()
            self._cap        = None   # backend de screen_capture
            self._t0         = None
            self._next       = 0.0    # instante previsto del próximo frame
            self._last_pts   = -1
            self._last_frame = None   # último frame válido; se sirve si la captura falla
            self._nivel      = 0      # índice en _ESCALONES
            self._ewma       = None   # media móvil del intervalo real entre frames
            self._ult_ajuste = 0.0
            self._ult_recv   = None
            self._muestras   = 0
            self._ewma_antes = None   # ritmo previo a la última bajada
            self._congelado  = 0.0    # instante hasta el que no se adapta
            self._congelar   = self._CONGELAR
            # Executor propio de un hilo: la captura no compite con otras tareas
            # del pool por defecto y los frames se producen siempre en orden.
            self._pool = ThreadPoolExecutor(max_workers=1,
                                            thread_name_prefix='vigia-cap')

        async def recv(self):
            loop = asyncio.get_event_loop()
            ahora = loop.time()
            if self._t0 is None:
                self._t0 = ahora
                self._next = ahora
                self._ult_ajuste = ahora
            periodo = 1.0 / self._TARGET_FPS

            espera = self._next - ahora
            if espera > 0:
                await asyncio.sleep(espera)
                ahora = loop.time()
            self._next += periodo
            # Si vamos con retraso (equipo lento), SALTAR los instantes perdidos
            # en vez de arrastrarlos: así no se acumula latencia.
            if self._next < ahora:
                self._next = ahora + periodo

            self._medir(ahora, periodo)
            frame = await loop.run_in_executor(self._pool, self._capturar)

            # PTS tomado del reloj REAL, no de un contador de frames. Con el
            # contador, un equipo que solo alcanzaba 15 de los 30 fps objetivo
            # marcaba los frames con el doble de duración de la que tenían: el
            # navegador los reproducía a cámara lenta y el retardo del control
            # remoto crecía sin parar. Con reloj real el vídeo va siempre «al
            # día» aunque caigan fps.
            pts = int((loop.time() - self._t0) * self._CLOCK_RATE)
            if pts <= self._last_pts:
                pts = self._last_pts + 1
            self._last_pts  = pts
            frame.pts       = pts
            frame.time_base = fractions.Fraction(1, self._CLOCK_RATE)
            return frame

        def _medir(self, ahora, periodo):
            """Vigila el ritmo real y ajusta la resolución si el equipo no llega.

            El intervalo entre llamadas a recv() incluye captura, escalado y
            codificación: es la medida directa de lo que aguanta el equipo.
            """
            if self._ult_recv is not None:
                dt = ahora - self._ult_recv
                base = periodo if self._ewma is None else self._ewma
                # Media lenta (memoria ~12 frames): un tirón puntual del equipo
                # no debe bastar para cambiar de resolución.
                self._ewma = base * 0.92 + dt * 0.08
                self._muestras += 1
            self._ult_recv = ahora
            # Rodaje: los primeros frames incluyen el arranque del encoder y de
            # la captura; decidir con ellos bajaba la resolución sin motivo.
            if self._muestras < self._MUESTRAS or ahora < self._congelado:
                return
            transcurrido = ahora - self._ult_ajuste
            nivel = self._nivel

            # ¿Sirvió de algo la última bajada? Si el cuello de botella no es la
            # resolución (p. ej. captura por spectacle a 2 fps, o el propio
            # compositor), seguir bajando solo empeora la imagen sin ganar
            # fluidez: se vuelve al escalón anterior y se deja de tocar un rato.
            if self._ewma_antes is not None and transcurrido >= self._BAJAR_SEG:
                mejoro = self._ewma < self._ewma_antes * 0.9
                self._ewma_antes = None
                if not mejoro:
                    self._congelado = ahora + self._congelar
                    # Cada intento fallido espera el doble: si el límite es la
                    # captura (o los fps pedidos superan lo que da el
                    # compositor), no tiene sentido reintentarlo cada minuto.
                    self._congelar = min(self._congelar * 2, 600.0)
                    self._cambiar_nivel(nivel - 1, ahora, periodo,
                                        'bajar no mejoró el ritmo')
                    return
                self._congelar = self._CONGELAR

            if self._ewma > periodo * 1.6 and nivel < len(self._ESCALONES) - 1 \
                    and transcurrido >= self._BAJAR_SEG:
                self._ewma_antes = self._ewma
                self._cambiar_nivel(nivel + 1, ahora, periodo,
                                    f'{1/max(1e-6, self._ewma):.0f} fps reales')
            elif self._ewma < periodo * 1.25 and nivel > 0 \
                    and transcurrido >= self._SUBIR_SEG:
                self._cambiar_nivel(nivel - 1, ahora, periodo,
                                    f'{1/max(1e-6, self._ewma):.0f} fps reales')

        def _cambiar_nivel(self, nivel, ahora, periodo, motivo):
            nivel = max(0, min(len(self._ESCALONES) - 1, nivel))
            if nivel == self._nivel:
                return
            self._nivel = nivel
            self._ult_ajuste = ahora
            self._ewma = periodo   # empezar de cero tras el cambio
            self._muestras = 0
            print(f"  [WebRTC] {motivo} → anchura {self._ESCALONES[nivel]} px")

        def _out_size(self, w, h):
            """Tamaño de salida: tope adaptativo y dimensiones pares (yuv420p)."""
            tope = min(self._MAX_W, self._ESCALONES[self._nivel])
            if w > tope:
                h = int(h * tope / w)
                w = tope
            return w & ~1, h & ~1

        def _a_frame(self, arr, fmt):
            """ndarray → av.VideoFrame yuv420p ya escalado.

            swscale (libav) hace conversión de color + escala en UN paso SIMD;
            el encoder VP8 de aiortc recibe yuv420p y no vuelve a convertir.
            Esto sustituye la cadena PIL resize → numpy → conversión del
            encoder, que consumía la CPU del alumno a 30 fps."""
            frame = av.VideoFrame.from_ndarray(arr, format=fmt)
            out_w, out_h = self._out_size(frame.width, frame.height)
            try:
                return frame.reformat(out_w, out_h, 'yuv420p',
                                      interpolation='FAST_BILINEAR')
            except (TypeError, ValueError):
                return frame.reformat(out_w, out_h, 'yuv420p')

        def _capturar(self):
            try:
                if self._cap is None:
                    self._cap = screen_capture.create_capturer(verbose=False)
                mon = self._cap.monitor()
                # Mantener offset/tamaño sincronizados para el mapeo de coordenadas
                global _mon_left, _mon_top, _mon_width, _mon_height, _mon_valido
                _mon_left = mon.get('left', 0)
                _mon_top  = mon.get('top',  0)
                _mon_width  = mon.get('width',  _mon_width)
                _mon_height = mon.get('height', _mon_height)
                _mon_valido = True
                if hasattr(self._cap, 'grab_raw'):
                    # Vía rápida (PipeWire en Wayland, mss en X11): frame BGRx
                    # crudo, sin PIL. Igual que RustDesk: captura nativa → swscale.
                    data, w, h, stride = self._cap.grab_raw()
                    arr = np.frombuffer(data, dtype=np.uint8)
                    if stride == w * 4:
                        arr = arr.reshape(h, w, 4)
                    else:  # filas con padding: compactar
                        arr = np.ascontiguousarray(
                            arr.reshape(h, stride)[:, :w * 4]).reshape(h, w, 4)
                    frame = self._a_frame(arr, 'bgra')
                else:
                    # Backends CLI (spectacle/grim): siguen entregando PIL
                    img = self._cap.grab()
                    frame = self._a_frame(np.asarray(img), 'rgb24')
                self._last_frame = frame
                return frame
            except Exception as e:
                print(f"  [WebRTC] Captura: {e}")
                if self._cap:
                    try: self._cap.close()
                    except: pass
                    self._cap = None
                # Devolver el último frame válido (imagen congelada) en lugar de negro
                if self._last_frame is not None:
                    return self._last_frame
                return self._a_frame(np.zeros((720, 1280, 3), dtype=np.uint8),
                                     'rgb24')

        def stop(self):
            super().stop()
            if self._cap:
                try: self._cap.close()
                except Exception: pass
                self._cap = None
            self._pool.shutdown(wait=False)

def _asyncio_runner():
    global _webrtc_loop
    _webrtc_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_webrtc_loop)
    _webrtc_loop.run_forever()

def _wrtc(coro):
    """Encola una coroutine en el loop asyncio desde threads síncronos."""
    if _webrtc_loop and _webrtc_loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, _webrtc_loop)

def bucle_capturas():
    _ultimo_screenshot = 0.0
    _aviso_captura = 0.0
    cap = None
    while True:
        if not sio.connected:
            time.sleep(0.5); continue
        if cap is None:
            try:
                cap = screen_capture.create_capturer()
            except Exception as e:
                # Avisar como mucho una vez por minuto para no inundar el log
                if time.monotonic() - _aviso_captura > 60:
                    print(f"  [!] Captura de pantalla no disponible: {e}")
                    _aviso_captura = time.monotonic()
                time.sleep(5); continue

        now = time.monotonic()
        try:
            monitor = cap.monitor()
            orig_w, orig_h = monitor['width'], monitor['height']
            # Actualizar offset global del monitor para el mapeo de coordenadas
            global _mon_left, _mon_top, _mon_width, _mon_height, _mon_valido
            _mon_left = monitor.get('left', 0)
            _mon_top  = monitor.get('top',  0)
            _mon_width  = orig_w
            _mon_height = orig_h
            _mon_valido = True

            if (now - _ultimo_screenshot) >= INTERVALO_SEG:
                # max_age: si WebRTC acaba de capturar un frame, se reaprovecha
                # en lugar de pedir otro al compositor (y de pelearse con él por
                # el appsink de PipeWire, que solo guarda el último frame).
                img = screen_capture.grab_shared(cap, max_age=INTERVALO_SEG * 0.5)
                if img.width > ANCHO_IMAGEN:
                    # BILINEAR con reducing_gap: prefiltra por bloques y luego
                    # interpola. Calidad casi idéntica a LANCZOS para una
                    # miniatura y ~5× más rápido (esto corría en cada alumno
                    # una vez por segundo, compitiendo con el vídeo en vivo).
                    alto = max(1, int(img.height * ANCHO_IMAGEN / img.width))
                    img = img.resize((ANCHO_IMAGEN, alto), Image.BILINEAR,
                                     reducing_gap=2.0)
                buf = io.BytesIO(); img.save(buf, format='JPEG', quality=CALIDAD_JPEG)
                sio.emit('screenshot', {'image': _b64(buf.getvalue())})
                _ultimo_screenshot = now

            if _en_observacion and not _webrtc_activo:
                img = cap.grab()
                ancho_r = min(orig_w, 1280)
                if img.width > ancho_r:
                    img = img.resize((ancho_r, int(img.height * ancho_r / img.width)), Image.BILINEAR)
                buf = io.BytesIO(); img.save(buf, format='JPEG', quality=_LIVE_QUALITY)
                sio.emit('remote_frame', {'image': _b64(buf.getvalue()), 'orig_w': orig_w, 'orig_h': orig_h})
                time.sleep(_LIVE_FPS_SLEEP)
            else:
                time.sleep(0.2)
        except:
            try: cap.close()
            except: pass
            cap = None; time.sleep(1)

# ── Manejo de entrada ─────────────────────────────────────────────────────────

def _procesar_input_ydo(tipo, data, x, y):
    """Ejecuta un evento de entrada vía ydotool (sesiones Wayland)."""
    if tipo == 'mousemove':
        _ydo_sync('mousemove', '-a', '-x', x, '-y', y)
        return
    if tipo == 'scroll':
        dy = int(data.get('dy', 0))
        _ydo_sync('mousemove', '-w', '-x', 0, '-y', dy)
        return
    btn = _BTN_MAP_YDO.get(data.get('button', 'left'), 0x00)
    if tipo == 'mousedown':
        _ydo_sync('mousemove', '-a', '-x', x, '-y', y)
        _ydo_sync('click', f'{0x40 | btn:#04x}')
        return
    if tipo == 'mouseup':
        _ydo_sync('click', f'{0x80 | btn:#04x}')
        return
    if tipo == 'type':
        char = data.get('char', '')
        if char:
            _ydo_sync('type', *_YDO_TYPE_ARGS, '--', char)
        return
    if tipo in ('keypress', 'keydown', 'keyup'):
        code = _YDO_KEY_MAP.get(data.get('key', '').lower())
        if code is None:
            return
        if tipo == 'keypress':
            _ydo_sync('key', f'{code}:1', f'{code}:0')
        elif tipo == 'keydown':
            _ydo_sync('key', f'{code}:1')
        else:
            _ydo_sync('key', f'{code}:0')
        return
    if tipo == 'keycombo':
        combo = data.get('combo', '')
        codes = [_YDO_KEY_MAP.get(p.lower()) for p in combo.split('+') if p]
        if not codes or None in codes:
            return
        args = [f'{c}:1' for c in codes] + [f'{c}:0' for c in reversed(codes)]
        _ydo_sync('key', *args)


def _procesar_pointer_vigia(tipo, data):
    """Enruta eventos de ratón al demonio uinput absoluto (vigia_input).

    El dashboard envía x,y en píxeles del frame capturado (0..ancho_monitor).
    Se normaliza a 0..ABS_MAX, que KWin mapea a toda la pantalla → mapeo 1:1
    (sin el salto a la esquina de ydotool). Devuelve True si se inyectó.
    """
    try:
        px = int(data.get('x', 0)); py = int(data.get('y', 0))
    except (TypeError, ValueError):
        px = py = 0
    w = _mon_width or 1920
    h = _mon_height or 1080
    xn = max(0, min(_VI_ABS_MAX, round(px * _VI_ABS_MAX / max(1, w))))
    yn = max(0, min(_VI_ABS_MAX, round(py * _VI_ABS_MAX / max(1, h))))
    if tipo == 'mousemove':
        return _VIGIA_INPUT.move(xn, yn)
    if tipo == 'scroll':
        _VIGIA_INPUT.move(xn, yn)
        return _VIGIA_INPUT.scroll(int(data.get('dy', 0)))
    if tipo == 'mousedown':
        _VIGIA_INPUT.move(xn, yn)
        return _VIGIA_INPUT.button(data.get('button', 'left'), 1)
    if tipo == 'mouseup':
        return _VIGIA_INPUT.button(data.get('button', 'left'), 0)
    return False


def _vi_teclado_disponible():
    """True si el demonio uinput acepta teclas.

    Reintenta el saludo cada 30 s: el demonio `vigia-input` puede arrancar
    DESPUÉS que el cliente (carrera típica en el arranque de la sesión), y sin
    reintento el teclado se quedaría en ydotool hasta reiniciar el cliente.
    """
    global _VI_TECLADO, _VI_KB_PROBE
    if _VI_TECLADO:
        return True
    if not (_ES_WAYLAND and _VIGIA_INPUT is not None):
        return False
    ahora = time.monotonic()
    if ahora - _VI_KB_PROBE < 30.0:
        return False
    _VI_KB_PROBE = ahora
    try:
        _VI_TECLADO = 'kb' in _VIGIA_INPUT.features()
    except Exception:
        _VI_TECLADO = False
    return _VI_TECLADO


def _procesar_teclado_vigia(tipo, data):
    """Inyecta teclas por el demonio uinput (Wayland). True si se inyectó.

    Usa los mismos códigos de kernel que ydotool, así que el comportamiento es
    idéntico — pero sin lanzar un proceso por pulsación. Las teclas que no estén
    en el mapa se devuelven como no tratadas para que las haga ydotool.
    """
    if tipo in ('keypress', 'keydown', 'keyup'):
        code = _YDO_KEY_MAP.get(data.get('key', '').lower())
        if code is None:
            return False
        if tipo == 'keypress':
            return bool(_VIGIA_INPUT.key(code, 1) and _VIGIA_INPUT.key(code, 0))
        return _VIGIA_INPUT.key(code, 1 if tipo == 'keydown' else 0)
    if tipo == 'keycombo':
        codes = [_YDO_KEY_MAP.get(p.lower())
                 for p in data.get('combo', '').split('+') if p]
        if not codes or None in codes:
            return False
        ok = True
        for c in codes:
            ok = _VIGIA_INPUT.key(c, 1) and ok
        for c in reversed(codes):
            ok = _VIGIA_INPUT.key(c, 0) and ok
        return ok
    return False


def _procesar_input(data):
    """Ejecuta un evento de entrada. Llamar SOLO desde el hilo _input_worker."""
    tipo = data.get('type', '')
    try:
        # Sumar offset del monitor para convertir coords relativas al monitor
        # capturado en coordenadas absolutas del espacio virtual X11
        x = int(data.get('x', 0)) + _mon_left
        y = int(data.get('y', 0)) + _mon_top
    except:
        x = y = 0

    # Ratón en Wayland: SIEMPRE vía vigia_input (uinput absoluto). Si el demonio
    # estuviera caído, _send devuelve False y caemos a ydotool/pynput.
    if _VIGIA_INPUT is not None and tipo in (
            'mousemove', 'mousedown', 'mouseup', 'scroll'):
        if _procesar_pointer_vigia(tipo, data):
            return

    # Teclas por el mismo demonio uinput si lo soporta: ahorra un fork+exec de
    # ydotool por pulsación (lo que hacía «pegajoso» escribir en remoto).
    if tipo in ('keypress', 'keydown', 'keyup', 'keycombo') \
            and _vi_teclado_disponible():
        if _procesar_teclado_vigia(tipo, data):
            return

    # En Wayland, ydotool inyecta teclado (y ratón solo como fallback)
    if _YDO_CMD:
        _procesar_input_ydo(tipo, data, x, y)
        return

    # ── ratón ─────────────────────────────────────────────────────────────────
    if tipo == 'mousemove':
        if _mouse_ctrl:
            try: _mouse_ctrl.position = (x, y); return
            except: pass
        if _XDO_CMD:
            # No --sync: fire-and-forget is faster; X11 processes these in order anyway
            _xdo_sync('mousemove', x, y)
        return

    if tipo == 'scroll':
        dy = int(data.get('dy', 0))
        if _mouse_ctrl:
            try: _mouse_ctrl.position = (x, y); _mouse_ctrl.scroll(0, dy); return
            except Exception as e: print(f"  [!] pynput scroll: {e}")
        if _XDO_CMD:
            btn = 4 if dy > 0 else 5
            _xdo_sync('mousemove', x, y)
            for _ in range(abs(dy) or 1): _xdo_sync('click', btn)
        return

    _btn_map_pyn = {'left': _PBtn.left, 'middle': _PBtn.middle, 'right': _PBtn.right} if _PBtn else {}
    button = data.get('button', 'left')

    if tipo == 'mousedown':
        mods = data.get('mods', [])
        if _mouse_ctrl and _PBtn:
            try: _mouse_ctrl.position = (x, y); _mouse_ctrl.press(_btn_map_pyn.get(button, _PBtn.left)); return
            except Exception as e: print(f"  [!] pynput mousedown: {e}")
        if _XDO_CMD:
            _xdo_sync('mousemove', x, y)
            for m in mods: _xdo_sync('keydown', m)
            _xdo_sync('mousedown', _BTN_MAP_XDO.get(button, 1))
            for m in reversed(mods): _xdo_sync('keyup', m)
        return

    if tipo == 'mouseup':
        if _mouse_ctrl and _PBtn:
            try: _mouse_ctrl.position = (x, y); _mouse_ctrl.release(_btn_map_pyn.get(button, _PBtn.left)); return
            except Exception as e: print(f"  [!] pynput mouseup: {e}")
        if _XDO_CMD:
            _xdo_sync('mousemove', x, y)
            _xdo_sync('mouseup', _BTN_MAP_XDO.get(button, 1))
        return

    # ── teclado ───────────────────────────────────────────────────────────────
    if tipo == 'type':
        char = data.get('char', '')
        if not char: return
        if _XDO_CMD:
            _xdo_sync('type', '--clearmodifiers', '--delay', '0', '--', char); return
        if _kbd_ctrl:
            try: _kbd_ctrl.type(char)
            except Exception as e: print(f"  [!] pynput type: {e}")
        return

    if tipo == 'keypress':
        k = _XDO_KEY_MAP.get(data.get('key', '').lower(), data.get('key'))
        if _XDO_CMD:
            _xdo_sync('key', '--clearmodifiers', k); return
        if _kbd_ctrl:
            pk = _get_pynput_key(data.get('key'))
            try: _kbd_ctrl.press(pk); _kbd_ctrl.release(pk)
            except Exception as e: print(f"  [!] pynput keypress: {e}")
        return

    if tipo == 'keycombo':
        combo = data.get('combo', '')
        if not combo: return
        if _XDO_CMD:
            _xdo_sync('key', combo); return
        if _kbd_ctrl:
            parts = combo.split('+')
            keys  = [_get_pynput_key(p) for p in parts]
            try:
                for k in keys:            _kbd_ctrl.press(k)
                for k in reversed(keys): _kbd_ctrl.release(k)
            except Exception as e: print(f"  [!] pynput keycombo: {e}")
        return

    if tipo == 'keydown':
        k = _XDO_KEY_MAP.get(data.get('key', '').lower(), data.get('key'))
        if _XDO_CMD:
            _xdo_sync('keydown', k); return
        if _kbd_ctrl:
            try: _kbd_ctrl.press(_get_pynput_key(data.get('key')))
            except Exception as e: print(f"  [!] pynput keydown: {e}")
        return

    if tipo == 'keyup':
        k = _XDO_KEY_MAP.get(data.get('key', '').lower(), data.get('key'))
        if _XDO_CMD:
            _xdo_sync('keyup', k); return
        if _kbd_ctrl:
            try: _kbd_ctrl.release(_get_pynput_key(data.get('key')))
            except Exception as e: print(f"  [!] pynput keyup: {e}")


_last_mouse_time = 0.0
_MOUSE_THROTTLE  = 0.01   # 100 Hz maximum for mousemove events

@sio.on('do_input')
def on_do_input(data):
    """Encola el evento; el hilo vigia-input lo ejecuta en orden estricto."""
    global _last_mouse_time
    tipo = data.get('type', '')
    if tipo.startswith('overlay_'):
        # El overlay usa subproceso GTK independiente de TK_OK
        try:
            _cola_overlay.put_nowait(data)
        except queue.Full:
            try:
                _cola_overlay.get_nowait()
                _cola_overlay.put_nowait(data)
            except Exception:
                pass
        return
    if not INPUT_OK:
        return
    if tipo == 'mousemove':
        # Throttle to 100 Hz max; excess events dropped before reaching the queue
        now = time.monotonic()
        if now - _last_mouse_time < _MOUSE_THROTTLE:
            return
        _last_mouse_time = now
        try: _input_q.put_nowait(data)
        except queue.Full: pass
    else:
        # Clicks y teclado: pequeño timeout para no perderlos
        try: _input_q.put(data, timeout=0.05)
        except queue.Full: pass

# ── Eventos Socket.IO ─────────────────────────────────────────────────────────
@sio.event
def connect():
    print(f"[✓] Conectado al servidor.")
    # 'caps' anuncia lo que sabe hacer este alumno; el panel solo emite su
    # pantalla como vídeo si TODOS los destinatarios saben descodificarlo.
    sio.emit('register', {
        'name': f"{platform_utils.get_username()} - {socket.gethostname()}",
        'caps': {'vstream': _AV_OK},
    })

@sio.on('viewer_start')
def on_viewer_start(data):
    global _en_observacion; _en_observacion = True
    print(f"[*] El profesor está observando/controlando.")
    # Enviar resolución real de pantalla para que el profesor mapee coordenadas
    # correctamente. Se usa la geometría que ya conoce el bucle de captura: abrir
    # un capturador nuevo aquí costaba un handshake completo del portal
    # ScreenCast (~0,5 s) justo al pulsar «ver/controlar».
    try:
        global _mon_left, _mon_top
        if _mon_valido:
            sio.emit('screen_info', {'w': _mon_width, 'h': _mon_height})
        else:
            _mon = screen_capture.get_monitor_geometry()
            _mon_left = _mon.get('left', 0)
            _mon_top  = _mon.get('top',  0)
            sio.emit('screen_info', {'w': _mon['width'], 'h': _mon['height']})
    except Exception:
        pass

@sio.on('viewer_stop')
def on_viewer_stop(_data):
    global _en_observacion; _en_observacion = False
    print(f"[*] Fin de observación.")
    try:
        _cola_overlay.put_nowait({'type': 'overlay_toggle', 'enabled': False})
    except Exception:
        pass
    if WEBRTC_OK:
        _wrtc(_cerrar_webrtc())

@sio.on('quit_app')
def on_quit_app(_data):
    platform_utils.shutdown_system()

@sio.on('show_message')
def on_show_message(data): _cola_mensajes.put_nowait(data)

@sio.on('lock_screen')
def on_lock_screen(_data): _cola_bloqueo.put_nowait(True)

@sio.on('unlock_screen')
def on_unlock_screen(_data): _cola_bloqueo.put_nowait(False)

@sio.on('config_update')
def on_config_update(data):
    global INTERVALO_SEG, CALIDAD_JPEG, _LIVE_FPS_SLEEP, _LIVE_QUALITY, _WEBRTC_FPS
    INTERVALO_SEG  = float(data.get('thumb_interval', INTERVALO_SEG))
    CALIDAD_JPEG   = int(data.get('thumb_quality', CALIDAD_JPEG))
    live_fps       = int(data.get('live_fps', 20))
    _LIVE_FPS_SLEEP = 1.0 / max(1, live_fps)
    _LIVE_QUALITY  = int(data.get('live_quality', _LIVE_QUALITY))
    _WEBRTC_FPS    = int(data.get('webrtc_fps', _WEBRTC_FPS))
    print(f"[*] Config actualizada: intervalo={INTERVALO_SEG}s, "
          f"live={live_fps}fps, webrtc={_WEBRTC_FPS}fps")

@sio.on('teacher_screen')
def on_teacher_screen(data):
    _poner_profesor(data)

@sio.on('teacher_stream_start')
def on_teacher_stream_start(data):
    if not _AV_OK:
        return
    codec = 'vp8' if str(data.get('codec', 'h264')).lower() == 'vp8' else 'h264'
    print(f"[*] Pantalla del profesor por vídeo {codec.upper()} "
          f"{data.get('w')}x{data.get('h')}")
    _stream_put(('start', codec))

@sio.on('teacher_stream_chunk')
def on_teacher_stream_chunk(data):
    if not _AV_OK:
        return
    datos = data.get('d')
    if isinstance(datos, (bytes, bytearray, memoryview)):
        _stream_put(('chunk', bytes(datos), bool(data.get('k'))))

@sio.on('teacher_stream_stop')
def on_teacher_stream_stop(_data=None):
    if _AV_OK:
        _stream_put(('stop',))
    else:
        _poner_profesor({'activa': False})

@sio.on('exec_command')
def on_exec_command(data):
    global _term_cwd
    cmd = data.get('command', '').strip()
    cmd_id = data.get('cmd_id', '')
    if not cmd:
        return
    stdout, stderr, returncode, _term_cwd = platform_utils.run_shell(cmd, _term_cwd)
    sio.emit('command_output', {
        'cmd_id': cmd_id,
        'command': cmd,
        'stdout': stdout[-6000:],
        'stderr': stderr[-3000:],
        'returncode': returncode,
        'cwd': _term_cwd,
    })

@sio.on('get_clipboard')
def on_get_clipboard(_data):
    text = platform_utils.get_clipboard_text(_xdo_env)
    # Fallback: portapapeles vía tkinter (hilo principal)
    if not text and TK_OK:
        try:
            # Vaciar respuesta anterior
            while not _cola_clipboard_res.empty():
                _cola_clipboard_res.get_nowait()
            _cola_clipboard_req.put_nowait(True)
            text = _cola_clipboard_res.get(timeout=2)
        except Exception:
            pass
    sio.emit('clipboard_data', {'text': text})

# ── WebRTC Socket.IO handlers ─────────────────────────────────────────────────
if WEBRTC_OK:
    @sio.on('webrtc_offer')
    def on_webrtc_offer(data):
        _wrtc(_procesar_offer(data))

    def _preferir_h264(pc):
        """Pone H.264 delante de VP8 en la negociación de códecs.

        aiortc respeta el orden que propone el navegador (Chrome pone VP8
        primero) salvo que el transceiver declare preferencias. VP8 queda al
        final de la lista, así que si el navegador no ofreciera H.264 —una
        compilación de Chromium sin códecs propietarios— la negociación sigue
        funcionando con VP8. Debe llamarse ANTES de setRemoteDescription.
        """
        if not WEBRTC_H264:
            return
        try:
            from aiortc import RTCRtpSender
            caps = RTCRtpSender.getCapabilities('video').codecs
            h264 = [c for c in caps if c.mimeType.lower() == 'video/h264']
            resto = [c for c in caps if c.mimeType.lower() != 'video/h264']
            if not h264:
                return
            for t in pc.getTransceivers():
                if t.kind == 'video':
                    t.setCodecPreferences(h264 + resto)
        except Exception as e:
            print(f"  [!] No se pudo preferir H.264: {e}")

    async def _procesar_offer(data):
        global _webrtc_pc, _webrtc_track, _webrtc_prof, _webrtc_activo, _pending_ice
        if _webrtc_pc:
            await _webrtc_pc.close()
        if _webrtc_track:
            try: _webrtc_track.stop()
            except Exception: pass
        _webrtc_pc = None; _webrtc_track = None; _webrtc_activo = False

        prof_sid = data.get('prof_sid')
        _webrtc_prof = prof_sid

        pc = RTCPeerConnection()
        _webrtc_pc = pc
        _webrtc_track = ScreenStreamTrack()
        pc.addTrack(_webrtc_track)
        _preferir_h264(pc)

        @pc.on("datachannel")
        def on_dc(channel):
            # Acepta ambos canales: vigia-mouse (ratón, UDP-like) y vigia-input (teclado, fiable)
            @channel.on("message")
            def on_msg(msg):
                try: on_do_input(json.loads(msg))
                except Exception: pass

        @pc.on("icecandidate")
        def on_ice(cand):
            if cand:
                sio.emit('webrtc_ice', {
                    'prof_sid': prof_sid,
                    'candidate': {
                        'candidate':     cand.candidate,
                        'sdpMid':        cand.sdpMid,
                        'sdpMLineIndex': cand.sdpMLineIndex,
                    }
                })

        @pc.on("iceconnectionstatechange")
        async def on_ice_state():
            global _webrtc_activo
            state = pc.iceConnectionState
            if state == "connected":
                _webrtc_activo = True
                # Aumentar bitrate del encoder VP8 para mejor calidad de imagen
                try:
                    for sender in pc.getSenders():
                        if sender.track and sender.track.kind == 'video':
                            params = sender.getParameters()
                            if params.encodings:
                                params.encodings[0].maxBitrate = 4_000_000  # 4 Mbps
                                await sender.setParameters(params)
                except Exception:
                    pass  # API no disponible en esta versión de aiortc → bitrate por defecto
            elif state in ("failed", "closed", "disconnected"):
                _webrtc_activo = False

        await pc.setRemoteDescription(RTCSessionDescription(**data['sdp']))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        sio.emit('webrtc_answer', {
            'prof_sid': prof_sid,
            'sdp': {'sdp': pc.localDescription.sdp, 'type': pc.localDescription.type}
        })
        for c in _pending_ice:
            await _add_ice(c)
        _pending_ice.clear()

    @sio.on('webrtc_ice')
    def on_webrtc_ice(data):
        c = data.get('candidate')
        if not c: return
        if _webrtc_pc: _wrtc(_add_ice(c))
        else: _pending_ice.append(c)

    async def _add_ice(c):
        from aioice.candidate import Candidate as AioiceCand
        try:
            raw = c.get('candidate', '').replace('candidate:', '', 1)
            if not raw: return
            ac = AioiceCand.from_sdp(raw)
            from aiortc import RTCIceCandidate
            rtc_c = RTCIceCandidate(
                component=ac.component, foundation=ac.foundation,
                ip=ac.host, port=ac.port, priority=ac.priority,
                protocol=ac.transport.lower(), type=ac.type,
                sdpMid=c.get('sdpMid'), sdpMLineIndex=c.get('sdpMLineIndex'),
            )
            if _webrtc_pc: await _webrtc_pc.addIceCandidate(rtc_c)
        except Exception:
            pass  # Candidatos inválidos/tardíos: ignorar silenciosamente

    async def _cerrar_webrtc():
        global _webrtc_pc, _webrtc_track, _webrtc_activo, _webrtc_prof
        if _webrtc_pc: await _webrtc_pc.close()
        if _webrtc_track:
            try: _webrtc_track.stop()
            except Exception: pass
        _webrtc_pc = None; _webrtc_track = None
        _webrtc_activo = False; _webrtc_prof = None

# ── Overlay pizarra (cliente) ───────────────────────────────────────────────
# Click-through ahora delegado a platform_utils.set_clickthrough()

# ── Interfaz UI ──────────────────────────────────────────────────────────────
class _VentanaProfesor:
    def __init__(self, root):
        self.top = tk.Toplevel(root); self.top.title("📺 Pantalla del Profesor"); self.top.configure(bg='#0f1117')
        if platform_utils.IS_WINDOWS:
            self.top.state('zoomed')
        else:
            self.top.attributes('-zoomed', True)
        self.top.attributes('-topmost', True)
        self._label = tk.Label(self.top, bg='#0f1117', text="⏳ Esperando imagen…", fg='#718096', font=('Segoe UI', 12))
        self._label.pack(expand=True, fill='both')
        self._foto = None
        self._img_raw = None   # PIL Image original sin redimensionar
        # Tamaño de partida para el descodificador hasta que llegue <Configure>
        # (la ventana se abre maximizada).
        _prof_destino[0] = self.top.winfo_screenwidth()
        _prof_destino[1] = self.top.winfo_screenheight()
        self._after_id = None  # ID del after de redibujado pendiente
        self.top.protocol("WM_DELETE_WINDOW", self.destruir)
        self.top.bind('<Configure>', self._on_resize)

    def _on_resize(self, event):
        # Publicar el tamaño útil para que el descodificador de vídeo escale
        # con swscale (una pasada SIMD) en vez de dejárselo a PIL aquí.
        _prof_destino[0] = max(self.top.winfo_width(), 1)
        _prof_destino[1] = max(self.top.winfo_height(), 1)
        if self._img_raw is None: return
        if self._after_id: self.top.after_cancel(self._after_id)
        self._after_id = self.top.after(120, self._render)

    def _render(self):
        self._after_id = None
        if self._img_raw is None: return
        try:
            w = max(self.top.winfo_width(), 1)
            h = max(self.top.winfo_height(), 1)
            img = self._img_raw
            # Escalar solo si hace falta de verdad. Redimensionar con LANCZOS en
            # CADA frame (10 fps) se comía un núcleo del equipo del alumno y
            # dejaba la imagen del profesor a tirones; BILINEAR sobre una imagen
            # que ya viene casi al tamaño de la ventana es visualmente igual.
            escala = min(w / img.width, h / img.height)
            if escala < 0.98:
                destino = (max(1, int(img.width * escala)),
                           max(1, int(img.height * escala)))
                img = img.resize(destino, Image.BILINEAR, reducing_gap=2.0)
            self._foto = ImageTk.PhotoImage(img)
            self._label.config(image=self._foto, text='')
        except: pass

    def actualizar_pil(self, img):
        """Fotograma ya descodificado (vía vídeo comprimido): solo pintarlo."""
        self._img_raw = img
        self._render()

    def actualizar(self, b64):
        try:
            if not b64 or ',' not in b64:
                return
            img = Image.open(io.BytesIO(base64.b64decode(b64.split(',', 1)[1])))
            # draft(): el decodificador JPEG entrega la imagen ya reducida (1/2,
            # 1/4…) directamente desde los coeficientes DCT. Descomprimir a
            # tamaño completo para luego encoger era el grueso del coste.
            w = max(self.top.winfo_width(), 1)
            h = max(self.top.winfo_height(), 1)
            try:
                img.draft('RGB', (w, h))
            except Exception:
                pass
            img.load()
            self._img_raw = img
            self._render()
        except Exception as e:
            print(f"  [!] Error actualizando pantalla del profesor: {e}")

    def destruir(self): self.top.destroy()

def _render_html_mensaje(txt, html_src):
    """Renderiza un subconjunto de HTML (negrita, cursiva, subrayado, listas,
    enlaces, títulos, colores) en un tk.Text usando tags de estilo.
    Es el formato que genera el compositor contenteditable del dashboard."""
    from html.parser import HTMLParser

    class _R(HTMLParser):
        _H = {'h1': 20, 'h2': 17, 'h3': 15, 'h4': 13}

        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.bold = 0; self.italic = 0; self.under = 0
            self.strike = 0; self.mono = 0; self.pre = 0
            self.sizes = [12]; self.colors = ['#e2e8f0']
            self.lists = []          # [tipo, contador] por nivel (ul/ol)
            self.href = None; self._nlink = 0
            self.elems = []          # pila (tag, ops_de_deshacer)
            self.tags = {}           # estilo → nombre de tag ya configurado

        def _linestart(self):
            return txt.index('end-1c').split('.')[1] == '0'

        def _nl(self):
            if not self._linestart():
                txt.insert('end', '\n')

        def _emit(self, s):
            if not s:
                return
            key = (self.bold > 0, self.italic > 0, self.under > 0,
                   self.strike > 0, self.mono > 0, self.sizes[-1], self.colors[-1])
            name = self.tags.get(key)
            if name is None:
                name = f'st{len(self.tags)}'
                fam = 'DejaVu Sans Mono' if self.mono else 'Segoe UI'
                style = (('bold ' if self.bold else '') +
                         ('italic' if self.italic else '')).strip() or 'normal'
                color = self.colors[-1]
                try: txt.winfo_rgb(color)
                except Exception: color = '#e2e8f0'
                txt.tag_configure(name, font=(fam, self.sizes[-1], style),
                                  foreground=color,
                                  underline=bool(self.under),
                                  overstrike=bool(self.strike))
                self.tags[key] = name
            tags = (name,)
            if self.href:
                ln = f'lnk{self._nlink}'; self._nlink += 1
                txt.tag_configure(ln, foreground='#6ea8ff', underline=True)
                url = self.href
                txt.tag_bind(ln, '<Button-1>',
                             lambda _e, u=url: __import__('webbrowser').open(u))
                txt.tag_bind(ln, '<Enter>', lambda _e: txt.config(cursor='hand2'))
                txt.tag_bind(ln, '<Leave>', lambda _e: txt.config(cursor=''))
                tags = (name, ln)
            txt.insert('end', s, tags)

        @staticmethod
        def _color_de(attrs):
            c = attrs.get('color')
            m = re.search(r'(?:^|;)\s*color\s*:\s*([^;]+)', attrs.get('style', ''))
            if m: c = m.group(1).strip()
            if not c: return None
            m = re.match(r'rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', c)
            if m: c = '#%02x%02x%02x' % tuple(int(v) for v in m.groups())
            return c

        def handle_starttag(self, tag, attrs):
            a = dict(attrs); undo = []
            if tag in ('b', 'strong'): self.bold += 1; undo.append('bold')
            elif tag in ('i', 'em'): self.italic += 1; undo.append('italic')
            elif tag in ('u', 'ins'): self.under += 1; undo.append('under')
            elif tag in ('s', 'strike', 'del'): self.strike += 1; undo.append('strike')
            elif tag in ('code', 'tt', 'kbd'): self.mono += 1; undo.append('mono')
            elif tag == 'pre':
                self._nl(); self.mono += 1; self.pre += 1
                undo += ['mono', 'pre']
            elif tag in self._H:
                self._nl(); self.bold += 1; self.sizes.append(self._H[tag])
                undo += ['bold', 'size']
            elif tag in ('p', 'div', 'blockquote', 'tr'):
                self._nl()
            elif tag == 'br':
                txt.insert('end', '\n')
            elif tag in ('ul', 'ol'):
                self._nl(); self.lists.append([tag, 0]); undo.append('list')
            elif tag == 'li':
                self._nl()
                indent = '   ' * max(0, len(self.lists) - 1)
                if self.lists and self.lists[-1][0] == 'ol':
                    self.lists[-1][1] += 1
                    self._emit(f'{indent}{self.lists[-1][1]}. ')
                else:
                    self._emit(f'{indent}• ')
            elif tag == 'a':
                self.href = a.get('href'); undo.append('href')
            c = self._color_de(a)
            if c:
                self.colors.append(c); undo.append('color')
            self.elems.append((tag, undo))

        def handle_endtag(self, tag):
            for i in range(len(self.elems) - 1, -1, -1):
                if self.elems[i][0] == tag:
                    _t, undo = self.elems.pop(i)
                    for op in undo:
                        if op == 'bold': self.bold -= 1
                        elif op == 'italic': self.italic -= 1
                        elif op == 'under': self.under -= 1
                        elif op == 'strike': self.strike -= 1
                        elif op == 'mono': self.mono -= 1
                        elif op == 'pre': self.pre -= 1
                        elif op == 'size': self.sizes.pop()
                        elif op == 'color': self.colors.pop()
                        elif op == 'list': self.lists and self.lists.pop()
                        elif op == 'href': self.href = None
                    break
            if tag in ('p', 'div', 'blockquote', 'tr', 'li', 'ul', 'ol',
                       'pre', 'h1', 'h2', 'h3', 'h4'):
                self._nl()

        def handle_data(self, data):
            if self.pre:
                self._emit(data)
                return
            s = re.sub(r'\s+', ' ', data)
            if s == ' ' and self._linestart():
                return
            if self._linestart():
                s = s.lstrip()
            self._emit(s)

    _R().feed(html_src)


class _VentanaMensaje:
    def __init__(self, root, msg):
        import pathlib
        t = tk.Toplevel(root)
        t.title(msg.get('title', 'Mensaje'))
        t.configure(bg='#1a1d27')
        t.attributes('-topmost', True)
        c = tk.Frame(t, bg='#1a1d27', padx=20, pady=20)
        c.pack()
        body_html = msg.get('body', '')
        body_text = re.sub(r'<[^>]+>', '', body_html).strip()
        if body_text:
            txt = tk.Text(c, bg='#1a1d27', fg='#e2e8f0', font=('Segoe UI', 12),
                          wrap='word', height=6, width=52, relief='flat',
                          highlightthickness=0)
            try:
                _render_html_mensaje(txt, body_html)
            except Exception:
                txt.delete('1.0', 'end')
                txt.insert('end', body_text)
            # Altura adaptativa al contenido renderizado
            lineas = int(txt.index('end-1c').split('.')[0])
            txt.config(height=max(3, min(18, lineas + 1)), state='disabled')
            txt.pack()
        adjuntos = msg.get('attachments', [])
        if adjuntos:
            descargas = platform_utils.get_downloads_dir()
            tk.Label(c, text='📎 Archivos adjuntos recibidos:', bg='#1a1d27',
                     fg='#718096', font=('Segoe UI', 9)).pack(
                         anchor='w', pady=(10 if body_text else 0, 4))
            for att in adjuntos:
                try:
                    dest = descargas / att['name']
                    counter = 1
                    while dest.exists():
                        p = pathlib.Path(att['name'])
                        dest = descargas / f"{p.stem}_{counter}{p.suffix}"
                        counter += 1
                    dest.write_bytes(base64.b64decode(att['data']))
                    def _abrir(p=dest):
                        platform_utils.open_file(p)
                    fila = tk.Frame(c, bg='#1a1d27')
                    fila.pack(fill='x', pady=2)
                    tk.Button(fila, text=f'📄 {att["name"]}', bg='#252840', fg='#e2e8f0',
                              font=('Segoe UI', 9), relief='flat', anchor='w',
                              command=_abrir).pack(side='left')
                    tk.Label(fila, text=f'→ {dest}', bg='#1a1d27', fg='#718096',
                             font=('Segoe UI', 7)).pack(side='left', padx=(6, 0))
                except Exception as exc:
                    tk.Label(c, text=f'⚠ Error al guardar {att.get("name", "?")}: {exc}',
                             bg='#1a1d27', fg='#fc8181', font=('Segoe UI', 8)).pack(anchor='w')
        tk.Button(c, text="Aceptar", bg='#4f8ef7', fg='white', command=t.destroy).pack(pady=(15, 0))

class _VentanaBloqueo:
    def __init__(self, root):
        # Bloqueo REAL en Wayland PRIMERO (antes del overlay): agarrar (EVIOCGRAB)
        # el teclado/ratón físicos del alumno vía el demonio root. Así el input
        # queda bloqueado aunque la creación del overlay Tkinter falle.
        # grab_set_global() solo funciona en X11.
        self._vi_grab = False
        if _VIGIA_INPUT is not None:
            try:
                if _VIGIA_INPUT.grab(True):
                    self._vi_grab = True
                    print("  [✓] Pantalla bloqueada (input físico agarrado).")
                else:
                    print("  [!] Bloqueo: el demonio vigia-input no respondió.")
            except Exception as e:
                print(f"  [!] Bloqueo: fallo al agarrar input: {e}")
        self.top = tk.Toplevel(root); self.top.attributes('-fullscreen', True, '-topmost', True); self.top.configure(bg='#0a0c14'); self.top.overrideredirect(True)
        m = tk.Frame(self.top, bg='#0a0c14'); m.place(relx=0.5, rely=0.5, anchor='center')
        tk.Label(m, text='🔒', bg='#0a0c14', fg='#fc8181', font=('Segoe UI', 80)).pack()
        tk.Label(m, text='Pantalla bloqueada', bg='#0a0c14', fg='#e2e8f0', font=('Segoe UI', 24, 'bold')).pack()
        self.top.update(); self.top.focus_force()
        try: self.top.grab_set_global()
        except: self.top.grab_set()
        self._activa = True; self._mantener()
    def _mantener(self):
        if self._activa:
            try: self.top.lift(); self.top.focus_force(); self.top.after(100, self._mantener)
            except: pass
    def desbloquear(self):
        self._activa = False
        if self._vi_grab and _VIGIA_INPUT is not None:
            try: _VIGIA_INPUT.grab(False)
            except Exception: pass
            self._vi_grab = False
        self.top.destroy()

class _VentanaPizarra:
    """Overlay visual para anotaciones del profesor (click-through en X11)."""

    def __init__(self, root):
        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        # NO usar -fullscreen: con overrideredirect el WM no gestiona la ventana
        # y el hint se ignora, dejando la ventana en su tamaño por defecto (300×150).
        # La geometría se establece explícitamente en mostrar().
        self._transparent = '#010203'
        self.top.configure(bg=self._transparent)
        self.canvas = tk.Canvas(self.top, bg=self._transparent, highlightthickness=0, bd=0)
        self.canvas.pack(fill='both', expand=True)

        self._clickthrough_checked = False
        self._clickthrough_ok = False
        self._visible = False
        self.top.withdraw()

    def _ensure_clickthrough(self):
        if self._clickthrough_checked:
            return self._clickthrough_ok
        try:
            self.top.update_idletasks()
            if platform_utils.IS_WINDOWS:
                # En Windows, winfo_id() devuelve el HWND del frame hijo de Tkinter,
                # no del toplevel real. Necesitamos el HWND padre para set_clickthrough.
                import ctypes
                child_hwnd = int(self.top.winfo_id())
                hwnd = ctypes.windll.user32.GetParent(child_hwnd)
                if not hwnd:
                    hwnd = child_hwnd
                self._clickthrough_ok = platform_utils.set_clickthrough(hwnd)
            else:
                self._clickthrough_ok = platform_utils.set_clickthrough(int(self.top.winfo_id()))
        except Exception:
            self._clickthrough_ok = False
        self._clickthrough_checked = True
        if not self._clickthrough_ok:
            print("  [!] No se pudo activar click-through; pizarra en modo degradado.")
        return self._clickthrough_ok

    def mostrar(self):
        # Posicionar la ventana sobre el monitor que se está capturando
        try:
            mon = screen_capture.get_monitor_geometry()
            w = mon['width']; h = mon['height']
            l = mon.get('left', 0); t = mon.get('top', 0)
        except Exception:
            l, t = 0, 0
            w = self.top.winfo_screenwidth()
            h = self.top.winfo_screenheight()
        self.top.geometry(f"{w}x{h}+{l}+{t}")
        # La transparencia debe aplicarse con la ventana ya visible para que
        # el compositor del WM (KWin/Mutter) la tenga en cuenta.
        # En Windows: -transparentcolor configura WS_EX_LAYERED + LWA_COLORKEY
        # internamente en Tk. Debe ir ANTES de set_clickthrough para que
        # WS_EX_TRANSPARENT se añada sobre WS_EX_LAYERED ya existente.
        try:
            self.top.wm_attributes('-transparentcolor', self._transparent)
        except Exception:
            pass
        self.top.deiconify()
        self.top.lift()
        self.top.attributes('-topmost', True)
        self.top.update_idletasks()
        # Resetear estado de click-through (el HWND puede haber cambiado)
        self._clickthrough_checked = False
        if not self._ensure_clickthrough():
            self.top.withdraw()
            self._visible = False
            return False
        self._visible = True
        return True

    def ocultar(self):
        self.top.withdraw()
        self._visible = False

    def visible(self):
        return self._visible

    def limpiar(self):
        self.canvas.delete('all')

    def dibujar(self, x0, y0, x1, y1, color='#ff3b30', size=6):
        if not self._visible:
            return
        w = max(1, int(size))
        self.canvas.create_line(
            int(x0), int(y0), int(x1), int(y1),
            fill=color, width=w, capstyle='round', smooth=True, splinesteps=12
        )

    def texto(self, x, y, text, color='#ff3b30', size=6):
        if not self._visible or not text:
            return
        fs = max(14, int(size) * 3)
        self.canvas.create_text(
            int(x), int(y), text=str(text), anchor='nw',
            fill=color, font=('Segoe UI', fs, 'bold')
        )

def ejecutar_interfaz():
    root = tk.Tk(); root.withdraw(); v_prof = None; v_bloq = None; v_pizarra = None
    overlay_activa = False
    def check():
        nonlocal v_prof, v_bloq, v_pizarra, overlay_activa
        try:
            while not _cola_profesor.empty():
                d = _cola_profesor.get_nowait()
                if d.get('activa'):
                    if not v_prof: v_prof = _VentanaProfesor(root)
                    if d.get('pil') is not None:
                        v_prof.actualizar_pil(d['pil'])
                    else:
                        v_prof.actualizar(d.get('image'))
                elif v_prof:
                    v_prof.destruir(); v_prof = None
                    _prof_destino[0] = _prof_destino[1] = 0
            while not _cola_bloqueo.empty():
                if _cola_bloqueo.get_nowait():
                    if not v_bloq: v_bloq = _VentanaBloqueo(root)
                elif v_bloq: v_bloq.desbloquear(); v_bloq = None
            while not _cola_mensajes.empty(): _VentanaMensaje(root, _cola_mensajes.get_nowait())
            while not _cola_overlay.empty():
                d = _cola_overlay.get_nowait()
                tipo = d.get('type', '')
                if tipo == 'overlay_toggle':
                    overlay_activa = bool(d.get('enabled', False))
                    if overlay_activa:
                        if _start_overlay_proc():
                            _send_overlay_cmd(d)   # Linux GTK: toggle enabled=True → show()
                        elif platform_utils.IS_WINDOWS:
                            # Fallback: pizarra tkinter en Windows
                            if not v_pizarra:
                                v_pizarra = _VentanaPizarra(root)
                            v_pizarra.mostrar()
                        else:
                            overlay_activa = False
                    else:
                        if v_pizarra and v_pizarra.visible():
                            v_pizarra.ocultar()
                            v_pizarra.limpiar()
                        _send_overlay_cmd(d)        # toggle enabled=False → hide()
                        _stop_overlay_proc()
                else:
                    if overlay_activa:
                        if v_pizarra and v_pizarra.visible():
                            # Procesar comandos de dibujo en pizarra tkinter (Windows)
                            if tipo == 'overlay_draw':
                                v_pizarra.dibujar(
                                    d.get('x0', 0), d.get('y0', 0),
                                    d.get('x1', 0), d.get('y1', 0),
                                    d.get('color', '#ff3b30'), d.get('size', 6))
                            elif tipo == 'overlay_text':
                                v_pizarra.texto(
                                    d.get('x', 0), d.get('y', 0),
                                    d.get('text', ''), d.get('color', '#ff3b30'), d.get('size', 6))
                            elif tipo == 'overlay_clear':
                                v_pizarra.limpiar()
                        else:
                            _send_overlay_cmd(d)     # Linux GTK
            while not _cola_clipboard_req.empty():
                _cola_clipboard_req.get_nowait()
                try:
                    cb = root.selection_get(selection='CLIPBOARD')
                except Exception:
                    cb = ''
                try: _cola_clipboard_res.put_nowait(cb)
                except Exception: pass
        except: pass
        root.after(33, check)
    check(); root.mainloop()

if __name__ == '__main__':
    platform_utils.set_dpi_aware()
    ip = None
    if len(sys.argv) > 1:
        ip = sys.argv[1]
    else:
        _conf_path = platform_utils.get_config_path()
        if os.path.exists(_conf_path):
            try:
                with open(_conf_path, 'r') as f:
                    ip = f.read().strip()
            except: pass
    
    if not ip:
        try:
            ip = input("IP Servidor: ").strip()
        except EOFError:
            ip = "127.0.0.1" # Fallback if no input possible

    if not ip: ip = "127.0.0.1"
    if WEBRTC_OK:
        threading.Thread(target=_asyncio_runner, name='WebRTC-Loop', daemon=True).start()
        time.sleep(0.1)   # Dar tiempo al loop a arrancar
    def _conectar(ip):
        while True:
            try:
                sio.connect(f"http://{ip}:5000", transports=['polling', 'websocket'])
                return
            except Exception as e:
                print(f"[VIGIA] Sin conexión con {ip}:5000, reintentando en 5 s… ({e})")
                time.sleep(5)
    threading.Thread(target=lambda: _conectar(ip), daemon=True).start()
    threading.Thread(target=bucle_capturas, daemon=True).start()
    if TK_OK: ejecutar_interfaz()
    else: 
        try: 
            while True: time.sleep(1)
        except KeyboardInterrupt: pass
