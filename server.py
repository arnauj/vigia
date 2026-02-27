#!/usr/bin/env python3
"""
VIGIA - Servidor del Profesor (v1.6)
Muestra en tiempo real las pantallas de los alumnos conectados.
Uso: python server.py [puerto]
"""

import sys
import warnings

# Silenciar avisos de deprecación de eventlet (Python 3.12+)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="eventlet")

# Eventlet monkey patching debe hacerse ANTES de cualquier otra importación
try:
    import eventlet
    eventlet.monkey_patch()
    async_mode = 'eventlet'
except ImportError:
    async_mode = 'threading'

import socket
from datetime import datetime
from flask import Flask, render_template, jsonify, request
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
    return render_template('dashboard.html')


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

@socketio.on('connect')
def on_connect():
    client_ip = (request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR', 'Desconocida'))
    print(f"[+] Conexión: {request.sid}  IP: {client_ip}")


@socketio.on('disconnect')
def on_disconnect():
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
    client_ip = (request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR', 'Desconocida'))
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
def on_request_students():
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
    payload = {'title': data.get('title', 'Mensaje'), 'body': data.get('body', '').strip()}
    if payload['body']:
        emit('show_message', payload, broadcast=True, include_self=False)
        print(f"[*] Mensaje enviado a todos: {payload['title']}")


@socketio.on('send_message_to')
def on_send_message_to(data):
    sid = data.get('sid')
    if sid in students:
        payload = {'title': data.get('title', 'Mensaje'), 'body': data.get('body', '').strip()}
        socketio.emit('show_message', payload, to=sid)
        print(f"[*] Mensaje enviado a {students[sid]['name']}: {payload['title']}")


@socketio.on('lock_student')
def on_lock_student(data):
    sid = data.get('sid')
    locked = bool(data.get('locked', True))
    if sid in students:
        students[sid]['locked'] = locked
        socketio.emit('lock_screen' if locked else 'unlock_screen', {}, to=sid)
        emit('student_lock_state', {'sid': sid, 'locked': locked}, broadcast=True)
        print(f"[*] {students[sid]['name']} -> {'BLOQUEADO' if locked else 'desbloqueado'}")


@socketio.on('teacher_screenshot')
def on_teacher_screenshot(data):
    activa = data.get('activa', True)
    payload = {'activa': activa, 'image': data.get('image') if activa else None}
    # Broadcast directo a todos los clientes (alumnos)
    socketio.emit('teacher_screen', payload, broadcast=True, include_self=False)


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


# ── Arranque ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import threading
    import webbrowser

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    ip = get_local_ip()
    sep = '=' * 52
    print(f"\n{sep}")
    print(f"  VIGIA — Servidor del Profesor")
    print(sep)
    print(f"  Dashboard: http://{ip}:{port}")
    print(f"  Alumnos se conectan a IP: {ip}  puerto: {port}")
    print(f"{sep}\n")

    def _abrir_navegador():
        import time
        time.sleep(1.5)
        try:
            webbrowser.open(f"http://localhost:{port}")
        except Exception:
            # Silenciar errores de lanzamiento de navegador (timeout, etc)
            pass

    if async_mode == 'eventlet':
        eventlet.spawn_after(1.5, _abrir_navegador)
    else:
        threading.Thread(target=_abrir_navegador, daemon=True).start()
    
    if async_mode == 'eventlet':
        socketio.run(app, host='0.0.0.0', port=port, debug=False)
    else:
        socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
