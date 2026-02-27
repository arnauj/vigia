#!/usr/bin/env python3
"""
VIGIA - Cliente del Alumno (v1.3 - Control Remoto Fijo)
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

# ── Importaciones con autoinstalación amigable ───────────────────────────────

def _pip_disponible():
    """Detecta el comando pip que funciona para el intérprete actual."""
    try:
        if subprocess.run([sys.executable, '-m', 'pip', '--version'], 
                          capture_output=True, timeout=2).returncode == 0:
            return [sys.executable, '-m', 'pip']
    except Exception: pass
    if shutil.which('pip3'): return ['pip3']
    if shutil.which('pip'): return ['pip']
    p = os.path.expanduser('~/.local/bin/pip3')
    if os.path.exists(p) and os.access(p, os.X_OK): return [p]
    return None

def _instalar(paquete):
    """Intenta instalar un paquete Python de forma automática y robusta."""
    print(f"  [VIGIA] Instalando {paquete}...")
    import importlib
    pip_cmd = _pip_disponible()
    if not pip_cmd:
        print("  [*] pip no encontrado. Intentando instalar con apt...")
        os.system('sudo apt-get update -qq 2>/dev/null && sudo apt-get install -y python3-pip -qq 2>/dev/null')
        pip_cmd = _pip_disponible()
    if pip_cmd:
        try:
            res = subprocess.run(pip_cmd + ['install', '--user', '--break-system-packages', '-q'] + paquete.split(), timeout=60)
            if res.returncode == 0:
                importlib.invalidate_caches()
                return True
        except Exception: pass
    else:
        os.system(f'pip3 install --user --break-system-packages -q {paquete}')
    importlib.invalidate_caches()
    return False

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
        for _k in list(sys.modules.keys()):
            if _k == 'PIL' or _k.startswith('PIL.'): del sys.modules[_k]
        from PIL import Image, ImageTk
        IMGTK_OK = True
else:
    ImageTk = None; IMGTK_OK = False

# ── Control remoto (Preferir pynput, fallback xdotool) ─────────────────────────
_mouse_ctrl = None
_kbd_ctrl   = None
_XDO_CMD    = shutil.which('xdotool')

def _init_input():
    global _mouse_ctrl, _kbd_ctrl
    try:
        from pynput.mouse import Controller as MouseController
        from pynput.keyboard import Controller as KbdController
        _mouse_ctrl = MouseController()
        _kbd_ctrl = KbdController()
        print("  [✓] Control remoto vía pynput habilitado.")
        return True
    except Exception as e:
        if _XDO_CMD:
            print("  [✓] Control remoto vía xdotool habilitado.")
            return True
        else:
            print(f"  [!] Fallo inicializando pynput: {e}")
            print("  [*] Intentando instalar xdotool...")
            os.system('sudo apt-get install -y xdotool -qq 2>/dev/null')
            if shutil.which('xdotool'):
                global _XDO_CMD
                _XDO_CMD = shutil.which('xdotool')
                print("  [✓] xdotool instalado con éxito.")
                return True
    return False

INPUT_OK = _init_input()

# Mapeo para xdotool
_XDO_KEY_MAP = {
    'space': 'space', 'enter': 'Return', 'esc': 'Escape', 'tab': 'Tab',
    'backspace': 'BackSpace', 'delete': 'Delete', 'insert': 'Insert',
    'home': 'Home', 'end': 'End', 'pageup': 'Page_Up', 'pagedown': 'Page_Down',
    'left': 'Left', 'right': 'Right', 'up': 'Up', 'down': 'Down',
    'f1': 'F1', 'f2': 'F2', 'f3': 'F3', 'f4': 'F4', 'f5': 'F5', 'f6': 'F6',
    'f7': 'F7', 'f8': 'F8', 'f9': 'F9', 'f10': 'F10', 'f11': 'F11', 'f12': 'F12',
    'ctrl': 'Control_L', 'alt': 'Alt_L', 'shift': 'Shift_L', 'win': 'Super_L',
    'capslock': 'Caps_Lock', 'numlock': 'Num_Lock'
}

# Mapeo para pynput
def _get_pynput_key(key):
    from pynput.keyboard import Key
    m = {
        'enter': Key.enter, 'esc': Key.esc, 'tab': Key.tab, 'space': Key.space,
        'backspace': Key.backspace, 'delete': Key.delete, 'insert': Key.insert,
        'home': Key.home, 'end': Key.end, 'pageup': Key.page_up, 'pagedown': Key.page_down,
        'left': Key.left, 'right': Key.right, 'up': Key.up, 'down': Key.down,
        'f1': Key.f1, 'f2': Key.f2, 'f3': Key.f3, 'f4': Key.f4, 'f5': Key.f5, 'f6': Key.f6,
        'f7': Key.f7, 'f8': Key.f8, 'f9': Key.f9, 'f10': Key.f10, 'f11': Key.f11, 'f12': Key.f12,
        'ctrl': Key.ctrl, 'alt': Key.alt, 'shift': Key.shift, 'win': Key.cmd,
        'capslock': Key.caps_lock, 'numlock': Key.num_lock
    }
    return m.get(key.lower(), key)

# ── Configuración ────────────────────────────────────────────────────────────
ANCHO_IMAGEN      = 1280
CALIDAD_JPEG      = 55
INTERVALO_SEG     = 2.5
INTERVALO_REMOTO  = 0.4
REINTENTOS_ESPERA = 5

# ── Estado global ─────────────────────────────────────────────────────────────
conectado         = False
_en_observacion   = False
_modo_observacion = 'view'
sio = sio_module.Client(reconnection=True, reconnection_attempts=0, reconnection_delay=REINTENTOS_ESPERA)

_cola_profesor:  queue.Queue = queue.Queue(maxsize=3)
_cola_bloqueo:   queue.Queue = queue.Queue(maxsize=10)
_cola_mensajes:  queue.Queue = queue.Queue(maxsize=20)

# ── Bucle de capturas ─────────────────────────────────────────────────────────
def _b64(jpeg: bytes) -> str:
    return 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode()

def bucle_capturas():
    _ultimo_screenshot = 0.0
    sct = None
    while True:
        if not conectado:
            time.sleep(0.5); continue
        if sct is None:
            try: sct = mss.mss()
            except: time.sleep(2); continue
        en_obs = _en_observacion
        now    = time.monotonic()
        if not en_obs and (now - _ultimo_screenshot) < INTERVALO_SEG:
            time.sleep(0.2); continue
        try:
            monitor = sct.monitors[1]
            orig_w, orig_h = monitor['width'], monitor['height']
            captura = sct.grab(monitor)
            img = Image.frombytes('RGB', captura.size, captura.bgra, 'raw', 'BGRX')
        except:
            try: sct.close()
            except: pass
            sct = None; time.sleep(1); continue

        if en_obs:
            ancho_r = min(orig_w, 1920)
            img_r = img.resize((ancho_r, int(img.height * ancho_r / img.width)), Image.LANCZOS) if img.width > ancho_r else img
            buf = io.BytesIO(); img_r.save(buf, format='JPEG', quality=75, optimize=True)
            try: sio.emit('remote_frame', {'image': _b64(buf.getvalue()), 'orig_w': orig_w, 'orig_h': orig_h})
            except: pass

        if (now - _ultimo_screenshot) >= INTERVALO_SEG:
            img_n = img.resize((ANCHO_IMAGEN, int(img.height * ANCHO_IMAGEN / img.width)), Image.LANCZOS) if img.width > ANCHO_IMAGEN else img
            buf2 = io.BytesIO(); img_n.save(buf2, format='JPEG', quality=CALIDAD_JPEG, optimize=True)
            try:
                sio.emit('screenshot', {'image': _b64(buf2.getvalue())})
                _ultimo_screenshot = now
            except: pass
        time.sleep(INTERVALO_REMOTO if en_obs else 0.5)

# ── Manejo de entrada remota ───────────────────────────────────────────────────
@sio.on('do_input')
def on_do_input(data):
    if not INPUT_OK: return
    tipo = data.get('type', '')
    x, y = data.get('x'), data.get('y')
    
    # Intentar con pynput primero
    if _mouse_ctrl and _kbd_ctrl:
        try:
            from pynput.mouse import Button
            if tipo == 'mousemove' and x is not None:
                _mouse_ctrl.position = (x, y)
            elif tipo == 'mousedown' and x is not None:
                _mouse_ctrl.position = (x, y)
                btn = {'left': Button.left, 'middle': Button.middle, 'right': Button.right}.get(data.get('button'), Button.left)
                _mouse_ctrl.press(btn)
            elif tipo == 'mouseup' and x is not None:
                btn = {'left': Button.left, 'middle': Button.middle, 'right': Button.right}.get(data.get('button'), Button.left)
                _mouse_ctrl.release(btn)
            elif tipo == 'scroll' and x is not None:
                _mouse_ctrl.position = (x, y)
                _mouse_ctrl.scroll(0, int(data.get('dy', 0)))
            elif tipo == 'keydown':
                _kbd_ctrl.press(_get_pynput_key(data.get('key')))
            elif tipo == 'keyup':
                _kbd_ctrl.release(_get_pynput_key(data.get('key')))
            return
        except Exception as e:
            print(f"  [!] Error pynput: {e}. Reintentando con xdotool...")

    # Fallback xdotool
    if _XDO_CMD:
        try:
            env = dict(os.environ); env.setdefault('DISPLAY', ':0')
            def _xdo(*args): subprocess.Popen([_XDO_CMD] + [str(a) for a in args], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if tipo == 'mousemove' and x is not None:
                _xdo('mousemove', '--sync', x, y)
            elif tipo == 'mousedown' and x is not None:
                btn = {'left': 1, 'middle': 2, 'right': 3}.get(data.get('button'), 1)
                _xdo('mousemove', '--sync', x, y, 'mousedown', btn)
            elif tipo == 'mouseup' and x is not None:
                btn = {'left': 1, 'middle': 2, 'right': 3}.get(data.get('button'), 1)
                _xdo('mouseup', btn)
            elif tipo == 'scroll' and x is not None:
                dy = int(data.get('dy', 0))
                btn = 4 if dy > 0 else 5
                for _ in range(min(abs(dy), 10)): _xdo('click', btn)
            elif tipo == 'keydown':
                k = _XDO_KEY_MAP.get(data.get('key', '').lower(), data.get('key'))
                _xdo('keydown', k)
            elif tipo == 'keyup':
                k = _XDO_KEY_MAP.get(data.get('key', '').lower(), data.get('key'))
                _xdo('keyup', k)
        except Exception as e:
            print(f"  [!] Fallo crítico xdotool: {e}")

# ── Resto de eventos ──────────────────────────────────────────────────────────
@sio.event
def connect():
    global conectado; conectado = True
    user = os.environ.get('USER','alumno')
    sio.emit('register', {'name': f"{user} - {socket.gethostname()}"})

@sio.event
def disconnect():
    global conectado; conectado = False

@sio.on('quit_app')
def on_quit_app(_data): os._exit(0)

@sio.on('show_message')
def on_show_message(data):
    if TK_OK: _cola_mensajes.put_nowait(data)

@sio.on('viewer_start')
def on_viewer_start(data):
    global _en_observacion, _modo_observacion
    _en_observacion = True; _modo_observacion = data.get('mode', 'view')

@sio.on('viewer_stop')
def on_viewer_stop(_data):
    global _en_observacion; _en_observacion = False

@sio.on('lock_screen')
def on_lock_screen(_data):
    if TK_OK: _cola_bloqueo.put_nowait(True)

@sio.on('unlock_screen')
def on_unlock_screen(_data):
    if TK_OK: _cola_bloqueo.put_nowait(False)

@sio.on('teacher_screen')
def on_teacher_screen(data):
    if IMGTK_OK:
        try: _cola_profesor.put_nowait(data)
        except queue.Full:
            try: _cola_profesor.get_nowait(); _cola_profesor.put_nowait(data)
            except: pass

# ── Interfaz UI ──────────────────────────────────────────────────────────────
class _VentanaProfesor:
    def __init__(self, root):
        self.top = tk.Toplevel(root); self.top.title("📺 Pantalla del Profesor — VIGIA")
        self.top.configure(bg='#0f1117'); self.top.geometry("960x560")
        cab = tk.Frame(self.top, bg='#1a1d27'); cab.pack(fill='x')
        tk.Label(cab, text="  El profesor está compartiendo su pantalla", bg='#1a1d27', fg='#4f8ef7', font=('Segoe UI', 9, 'bold')).pack(side='left', pady=5)
        self._label = tk.Label(self.top, bg='#0f1117', text="⏳ Esperando imagen…", fg='#718096', font=('Segoe UI', 12)); self._label.pack(expand=True, fill='both')
        self._foto = None; self.top.attributes('-topmost', True); self.top.protocol("WM_DELETE_WINDOW", self.destruir)
    def actualizar(self, imagen_b64):
        try:
            img = Image.open(io.BytesIO(base64.b64decode(imagen_b64.split(',', 1)[1])))
            img.thumbnail((max(self.top.winfo_width(), 960), max(self.top.winfo_height()-30, 530)), Image.LANCZOS)
            self._foto = ImageTk.PhotoImage(img); self._label.config(image=self._foto, text='')
        except: pass
    def destruir(self): self.top.destroy()

class _VentanaMensaje:
    def __init__(self, root, msg):
        t = tk.Toplevel(root); t.title(msg.get('title', 'Mensaje'))
        t.configure(bg='#1a1d27'); t.attributes('-topmost', True)
        tk.Label(t, text=f"  ✉ {msg.get('title')}", bg='#4f8ef7', fg='white', font=('Segoe UI', 10, 'bold')).pack(fill='x', pady=0)
        c = tk.Frame(t, bg='#1a1d27', padx=20, pady=20); c.pack()
        txt = tk.Text(c, bg='#1a1d27', fg='#e2e8f0', font=('Segoe UI', 12), wrap='word', height=6, width=40, relief='flat')
        txt.insert('end', re.sub(r'<[^>]+>', '', msg.get('body', ''))); txt.config(state='disabled'); txt.pack()
        tk.Button(c, text="Aceptar", bg='#4f8ef7', fg='white', command=t.destroy).pack(pady=(15, 0))

class _VentanaBloqueo:
    def __init__(self, root):
        self.top = tk.Toplevel(root); self.top.attributes('-fullscreen', True, '-topmost', True)
        self.top.configure(bg='#0a0c14'); self.top.overrideredirect(True)
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
    root = tk.Tk(); root.withdraw()
    v_prof = None; v_bloq = None
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
