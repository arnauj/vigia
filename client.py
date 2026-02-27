#!/usr/bin/env python3
"""
VIGIA - Cliente del Alumno
Captura la pantalla y la envía al servidor del profesor.
Muestra la pantalla del profesor cuando este la comparte.
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
    return subprocess.run(
        [sys.executable, '-m', 'pip', '--version'],
        capture_output=True,
    ).returncode == 0


def _instalar(paquete):
    print(f"  Instalando {paquete}...")
    import importlib
    if not _pip_disponible():
        print("  [*] pip no disponible. Intentando activarlo con ensurepip...")
        # Intento 1: ensurepip — sin internet ni sudo, usa wheels del propio Python
        try:
            import ensurepip
            ensurepip.bootstrap(upgrade=True)
        except Exception:
            pass
        # Intento 2: apt-get (solo funciona si hay terminal con sudo disponible)
        if not _pip_disponible():
            os.system('sudo apt-get install -y python3-pip -qq 2>/dev/null')
    if _pip_disponible():
        ret = subprocess.run(
            [sys.executable, '-m', 'pip', 'install',
             '--user', '--break-system-packages', '-q'] + paquete.split(),
        ).returncode
    else:
        # Último recurso: pip3 del sistema
        ret = os.system(f'pip3 install --user --break-system-packages -q {paquete}')
    if ret != 0:
        print(f"\n  [!] No se pudo instalar '{paquete}' automáticamente.")
        print(f"  Ejecuta manualmente en una terminal:")
        print(f"    sudo apt install python3-pip")
        print(f"    pip3 install --break-system-packages {paquete}\n")
    importlib.invalidate_caches()


try:
    import socketio as sio_module
except ImportError:
    _instalar("python-socketio[client] websocket-client")
    try:
        import socketio as sio_module
    except ImportError:
        print("\n  [!] No se pudo cargar 'socketio'. Instálalo manualmente:")
        print("      sudo apt install python3-pip")
        print("      pip3 install --break-system-packages 'python-socketio[client]' websocket-client\n")
        input("Pulsa Enter para cerrar...")
        sys.exit(1)

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

# tkinter es opcional: sin él no se muestra la pantalla del profesor
try:
    import tkinter as tk
    TK_OK = True
except Exception:
    TK_OK = False

# Si tkinter está disponible pero ImageTk no se puede importar, el sistema
# tiene el PIL del sistema (sin ImageTk). Se reinstala Pillow con pip.
if TK_OK:
    try:
        from PIL import ImageTk as _imgtk_test
        del _imgtk_test
    except ImportError:
        print("  [*] PIL del sistema detectado (sin ImageTk). Reinstalando Pillow…")
        # Limpiar caché de módulos para que Python encuentre el Pillow de pip
        for _k in list(sys.modules.keys()):
            if _k == 'PIL' or _k.startswith('PIL.'):
                del sys.modules[_k]
        _instalar("--force-reinstall Pillow")
        from PIL import Image  # reimportar desde el nuevo Pillow

# ImageTk es necesario solo para mostrar la pantalla del profesor
try:
    from PIL import ImageTk
    IMGTK_OK = TK_OK
except Exception:
    ImageTk = None
    IMGTK_OK = False

# pyautogui es opcional: necesario solo para el control remoto
# ── Control remoto: xdotool (principal) + pynput (alternativa) ───────────────
#   xdotool: herramienta de sistema, sin dependencias Python, muy fiable en X11
#   pynput:  biblioteca Python, funciona en X11 y potencialmente en Wayland
INPUT_OK   = False
INPUT_MODE = None   # 'xdotool' | 'pynput'

# ── Intento 1: xdotool ───────────────────────────────────────────────────────
if shutil.which('xdotool'):
    INPUT_OK   = True
    INPUT_MODE = 'xdotool'
else:
    # Intentar instalar xdotool vía apt (no requiere internet)
    os.system('sudo apt-get install -y xdotool -qq 2>/dev/null')
    if shutil.which('xdotool'):
        INPUT_OK   = True
        INPUT_MODE = 'xdotool'

# ── Intento 2: pynput (si xdotool no está disponible) ───────────────────────
_mouse_ctrl = None
_kbd_ctrl   = None
_KEY_MAP: dict = {}
_BTN_MAP: dict = {}

if not INPUT_OK:
    def _cargar_pynput():
        global INPUT_OK, INPUT_MODE, _mouse_ctrl, _kbd_ctrl, _KEY_MAP, _BTN_MAP
        from pynput.mouse    import Button as _PBtn, Controller as _PMouse
        from pynput.keyboard import Key    as _PKey, Controller as _PKbd
        _mouse_ctrl = _PMouse()
        _kbd_ctrl   = _PKbd()
        _KEY_MAP = {
            'enter':    _PKey.enter,    'esc':       _PKey.esc,
            'tab':      _PKey.tab,      'backspace':  _PKey.backspace,
            'delete':   _PKey.delete,   'insert':    _PKey.insert,
            'home':     _PKey.home,     'end':       _PKey.end,
            'pageup':   _PKey.page_up,  'pagedown':  _PKey.page_down,
            'left':     _PKey.left,     'right':     _PKey.right,
            'up':       _PKey.up,       'down':      _PKey.down,
            'space':    _PKey.space,
            'ctrl':     _PKey.ctrl,     'alt':       _PKey.alt,
            'shift':    _PKey.shift,    'win':       _PKey.cmd,
            'capslock': _PKey.caps_lock,'numlock':   _PKey.num_lock,
            'f1':_PKey.f1,'f2':_PKey.f2,'f3':_PKey.f3,'f4':_PKey.f4,
            'f5':_PKey.f5,'f6':_PKey.f6,'f7':_PKey.f7,'f8':_PKey.f8,
            'f9':_PKey.f9,'f10':_PKey.f10,'f11':_PKey.f11,'f12':_PKey.f12,
        }
        _BTN_MAP = {'left':_PBtn.left,'middle':_PBtn.middle,'right':_PBtn.right}
        INPUT_OK   = True
        INPUT_MODE = 'pynput'
    try:
        _cargar_pynput()
    except Exception:
        os.system('sudo apt-get install -y python3-pynput -qq 2>/dev/null')
        try:
            _cargar_pynput()
        except Exception:
            pass  # Control remoto no disponible

# ── Tabla xdotool ─────────────────────────────────────────────────────────────
# Nombres de teclas del dashboard (_mapKey) → nombres de keysym de xdotool
_XDOKEY = {
    'enter':'Return','esc':'Escape','tab':'Tab',
    'backspace':'BackSpace','delete':'Delete','insert':'Insert',
    'home':'Home','end':'End','pageup':'Page_Up','pagedown':'Page_Down',
    'left':'Left','right':'Right','up':'Up','down':'Down','space':'space',
    'ctrl':'ctrl','shift':'shift','alt':'alt','win':'super',
    'capslock':'Caps_Lock','numlock':'Num_Lock',
    'f1':'F1','f2':'F2','f3':'F3','f4':'F4','f5':'F5','f6':'F6',
    'f7':'F7','f8':'F8','f9':'F9','f10':'F10','f11':'F11','f12':'F12',
    # Caracteres especiales → keysym X11
    '!':'exclam','@':'at','#':'numbersign','$':'dollar','%':'percent',
    '^':'asciicircum','&':'ampersand','*':'asterisk',
    '(':'parenleft',')':'parenright','_':'underscore','-':'minus',
    '+':'plus','=':'equal','[':'bracketleft',']':'bracketright',
    '{':'braceleft','}':'braceright','|':'bar','\\':'backslash',
    ';':'semicolon',':':'colon',"'":'apostrophe','"':'quotedbl',
    ',':'comma','.':'period','<':'less','>':'greater',
    '/':'slash','?':'question','`':'grave','~':'asciitilde',
}
_XDO_MODS   = frozenset({'ctrl','shift','alt','win'})
_xdo_mods_held: set = set()   # teclas modificadoras actualmente pulsadas

def _xdo(*args):
    """Lanza xdotool de forma no bloqueante con DISPLAY garantizado."""
    env = dict(os.environ)
    env.setdefault('DISPLAY', ':0')
    subprocess.Popen(
        ['xdotool'] + [str(a) for a in args],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

PYAUTOGUI_OK = INPUT_OK  # alias

# ── Configuración ────────────────────────────────────────────────────────────

ANCHO_IMAGEN      = 1280   # px máximos de ancho enviados al servidor
CALIDAD_JPEG      = 55     # 0-95; menor = más rápido, peor calidad
INTERVALO_SEG     = 2.5    # segundos entre capturas normales
INTERVALO_REMOTO  = 0.4    # segundos entre frames en modo observación/control
REINTENTOS_ESPERA = 5      # segundos entre reconexiones

# ── Estado global ─────────────────────────────────────────────────────────────

conectado         = False
_en_observacion   = False
_modo_observacion = 'view'   # 'view' | 'control'
sio = sio_module.Client(
    reconnection=True,
    reconnection_attempts=0,
    reconnection_delay=REINTENTOS_ESPERA,
)

# Colas para comunicar hilos → Tkinter principal
_cola_profesor:  queue.Queue = queue.Queue(maxsize=3)
_cola_bloqueo:   queue.Queue = queue.Queue(maxsize=10)
_cola_mensajes:  queue.Queue = queue.Queue(maxsize=20)


# ── Captura de pantalla del alumno ────────────────────────────────────────────

def capturar_pantalla() -> bytes | None:
    """Captura el monitor principal y devuelve JPEG comprimido en bytes."""
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            captura = sct.grab(monitor)
            img = Image.frombytes('RGB', captura.size, captura.bgra, 'raw', 'BGRX')
    except Exception as e:
        try:
            ruta = '/tmp/_vigia_cap.png'
            if os.system(f'scrot "{ruta}" 2>/dev/null') != 0:
                raise RuntimeError("scrot falló")
            img = Image.open(ruta).convert('RGB')
        except Exception:
            print(f"[!] Error capturando pantalla: {e}")
            return None

    if img.width > ANCHO_IMAGEN:
        h = int(img.height * ANCHO_IMAGEN / img.width)
        img = img.resize((ANCHO_IMAGEN, h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=CALIDAD_JPEG, optimize=True)
    return buf.getvalue()


def _b64(jpeg: bytes) -> str:
    return 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode()


def bucle_capturas():
    """Hilo daemon unificado: capturas normales + frames remotos en un único contexto mss."""
    _ultimo_screenshot = 0.0
    sct = None

    while True:
        if not conectado:
            time.sleep(0.5)
            continue

        # Mantener un único contexto mss abierto para evitar conflictos X11
        if sct is None:
            try:
                sct = mss.mss()
            except Exception as e:
                print(f"[!] No se puede iniciar mss: {e}")
                time.sleep(2)
                continue

        en_obs = _en_observacion
        now    = time.monotonic()

        # En modo normal: esperar hasta que toque capturar
        if not en_obs and (now - _ultimo_screenshot) < INTERVALO_SEG:
            restante = INTERVALO_SEG - (now - _ultimo_screenshot)
            time.sleep(min(0.3, restante))
            continue

        # Capturar pantalla una sola vez con el contexto mss abierto
        try:
            monitor = sct.monitors[1]
            orig_w  = monitor['width']
            orig_h  = monitor['height']
            captura = sct.grab(monitor)
            img = Image.frombytes('RGB', captura.size, captura.bgra, 'raw', 'BGRX')
        except Exception as e:
            print(f"[!] Error capturando: {e}")
            try:
                sct.close()
            except Exception:
                pass
            sct = None
            time.sleep(1)
            continue

        # Frame remoto de alta frecuencia (cuando el profesor observa)
        if en_obs:
            ancho_r = min(orig_w, 1920)
            if img.width > ancho_r:
                img_r = img.resize((ancho_r, int(img.height * ancho_r / img.width)), Image.LANCZOS)
            else:
                img_r = img
            buf = io.BytesIO()
            img_r.save(buf, format='JPEG', quality=75, optimize=True)
            try:
                sio.emit('remote_frame', {
                    'image':  _b64(buf.getvalue()),
                    'orig_w': orig_w,
                    'orig_h': orig_h,
                })
            except Exception as e:
                print(f"[!] Error frame remoto: {e}")

        # Screenshot normal al dashboard (cada INTERVALO_SEG)
        if (now - _ultimo_screenshot) >= INTERVALO_SEG:
            if img.width > ANCHO_IMAGEN:
                img_n = img.resize((ANCHO_IMAGEN, int(img.height * ANCHO_IMAGEN / img.width)), Image.LANCZOS)
            else:
                img_n = img
            buf2 = io.BytesIO()
            img_n.save(buf2, format='JPEG', quality=CALIDAD_JPEG, optimize=True)
            try:
                sio.emit('screenshot', {'image': _b64(buf2.getvalue())})
                _ultimo_screenshot = now
            except Exception as e:
                print(f"[!] Error enviando captura: {e}")

        time.sleep(INTERVALO_REMOTO if en_obs else INTERVALO_SEG)


# ── Eventos Socket.IO ────────────────────────────────────────────────────────

@sio.event
def connect():
    global conectado
    conectado = True
    sio.emit('register', {'name': _nombre()})
    print(f"[✓] Conectado. Nombre: {_nombre()}")


@sio.event
def disconnect():
    global conectado
    conectado = False
    print("[!] Desconectado. Reintentando...")


@sio.on('registered')
def on_registered(data):
    print(f"[✓] Registrado (sid={data.get('sid','?')[:8]}…)")


@sio.on('quit_app')
def on_quit_app(_data):
    """El profesor ha ordenado cerrar esta aplicación."""
    print("[*] Cerrando por orden del profesor.")
    os._exit(0)


@sio.on('show_message')
def on_show_message(data):
    """Recibe un mensaje del profesor y lo encola para mostrarlo."""
    titulo = data.get('title', 'Mensaje del profesor')
    body   = data.get('body', data.get('text', '')).strip()
    if not body:
        return
    if TK_OK:
        _cola_mensajes.put_nowait({'title': titulo, 'body': body})
    texto_plano = re.sub(r'<[^>]+>', '', body)
    print(f"[✉] {titulo}: {texto_plano[:80]}")


@sio.on('viewer_start')
def on_viewer_start(data):
    """El profesor empieza a ver o controlar esta pantalla."""
    global _en_observacion, _modo_observacion
    _en_observacion   = True
    _modo_observacion = data.get('mode', 'view')
    accion = 'controla' if _modo_observacion == 'control' else 'observa'
    if not INPUT_OK and _modo_observacion == 'control':
        print("[!] Control remoto no disponible. Ejecuta: sudo apt install xdotool")
    print(f"[👁] El profesor {accion} esta pantalla.")


@sio.on('viewer_stop')
def on_viewer_stop(_data):
    """El profesor deja de observar/controlar."""
    global _en_observacion
    _en_observacion = False
    print("[👁] El profesor dejó de observar.")


@sio.on('do_input')
def on_do_input(data):
    """Ejecuta un evento de ratón/teclado enviado por el profesor."""
    if not INPUT_OK:
        return
    tipo = data.get('type', '')
    x, y = data.get('x'), data.get('y')
    try:
        if INPUT_MODE == 'xdotool':
            _do_input_xdotool(tipo, data, x, y)
        else:
            _do_input_pynput(tipo, data, x, y)
    except Exception as e:
        print(f"[!] Error input remoto ({INPUT_MODE}): {e}")


def _do_input_xdotool(tipo, data, x, y):
    """Backend xdotool: fiable en X11 y Xwayland."""
    btn_num = {'left': 1, 'middle': 2, 'right': 3}

    if tipo == 'mousemove' and x is not None:
        _xdo('mousemove', '--sync', x, y)

    elif tipo == 'mousedown' and x is not None:
        _xdo('mousemove', '--sync', x, y)
        _xdo('mousedown', btn_num.get(data.get('button', 'left'), 1))

    elif tipo == 'mouseup' and x is not None:
        _xdo('mouseup', btn_num.get(data.get('button', 'left'), 1))

    elif tipo == 'scroll' and x is not None:
        dy = int(data.get('dy', 0))
        btn = 4 if dy > 0 else 5
        for _ in range(min(abs(dy), 10)):
            _xdo('click', btn)

    elif tipo == 'keydown':
        raw = data.get('key', '')
        if not raw:
            return
        if raw in _XDO_MODS:
            _xdo_mods_held.add(raw)
            return
        # Obtener nombre xdotool de la tecla
        xdo_k = _XDOKEY.get(raw)
        if xdo_k is None:
            if len(raw) == 1:
                # Letra mayúscula → minúscula (el modificador shift del combo lo convierte)
                xdo_k = raw.lower() if raw.isupper() else raw
            else:
                return
        # Construir combo con modificadores activos
        mods = [_XDOKEY.get(m, m) for m in sorted(_xdo_mods_held)]
        combo = '+'.join(mods + [xdo_k]) if mods else xdo_k
        _xdo('key', combo)

    elif tipo == 'keyup':
        _xdo_mods_held.discard(data.get('key', ''))


def _do_input_pynput(tipo, data, x, y):
    """Backend pynput."""
    if tipo == 'mousemove' and x is not None:
        _mouse_ctrl.position = (x, y)
    elif tipo == 'mousedown' and x is not None:
        _mouse_ctrl.position = (x, y)
        _mouse_ctrl.press(_BTN_MAP.get(data.get('button', 'left'), list(_BTN_MAP.values())[0]))
    elif tipo == 'mouseup' and x is not None:
        _mouse_ctrl.position = (x, y)
        _mouse_ctrl.release(_BTN_MAP.get(data.get('button', 'left'), list(_BTN_MAP.values())[0]))
    elif tipo == 'scroll' and x is not None:
        _mouse_ctrl.position = (x, y)
        _mouse_ctrl.scroll(0, int(data.get('dy', 0)))
    elif tipo in ('keydown', 'keyup'):
        raw = data.get('key', '')
        if not raw:
            return
        k = _KEY_MAP.get(raw) or (raw if len(raw) == 1 else None)
        if k is None:
            return
        if tipo == 'keydown':
            _kbd_ctrl.press(k)
        else:
            _kbd_ctrl.release(k)


@sio.on('lock_screen')
def on_lock_screen(_data):
    """El profesor bloquea este equipo."""
    if not TK_OK:
        print("[!] BLOQUEO FALLIDO — python3-tk no está instalado.")
        print("    Instala con: sudo apt install python3-tk  y reinicia el cliente.")
        return
    _cola_bloqueo.put_nowait(True)
    print("[!] Pantalla BLOQUEADA por el profesor.")


@sio.on('unlock_screen')
def on_unlock_screen(_data):
    """El profesor desbloquea este equipo."""
    _cola_bloqueo.put_nowait(False)
    print("[✓] Pantalla desbloqueada.")


@sio.on('teacher_screen')
def on_teacher_screen(data):
    """Recibe frame del profesor y lo encola para mostrarlo en Tkinter."""
    if not IMGTK_OK:
        if data.get('activa'):
            print("[!] El profesor está compartiendo pantalla (instala python3-tk y Pillow para verla)")
        return
    try:
        _cola_profesor.put_nowait(data)
    except queue.Full:
        # Descartar el frame más antiguo y meter el nuevo
        try:
            _cola_profesor.get_nowait()
            _cola_profesor.put_nowait(data)
        except Exception:
            pass


# ── Ventana Tkinter para mostrar pantalla del profesor ────────────────────────

class _VentanaProfesor:
    """Ventana flotante que muestra la pantalla compartida del profesor."""

    def __init__(self, root: tk.Tk):
        self.top = tk.Toplevel(root)
        self.top.title("📺 Pantalla del Profesor — VIGIA")
        self.top.configure(bg='#0f1117')
        self.top.geometry("960x560")
        self.top.resizable(True, True)
        self._cerrada = False

        # Cabecera
        cab = tk.Frame(self.top, bg='#1a1d27')
        cab.pack(fill='x')
        tk.Label(
            cab, text="  El profesor está compartiendo su pantalla",
            bg='#1a1d27', fg='#4f8ef7',
            font=('Segoe UI', 9, 'bold'), anchor='w',
        ).pack(side='left', fill='x', pady=5)

        # Imagen
        self._label = tk.Label(
            self.top, bg='#0f1117',
            text="⏳  Esperando imagen…", fg='#718096',
            font=('Segoe UI', 12),
        )
        self._label.pack(expand=True, fill='both')
        self._foto = None

        # Traer al frente
        self.top.lift()
        self.top.attributes('-topmost', True)
        self.top.after(2000, lambda: self.top.attributes('-topmost', False))

        self.top.protocol("WM_DELETE_WINDOW", self._al_cerrar)

    def actualizar(self, imagen_b64: str):
        if self._cerrada:
            return
        try:
            datos = imagen_b64.split(',', 1)[1]
            img = Image.open(io.BytesIO(base64.b64decode(datos)))
            w = max(self.top.winfo_width(), 960)
            h = max(self.top.winfo_height() - 30, 530)
            img.thumbnail((w, h), Image.LANCZOS)
            self._foto = ImageTk.PhotoImage(img)
            self._label.config(image=self._foto, text='')
        except Exception as e:
            print(f"[!] Error mostrando pantalla del profesor: {e}")

    def destruir(self):
        self._cerrada = True
        try:
            self.top.destroy()
        except Exception:
            pass

    def _al_cerrar(self):
        # El alumno cierra la ventana manualmente: marcar como cerrada
        # para que no se reabra con el siguiente frame
        self._cerrada = True
        self.top.destroy()


# ── Parser HTML → segmentos para Tkinter Text ────────────────────────────────

class _ParseadorHTML(_HTMLParser):
    """Convierte HTML (b, i, u, a, code, p, br, li…) en segmentos (texto, tags)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._segs: list[tuple[str, tuple]] = []
        self._b = self._i = self._u = self._code = 0
        self._a_hrefs: list[str] = []   # stack de hrefs activos
        self._a_texts: list[str] = []   # texto acumulado por enlace

    def _tags(self):
        t = []
        if self._b:             t.append('b')
        if self._i:             t.append('i')
        if self._u:             t.append('u')
        if self._a_hrefs:       t.append('a')
        if self._code:          t.append('code')
        return tuple(t)

    def handle_starttag(self, tag, attrs):
        if   tag in ('b', 'strong'):  self._b += 1
        elif tag in ('i', 'em'):      self._i += 1
        elif tag == 'u':              self._u += 1
        elif tag in ('code', 'pre'):  self._code += 1
        elif tag == 'a':
            self._a_hrefs.append(dict(attrs).get('href', ''))
            self._a_texts.append('')
        elif tag in ('p', 'div', 'br', 'li'):
            self._segs.append(('\n', ()))

    def handle_endtag(self, tag):
        if   tag in ('b', 'strong'):  self._b    = max(0, self._b - 1)
        elif tag in ('i', 'em'):      self._i    = max(0, self._i - 1)
        elif tag == 'u':              self._u    = max(0, self._u - 1)
        elif tag in ('code', 'pre'):  self._code = max(0, self._code - 1)
        elif tag == 'a' and self._a_hrefs:
            href = self._a_hrefs.pop()
            text = self._a_texts.pop() if self._a_texts else ''
            # Mostrar la URL entre corchetes si difiere del texto visible
            if href and href.strip() != text.strip():
                self._segs.append((f' [{href}]', ('link_url',)))
        elif tag in ('p', 'div'):
            self._segs.append(('\n', ()))

    def handle_data(self, data):
        if data:
            if self._a_texts:
                self._a_texts[-1] += data
            self._segs.append((data, self._tags()))

    def resultado(self):
        return self._segs


# ── Ventana de mensaje del profesor ─────────────────────────────────────────

class _VentanaMensaje:
    """Popup con el mensaje enviado por el profesor. Se cierra solo o con Aceptar."""

    _AUTO_CIERRE_MS = 30_000   # 30 segundos

    def __init__(self, root: tk.Tk, msg: dict):
        titulo = msg.get('title', 'Mensaje del profesor')
        body   = msg.get('body', '')

        self.top = tk.Toplevel(root)
        self.top.title(titulo)
        self.top.configure(bg='#1a1d27')
        self.top.resizable(False, False)
        self.top.attributes('-topmost', True)

        # Cabecera azul con el título del mensaje
        cab = tk.Frame(self.top, bg='#4f8ef7')
        cab.pack(fill='x')
        tk.Label(cab, text=f"  ✉  {titulo}",
                 bg='#4f8ef7', fg='white',
                 font=('Segoe UI', 10, 'bold')).pack(side='left', pady=7, padx=6)

        # Cuerpo
        cuerpo = tk.Frame(self.top, bg='#1a1d27', padx=24, pady=18)
        cuerpo.pack(fill='both', expand=True)

        # Parsear HTML y construir el Text widget con formato
        parser = _ParseadorHTML()
        parser.feed(body)
        segmentos = parser.resultado()

        # Calcular alto: contar líneas del texto plano
        texto_plano = ''.join(t for t, _ in segmentos)
        n_lineas = max(2, min(12,
            texto_plano.count('\n') +
            sum(max(1, len(l) // 36) for l in texto_plano.split('\n'))
        ))

        txt = tk.Text(
            cuerpo,
            bg='#1a1d27', fg='#e2e8f0',
            font=('Segoe UI', 13),
            wrap='word', relief='flat',
            highlightthickness=0, borderwidth=0,
            cursor='xterm',
            width=36, height=n_lineas,
        )
        # Configurar tags de formato
        txt.tag_configure('b',        font=('Segoe UI', 13, 'bold'))
        txt.tag_configure('i',        font=('Segoe UI', 13, 'italic'))
        txt.tag_configure('bi',       font=('Segoe UI', 13, 'bold italic'))
        txt.tag_configure('u',        underline=True)
        txt.tag_configure('a',        foreground='#4f8ef7', underline=True)
        txt.tag_configure('code',     font=('Courier New', 12), background='#1a2030')
        txt.tag_configure('link_url', foreground='#718096', font=('Segoe UI', 11))

        for texto_seg, tags in segmentos:
            # Tag de fuente: combinar b+i si es necesario; code tiene prioridad
            apply: list[str] = []
            font_set = frozenset(t for t in tags if t in ('b', 'i'))
            if 'code' in tags:
                apply.append('code')
            elif font_set:
                apply.append(''.join(sorted(font_set)))  # 'b', 'i' o 'bi'
            # Tags adicionales (no conflictivos con fuente)
            for t in ('u', 'a', 'link_url'):
                if t in tags:
                    apply.append(t)
            txt.insert('end', texto_seg, apply if apply else '')

        txt.config(state='disabled')   # solo lectura pero seleccionable (Ctrl+C)
        txt.pack(anchor='w', fill='x')

        tk.Button(cuerpo, text="Aceptar",
                  bg='#4f8ef7', fg='white', activebackground='#3a7de0',
                  font=('Segoe UI', 10, 'bold'),
                  relief='flat', padx=22, pady=5,
                  cursor='hand2',
                  command=self.top.destroy).pack(pady=(16, 0))

        # Centrar en pantalla
        self.top.update_idletasks()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        w  = self.top.winfo_width()
        h  = self.top.winfo_height()
        self.top.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

        # Cierre automático
        self.top.after(self._AUTO_CIERRE_MS,
                       lambda: self.top.destroy() if self.top.winfo_exists() else None)


# ── Ventana de bloqueo ───────────────────────────────────────────────────────

class _VentanaBloqueo:
    """
    Pantalla completa de bloqueo con grab X11 global.

    grab_set_global() llama a XGrabPointer + XGrabKeyboard a nivel X11:
    ALL los eventos de teclado y ratón van a esta ventana, incluidos los
    de otras aplicaciones. El alumno no puede escribir ni hacer clic en nada.
    """

    def __init__(self, root: tk.Tk):
        w = root.winfo_screenwidth()
        h = root.winfo_screenheight()

        self.top = tk.Toplevel(root)
        self.top.title("Bloqueado")
        self.top.configure(bg='#0a0c14')
        self.top.geometry(f"{w}x{h}+0+0")
        self.top.attributes('-fullscreen', True)
        self.top.attributes('-topmost', True)
        self.top.overrideredirect(True)   # sin decoraciones del gestor de ventanas

        # Contenido visual (antes del grab para que se renderice)
        marco = tk.Frame(self.top, bg='#0a0c14')
        marco.place(relx=0.5, rely=0.5, anchor='center')
        tk.Label(marco, text='🔒',
                 bg='#0a0c14', fg='#fc8181',
                 font=('Segoe UI', 80)).pack()
        tk.Label(marco, text='Pantalla bloqueada',
                 bg='#0a0c14', fg='#e2e8f0',
                 font=('Segoe UI', 30, 'bold')).pack(pady=(8, 4))
        tk.Label(marco, text='El profesor ha bloqueado este equipo.',
                 bg='#0a0c14', fg='#718096',
                 font=('Segoe UI', 14)).pack()

        # Asegurarse de que la ventana existe y tiene foco antes del grab
        self.top.update()
        self.top.focus_force()
        self.top.update()

        # Protocolo: no se puede cerrar
        self.top.protocol("WM_DELETE_WINDOW", lambda: None)

        # Grab global X11: captura teclado y ratón de TODAS las aplicaciones
        try:
            self.top.grab_set_global()
        except Exception:
            # Fallback si ya hay otro grab activo
            self.top.grab_set()

        # Interceptar todos los eventos (segunda línea de defensa)
        self.top.bind_all('<Key>',           lambda e: 'break')
        self.top.bind_all('<KeyRelease>',    lambda e: 'break')
        self.top.bind_all('<Button>',        lambda e: 'break')
        self.top.bind_all('<ButtonRelease>', lambda e: 'break')
        self.top.bind_all('<Motion>',        lambda e: 'break')

        self._activa = True
        self._mantener_frente()

    def _mantener_frente(self):
        """Cada 100 ms: refuerza topmost y foco (defensa ante atajos del WM)."""
        if not self._activa:
            return
        try:
            self.top.lift()
            self.top.focus_force()
            self.top.attributes('-topmost', True)
            self.top.after(100, self._mantener_frente)
        except Exception:
            pass

    def desbloquear(self):
        self._activa = False
        try:
            self.top.grab_release()
            for seq in ('<Key>', '<KeyRelease>', '<Button>',
                        '<ButtonRelease>', '<Motion>'):
                self.top.unbind_all(seq)
            self.top.destroy()
        except Exception:
            pass


# ── Bucle principal Tkinter ──────────────────────────────────────────────────

_ventana_profesor: _VentanaProfesor | None = None
_alumno_cerro_ventana = False   # True cuando el alumno cierra manualmente


def _revisar_cola(root: tk.Tk):
    """Ejecutado cada 80 ms en el hilo principal para procesar frames del profesor."""
    global _ventana_profesor, _alumno_cerro_ventana

    try:
        while True:   # vaciar la cola entera en cada ciclo
            data = _cola_profesor.get_nowait()
            activa = data.get('activa', True)
            imagen = data.get('image')

            if not activa:
                # Profesor dejó de compartir
                if _ventana_profesor:
                    _ventana_profesor.destruir()
                    _ventana_profesor = None
                _alumno_cerro_ventana = False
                print("[*] El profesor dejó de compartir pantalla.")
            elif imagen and not _alumno_cerro_ventana and IMGTK_OK:
                # Crear ventana si no existe (o si fue destruida por el sistema)
                if _ventana_profesor is None or _ventana_profesor._cerrada:
                    _ventana_profesor = _VentanaProfesor(root)
                    _alumno_cerro_ventana = False
                _ventana_profesor.actualizar(imagen)

    except queue.Empty:
        pass

    root.after(80, lambda: _revisar_cola(root))


_ventana_bloqueo:  _VentanaBloqueo  | None = None


def _revisar_cola_bloqueo(root: tk.Tk):
    """Ejecutado cada 100 ms: procesa órdenes de bloqueo/desbloqueo."""
    global _ventana_bloqueo
    try:
        while True:
            bloquear = _cola_bloqueo.get_nowait()
            if bloquear:
                if _ventana_bloqueo is None or not _ventana_bloqueo._activa:
                    _ventana_bloqueo = _VentanaBloqueo(root)
            else:
                if _ventana_bloqueo:
                    _ventana_bloqueo.desbloquear()
                    _ventana_bloqueo = None
    except queue.Empty:
        pass
    root.after(100, lambda: _revisar_cola_bloqueo(root))


def _revisar_cola_mensajes(root: tk.Tk):
    """Ejecutado cada 200 ms: muestra mensajes del profesor."""
    try:
        while True:
            msg = _cola_mensajes.get_nowait()
            _VentanaMensaje(root, msg)
    except queue.Empty:
        pass
    root.after(200, lambda: _revisar_cola_mensajes(root))


def ejecutar_interfaz():
    """Hilo principal: Tkinter oculto que gestiona ventanas flotantes."""
    import signal
    root = tk.Tk()
    root.withdraw()          # raíz oculta; solo usamos Toplevel
    root.title("VIGIA")

    _revisar_cola(root)
    _revisar_cola_bloqueo(root)
    _revisar_cola_mensajes(root)

    # Permitir Ctrl+C desde terminal
    signal.signal(signal.SIGINT, lambda *_: root.quit())

    root.mainloop()


# ── Hilo de conexión Socket.IO ────────────────────────────────────────────────

def hilo_conexion(url: str):
    while True:
        try:
            sio.connect(url, transports=['websocket'])
            sio.wait()
        except sio_module.exceptions.ConnectionError:
            print(f"[!] No se pudo conectar a {url}. Reintentando en {REINTENTOS_ESPERA}s…")
            time.sleep(REINTENTOS_ESPERA)
        except Exception as e:
            print(f"[!] Error de conexión: {e}")
            time.sleep(REINTENTOS_ESPERA)


# ── Utilidades ────────────────────────────────────────────────────────────────

def _nombre() -> str:
    try:
        usuario = os.environ.get('USER') or os.environ.get('USERNAME') or 'alumno'
        return f"{usuario} - {socket.gethostname()}"
    except Exception:
        return "Alumno"


def preguntar_servidor() -> tuple[str, int]:
    if len(sys.argv) >= 2:
        ip = sys.argv[1]
    else:
        print("\n  VIGIA — Cliente del Alumno")
        print("  " + "─" * 38)
        ip = input("  IP del servidor (profesor): ").strip()
        if not ip:
            print("  Error: debes introducir una IP.")
            sys.exit(1)
    puerto = int(sys.argv[2]) if len(sys.argv) >= 3 else 5000
    return ip, puerto


# ── Arranque ──────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    ip_servidor, puerto = preguntar_servidor()
    url = f"http://{ip_servidor}:{puerto}"

    print(f"\n  Conectando a {url} …")
    if INPUT_OK:
        print(f"  [✓] Control remoto habilitado ({INPUT_MODE})")
    else:
        print("  [!] Control remoto NO disponible.")
        print("      Instala xdotool con: sudo apt install xdotool")
    if not TK_OK:
        print("  [!] python3-tk no instalado: la pantalla del profesor no se mostrará.")
        print("      Instala con: sudo apt install python3-tk\n")
    else:
        print("  (Ctrl+C para salir)\n")

    # Daemon threads: Socket.IO + bucle de captura unificado
    threading.Thread(target=hilo_conexion,  args=(url,), daemon=True).start()
    threading.Thread(target=bucle_capturas, daemon=True).start()

    if TK_OK:
        # Hilo principal: Tkinter (bloqueante hasta salir)
        ejecutar_interfaz()
    else:
        # Sin Tkinter: esperar indefinidamente
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Saliendo…")
