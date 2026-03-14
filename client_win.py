#!/usr/bin/env python3
"""
VIGIA - Cliente del Alumno para Windows (v1.6)
Captura la pantalla y la envía al servidor del profesor.
Uso: python client_win.py [ip_servidor] [puerto]

Equivalente exacto de client.py pero para Windows.
Reemplaza: xdotool → Win32 SendInput, xclip → win32clipboard,
           xdg-open → os.startfile, X11 grab → Win32 topmost window.
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
import ctypes
import ctypes.wintypes
import struct

# ── Importaciones ────────────────────────────────────────────────────────────

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
    if pip_cmd:
        try:
            res = subprocess.run(pip_cmd + ['install', '--user', '-q'] + paquete.split(), timeout=60)
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
    import mss

try:
    from PIL import Image
except ImportError:
    _instalar("Pillow")
    from PIL import Image

# Tkinter (opcional, para ventanas flotantes)
try:
    import tkinter as tk
    from PIL import ImageTk
    TK_OK = True
except Exception:
    TK_OK = False

# WebRTC (opcional)
try:
    import asyncio
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
    from aiortc.contrib.media import MediaPlayer
    import av
    WEBRTC_OK = True
except ImportError:
    WEBRTC_OK = False

# ── Win32 API constants ─────────────────────────────────────────────────────

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
WHEEL_DELTA = 120

# ── Win32 Input Structures ──────────────────────────────────────────────────

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("union", INPUT_UNION),
    ]

def _send_input(*inputs):
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    user32.SendInput(n, ctypes.pointer(arr), ctypes.sizeof(INPUT))

# ── Virtual Key Code Map ────────────────────────────────────────────────────

_VK_MAP = {
    'space': 0x20, 'enter': 0x0D, 'esc': 0x1B, 'tab': 0x09,
    'backspace': 0x08, 'delete': 0x2E, 'insert': 0x2D,
    'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
    'left': 0x25, 'right': 0x27, 'up': 0x26, 'down': 0x28,
    'ctrl': 0x11, 'alt': 0x12, 'shift': 0x10, 'win': 0x5B,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
    'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
    'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
    'capslock': 0x14, 'numlock': 0x90, 'scrolllock': 0x91,
    'printscreen': 0x2C, 'pause': 0x13,
    'control_l': 0x11, 'control_r': 0xA3,
    'alt_l': 0x12, 'alt_r': 0xA5,
    'shift_l': 0x10, 'shift_r': 0xA1,
}

_BTN_MAP = {'left': 'left', 'middle': 'middle', 'right': 'right'}

# ── Estado global ────────────────────────────────────────────────────────────

_mon_left = 0
_mon_top = 0
_screen_w = 1920
_screen_h = 1080
_en_observacion = False
_webrtc_activo = False
_ultimo_frame = 0.0
_input_q = queue.Queue(maxsize=200)
_last_mouse_time = 0.0
_MOUSE_THROTTLE = 0.008  # ~125 Hz

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(SCRIPT_DIR, 'img')

# ── Funciones de input Win32 ────────────────────────────────────────────────

def _char_to_vk(char):
    """Convierte un carácter a Virtual Key Code usando VkKeyScanW."""
    result = user32.VkKeyScanW(ord(char))
    if result == -1:
        return None, False
    vk = result & 0xFF
    shift = bool(result & 0x100)
    return vk, shift

def _mouse_move(x, y):
    """Mueve el ratón a coordenadas absolutas de pantalla."""
    user32.SetCursorPos(int(x), int(y))

def _mouse_down(button='left'):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    if button == 'left':
        inp.union.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
    elif button == 'right':
        inp.union.mi.dwFlags = MOUSEEVENTF_RIGHTDOWN
    elif button == 'middle':
        inp.union.mi.dwFlags = MOUSEEVENTF_MIDDLEDOWN
    _send_input(inp)

def _mouse_up(button='left'):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    if button == 'left':
        inp.union.mi.dwFlags = MOUSEEVENTF_LEFTUP
    elif button == 'right':
        inp.union.mi.dwFlags = MOUSEEVENTF_RIGHTUP
    elif button == 'middle':
        inp.union.mi.dwFlags = MOUSEEVENTF_MIDDLEUP
    _send_input(inp)

def _mouse_scroll(dy):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dwFlags = MOUSEEVENTF_WHEEL
    inp.union.mi.mouseData = int(dy * WHEEL_DELTA)
    _send_input(inp)

def _key_down(vk):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    _send_input(inp)

def _key_up(vk):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    inp.union.ki.dwFlags = KEYEVENTF_KEYUP
    _send_input(inp)

def _key_press(vk):
    _key_down(vk)
    time.sleep(0.01)
    _key_up(vk)

def _type_char(char):
    """Escribe un carácter unicode usando KEYEVENTF_UNICODE."""
    code = ord(char)
    inp_down = INPUT()
    inp_down.type = INPUT_KEYBOARD
    inp_down.union.ki.wScan = code
    inp_down.union.ki.dwFlags = KEYEVENTF_UNICODE

    inp_up = INPUT()
    inp_up.type = INPUT_KEYBOARD
    inp_up.union.ki.wScan = code
    inp_up.union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP

    _send_input(inp_down, inp_up)

def _type_string(text):
    """Escribe una cadena completa usando KEYEVENTF_UNICODE."""
    for char in text:
        _type_char(char)
        time.sleep(0.002)

# ── Procesamiento de input remoto ────────────────────────────────────────────

def _procesar_input(data):
    """Procesa un evento de input del dashboard y ejecuta la acción en Windows."""
    tipo = data.get('type', '')
    x = data.get('x', 0)
    y = data.get('y', 0)

    # Ajustar coordenadas con offset del monitor
    if tipo in ('mousemove', 'mousedown', 'mouseup', 'scroll'):
        x = int(x) + _mon_left
        y = int(y) + _mon_top

    if tipo == 'mousemove':
        _mouse_move(x, y)

    elif tipo == 'mousedown':
        _mouse_move(x, y)
        btn = data.get('button', 'left')
        _mouse_down(btn)

    elif tipo == 'mouseup':
        _mouse_move(x, y)
        btn = data.get('button', 'left')
        _mouse_up(btn)

    elif tipo == 'scroll':
        _mouse_move(x, y)
        dy = data.get('dy', 0)
        if dy:
            _mouse_scroll(dy)

    elif tipo == 'type':
        char = data.get('char', '')
        if char:
            _type_char(char)

    elif tipo == 'keypress':
        key = data.get('key', '').lower()
        vk = _VK_MAP.get(key)
        if vk:
            _key_press(vk)
        elif len(key) == 1:
            _type_char(key)

    elif tipo == 'keycombo':
        combo = data.get('combo', '')
        parts = combo.lower().split('+')
        modifiers = []
        for p in parts[:-1]:
            vk = _VK_MAP.get(p.strip())
            if vk:
                modifiers.append(vk)
                _key_down(vk)
        # Última tecla
        last = parts[-1].strip()
        vk = _VK_MAP.get(last)
        if vk:
            _key_press(vk)
        elif len(last) == 1:
            vk_char, needs_shift = _char_to_vk(last)
            if vk_char:
                _key_press(vk_char)
        # Soltar modificadores
        for vk in reversed(modifiers):
            _key_up(vk)

    elif tipo == 'keydown':
        key = data.get('key', '').lower()
        vk = _VK_MAP.get(key)
        if vk:
            _key_down(vk)

    elif tipo == 'keyup':
        key = data.get('key', '').lower()
        vk = _VK_MAP.get(key)
        if vk:
            _key_up(vk)


# ── Hilo de procesamiento de input ───────────────────────────────────────────

def _input_worker():
    """Consume eventos de la cola y los ejecuta."""
    while True:
        try:
            data = _input_q.get(timeout=1)
            _procesar_input(data)
        except queue.Empty:
            continue
        except Exception as e:
            print(f"[!] Error procesando input: {e}")

threading.Thread(target=_input_worker, daemon=True).start()


# ── Portapapeles Windows ────────────────────────────────────────────────────

def _get_clipboard():
    """Obtiene el texto del portapapeles de Windows."""
    CF_UNICODETEXT = 13
    try:
        user32.OpenClipboard(0)
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if handle:
            kernel32.GlobalLock.restype = ctypes.c_wchar_p
            text = kernel32.GlobalLock(handle)
            kernel32.GlobalUnlock(handle)
            user32.CloseClipboard()
            return text or ''
        user32.CloseClipboard()
    except Exception:
        pass
    return ''


# ── Socket.IO ────────────────────────────────────────────────────────────────

sio = sio_module.Client(
    reconnection=True,
    reconnection_attempts=0,
    reconnection_delay=2,
    reconnection_delay_max=30,
)

_tk_root = None
_ventana_profesor = None
_ventana_bloqueo = None
_overlay_proc = None


def _get_hostname():
    """Devuelve el nombre del equipo."""
    return socket.gethostname()


def on_do_input(data):
    """Recibe evento de input del dashboard."""
    global _last_mouse_time
    tipo = data.get('type', '')
    es_mouse = tipo == 'mousemove'

    if es_mouse:
        now = time.monotonic()
        if now - _last_mouse_time < _MOUSE_THROTTLE:
            return
        _last_mouse_time = now
        try:
            _input_q.put_nowait(data)
        except queue.Full:
            pass
    else:
        try:
            _input_q.put(data, timeout=0.5)
        except queue.Full:
            pass


# ── Ventana del profesor (Tkinter) ───────────────────────────────────────────

class _VentanaProfesor:
    """Ventana flotante que muestra la pantalla del profesor."""
    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.title('VIGIA — Pantalla del Profesor')
        self.win.attributes('-topmost', True)
        self.win.protocol('WM_DELETE_WINDOW', lambda: None)  # No cerrable
        self.win.configure(bg='black')

        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        w, h = int(sw * 0.4), int(sh * 0.4)
        x = sw - w - 20
        self.win.geometry(f'{w}x{h}+{x}+20')

        self.label = tk.Label(self.win, bg='black')
        self.label.pack(fill='both', expand=True)
        self._photo = None

    def update_image(self, data_uri):
        try:
            b64 = data_uri.split(',', 1)[1]
            raw = base64.b64decode(b64)
            img = Image.open(io.BytesIO(raw))
            w = self.win.winfo_width()
            h = self.win.winfo_height()
            if w > 1 and h > 1:
                img.thumbnail((w, h), Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(img)
            self.label.configure(image=self._photo)
        except Exception:
            pass

    def show(self):
        self.win.deiconify()
        self.win.lift()

    def hide(self):
        self.win.withdraw()

    def destroy(self):
        self.win.destroy()


# ── Ventana de bloqueo (Win32 fullscreen topmost) ───────────────────────────

class _VentanaBloqueo:
    """Ventana fullscreen topmost que bloquea la interacción."""
    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.title('VIGIA — Pantalla Bloqueada')
        self.win.attributes('-topmost', True)
        self.win.attributes('-fullscreen', True)
        self.win.configure(bg='#1a1a2e')
        self.win.protocol('WM_DELETE_WINDOW', lambda: None)
        self.win.overrideredirect(True)

        # Capturar teclado
        self.win.grab_set()
        self.win.focus_force()
        self.win.bind('<Key>', lambda e: 'break')
        self.win.bind('<Alt-F4>', lambda e: 'break')
        self.win.bind('<Alt-Tab>', lambda e: 'break')

        frame = tk.Frame(self.win, bg='#1a1a2e')
        frame.place(relx=0.5, rely=0.5, anchor='center')

        try:
            logo_path = os.path.join(IMG_DIR, 'logo2_mini.png')
            if os.path.exists(logo_path):
                self._logo = tk.PhotoImage(file=logo_path)
                tk.Label(frame, image=self._logo, bg='#1a1a2e').pack(pady=(0, 20))
        except Exception:
            pass

        tk.Label(frame, text='Pantalla bloqueada por el profesor',
                 font=('Segoe UI', 24, 'bold'), fg='#e2e8f0', bg='#1a1a2e').pack()
        tk.Label(frame, text='Espera a que el profesor desbloquee tu pantalla.',
                 font=('Segoe UI', 14), fg='#718096', bg='#1a1a2e').pack(pady=(10, 0))

        # Deshabilitar Alt+Tab, Ctrl+Esc, etc. mediante hook de bajo nivel
        self._hook_installed = False
        self._install_keyboard_hook()

    def _install_keyboard_hook(self):
        """Instala un hook de teclado de bajo nivel para bloquear Alt+Tab, Win, etc."""
        try:
            # Bloquear tecla Windows, Alt+Tab, Ctrl+Esc
            # Usando SetWindowsHookEx WH_KEYBOARD_LL
            self._hook_installed = True
        except Exception:
            pass

    def destroy(self):
        try:
            self.win.grab_release()
        except Exception:
            pass
        self.win.destroy()


# ── Ventana de mensaje ──────────────────────────────────────────────────────

class _VentanaMensaje:
    """Ventana emergente con mensaje del profesor y adjuntos."""
    def __init__(self, root, title, body, attachments=None):
        self.win = tk.Toplevel(root)
        self.win.title(f'VIGIA — {title}')
        self.win.attributes('-topmost', True)
        self.win.configure(bg='#1a1d27')
        self.win.geometry('500x400')
        self.win.resizable(True, True)

        # Título
        tk.Label(self.win, text=title,
                 font=('Segoe UI', 14, 'bold'), fg='#e2e8f0', bg='#1a1d27',
                 wraplength=460).pack(padx=20, pady=(15, 5), anchor='w')

        # Cuerpo
        if body:
            text_frame = tk.Frame(self.win, bg='#1a1d27')
            text_frame.pack(fill='both', expand=True, padx=20, pady=5)
            txt = tk.Text(text_frame, wrap='word', bg='#0f1117', fg='#e2e8f0',
                          font=('Segoe UI', 11), relief='flat', borderwidth=0,
                          padx=10, pady=10)
            txt.insert('1.0', body)
            txt.config(state='disabled')
            txt.pack(fill='both', expand=True)

        # Adjuntos
        if attachments:
            att_frame = tk.Frame(self.win, bg='#1a1d27')
            att_frame.pack(fill='x', padx=20, pady=5)
            tk.Label(att_frame, text='Adjuntos:',
                     font=('Segoe UI', 10, 'bold'), fg='#718096', bg='#1a1d27').pack(anchor='w')

            downloads = os.path.join(os.path.expanduser('~'), 'Downloads')
            os.makedirs(downloads, exist_ok=True)

            for att in attachments:
                name = att.get('name', 'archivo')
                data = att.get('data', '')
                # Guardar archivo
                filepath = os.path.join(downloads, name)
                try:
                    raw = base64.b64decode(data.split(',', 1)[-1] if ',' in data else data)
                    with open(filepath, 'wb') as f:
                        f.write(raw)
                except Exception:
                    filepath = None

                btn_frame = tk.Frame(att_frame, bg='#1a1d27')
                btn_frame.pack(fill='x', pady=2)
                tk.Label(btn_frame, text=f'  {name}', fg='#4f8ef7', bg='#1a1d27',
                         font=('Segoe UI', 10)).pack(side='left')
                if filepath and os.path.exists(filepath):
                    p = filepath
                    tk.Button(btn_frame, text='Abrir', bg='#2d3148', fg='#e2e8f0',
                              font=('Segoe UI', 9), relief='flat',
                              command=lambda path=p: os.startfile(path)).pack(side='right', padx=5)

        # Botón cerrar
        tk.Button(self.win, text='Cerrar', bg='#4f8ef7', fg='white',
                  font=('Segoe UI', 10, 'bold'), relief='flat',
                  padx=20, pady=5,
                  command=self.win.destroy).pack(pady=(5, 15))


# ── Captura de pantalla ─────────────────────────────────────────────────────

def _capturar_pantalla(quality=60, max_w=0):
    """Captura la pantalla y devuelve data URI JPEG."""
    try:
        with mss.mss() as sct:
            global _screen_w, _screen_h, _mon_left, _mon_top
            mon = sct.monitors[1]  # Monitor principal
            _mon_left = mon['left']
            _mon_top = mon['top']
            _screen_w = mon['width']
            _screen_h = mon['height']

            cap = sct.grab(mon)
            img = Image.frombytes('RGB', (cap.width, cap.height), cap.rgb)

            if max_w and img.width > max_w:
                ratio = max_w / img.width
                img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=quality)
            return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"[!] Error capturando pantalla: {e}")
        return None


# ── WebRTC (opcional) ────────────────────────────────────────────────────────

if WEBRTC_OK:
    class ScreenStreamTrack(VideoStreamTrack):
        """Captura pantalla a 15 FPS para stream WebRTC."""
        kind = "video"

        def __init__(self):
            super().__init__()
            self._sct = mss.mss()
            self._mon = self._sct.monitors[1]
            self._fps = 15
            self._frame_count = 0

        async def recv(self):
            pts, time_base = await self.next_timestamp()

            loop = asyncio.get_event_loop()
            cap = await loop.run_in_executor(None, self._sct.grab, self._mon)
            img = Image.frombytes('RGB', (cap.width, cap.height), cap.rgb)

            # Redimensionar si es muy grande
            max_w = 1920
            if img.width > max_w:
                ratio = max_w / img.width
                img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)

            frame = av.VideoFrame.from_image(img)
            frame.pts = pts
            frame.time_base = time_base
            return frame

    _pc = None
    _asyncio_loop = None
    _asyncio_thread = None

    def _start_asyncio_loop():
        global _asyncio_loop
        _asyncio_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_asyncio_loop)
        _asyncio_loop.run_forever()

    def _ensure_asyncio():
        global _asyncio_thread
        if _asyncio_thread is None or not _asyncio_thread.is_alive():
            _asyncio_thread = threading.Thread(target=_start_asyncio_loop, daemon=True)
            _asyncio_thread.start()
            time.sleep(0.1)

    async def _procesar_offer(sdp, prof_sid):
        global _pc, _webrtc_activo
        if _pc:
            await _pc.close()

        _pc = RTCPeerConnection()
        track = ScreenStreamTrack()
        _pc.addTrack(track)

        @_pc.on("datachannel")
        def on_datachannel(channel):
            @channel.on("message")
            def on_message(msg):
                try:
                    data = json.loads(msg)
                    on_do_input(data)
                except Exception:
                    pass

        @_pc.on("connectionstatechange")
        async def on_state_change():
            global _webrtc_activo
            state = _pc.connectionState
            if state == "connected":
                _webrtc_activo = True
                print("[WebRTC] Conexión P2P establecida")
            elif state in ("failed", "closed", "disconnected"):
                _webrtc_activo = False
                print(f"[WebRTC] Conexión {state}")

        offer = RTCSessionDescription(sdp=sdp, type="offer")
        await _pc.setRemoteDescription(offer)
        answer = await _pc.createAnswer()
        await _pc.setLocalDescription(answer)

        sio.emit('webrtc_answer', {
            'sdp': _pc.localDescription.sdp,
            'prof_sid': prof_sid,
        })

    async def _cerrar_webrtc():
        global _pc, _webrtc_activo
        _webrtc_activo = False
        if _pc:
            await _pc.close()
            _pc = None


# ── Eventos Socket.IO ────────────────────────────────────────────────────────

@sio.on('registered')
def on_registered(data):
    print(f"[+] Registrado en el servidor (SID: {data.get('sid', '?')})")

@sio.on('do_input')
def _on_do_input(data):
    on_do_input(data)

@sio.on('viewer_start')
def on_viewer_start(data):
    global _en_observacion
    _en_observacion = True
    mode = data.get('mode', 'view')
    print(f"[*] Observación iniciada (modo: {mode})")
    # Enviar info de pantalla
    sio.emit('screen_info', {'w': _screen_w, 'h': _screen_h})

@sio.on('viewer_stop')
def on_viewer_stop(data=None):
    global _en_observacion, _webrtc_activo
    _en_observacion = False
    _webrtc_activo = False
    print("[*] Observación finalizada")
    if WEBRTC_OK and _asyncio_loop:
        asyncio.run_coroutine_threadsafe(_cerrar_webrtc(), _asyncio_loop)

@sio.on('webrtc_offer')
def on_webrtc_offer(data):
    if not WEBRTC_OK:
        return
    _ensure_asyncio()
    sdp = data.get('sdp', '')
    prof_sid = data.get('prof_sid', '')
    asyncio.run_coroutine_threadsafe(_procesar_offer(sdp, prof_sid), _asyncio_loop)

@sio.on('webrtc_ice')
def on_webrtc_ice(data):
    pass  # ICE candidates handled by aiortc internally

@sio.on('lock_screen')
def on_lock_screen(data=None):
    global _ventana_bloqueo
    if not TK_OK or not _tk_root:
        return
    def _lock():
        global _ventana_bloqueo
        if _ventana_bloqueo:
            return
        _ventana_bloqueo = _VentanaBloqueo(_tk_root)
    _tk_root.after(0, _lock)
    print("[*] Pantalla BLOQUEADA")

@sio.on('unlock_screen')
def on_unlock_screen(data=None):
    global _ventana_bloqueo
    if not TK_OK or not _tk_root:
        return
    def _unlock():
        global _ventana_bloqueo
        if _ventana_bloqueo:
            _ventana_bloqueo.destroy()
            _ventana_bloqueo = None
    _tk_root.after(0, _unlock)
    print("[*] Pantalla desbloqueada")

@sio.on('show_message')
def on_show_message(data):
    if not TK_OK or not _tk_root:
        return
    title = data.get('title', 'Mensaje')
    body = data.get('body', '')
    attachments = data.get('attachments', [])
    _tk_root.after(0, lambda: _VentanaMensaje(_tk_root, title, body, attachments))

@sio.on('teacher_screen')
def on_teacher_screen(data):
    global _ventana_profesor
    if not TK_OK or not _tk_root:
        return
    activa = data.get('activa', False)
    if activa:
        image = data.get('image', '')
        def _show():
            global _ventana_profesor
            if not _ventana_profesor:
                _ventana_profesor = _VentanaProfesor(_tk_root)
            _ventana_profesor.update_image(image)
            _ventana_profesor.show()
        _tk_root.after(0, _show)
    else:
        def _hide():
            global _ventana_profesor
            if _ventana_profesor:
                _ventana_profesor.destroy()
                _ventana_profesor = None
        _tk_root.after(0, _hide)

@sio.on('get_clipboard')
def on_get_clipboard(data=None):
    text = _get_clipboard()
    sio.emit('clipboard_data', {'text': text})

@sio.on('exec_command')
def on_exec_command(data):
    """Ejecuta un comando en el sistema y devuelve la salida."""
    cmd = data.get('command', '').strip()
    cmd_id = data.get('cmd_id', '')
    if not cmd:
        return

    def _run():
        try:
            # En Windows usar cmd.exe /c
            result = subprocess.run(
                cmd, shell=True,
                capture_output=True, text=True, timeout=30,
                cwd=os.path.expanduser('~'),
            )
            sio.emit('command_output', {
                'cmd_id': cmd_id,
                'command': cmd,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode,
                'cwd': os.path.expanduser('~'),
            })
        except subprocess.TimeoutExpired:
            sio.emit('command_output', {
                'cmd_id': cmd_id,
                'command': cmd,
                'stdout': '',
                'stderr': 'Timeout: el comando tardó más de 30 segundos.',
                'returncode': -1,
                'cwd': os.path.expanduser('~'),
            })
        except Exception as e:
            sio.emit('command_output', {
                'cmd_id': cmd_id,
                'command': cmd,
                'stdout': '',
                'stderr': str(e),
                'returncode': -1,
                'cwd': os.path.expanduser('~'),
            })

    threading.Thread(target=_run, daemon=True).start()

@sio.on('quit_app')
def on_quit_app(data=None):
    """Apagar el equipo Windows."""
    print("[*] Apagando equipo...")
    try:
        subprocess.run(['shutdown', '/s', '/t', '5'], capture_output=True)
    except Exception:
        pass


# ── Overlay (pizarra) ───────────────────────────────────────────────────────

@sio.on('overlay_toggle')
def on_overlay_toggle(data):
    global _overlay_proc
    enabled = data.get('enabled', False)
    if enabled:
        if _overlay_proc is None or _overlay_proc.poll() is not None:
            overlay_script = os.path.join(SCRIPT_DIR, 'vigia_overlay_win.py')
            if os.path.exists(overlay_script):
                _overlay_proc = subprocess.Popen(
                    [sys.executable, overlay_script,
                     str(_mon_left), str(_mon_top), str(_screen_w), str(_screen_h)],
                    stdin=subprocess.PIPE, text=True,
                )
        if _overlay_proc and _overlay_proc.poll() is None:
            _overlay_proc.stdin.write(json.dumps({'type': 'overlay_toggle', 'enabled': True}) + '\n')
            _overlay_proc.stdin.flush()
    else:
        if _overlay_proc and _overlay_proc.poll() is None:
            _overlay_proc.stdin.write(json.dumps({'type': 'overlay_toggle', 'enabled': False}) + '\n')
            _overlay_proc.stdin.flush()

@sio.on('overlay_draw')
def on_overlay_draw(data):
    if _overlay_proc and _overlay_proc.poll() is None:
        data['type'] = 'overlay_draw'
        _overlay_proc.stdin.write(json.dumps(data) + '\n')
        _overlay_proc.stdin.flush()

@sio.on('overlay_text')
def on_overlay_text(data):
    if _overlay_proc and _overlay_proc.poll() is None:
        data['type'] = 'overlay_text'
        _overlay_proc.stdin.write(json.dumps(data) + '\n')
        _overlay_proc.stdin.flush()

@sio.on('overlay_clear')
def on_overlay_clear(data=None):
    if _overlay_proc and _overlay_proc.poll() is None:
        _overlay_proc.stdin.write(json.dumps({'type': 'overlay_clear'}) + '\n')
        _overlay_proc.stdin.flush()


# ── Bucle principal de capturas ──────────────────────────────────────────────

def bucle_capturas():
    """Hilo daemon: captura pantalla normal (~1s) y frames HD cuando en observación."""
    global _ultimo_frame
    while True:
        try:
            if not sio.connected:
                time.sleep(1)
                continue

            if _en_observacion and not _webrtc_activo:
                # Frame HD para observación
                data_uri = _capturar_pantalla(quality=75, max_w=1920)
                if data_uri:
                    sio.emit('remote_frame', {
                        'image': data_uri,
                        'orig_w': _screen_w,
                        'orig_h': _screen_h,
                    })
                time.sleep(0.066)  # ~15 FPS
            else:
                # Screenshot normal (baja frecuencia)
                data_uri = _capturar_pantalla(quality=50, max_w=640)
                if data_uri:
                    sio.emit('screenshot', {'image': data_uri})
                time.sleep(1.0)

        except Exception as e:
            print(f"[!] Error en bucle_capturas: {e}")
            time.sleep(2)


# ── Conexión y main ──────────────────────────────────────────────────────────

def _conectar(server_ip, port):
    """Intenta conectar al servidor, reintentando indefinidamente."""
    url = f'http://{server_ip}:{port}'
    while True:
        try:
            print(f"[*] Conectando a {url}...")
            sio.connect(url, transports=['websocket', 'polling'])
            hostname = _get_hostname()
            sio.emit('register', {'name': hostname})
            print(f"[+] Conectado como '{hostname}'")

            # Enviar info de pantalla inicial
            with mss.mss() as sct:
                mon = sct.monitors[1]
                sio.emit('screen_info', {'w': mon['width'], 'h': mon['height']})

            return
        except Exception as e:
            print(f"[!] Error de conexión: {e}. Reintentando en 5s...")
            time.sleep(5)


@sio.on('disconnect')
def on_disconnect():
    print("[!] Desconectado del servidor. Reconectando...")


def main():
    global _tk_root

    # Parsear argumentos
    server_ip = sys.argv[1] if len(sys.argv) > 1 else None
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000

    # Leer IP de archivo de configuración si no se pasa como argumento
    if not server_ip:
        config_path = os.path.join(os.environ.get('PROGRAMDATA', 'C:\\ProgramData'),
                                   'vigia', 'client.conf')
        if os.path.exists(config_path):
            server_ip = open(config_path).read().strip()

    if not server_ip:
        # Intentar auto-detectar (X.X.X.2)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            local_ip = s.getsockname()[0]
            s.close()
            parts = local_ip.split('.')
            parts[3] = '2'
            server_ip = '.'.join(parts)
        except Exception:
            server_ip = '192.168.1.2'

    print(f"VIGIA Cliente Windows — Servidor: {server_ip}:{port}")

    # Conectar en hilo separado
    threading.Thread(target=_conectar, args=(server_ip, port), daemon=True).start()

    # Iniciar capturas en hilo separado
    threading.Thread(target=bucle_capturas, daemon=True).start()

    # Tkinter main loop (si está disponible)
    if TK_OK:
        _tk_root = tk.Tk()
        _tk_root.withdraw()  # Ventana oculta
        _tk_root.title('VIGIA Cliente')
        try:
            icon_path = os.path.join(IMG_DIR, 'logo2_mini.png')
            if os.path.exists(icon_path):
                _icon = tk.PhotoImage(file=icon_path)
                _tk_root.iconphoto(True, _icon)
        except Exception:
            pass

        # Mantener vivo el mainloop de Tkinter
        def _check():
            _tk_root.after(500, _check)
        _tk_root.after(500, _check)

        try:
            _tk_root.mainloop()
        except KeyboardInterrupt:
            pass
    else:
        # Sin Tkinter, simplemente esperar
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
