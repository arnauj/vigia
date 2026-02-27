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
        _instalar("--force-reinstall Pillow")
        from PIL import Image, ImageTk
        IMGTK_OK = True
else:
    ImageTk = None; IMGTK_OK = False

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
    
    if _XDO_CMD:
        print(f"  [✓] xdotool detectado en {_XDO_CMD}.")
    
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
INTERVALO_SEG     = 2.5
REINTENTOS_ESPERA = 5

# ── Estado ───────────────────────────────────────────────────────────────────
sio = sio_module.Client(reconnection=True, reconnection_attempts=0)
_cola_profesor = queue.Queue(maxsize=3)
_cola_bloqueo  = queue.Queue(maxsize=10)
_cola_mensajes = queue.Queue(maxsize=20)
_en_observacion = False

def _b64(jpeg: bytes) -> str:
    return 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode()

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
            
            if _en_observacion:
                captura = sct.grab(monitor)
                img = Image.frombytes('RGB', captura.size, captura.bgra, 'raw', 'BGRX')
                ancho_r = min(orig_w, 1920)
                if img.width > ancho_r:
                    img = img.resize((ancho_r, int(img.height * ancho_r / img.width)), Image.LANCZOS)
                buf = io.BytesIO(); img.save(buf, format='JPEG', quality=75)
                sio.emit('remote_frame', {'image': _b64(buf.getvalue()), 'orig_w': orig_w, 'orig_h': orig_h})
                time.sleep(0.3)
            else:
                time.sleep(0.5)
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
            env = dict(os.environ); env.setdefault('DISPLAY', ':0')
            def _xdo(*args): subprocess.Popen([_XDO_CMD] + [str(a) for a in args], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
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
    threading.Thread(target=lambda: sio.connect(f"http://{ip}:5000", transports=['websocket']), daemon=True).start()
    threading.Thread(target=bucle_capturas, daemon=True).start()
    if TK_OK: ejecutar_interfaz()
    else: 
        try: 
            while True: time.sleep(1)
        except KeyboardInterrupt: pass
