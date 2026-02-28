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
from html.parser import HTMLParser as _HTMLParser

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
    if not pip_cmd:
        os.system('sudo apt-get update -qq 2>/dev/null && sudo apt-get install -y python3-pip -qq 2>/dev/null')
        pip_cmd = _pip_disponible()
    if pip_cmd:
        try:
            res = subprocess.run(pip_cmd + ['install', '--user', '--break-system-packages', '-q'] + paquete.split(), timeout=60)
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
        print("  [*] Falta ImageTk (PIL). Intentando instalar dependencias de sistema...")
        os.system('sudo apt-get update -qq 2>/dev/null && sudo apt-get install -y python3-pil.imagetk -qq 2>/dev/null')
        try:
            from PIL import ImageTk
            IMGTK_OK = True
        except ImportError:
            print("  [*] No se pudo cargar ImageTk vía apt. Reinstalando Pillow...")
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

def _init_input():
    global _mouse_ctrl, _kbd_ctrl, _PBtn, _XDO_CMD
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
        print("  [!] xdotool NO detectado. Intentando instalar...")
        os.system('sudo apt-get update -qq 2>/dev/null && sudo apt-get install -y xdotool -qq 2>/dev/null')
        _XDO_CMD = shutil.which('xdotool')
        if _XDO_CMD: print(f"  [✓] xdotool instalado correctamente.")
    
    return (_mouse_ctrl is not None) or (_XDO_CMD is not None)

INPUT_OK = _init_input()

_XDO_KEY_MAP = {
    'space': 'space', 'enter': 'Return', 'esc': 'Escape', 'tab': 'Tab',
    'backspace': 'BackSpace', 'delete': 'Delete', 'insert': 'Insert',
    'home': 'Home', 'end': 'End', 'pageup': 'Page_Up', 'pagedown': 'Page_Down',
    'left': 'Left', 'right': 'Right', 'up': 'Up', 'down': 'Down',
    'ctrl': 'Control_L', 'alt': 'Alt_L', 'shift': 'Shift_L', 'win': 'Super_L'
}

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
_cola_profesor = queue.Queue(maxsize=3)
_cola_bloqueo  = queue.Queue(maxsize=10)
_cola_mensajes = queue.Queue(maxsize=20)
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
        _TARGET_FPS = 15

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
                if w > 1920:
                    new_w, new_h = 1920, int(h * 1920 / w)
                    img = Image.fromarray(rgb).resize((new_w, new_h), Image.LANCZOS)
                    rgb = np.array(img)
                return rgb
            except Exception as e:
                print(f"  [WebRTC] Captura: {e}")
                if self._sct:
                    try: self._sct.close()
                    except: pass
                    self._sct = None
                return np.zeros((720, 1280, 3), dtype=np.uint8)

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
                ancho_r = min(orig_w, 1920)
                if img.width > ancho_r:
                    img = img.resize((ancho_r, int(img.height * ancho_r / img.width)), Image.LANCZOS)
                buf = io.BytesIO(); img.save(buf, format='JPEG', quality=75)
                sio.emit('remote_frame', {'image': _b64(buf.getvalue()), 'orig_w': orig_w, 'orig_h': orig_h})
                time.sleep(0.1)
            else:
                time.sleep(0.3)
        except:
            try: sct.close()
            except: pass
            sct = None; time.sleep(1)

# ── Manejo de entrada ─────────────────────────────────────────────────────────
@sio.on('do_input')
def on_do_input(data):
    if not INPUT_OK: return
    tipo = data.get('type', '')
    try:
        x = int(data.get('x', 0))
        y = int(data.get('y', 0))
    except: return

    pynput_done = False
    if _mouse_ctrl and _PBtn:
        try:
            if tipo == 'mousemove':
                _mouse_ctrl.position = (x, y)
            elif tipo == 'mousedown':
                _mouse_ctrl.position = (x, y)
                btn = {'left': _PBtn.left, 'middle': _PBtn.middle, 'right': _PBtn.right}.get(data.get('button'), _PBtn.left)
                _mouse_ctrl.press(btn)
            elif tipo == 'mouseup':
                _mouse_ctrl.position = (x, y)
                btn = {'left': _PBtn.left, 'middle': _PBtn.middle, 'right': _PBtn.right}.get(data.get('button'), _PBtn.left)
                _mouse_ctrl.release(btn)
            elif tipo == 'scroll':
                _mouse_ctrl.position = (x, y); _mouse_ctrl.scroll(0, int(data.get('dy', 0)))
            elif tipo == 'keydown':
                _kbd_ctrl.press(_get_pynput_key(data.get('key')))
            elif tipo == 'keyup':
                _kbd_ctrl.release(_get_pynput_key(data.get('key')))
            pynput_done = True
        except: pass

    if not pynput_done and _XDO_CMD:
        try:
            env = dict(os.environ); 
            if 'DISPLAY' not in env: env['DISPLAY'] = ':0'
            
            def _xdo(*args): 
                try:
                    subprocess.Popen([_XDO_CMD] + [str(a) for a in args], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception as e:
                    print(f"  [!] Error ejecutando xdo {args}: {e}")
            
            if tipo == 'mousemove':
                _xdo('mousemove', '--sync', x, y)
            elif tipo == 'mousedown':
                btn = {'left': 1, 'middle': 2, 'right': 3}.get(data.get('button'), 1)
                _xdo('mousemove', '--sync', x, y, 'mousedown', btn)
            elif tipo == 'mouseup':
                btn = {'left': 1, 'middle': 2, 'right': 3}.get(data.get('button'), 1)
                _xdo('mousemove', '--sync', x, y, 'mouseup', btn)
            elif tipo == 'scroll':
                btn = 4 if int(data.get('dy', 0)) > 0 else 5
                _xdo('mousemove', '--sync', x, y)
                for _ in range(3): _xdo('click', btn)
            elif tipo == 'keydown':
                k = _XDO_KEY_MAP.get(data.get('key', '').lower(), data.get('key'))
                _xdo('keydown', k)
            elif tipo == 'keyup':
                k = _XDO_KEY_MAP.get(data.get('key', '').lower(), data.get('key'))
                _xdo('keyup', k)
        except: pass

# ── Eventos Socket.IO ─────────────────────────────────────────────────────────
@sio.event
def connect():
    print(f"[✓] Conectado al servidor.")
    sio.emit('register', {'name': f"{os.environ.get('USER','alumno')} - {socket.gethostname()}"})

@sio.on('viewer_start')
def on_viewer_start(data):
    global _en_observacion; _en_observacion = True
    print(f"[*] El profesor está observando/controlando.")

@sio.on('viewer_stop')
def on_viewer_stop(_data):
    global _en_observacion; _en_observacion = False
    print(f"[*] Fin de observación.")
    if WEBRTC_OK:
        _wrtc(_cerrar_webrtc())

@sio.on('quit_app')
def on_quit_app(_data): os._exit(0)

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
        self.top.geometry("960x560"); self.top.attributes('-topmost', True)
        self._label = tk.Label(self.top, bg='#0f1117', text="⏳ Esperando imagen…", fg='#718096', font=('Segoe UI', 12))
        self._label.pack(expand=True, fill='both'); self._foto = None
        self.top.protocol("WM_DELETE_WINDOW", self.destruir)
    def actualizar(self, b64):
        try:
            img = Image.open(io.BytesIO(base64.b64decode(b64.split(',', 1)[1])))
            img.thumbnail((self.top.winfo_width() or 960, self.top.winfo_height() or 560), Image.LANCZOS)
            self._foto = ImageTk.PhotoImage(img); self._label.config(image=self._foto, text='')
        except: pass
    def destruir(self): self.top.destroy()

class _VentanaMensaje:
    def __init__(self, root, msg):
        t = tk.Toplevel(root); t.title(msg.get('title', 'Mensaje')); t.configure(bg='#1a1d27'); t.attributes('-topmost', True)
        c = tk.Frame(t, bg='#1a1d27', padx=20, pady=20); c.pack()
        txt = tk.Text(c, bg='#1a1d27', fg='#e2e8f0', font=('Segoe UI', 12), wrap='word', height=6, width=40, relief='flat')
        txt.insert('end', re.sub(r'<[^>]+>', '', msg.get('body', ''))); txt.config(state='disabled'); txt.pack()
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
        except: pass
        root.after(100, check)
    check(); root.mainloop()

if __name__ == '__main__':
    ip = sys.argv[1] if len(sys.argv) > 1 else input("IP Servidor: ")
    if WEBRTC_OK:
        threading.Thread(target=_asyncio_runner, name='WebRTC-Loop', daemon=True).start()
        time.sleep(0.1)   # Dar tiempo al loop a arrancar
    threading.Thread(target=lambda: sio.connect(f"http://{ip}:5000", transports=['websocket']), daemon=True).start()
    threading.Thread(target=bucle_capturas, daemon=True).start()
    if TK_OK: ejecutar_interfaz()
    else: 
        try: 
            while True: time.sleep(1)
        except KeyboardInterrupt: pass
