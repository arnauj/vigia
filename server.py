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

async_mode = 'eventlet'

import socket
from datetime import datetime
from flask import Flask, render_template, jsonify, request, make_response
from flask_socketio import SocketIO, emit

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
_teacher_capture = {'running': False, 'sid': None}


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


@socketio.on('disconnect')
def on_disconnect():
    if request.sid == _teacher_capture.get('sid'):
        _teacher_capture['running'] = False
        socketio.emit('teacher_screen', {'activa': False}, broadcast=True)
    if request.sid in students:
        name = students[request.sid]['name']
        del students[request.sid]
        if request.sid in viewers:
            prof_sid = viewers.pop(request.sid)['prof_sid']
            socketio.emit('student_view_ended', {'sid': request.sid}, to=prof_sid)
        print(f"[-] Desconectado: {name}")
        emit('student_disconnected', {'sid': request.sid}, broadcast=True)


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
    emit('student_connected', {'sid': request.sid, 'name': name, 'ip': client_ip, 'connected_at': now}, broadcast=True)


@socketio.on('screenshot')
def on_screenshot(data):
    if request.sid not in students: return
    now = datetime.now().strftime('%H:%M:%S')
    students[request.sid]['screenshot'] = data.get('image')
    students[request.sid]['last_seen'] = now
    emit('update_screenshot', {'sid': request.sid, 'image': data.get('image'), 'last_seen': now}, broadcast=True, include_self=False)


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
        print(f"[*] Cerrando cliente: {students[sid]['name']}")


@socketio.on('quit_all_students')
def on_quit_all_students(_data):
    for sid in list(students.keys()):
        socketio.emit('quit_app', {}, to=sid)
    print(f"[*] Cerrando todos los clientes")


@socketio.on('send_message')
def on_send_message(data):
    payload = {
        'title': data.get('title', 'Mensaje'),
        'body': data.get('body', '').strip(),
        'attachments': data.get('attachments', []),
    }
    if payload['body'] or payload['attachments']:
        emit('show_message', payload, broadcast=True, include_self=False)
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
        emit('student_lock_state', {'sid': sid, 'locked': locked}, broadcast=True)
        print(f"[*] {students[sid]['name']} -> {'BLOQUEADO' if locked else 'desbloqueado'}")


def _get_window_list():
    """Devuelve ventanas visibles usando xprop (_NET_CLIENT_LIST + _NET_WM_NAME)."""
    try:
        r = subprocess.run(['xprop', '-root', '-notype', '_NET_CLIENT_LIST'],
                           capture_output=True, text=True, timeout=3)
        if r.returncode != 0 or '_NET_CLIENT_LIST' not in r.stdout:
            return []
        # Extraer IDs hex con regex (evita el prefijo "window id # " del primer elemento)
        wids = re.findall(r'0x[0-9a-fA-F]+', r.stdout.split(':', 1)[1])
        windows = []
        for wid in wids:
            # Omitir ventanas minimizadas/ocultas
            state_r = subprocess.run(['xprop', '-id', wid, '-notype', '_NET_WM_STATE'],
                                     capture_output=True, text=True, timeout=1)
            if '_NET_WM_STATE_HIDDEN' in state_r.stdout:
                continue
            # Nombre de la ventana
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
            # Geometría
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


def _get_window_region(wid):
    """Devuelve la región actual de una ventana vía xdotool."""
    try:
        gr = subprocess.run(['xdotool', 'getwindowgeometry', '--shell', wid],
                            capture_output=True, text=True, timeout=2)
        geom = dict(kv.split('=', 1) for kv in gr.stdout.splitlines() if '=' in kv)
        if 'WIDTH' in geom:
            return {'left': int(geom['X']), 'top': int(geom['Y']),
                    'width': int(geom['WIDTH']), 'height': int(geom['HEIGHT'])}
    except Exception:
        pass
    return None


def _teacher_capture_loop():
    """Captura la pantalla del profesor con mss y emite los frames por Socket.IO."""
    try:
        import mss
        from PIL import Image
    except ImportError:
        socketio.emit('teacher_screen_preview', {'error': 'Instala mss y Pillow en el servidor: pip install mss Pillow'},
                      to=_teacher_capture['sid'])
        return

    with mss.mss() as sct:
        while _teacher_capture['running']:
            try:
                if _teacher_capture.get('type') == 'window':
                    region = _get_window_region(_teacher_capture['wid'])
                    if region is None:
                        time.sleep(0.5)
                        continue
                    cap = sct.grab(region)
                else:
                    mon = sct.monitors[_teacher_capture.get('monitor', 1)]
                    cap = sct.grab(mon)
                img = Image.frombytes('RGB', (cap.width, cap.height), cap.rgb)
                max_w = 1280
                if img.width > max_w:
                    ratio = max_w / img.width
                    img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, 'JPEG', quality=85)
                data_uri = 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
                socketio.emit('teacher_screen', {'activa': True, 'image': data_uri}, broadcast=True)
                socketio.emit('teacher_screen_preview', {'image': data_uri}, to=_teacher_capture['sid'])
            except Exception as e:
                print(f'[!] Error capturando pantalla del profesor: {e}')
            time.sleep(0.5)  # 2 FPS


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


def _capture_window_thumb(wid_hex, max_w=192):
    """Captura thumbnail de ventana via Xlib GetImage.
    En compositors (KWin, Mutter) obtiene el contenido real de la ventana
    aunque esté oculta detrás de otras ventanas."""
    try:
        from Xlib import display as xlib_display, X
        from PIL import Image
        wid = int(wid_hex, 16)
        d = xlib_display.Display()
        win = d.create_resource_object('window', wid)
        geom = win.get_geometry()
        w, h = geom.width, geom.height
        if w < 1 or h < 1:
            return None
        raw = win.get_image(0, 0, w, h, X.ZPixmap, 0xffffffff)
        # ZPixmap con profundidad 24/32: datos en formato BGRA (little-endian)
        img = Image.frombytes('RGBA', (w, h), raw.data, 'raw', 'BGRA')
        img = img.convert('RGB')
        th = max(1, round(max_w * h / w))
        img = img.resize((max_w, th), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=60)
        return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _find_desktop_icon(classes):
    """Devuelve el nombre de icono de la app buscando en archivos .desktop por WM_CLASS."""
    lower = [c.lower() for c in classes]
    dirs = [
        '/usr/share/applications',
        os.path.expanduser('~/.local/share/applications'),
        '/usr/local/share/applications',
        '/var/lib/snapd/desktop/applications',
        '/var/lib/flatpak/exports/share/applications',
    ]
    second_pass = []  # coincidencias por nombre de archivo (menor prioridad)
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
                # 1ª prioridad: StartupWMClass exacto
                swm = re.search(r'^StartupWMClass=(.+)$', text, re.MULTILINE)
                if swm and swm.group(1).strip().lower() in lower:
                    return icon
                # 2ª prioridad: nombre del .desktop == clase (filezilla.desktop → filezilla)
                stem = fname[:-8].lower()
                if stem in lower:
                    second_pass.append(icon)
            except Exception:
                pass
    return second_pass[0] if second_pass else None


def _find_icon_path(name, preferred_size=48):
    """Resuelve un nombre de icono a la ruta del archivo usando GTK IconTheme."""
    if not name:
        return None
    if os.path.isabs(name):
        return name if os.path.exists(name) else None
    base = os.path.splitext(os.path.basename(name))[0]
    # GTK IconTheme maneja correctamente todos los temas (hicolor, breeze, etc.)
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk
        info = Gtk.IconTheme.get_default().lookup_icon(base, preferred_size, 0)
        if info:
            return info.get_filename()
    except Exception:
        pass
    # Fallback: búsqueda directa en pixmaps
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


def _get_window_app_icon(wid_hex):
    """Obtiene el icono de la aplicación de una ventana via WM_CLASS y .desktop."""
    try:
        r = subprocess.run(['xprop', '-id', wid_hex, '-notype', 'WM_CLASS'],
                           capture_output=True, text=True, timeout=1)
        classes = re.findall(r'"([^"]+)"', r.stdout)
        if not classes:
            return None
        icon_name = _find_desktop_icon(classes) or classes[-1].lower()
        return _icon_to_b64(_find_icon_path(icon_name))
    except Exception:
        return None


@socketio.on('get_screens')
def on_get_screens():
    try:
        import mss
        screens = []
        with mss.mss() as sct:
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
        emit('screens_list', {'screens': screens})
    except Exception as e:
        emit('screens_list', {'error': f'Error al obtener pantallas: {e}\nAsegúrate de tener mss instalado: pip install mss Pillow'})


@socketio.on('start_teacher_capture')
def on_start_teacher_capture(data=None):
    _teacher_capture['running'] = False  # detener captura previa si la hubiera
    time.sleep(0.1)
    data = data or {}
    _teacher_capture['sid'] = request.sid
    _teacher_capture['type'] = data.get('type', 'monitor')
    _teacher_capture['monitor'] = data.get('monitor', 1)
    _teacher_capture['wid'] = data.get('wid')
    _teacher_capture['running'] = True
    t = threading.Thread(target=_teacher_capture_loop, daemon=True)
    t.start()
    print('[📺] Compartir pantalla del profesor: iniciado')


@socketio.on('stop_teacher_capture')
def on_stop_teacher_capture():
    _teacher_capture['running'] = False
    socketio.emit('teacher_screen', {'activa': False}, broadcast=True)
    print('[📺] Compartir pantalla del profesor: detenido')


@socketio.on('teacher_screenshot')
def on_teacher_screenshot(data):
    activa = data.get('activa', True)
    payload = {'activa': activa, 'image': data.get('image') if activa else None}
    emit('teacher_screen', payload, broadcast=True)


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

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    ip = get_local_ip()
    sep = '=' * 52
    print(f"\n{sep}")
    print(f"  VIGIA — Servidor del Profesor")
    print(sep)
    print(f"  Dashboard: http://{ip}:{port}")
    print(f"  Alumnos se conectan a IP: {ip}  puerto: {port}")
    print(f"{sep}\n")

    # Solo abrir navegador cuando no está corriendo dentro de Tauri
    if not os.environ.get('VIGIA_TAURI'):
        def _abrir_navegador():
            time.sleep(1.5)
            try:
                webbrowser.open(f"http://localhost:{port}")
            except Exception:
                pass

        threading.Thread(target=_abrir_navegador, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
