#!/usr/bin/env python3
"""
VIGIA - Servidor del Profesor (v1.6)
Muestra en tiempo real las pantallas de los alumnos conectados.
Uso: python server.py [puerto]
"""

import os
import sys
import io
import re
import time
import base64
import threading
import subprocess
import webbrowser
import platform_utils
import screen_capture

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
            import tempfile
            _vbs = os.path.join(tempfile.gettempdir(), 'vigia_server_launch.vbs')
            _cmd = f'"{_pythonw}" ' + ' '.join(f'"{a}"' for a in sys.argv)
            with open(_vbs, 'w') as _f:
                _f.write(f'CreateObject("WScript.Shell").Run "{_cmd}", 0, False\n')
            os.startfile(_vbs)
            sys.exit(0)
    # Paso 4: redirigir stdout/stderr a log
    _log_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'vigia')
    os.makedirs(_log_dir, exist_ok=True)
    _log_file = open(os.path.join(_log_dir, 'server.log'), 'a', encoding='utf-8', errors='replace')
    if sys.stdout is None:
        sys.stdout = _log_file
    if sys.stderr is None:
        sys.stderr = _log_file

# Reconfigurar stdout/stderr para UTF-8 en Windows (cp1252 no soporta emojis)
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# eventlet depende de greenlet (extensión C) y se rompe con cada salto de
# versión de Python (p.ej. Kubuntu 26.04 / Python nuevo). Si no está instalado
# o no importa, usar threading: Flask-SocketIO funciona igual (WebSocket vía
# simple-websocket si está disponible, long-polling si no).
try:
    import eventlet  # noqa: F401
    async_mode = 'eventlet'
except Exception:
    async_mode = 'threading'

import socket
from datetime import datetime
from flask import Flask, render_template, jsonify, request, make_response
from flask_socketio import SocketIO, emit, join_room

print(f"[*] Iniciando servidor VIGIA (modo: {async_mode})")

app = Flask(__name__)
app.config['SECRET_KEY'] = 'vigia-aula-2024'

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    max_http_buffer_size=20 * 1024 * 1024,  # 20 MB para soportar frames de alta resolución
    async_mode=async_mode,
    ping_timeout=30,
    ping_interval=10,
)

# Almacén de alumnos: {sid: {name, ip, screenshot, last_seen, connected_at}}
students = {}

# Sesiones activas de vista/control: {student_sid: {prof_sid, mode}}
viewers: dict = {}

# Estado de compartir pantalla del profesor
_teacher_capture = {'running': False, 'sid': None, 'sids': None}


def get_local_ip():
    """Detecta la IP local de la máquina."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()


# ── Rutas HTTP ──────────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    ua = request.headers.get('User-Agent', '')
    # Chrome, Firefox y Chromium se identifican con su nombre en el UA.
    # WebKit2GTK (el launcher) usa AppleWebKit pero sin esos tokens.
    is_launcher = not any(b in ua for b in ('Chrome/', 'Chromium/', 'Firefox/'))
    resp = make_response(render_template('dashboard.html', is_launcher=is_launcher))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@app.route('/img/<path:filename>')
def serve_img(filename):
    from flask import send_from_directory
    img_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'img')
    return send_from_directory(img_dir, filename)


@app.route('/manifest.json')
def web_manifest():
    from flask import jsonify
    manifest = {
        "name": "VIGIA — Panel del Profesor",
        "short_name": "VIGIA",
        "description": "Supervisión de aula en tiempo real",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1a1d27",
        "theme_color": "#1a1d27",
        "icons": [
            {"src": "/img/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/img/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    resp = make_response(jsonify(manifest))
    resp.headers['Content-Type'] = 'application/manifest+json'
    return resp


@app.route('/api/students')
def api_students():
    result = []
    for sid, data in students.items():
        result.append({
            'sid': sid,
            'name': data['name'],
            'ip': data['ip'],
            'last_seen': data['last_seen'],
            'connected_at': data['connected_at'],
            'has_screenshot': data['screenshot'] is not None,
        })
    return jsonify(result)


# ── Eventos Socket.IO ────────────────────────────────────────────────────────

def _get_client_ip():
    return (request.environ.get('HTTP_X_FORWARDED_FOR')
            or request.environ.get('REMOTE_ADDR', 'Desconocida'))


@socketio.on('connect')
def on_connect():
    client_ip = _get_client_ip()
    print(f"[+] Conexión: {request.sid}  IP: {client_ip}")


@socketio.on('register_teacher')
def on_register_teacher():
    """Dashboard joins the 'professors' room so broadcasts target only teachers."""
    join_room('professors')
    print(f"[👁] Dashboard registrado en sala 'professors': {request.sid}")


@socketio.on('disconnect')
def on_disconnect():
    if request.sid == _teacher_capture.get('sid'):
        _teacher_capture['running'] = False
        # socketio.emit sin 'to' ya difunde a todos; broadcast=True provoca
        # TypeError con python-socketio/flask-socketio modernos (apt).
        socketio.emit('teacher_screen', {'activa': False})
    if request.sid in students:
        name = students[request.sid]['name']
        del students[request.sid]
        if request.sid in viewers:
            prof_sid = viewers.pop(request.sid)['prof_sid']
            socketio.emit('student_view_ended', {'sid': request.sid}, to=prof_sid)
        print(f"[-] Desconectado: {name}")
        socketio.emit('student_disconnected', {'sid': request.sid}, to='professors')


@socketio.on('register')
def on_register(data):
    client_ip = _get_client_ip()
    name = data.get('name', 'Alumno')
    now = datetime.now().strftime('%H:%M:%S')
    students[request.sid] = {
        'name': name, 'ip': client_ip, 'screenshot': None,
        'last_seen': now, 'connected_at': now, 'locked': False,
    }
    print(f"[+] Registrado: {name}  ({client_ip})")
    emit('registered', {'status': 'ok', 'sid': request.sid})
    socketio.emit('student_connected', {'sid': request.sid, 'name': name, 'ip': client_ip, 'connected_at': now}, to='professors')


@socketio.on('screenshot')
def on_screenshot(data):
    if request.sid not in students: return
    now = datetime.now().strftime('%H:%M:%S')
    students[request.sid]['screenshot'] = data.get('image')
    students[request.sid]['last_seen'] = now
    socketio.emit('update_screenshot', {'sid': request.sid, 'image': data.get('image'), 'last_seen': now}, to='professors')


@socketio.on('request_students')
def on_request_students(_data=None):
    payload = []
    for sid, data in students.items():
        payload.append({
            'sid': sid, 'name': data['name'], 'ip': data['ip'],
            'last_seen': data['last_seen'], 'connected_at': data['connected_at'],
            'image': data['screenshot'], 'locked': data.get('locked', False),
        })
    emit('full_student_list', payload)


@socketio.on('quit_student')
def on_quit_student(data):
    sid = data.get('sid')
    if sid in students:
        socketio.emit('quit_app', {}, to=sid)
        print(f"[*] Apagando equipo: {students[sid]['name']}")


@socketio.on('quit_all_students')
def on_quit_all_students(_data):
    for sid in list(students.keys()):
        socketio.emit('quit_app', {}, to=sid)
    print(f"[*] Apagando todos los equipos")


@socketio.on('send_message')
def on_send_message(data):
    payload = {
        'title': data.get('title', 'Mensaje'),
        'body': data.get('body', '').strip(),
        'attachments': data.get('attachments', []),
    }
    if payload['body'] or payload['attachments']:
        # Sin broadcast=True (TypeError con flask-socketio moderno); emitir sin
        # 'to' difunde a todos y skip_sid excluye al dashboard emisor.
        socketio.emit('show_message', payload, skip_sid=request.sid)
        n = len(payload['attachments'])
        print(f"[*] Mensaje enviado a todos: {payload['title']}" + (f" ({n} adjunto(s))" if n else ""))


@socketio.on('send_message_to')
def on_send_message_to(data):
    sid = data.get('sid')
    if sid in students:
        payload = {
            'title': data.get('title', 'Mensaje'),
            'body': data.get('body', '').strip(),
            'attachments': data.get('attachments', []),
        }
        socketio.emit('show_message', payload, to=sid)
        n = len(payload['attachments'])
        print(f"[*] Mensaje enviado a {students[sid]['name']}: {payload['title']}" + (f" ({n} adjunto(s))" if n else ""))


@socketio.on('lock_student')
def on_lock_student(data):
    sid = data.get('sid')
    locked = bool(data.get('locked', True))
    if sid in students:
        students[sid]['locked'] = locked
        socketio.emit('lock_screen' if locked else 'unlock_screen', {}, to=sid)
        socketio.emit('student_lock_state', {'sid': sid, 'locked': locked}, to='professors')
        print(f"[*] {students[sid]['name']} -> {'BLOQUEADO' if locked else 'desbloqueado'}")


@socketio.on('update_config')
def on_update_config(data):
    """Retransmite la configuración de rendimiento a todos los clientes."""
    cfg = {
        'thumb_interval': float(data.get('thumb_interval', 1.0)),
        'thumb_quality':  int(data.get('thumb_quality', 55)),
        'live_fps':       int(data.get('live_fps', 20)),
        'webrtc_fps':     int(data.get('webrtc_fps', 30)),
        'live_quality':   int(data.get('live_quality', 70)),
    }
    socketio.emit('config_update', cfg, include_self=False)
    print(f"[*] Configuración actualizada: intervalo={cfg['thumb_interval']}s, "
          f"JPEG live={cfg['live_fps']}fps, WebRTC={cfg['webrtc_fps']}fps")


def _get_window_list():
    """Devuelve ventanas visibles (delegado a platform_utils para multiplataforma)."""
    return platform_utils.get_window_list()


def _get_window_region(wid):
    """Devuelve la región actual de una ventana (delegado a platform_utils)."""
    return platform_utils.get_window_region(wid)


def _teacher_capture_loop():
    """Captura la pantalla del profesor y emite los frames por Socket.IO.
    Usa screen_capture (mss en X11, spectacle/grim en Wayland)."""
    try:
        from PIL import Image
    except ImportError:
        socketio.emit('teacher_screen_preview',
                      {'error': 'Instala Pillow en el servidor: sudo apt install python3-pil'},
                      to=_teacher_capture['sid'])
        return

    capturer = None
    sct = None
    if _teacher_capture.get('type') == 'window':
        # Captura de ventana: solo X11 (mss + xdotool)
        try:
            import mss
            sct = mss.mss()
        except Exception as e:
            socketio.emit('teacher_screen_preview',
                          {'error': f'Captura de ventana no disponible (requiere X11): {e}'},
                          to=_teacher_capture['sid'])
            return
    else:
        try:
            capturer = screen_capture.create_capturer()
            if hasattr(capturer, 'set_monitor'):
                capturer.set_monitor(_teacher_capture.get('monitor', 1))
        except Exception as e:
            socketio.emit('teacher_screen_preview',
                          {'error': f'Captura de pantalla no disponible: {e}'},
                          to=_teacher_capture['sid'])
            return

    try:
        while _teacher_capture['running']:
            try:
                if sct is not None:
                    region = _get_window_region(_teacher_capture['wid'])
                    if region is None:
                        socketio.sleep(0.5)
                        continue
                    cap = sct.grab(region)
                    img = Image.frombytes('RGB', (cap.width, cap.height), cap.rgb)
                else:
                    img = capturer.grab()
                max_w = 1920
                if img.width > max_w:
                    ratio = max_w / img.width
                    img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, 'JPEG', quality=70)
                data_uri = 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
                _sids = _teacher_capture.get('sids')
                if _sids:
                    for _sid in _sids:
                        socketio.emit('teacher_screen', {'activa': True, 'image': data_uri}, to=_sid)
                else:
                    socketio.emit('teacher_screen', {'activa': True, 'image': data_uri})
                socketio.emit('teacher_screen_preview', {'image': data_uri}, to=_teacher_capture['sid'])
            except Exception as e:
                print(f'[!] Error capturando pantalla del profesor: {e}')
            socketio.sleep(0.1)  # 10 FPS — cede el event loop (eventlet/threading)
    finally:
        for c in (capturer, sct):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass


def _capture_thumb(sct, region, max_w=192):
    """Captura y devuelve un thumbnail JPEG base64 de una región de pantalla."""
    try:
        from PIL import Image
        cap = sct.grab(region)
        img = Image.frombytes('RGB', (cap.width, cap.height), cap.rgb)
        th = max(1, round(max_w * img.height / img.width))
        img = img.resize((max_w, th), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=60)
        return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _capture_window_thumb(wid, max_w=192):
    """Captura thumbnail de ventana.
    Linux: Xlib GetImage (contenido real incluso si está detrás de otras ventanas).
    Windows: fallback a captura de región con mss."""
    if platform_utils.IS_LINUX:
        try:
            from Xlib import display as xlib_display, X
            from PIL import Image
            wid_int = int(wid, 16) if isinstance(wid, str) else int(wid)
            d = xlib_display.Display()
            win = d.create_resource_object('window', wid_int)
            geom = win.get_geometry()
            w, h = geom.width, geom.height
            if w < 1 or h < 1:
                return None
            raw = win.get_image(0, 0, w, h, X.ZPixmap, 0xffffffff)
            img = Image.frombytes('RGBA', (w, h), raw.data, 'raw', 'BGRA')
            img = img.convert('RGB')
            th = max(1, round(max_w * h / w))
            img = img.resize((max_w, th), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=60)
            return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
        except Exception:
            return None
    else:
        # Windows: captura región via mss (fallback)
        region = _get_window_region(wid)
        if region:
            try:
                import mss
                with mss.mss() as sct:
                    return _capture_thumb(sct, region, max_w)
            except Exception:
                pass
        return None


def _find_desktop_icon(classes):
    """Devuelve el nombre de icono de la app buscando en archivos .desktop por WM_CLASS.
    Solo funciona en Linux; en Windows retorna None."""
    if platform_utils.IS_WINDOWS:
        return None
    lower = [c.lower() for c in classes]
    dirs = [
        '/usr/share/applications',
        os.path.expanduser('~/.local/share/applications'),
        '/usr/local/share/applications',
        '/var/lib/snapd/desktop/applications',
        '/var/lib/flatpak/exports/share/applications',
    ]
    second_pass = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if not fname.endswith('.desktop'):
                continue
            try:
                text = open(os.path.join(d, fname), encoding='utf-8', errors='ignore').read()
                icon_m = re.search(r'^Icon=(.+)$', text, re.MULTILINE)
                if not icon_m:
                    continue
                icon = icon_m.group(1).strip()
                swm = re.search(r'^StartupWMClass=(.+)$', text, re.MULTILINE)
                if swm and swm.group(1).strip().lower() in lower:
                    return icon
                stem = fname[:-8].lower()
                if stem in lower:
                    second_pass.append(icon)
            except Exception:
                pass
    return second_pass[0] if second_pass else None


def _find_icon_path(name, preferred_size=48):
    """Resuelve un nombre de icono a la ruta del archivo.
    Linux: GTK IconTheme + /usr/share/pixmaps.
    Windows: retorna None (iconos embebidos en .exe no se extraen)."""
    if not name:
        return None
    if os.path.isabs(name):
        return name if os.path.exists(name) else None
    if platform_utils.IS_WINDOWS:
        return None
    base = os.path.splitext(os.path.basename(name))[0]
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk
        info = Gtk.IconTheme.get_default().lookup_icon(base, preferred_size, 0)
        if info:
            return info.get_filename()
    except Exception:
        pass
    for n in (name, base):
        for ext in ('png', 'svg', 'xpm'):
            p = f'/usr/share/pixmaps/{n}.{ext}'
            if os.path.exists(p):
                return p
    return None


def _icon_to_b64(path):
    """Convierte un archivo de icono (PNG/SVG/XPM) a data URI base64."""
    if not path:
        return None
    try:
        if path.endswith('.svg'):
            return 'data:image/svg+xml;base64,' + base64.b64encode(
                open(path, 'rb').read()).decode()
        from PIL import Image
        img = Image.open(path).convert('RGBA')
        bg = Image.new('RGBA', img.size, (26, 29, 42, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg.convert('RGB').resize((48, 48), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _get_window_app_icon(wid):
    """Obtiene el icono de la aplicación de una ventana.
    Linux: WM_CLASS + .desktop.  Windows: no implementado (retorna None)."""
    if platform_utils.IS_WINDOWS:
        return None
    try:
        wid_hex = wid if isinstance(wid, str) else hex(wid)
        r = subprocess.run(['xprop', '-id', wid_hex, '-notype', 'WM_CLASS'],
                           capture_output=True, text=True, timeout=1)
        classes = re.findall(r'"([^"]+)"', r.stdout)
        if not classes:
            return None
        icon_name = _find_desktop_icon(classes) or classes[-1].lower()
        return _icon_to_b64(_find_icon_path(icon_name))
    except Exception:
        return None


def _thumb_from_image(img, max_w=192):
    """Genera un thumbnail JPEG base64 a partir de una PIL.Image."""
    try:
        th = max(1, round(max_w * img.height / img.width))
        img = img.resize((max_w, th))
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=60)
        return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


@socketio.on('get_screens')
def on_get_screens():
    try:
        screens = []
        capturer = screen_capture.create_capturer(verbose=False)
        try:
            if capturer.name == 'mss':
                sct = capturer._sct
                for i, mon in enumerate(sct.monitors):
                    label = f'Pantalla completa ({mon["width"]}×{mon["height"]})' if i == 0 \
                            else f'Monitor {i} ({mon["width"]}×{mon["height"]})'
                    screens.append({
                        'type': 'monitor', 'index': i, 'label': label,
                        'thumb': _capture_thumb(sct, mon),
                    })
                for win in _get_window_list():
                    # Capturar via Xlib (contenido real de la ventana, sin solapamiento)
                    # Si falla, usar mss como fallback (región de pantalla)
                    thumb = _capture_window_thumb(win['wid'])
                    if thumb is None:
                        region = {'left': win['x'], 'top': win['y'],
                                  'width': win['w'], 'height': win['h']}
                        thumb = _capture_thumb(sct, region)
                    screens.append({
                        'type': 'window', 'wid': win['wid'], 'label': win['title'],
                        'thumb': thumb,
                        'icon': _get_window_app_icon(win['wid']),
                    })
            else:
                # Wayland (spectacle/grim/gnome-screenshot): solo pantalla completa.
                # La lista de ventanas/monitores individuales requiere X11.
                img = capturer.grab()
                screens.append({
                    'type': 'monitor', 'index': 1,
                    'label': f'Pantalla completa ({img.width}×{img.height})',
                    'thumb': _thumb_from_image(img),
                })
        finally:
            capturer.close()
        emit('screens_list', {'screens': screens})
    except Exception as e:
        emit('screens_list', {'error': f'Error al obtener pantallas: {e}\n'
                              'En X11 instala mss (pip install mss); en Wayland '
                              'instala spectacle (KDE), grim o gnome-screenshot.'})


@socketio.on('start_teacher_capture')
def on_start_teacher_capture(data=None):
    _teacher_capture['running'] = False  # detener captura previa si la hubiera
    time.sleep(0.1)
    data = data or {}
    _teacher_capture['sid'] = request.sid
    _teacher_capture['type'] = data.get('type', 'monitor')
    _teacher_capture['monitor'] = data.get('monitor', 1)
    _teacher_capture['wid'] = data.get('wid')
    _teacher_capture['sids'] = data.get('sids') or None  # lista de sids destino (None = todos)
    _teacher_capture['running'] = True
    # start_background_task crea un green thread de eventlet (no un hilo OS),
    # garantizando que socketio.emit(broadcast=True) llegue a todos los clientes.
    socketio.start_background_task(_teacher_capture_loop)
    print('[📺] Compartir pantalla del profesor: iniciado')


@socketio.on('stop_teacher_capture')
def on_stop_teacher_capture():
    _teacher_capture['running'] = False
    socketio.emit('teacher_screen', {'activa': False})
    print('[📺] Compartir pantalla del profesor: detenido')


@socketio.on('teacher_screenshot')
def on_teacher_screenshot(data):
    activa = data.get('activa', True)
    payload = {'activa': activa, 'image': data.get('image') if activa else None}
    sids = data.get('sids')
    if sids:
        for sid in sids:
            socketio.emit('teacher_screen', payload, to=sid)
    else:
        socketio.emit('teacher_screen', payload, skip_sid=request.sid)


@socketio.on('run_command')
def on_run_command(data):
    sids = data.get('sids', [])
    cmd = data.get('command', '').strip()
    cmd_id = data.get('cmd_id', '')
    if not cmd or not sids:
        return
    payload = {'command': cmd, 'cmd_id': cmd_id}
    sent = 0
    for sid in sids:
        if sid in students:
            socketio.emit('exec_command', payload, to=sid)
            sent += 1
    print(f"[>_] Comando enviado a {sent} cliente(s): {cmd[:80]}")


@socketio.on('command_output')
def on_command_output(data):
    sid = request.sid
    if sid not in students:
        return
    socketio.emit('command_result', {
        'sid': sid,
        'name': students[sid]['name'],
        'cmd_id': data.get('cmd_id', ''),
        'command': data.get('command', ''),
        'stdout': data.get('stdout', ''),
        'stderr': data.get('stderr', ''),
        'returncode': data.get('returncode', -1),
        'cwd': data.get('cwd', ''),
    }, to='professors')


@socketio.on('send_message_to_many')
def on_send_message_to_many(data):
    sids = data.get('sids', [])
    payload = {
        'title': data.get('title', 'Mensaje'),
        'body': data.get('body', '').strip(),
        'attachments': data.get('attachments', []),
    }
    if not (payload['body'] or payload['attachments']):
        return
    n_sent = 0
    for sid in sids:
        if sid in students:
            socketio.emit('show_message', payload, to=sid)
            n_sent += 1
    n = len(payload['attachments'])
    print(f"[*] Mensaje enviado a {n_sent} alumno(s) seleccionados: {payload['title']}" + (f" ({n} adjunto(s))" if n else ""))


@socketio.on('start_view')
def on_start_view(data):
    student_sid = data.get('sid')
    mode = data.get('mode', 'view')
    if student_sid in students:
        viewers[student_sid] = {'prof_sid': request.sid, 'mode': mode}
        socketio.emit('viewer_start', {'mode': mode}, to=student_sid)
        print(f"[👁] Modo {mode} iniciado en: {students[student_sid]['name']}")


@socketio.on('stop_view')
def on_stop_view(data):
    student_sid = data.get('sid')
    if student_sid in viewers and viewers[student_sid]['prof_sid'] == request.sid:
        viewers.pop(student_sid)
        socketio.emit('viewer_stop', {}, to=student_sid)
        print(f"[👁] Modo observación finalizado.")


@socketio.on('remote_frame')
def on_remote_frame(data):
    # Retransmitir frame de alumno al profesor que lo observa
    v_data = viewers.get(request.sid)
    if v_data:
        socketio.emit('live_frame', {
            'sid':    request.sid,
            'image':  data.get('image'),
            'orig_w': data.get('orig_w', 1280),
            'orig_h': data.get('orig_h', 720),
        }, to=v_data['prof_sid'])


@socketio.on('screen_info')
def on_screen_info(data):
    # El cliente envía su resolución real de pantalla; reenviar al profesor observador
    v_data = viewers.get(request.sid)
    if v_data:
        socketio.emit('screen_info', {
            'sid': request.sid,
            'w':   data.get('w', 1280),
            'h':   data.get('h', 720),
        }, to=v_data['prof_sid'])


@socketio.on('remote_input')
def on_remote_input(data):
    student_sid = data.get('sid')
    v_data = viewers.get(student_sid)
    if v_data and v_data['prof_sid'] == request.sid and v_data['mode'] == 'control':
        socketio.emit('do_input', data, to=student_sid)


@socketio.on('get_clipboard')
def on_get_clipboard(data):
    student_sid = data.get('sid')
    v_data = viewers.get(student_sid)
    if v_data and v_data['prof_sid'] == request.sid and v_data['mode'] == 'control':
        socketio.emit('get_clipboard', {}, to=student_sid)


@socketio.on('clipboard_data')
def on_clipboard_data(data):
    v_data = viewers.get(request.sid)
    if v_data:
        socketio.emit('clipboard_data', {'text': data.get('text', '')}, to=v_data['prof_sid'])


# ── Señalización WebRTC ───────────────────────────────────────────────────────

@socketio.on('webrtc_offer')
def on_webrtc_offer(data):
    student_sid = data.get('sid')
    if student_sid not in students:
        return
    socketio.emit('webrtc_offer', {
        'sdp': data.get('sdp'),
        'prof_sid': request.sid,
    }, to=student_sid)

@socketio.on('webrtc_answer')
def on_webrtc_answer(data):
    prof_sid = data.get('prof_sid')
    v_data = viewers.get(request.sid)
    if not v_data or v_data['prof_sid'] != prof_sid:
        return
    socketio.emit('webrtc_answer', {
        'sid': request.sid,
        'sdp': data.get('sdp'),
    }, to=prof_sid)

@socketio.on('webrtc_ice')
def on_webrtc_ice(data):
    if 'sid' in data:  # Dashboard → Cliente
        student_sid = data['sid']
        if student_sid in students:
            socketio.emit('webrtc_ice', {'candidate': data.get('candidate')}, to=student_sid)
    elif 'prof_sid' in data:  # Cliente → Dashboard
        prof_sid = data['prof_sid']
        v_data = viewers.get(request.sid)
        if v_data and v_data['prof_sid'] == prof_sid:
            socketio.emit('webrtc_ice', {
                'sid': request.sid,
                'candidate': data.get('candidate'),
            }, to=prof_sid)


# ── Arranque ─────────────────────────────────────────────────────────────────

def _auto_open_browser(port):
    """En Windows, abre el dashboard en localhost (contexto seguro → getDisplayMedia funciona).
    Busca Chrome/Edge primero para modo --app; si no hay, abre el navegador por defecto."""
    if not platform_utils.IS_WINDOWS:
        return
    import shutil, tempfile
    # Esperar a que el servidor esté listo (max 15s)
    import socket as _sock
    for _ in range(30):
        try:
            with _sock.create_connection(('127.0.0.1', port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.5)
    url = f'http://localhost:{port}/'
    # Buscar Chrome o Edge para modo --app (sin barra de herramientas)
    candidates = []
    for env_var in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        base = os.environ.get(env_var, '')
        if not base:
            continue
        candidates.append(os.path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe'))
        candidates.append(os.path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe'))
    browser = None
    for c in candidates:
        if os.path.isfile(c):
            browser = c
            break
    if browser:
        tmpdir = tempfile.mkdtemp(prefix='vigia-chrome-')
        args = [
            browser, f'--app={url}',
            f'--user-data-dir={tmpdir}',
            '--no-first-run', '--no-default-browser-check',
            '--disable-infobars', '--disable-translate',
            '--disable-sync', '--disable-extensions',
            '--disable-background-networking',
        ]
        try:
            # CREATE_NO_WINDOW evita que Chrome herede una consola del padre
            _flags = subprocess.CREATE_NO_WINDOW if platform_utils.IS_WINDOWS else 0
            subprocess.Popen(args, creationflags=_flags)
            print(f'[*] Dashboard abierto en {os.path.basename(browser)} modo app')
        except Exception:
            webbrowser.open(url)
    else:
        webbrowser.open(url)
        print('[*] Dashboard abierto en el navegador del sistema')


if __name__ == '__main__':
    # --no-browser: arrancar sin abrir el dashboard (para tareas programadas / servicios)
    _no_browser = '--no-browser' in sys.argv
    _args = [a for a in sys.argv[1:] if a != '--no-browser']
    port = int(_args[0]) if _args else 5000
    ip = get_local_ip()
    sep = '=' * 52
    print(f"\n{sep}")
    print(f"  VIGIA — Servidor del Profesor")
    print(sep)
    print(f"  Dashboard: http://{ip}:{port}")
    print(f"  Alumnos se conectan a IP: {ip}  puerto: {port}")
    print(f"{sep}\n")

    # En Windows, abrir el navegador automáticamente (salvo --no-browser)
    if platform_utils.IS_WINDOWS and not _no_browser:
        t = threading.Timer(0.5, _auto_open_browser, args=[port])
        t.daemon = True
        t.start()

    if async_mode == 'threading':
        # Sin eventlet, flask-socketio usa Werkzeug y exige confirmar su uso
        # fuera de desarrollo (RuntimeError si no). Es el modo soportado en
        # Kubuntu 26 (eventlet/greenlet rotos); WebSocket vía simple-websocket.
        socketio.run(app, host='0.0.0.0', port=port, debug=False,
                     allow_unsafe_werkzeug=True)
    else:
        socketio.run(app, host='0.0.0.0', port=port, debug=False)
