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
import time
import socket
import threading
import queue
import base64
import shutil
import subprocess

# ── Importaciones ────────────────────────────────────────────────────────────
IS_WINDOWS = os.name == 'nt'
IS_LINUX = sys.platform.startswith('linux')


def _pip_install_flags():
    flags = ['install', '--user', '-q']
    if IS_LINUX:
        flags.insert(2, '--break-system-packages')
    return flags


def _open_file(path):
    try:
        if IS_WINDOWS:
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(path)])
        else:
            subprocess.Popen(['xdg-open', str(path)])
    except Exception:
        pass


def _candidate_client_conf_paths():
    paths = []
    if IS_WINDOWS:
        program_data = os.environ.get('PROGRAMDATA')
        if program_data:
            paths.append(os.path.join(program_data, 'VIGIA', 'client.conf'))
    paths.append('/etc/vigia/client.conf')
    base_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    paths.append(os.path.join(base_dir, 'client.conf'))
    return paths


def _read_server_ip_from_conf():
    for path in _candidate_client_conf_paths():
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                ip = f.read().strip()
            if ip:
                return ip
        except Exception:
            continue
    return None


def _machine_user():
    return os.environ.get('USER') or os.environ.get('USERNAME') or 'alumno'

def _pip_disponible():
    try:
        if subprocess.run([sys.executable, '-m', 'pip', '--version'], 
                          capture_output=True, timeout=2).returncode == 0:
            return [sys.executable, '-m', 'pip']
    except Exception: pass
    if shutil.which('pip3'): return ['pip3']
    if shutil.which('pip'): return ['pip']
    return None

def _instalar(paquete):
    print(f"  [VIGIA] Instalando {paquete}...")
    import importlib
    pip_cmd = _pip_disponible()
    if not pip_cmd and IS_LINUX:
        os.system('sudo apt-get update -qq 2>/dev/null && sudo apt-get install -y python3-pip -qq 2>/dev/null')
        pip_cmd = _pip_disponible()
    if pip_cmd:
        try:
            res = subprocess.run(pip_cmd + _pip_install_flags() + paquete.split(), timeout=60)
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
    _instalar("mss"); import mss

try:
    from PIL import Image
except ImportError:
    _instalar("Pillow"); from PIL import Image

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
        print("  [*] Falta ImageTk (PIL). Intentando resolver dependencias...")
        if IS_LINUX:
            os.system('sudo apt-get update -qq 2>/dev/null && sudo apt-get install -y python3-pil.imagetk -qq 2>/dev/null')
        try:
            from PIL import ImageTk
            IMGTK_OK = True
        except ImportError:
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
try:
    import asyncio, fractions
    import numpy as np
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
    import av
    WEBRTC_OK = True
    print("  [✓] aiortc disponible — WebRTC habilitado.")
except ImportError:
    print("  [!] aiortc no instalado — usando fallback JPEG.")

# ── Control remoto (Pynput + Xdotool) ─────────────────────────────────────────
_mouse_ctrl = None
_kbd_ctrl   = None
_PBtn       = None
_XDO_CMD    = shutil.which('xdotool')
_xdo_env    = None   # entorno precalculado para xdotool (evita copiar os.environ en cada evento)

def _xdo_sync(*args):
    """Ejecuta xdotool de forma síncrona (bloqueante). Usar solo desde el hilo de entrada."""
    try:
        subprocess.run([_XDO_CMD] + [str(a) for a in args],
                       env=_xdo_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=2)
    except Exception as e:
        print(f"  [!] xdotool {args}: {e}")

def _init_input():
    global _mouse_ctrl, _kbd_ctrl, _PBtn, _XDO_CMD, _xdo_env
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

    # 2. xdotool
    if not _XDO_CMD:
        _XDO_CMD = shutil.which('xdotool')
    if not _XDO_CMD and os.path.exists('/usr/bin/xdotool'):
        _XDO_CMD = '/usr/bin/xdotool'

    if _XDO_CMD:
        print(f"  [✓] xdotool detectado en {_XDO_CMD}.")
    else:
        print("  [!] xdotool no detectado — pynput manejará todo el control remoto.")

    # Precalcular entorno para xdotool (se reutiliza en cada evento)
    _xdo_env = dict(os.environ)
    if IS_LINUX and 'DISPLAY' not in _xdo_env:
        _xdo_env['DISPLAY'] = ':0'

    return (_mouse_ctrl is not None) or (_XDO_CMD is not None)

INPUT_OK = _init_input()

_XDO_KEY_MAP = {
    'space': 'space', 'enter': 'Return', 'esc': 'Escape', 'tab': 'Tab',
    'backspace': 'BackSpace', 'delete': 'Delete', 'insert': 'Insert',
    'home': 'Home', 'end': 'End', 'pageup': 'Page_Up', 'pagedown': 'Page_Down',
    'left': 'Left', 'right': 'Right', 'up': 'Up', 'down': 'Down',
    'ctrl': 'Control_L', 'alt': 'Alt_L', 'shift': 'Shift_L', 'win': 'Super_L'
}
_BTN_MAP_XDO = {'left': 1, 'middle': 2, 'right': 3}

# ── Cola de entrada dedicada ───────────────────────────────────────────────────
# Todos los eventos de ratón/teclado pasan por esta cola y son procesados
# en orden estricto por un único hilo. Esto evita:
#   - Ejecuciones paralelas de xdotool que llegan fuera de orden
#   - Race conditions en pynput (controladores Xlib no thread-safe entre hilos)
#   - Movimientos de ratón estancados por HOL blocking en el DataChannel
_input_q: queue.Queue = queue.Queue(maxsize=400)

def _input_worker():
    """Hilo dedicado: ejecuta eventos de entrada uno a uno, en orden."""
    while True:
        data = _input_q.get()
        try:
            # Coalescing de mousemove: si hay más moves en cola, descartar el actual
            # y procesar solo el más reciente antes del próximo evento no-move.
            if data.get('type') == 'mousemove':
                while True:
                    try:
                        nxt = _input_q.get_nowait()
                    except queue.Empty:
                        break
                    if nxt.get('type') == 'mousemove':
                        data = nxt          # descartar move viejo, usar el más reciente
                    else:
                        _procesar_input(data)   # ejecutar el move más reciente
                        data = nxt              # continuar con el siguiente evento
                        break
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

# ── Configuración ────────────────────────────────────────────────────────────
ANCHO_IMAGEN      = 1280
CALIDAD_JPEG      = 55
INTERVALO_SEG     = 1.0
REINTENTOS_ESPERA = 5

# ── Estado ───────────────────────────────────────────────────────────────────
sio = sio_module.Client(reconnection=True, reconnection_attempts=0)
_cola_profesor      = queue.Queue(maxsize=2)
_cola_bloqueo       = queue.Queue(maxsize=10)
_cola_mensajes      = queue.Queue(maxsize=20)
_cola_clipboard_req = queue.Queue(maxsize=1)
_cola_clipboard_res = queue.Queue(maxsize=1)
_en_observacion = False
_webrtc_loop   = None   # event loop asyncio dedicado
_webrtc_pc     = None   # RTCPeerConnection activa
_webrtc_prof   = None   # prof_sid del profesor conectado
_webrtc_activo = False  # True cuando P2P establecido
_pending_ice   = []     # ICE candidates recibidos antes del offer

def _b64(jpeg: bytes) -> str:
    return 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode()

if WEBRTC_OK:
    class ScreenStreamTrack(VideoStreamTrack):
        kind = "video"
        _CLOCK_RATE = 90000
        _TARGET_FPS = 30

        def __init__(self):
            super().__init__()
            self._sct = None
            self._ts  = 0
            self._t0  = None

        async def recv(self):
            if self._t0 is None:
                self._t0 = asyncio.get_event_loop().time()
            self._ts += int(self._CLOCK_RATE / self._TARGET_FPS)
            drift = self._ts / self._CLOCK_RATE - (asyncio.get_event_loop().time() - self._t0)
            if drift > 0:
                await asyncio.sleep(drift)

            loop = asyncio.get_event_loop()
            rgb = await loop.run_in_executor(None, self._capturar)

            frame = av.VideoFrame.from_ndarray(rgb, format='rgb24')
            frame.pts       = self._ts
            frame.time_base = fractions.Fraction(1, self._CLOCK_RATE)
            return frame

        def _capturar(self):
            try:
                if self._sct is None:
                    self._sct = mss.mss()
                mon = self._sct.monitors[1]
                cap = self._sct.grab(mon)
                bgra = np.frombuffer(cap.bgra, np.uint8).reshape(cap.height, cap.width, 4)
                rgb  = bgra[:, :, [2, 1, 0]]   # BGRA → RGB
                h, w = rgb.shape[:2]
                # Cap at 1920px wide for good resolution; VP8 at 4 Mbps handles 1080p well.
                if w > 1920:
                    new_w, new_h = 1920, int(h * 1920 / w)
                    img = Image.fromarray(rgb).resize((new_w, new_h), Image.BILINEAR)
                    rgb = np.array(img)
                return rgb
            except Exception as e:
                print(f"  [WebRTC] Captura: {e}")
                if self._sct:
                    try: self._sct.close()
                    except: pass
                    self._sct = None
                return np.zeros((1080, 1920, 3), dtype=np.uint8)

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
    sct = None
    while True:
        if not sio.connected:
            time.sleep(0.5); continue
        if sct is None:
            try: sct = mss.mss()
            except: time.sleep(2); continue
        
        now = time.monotonic()
        try:
            monitor = sct.monitors[1]
            orig_w, orig_h = monitor['width'], monitor['height']
            
            if (now - _ultimo_screenshot) >= INTERVALO_SEG:
                captura = sct.grab(monitor)
                img = Image.frombytes('RGB', captura.size, captura.bgra, 'raw', 'BGRX')
                if img.width > ANCHO_IMAGEN:
                    img = img.resize((ANCHO_IMAGEN, int(img.height * ANCHO_IMAGEN / img.width)), Image.LANCZOS)
                buf = io.BytesIO(); img.save(buf, format='JPEG', quality=CALIDAD_JPEG)
                sio.emit('screenshot', {'image': _b64(buf.getvalue())})
                _ultimo_screenshot = now
            
            if _en_observacion and not _webrtc_activo:
                captura = sct.grab(monitor)
                img = Image.frombytes('RGB', captura.size, captura.bgra, 'raw', 'BGRX')
                ancho_r = min(orig_w, 1280)
                if img.width > ancho_r:
                    img = img.resize((ancho_r, int(img.height * ancho_r / img.width)), Image.BILINEAR)
                buf = io.BytesIO(); img.save(buf, format='JPEG', quality=70)
                sio.emit('remote_frame', {'image': _b64(buf.getvalue()), 'orig_w': orig_w, 'orig_h': orig_h})
                time.sleep(0.05)   # ~20 fps JPEG fallback
            else:
                time.sleep(0.2)
        except:
            try: sct.close()
            except: pass
            sct = None; time.sleep(1)

# ── Manejo de entrada ─────────────────────────────────────────────────────────

def _procesar_input(data):
    """Ejecuta un evento de entrada. Llamar SOLO desde el hilo _input_worker."""
    tipo = data.get('type', '')
    try:
        x = int(data.get('x', 0))
        y = int(data.get('y', 0))
    except:
        x = y = 0

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
            except: pass
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
            except: pass
        if _XDO_CMD:
            _xdo_sync('mousemove', x, y)
            for m in mods: _xdo_sync('keydown', m)
            _xdo_sync('mousedown', _BTN_MAP_XDO.get(button, 1))
            for m in reversed(mods): _xdo_sync('keyup', m)
        return

    if tipo == 'mouseup':
        if _mouse_ctrl and _PBtn:
            try: _mouse_ctrl.position = (x, y); _mouse_ctrl.release(_btn_map_pyn.get(button, _PBtn.left)); return
            except: pass
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
            except: pass
        return

    if tipo == 'keypress':
        k = _XDO_KEY_MAP.get(data.get('key', '').lower(), data.get('key'))
        if _XDO_CMD:
            _xdo_sync('key', '--clearmodifiers', k); return
        if _kbd_ctrl:
            pk = _get_pynput_key(data.get('key'))
            try: _kbd_ctrl.press(pk); _kbd_ctrl.release(pk)
            except: pass
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
            except: pass
        return

    if tipo == 'keydown':
        k = _XDO_KEY_MAP.get(data.get('key', '').lower(), data.get('key'))
        if _XDO_CMD:
            _xdo_sync('keydown', k); return
        if _kbd_ctrl:
            try: _kbd_ctrl.press(_get_pynput_key(data.get('key')))
            except: pass
        return

    if tipo == 'keyup':
        k = _XDO_KEY_MAP.get(data.get('key', '').lower(), data.get('key'))
        if _XDO_CMD:
            _xdo_sync('keyup', k); return
        if _kbd_ctrl:
            try: _kbd_ctrl.release(_get_pynput_key(data.get('key')))
            except: pass


_last_mouse_time = 0.0
_MOUSE_THROTTLE  = 0.01   # 100 Hz maximum for mousemove events

@sio.on('do_input')
def on_do_input(data):
    """Encola el evento; el hilo vigia-input lo ejecuta en orden estricto."""
    global _last_mouse_time
    if not INPUT_OK: return
    tipo = data.get('type', '')
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
    sio.emit('register', {'name': f"{_machine_user()} - {socket.gethostname()}"})

@sio.on('viewer_start')
def on_viewer_start(data):
    global _en_observacion; _en_observacion = True
    print(f"[*] El profesor está observando/controlando.")
    # Enviar resolución real de pantalla para que el profesor mapee coordenadas correctamente
    try:
        with mss.mss() as _sct:
            _mon = _sct.monitors[1]
            sio.emit('screen_info', {'w': _mon['width'], 'h': _mon['height']})
    except Exception:
        pass

@sio.on('viewer_stop')
def on_viewer_stop(_data):
    global _en_observacion; _en_observacion = False
    print(f"[*] Fin de observación.")
    if WEBRTC_OK:
        _wrtc(_cerrar_webrtc())

@sio.on('quit_app')
def on_quit_app(_data):
    try:
        if IS_WINDOWS:
            subprocess.run(['shutdown', '/s', '/t', '0'], check=False, timeout=5)
        elif IS_LINUX:
            subprocess.run(['sudo', 'shutdown', '-h', 'now'], check=False, timeout=5)
        else:
            subprocess.run(['shutdown', '-h', 'now'], check=False, timeout=5)
    except Exception:
        os._exit(0)

@sio.on('show_message')
def on_show_message(data): _cola_mensajes.put_nowait(data)

@sio.on('lock_screen')
def on_lock_screen(_data): _cola_bloqueo.put_nowait(True)

@sio.on('unlock_screen')
def on_unlock_screen(_data): _cola_bloqueo.put_nowait(False)

@sio.on('teacher_screen')
def on_teacher_screen(data):
    try:
        _cola_profesor.put_nowait(data)
    except queue.Full:
        try: _cola_profesor.get_nowait(); _cola_profesor.put_nowait(data)
        except: pass

@sio.on('exec_command')
def on_exec_command(data):
    cmd = data.get('command', '').strip()
    cmd_id = data.get('cmd_id', '')
    if not cmd:
        return
    env = dict(os.environ)
    if IS_LINUX:
        env['DEBIAN_FRONTEND'] = 'noninteractive'
    env.setdefault('TERM', 'xterm')
    try:
        result = subprocess.run(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=60, env=env
        )
        sio.emit('command_output', {
            'cmd_id': cmd_id,
            'command': cmd,
            'stdout': result.stdout[-6000:],
            'stderr': result.stderr[-3000:],
            'returncode': result.returncode,
        })
    except subprocess.TimeoutExpired:
        sio.emit('command_output', {
            'cmd_id': cmd_id,
            'command': cmd,
            'stdout': '',
            'stderr': 'Timeout (60s): el comando tardó demasiado.',
            'returncode': -1,
        })
    except Exception as e:
        sio.emit('command_output', {
            'cmd_id': cmd_id,
            'command': cmd,
            'stdout': '',
            'stderr': str(e),
            'returncode': -1,
        })

@sio.on('get_clipboard')
def on_get_clipboard(_data):
    text = ''
    if IS_WINDOWS:
        for cmd in [
            ['powershell', '-NoProfile', '-Command', 'Get-Clipboard -Raw'],
            ['pwsh', '-NoProfile', '-Command', 'Get-Clipboard -Raw'],
        ]:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
                if r.returncode == 0:
                    text = r.stdout
                    break
            except Exception:
                continue
    else:
        _env = _xdo_env  # ya calculado en _init_input()
        # Intentar con xclip / xsel (requieren DISPLAY)
        for cmd in [
            ['xclip', '-o', '-selection', 'clipboard'],
            ['xsel',  '--clipboard', '--output'],
        ]:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=2, env=_env)
                if r.returncode == 0:
                    text = r.stdout
                    break
            except Exception:
                continue
    # Fallback: portapapeles X11 vía tkinter (hilo principal)
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

    async def _procesar_offer(data):
        global _webrtc_pc, _webrtc_prof, _webrtc_activo, _pending_ice
        if _webrtc_pc:
            await _webrtc_pc.close()
        _webrtc_pc = None; _webrtc_activo = False

        prof_sid = data.get('prof_sid')
        _webrtc_prof = prof_sid

        pc = RTCPeerConnection()
        _webrtc_pc = pc
        pc.addTrack(ScreenStreamTrack())

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
        global _webrtc_pc, _webrtc_activo, _webrtc_prof
        if _webrtc_pc: await _webrtc_pc.close()
        _webrtc_pc = None; _webrtc_activo = False; _webrtc_prof = None

# ── Interfaz UI ──────────────────────────────────────────────────────────────
class _VentanaProfesor:
    def __init__(self, root):
        self.top = tk.Toplevel(root); self.top.title("📺 Pantalla del Profesor"); self.top.configure(bg='#0f1117')
        try:
            self.top.state('zoomed')
        except Exception:
            try:
                self.top.attributes('-zoomed', True)
            except Exception:
                pass
        self.top.attributes('-topmost', True)
        self._label = tk.Label(self.top, bg='#0f1117', text="⏳ Esperando imagen…", fg='#718096', font=('Segoe UI', 12))
        self._label.pack(expand=True, fill='both')
        self._foto = None
        self._img_raw = None   # PIL Image original sin redimensionar
        self._after_id = None  # ID del after de redibujado pendiente
        self.top.protocol("WM_DELETE_WINDOW", self.destruir)
        self.top.bind('<Configure>', self._on_resize)

    def _on_resize(self, event):
        if self._img_raw is None: return
        if self._after_id: self.top.after_cancel(self._after_id)
        self._after_id = self.top.after(120, self._render)

    def _render(self):
        self._after_id = None
        if self._img_raw is None: return
        try:
            w = max(self.top.winfo_width(), 1)
            h = max(self.top.winfo_height(), 1)
            img = self._img_raw.copy()
            img.thumbnail((w, h), Image.LANCZOS)
            self._foto = ImageTk.PhotoImage(img)
            self._label.config(image=self._foto, text='')
        except: pass

    def actualizar(self, b64):
        try:
            self._img_raw = Image.open(io.BytesIO(base64.b64decode(b64.split(',', 1)[1])))
            self._render()
        except: pass

    def destruir(self): self.top.destroy()

class _VentanaMensaje:
    def __init__(self, root, msg):
        import pathlib
        t = tk.Toplevel(root)
        t.title(msg.get('title', 'Mensaje'))
        t.configure(bg='#1a1d27')
        t.attributes('-topmost', True)
        c = tk.Frame(t, bg='#1a1d27', padx=20, pady=20)
        c.pack()
        body_text = re.sub(r'<[^>]+>', '', msg.get('body', '')).strip()
        if body_text:
            txt = tk.Text(c, bg='#1a1d27', fg='#e2e8f0', font=('Segoe UI', 12),
                          wrap='word', height=6, width=44, relief='flat')
            txt.insert('end', body_text)
            txt.config(state='disabled')
            txt.pack()
        adjuntos = msg.get('attachments', [])
        if adjuntos:
            descargas = pathlib.Path.home() / 'Descargas'
            if not descargas.exists():
                descargas = pathlib.Path.home() / 'Downloads'
            if not descargas.exists():
                descargas = pathlib.Path.home()
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
                        _open_file(p)
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
    def desbloquear(self): self._activa = False; self.top.destroy()

def ejecutar_interfaz():
    root = tk.Tk(); root.withdraw(); v_prof = None; v_bloq = None
    def check():
        nonlocal v_prof, v_bloq
        try:
            while not _cola_profesor.empty():
                d = _cola_profesor.get_nowait()
                if d.get('activa'):
                    if not v_prof: v_prof = _VentanaProfesor(root)
                    v_prof.actualizar(d.get('image'))
                elif v_prof: v_prof.destruir(); v_prof = None
            while not _cola_bloqueo.empty():
                if _cola_bloqueo.get_nowait():
                    if not v_bloq: v_bloq = _VentanaBloqueo(root)
                elif v_bloq: v_bloq.desbloquear(); v_bloq = None
            while not _cola_mensajes.empty(): _VentanaMensaje(root, _cola_mensajes.get_nowait())
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
    ip = None
    if len(sys.argv) > 1:
        ip = sys.argv[1]
    elif os.environ.get('VIGIA_SERVER_IP'):
        ip = os.environ.get('VIGIA_SERVER_IP', '').strip()
    else:
        ip = _read_server_ip_from_conf()
    
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
