#!/usr/bin/env python3
"""
VIGIA - Servidor del Profesor
Muestra en tiempo real las pantallas de los alumnos conectados.
Uso: python server.py [puerto]
"""

import sys
import socket
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'vigia-aula-2024'

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    max_http_buffer_size=8 * 1024 * 1024,  # 8 MB max por mensaje
    async_mode='threading',
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
    """Devuelve la lista de alumnos (sin las imágenes grandes)."""
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
    client_ip = (
        request.environ.get('HTTP_X_FORWARDED_FOR')
        or request.environ.get('REMOTE_ADDR', 'Desconocida')
    )
    print(f"[+] Conexión: {request.sid}  IP: {client_ip}")


@socketio.on('disconnect')
def on_disconnect():
    if request.sid in students:
        name = students[request.sid]['name']
        del students[request.sid]
        # Notificar al profesor si estaba observando/controlando a este alumno
        if request.sid in viewers:
            prof_sid = viewers.pop(request.sid)['prof_sid']
            socketio.emit('student_view_ended', {'sid': request.sid}, to=prof_sid)
        print(f"[-] Desconectado: {name}")
        emit('student_disconnected', {'sid': request.sid}, broadcast=True)


@socketio.on('register')
def on_register(data):
    """El alumno se registra con su nombre y hostname."""
    client_ip = (
        request.environ.get('HTTP_X_FORWARDED_FOR')
        or request.environ.get('REMOTE_ADDR', 'Desconocida')
    )
    name = data.get('name', 'Alumno')
    now = datetime.now().strftime('%H:%M:%S')
    students[request.sid] = {
        'name': name,
        'ip': client_ip,
        'screenshot': None,
        'last_seen': now,
        'connected_at': now,
        'locked': False,
    }
    print(f"[+] Registrado: {name}  ({client_ip})")
    emit('registered', {'status': 'ok', 'sid': request.sid})
    emit(
        'student_connected',
        {'sid': request.sid, 'name': name, 'ip': client_ip, 'connected_at': now},
        broadcast=True,
    )


@socketio.on('screenshot')
def on_screenshot(data):
    """Recibe una captura de pantalla de un alumno y la retransmite al dashboard."""
    if request.sid not in students:
        return
    now = datetime.now().strftime('%H:%M:%S')
    img_data = data.get('image')
    students[request.sid]['screenshot'] = img_data
    students[request.sid]['last_seen'] = now

    # Retransmite al dashboard (a todos menos al alumno emisor)
    emit(
        'update_screenshot',
        {'sid': request.sid, 'image': img_data, 'last_seen': now},
        broadcast=True,
        include_self=False,
    )


@socketio.on('request_students')
def on_request_students():
    """El dashboard pide la lista completa con las últimas capturas."""
    payload = []
    for sid, data in students.items():
        payload.append({
            'sid': sid,
            'name': data['name'],
            'ip': data['ip'],
            'last_seen': data['last_seen'],
            'connected_at': data['connected_at'],
            'image': data['screenshot'],
            'locked': data.get('locked', False),
        })
    emit('full_student_list', payload)


@socketio.on('quit_student')
def on_quit_student(data):
    """Cierra la aplicación cliente de un alumno concreto."""
    sid = data.get('sid')
    if sid not in students:
        return
    socketio.emit('quit_app', {}, to=sid)
    print(f"[*] Cerrando cliente: {students[sid]['name']}")


@socketio.on('quit_all_students')
def on_quit_all_students(_data):
    """Cierra la aplicación cliente de todos los alumnos."""
    for sid in list(students.keys()):
        socketio.emit('quit_app', {}, to=sid)
    print(f"[*] Cerrando {len(students)} cliente(s)")


@socketio.on('send_message')
def on_send_message(data):
    """Envía un mensaje (con título y cuerpo HTML) a todos los alumnos."""
    titulo = data.get('title', 'Mensaje del profesor')
    body   = data.get('body', data.get('text', '')).strip()
    if not body:
        return
    payload = {'title': titulo, 'body': body}
    for sid in list(students.keys()):
        socketio.emit('show_message', payload, to=sid)
    print(f"[*] Mensaje → {len(students)} alumno(s): {titulo}")


@socketio.on('send_message_to')
def on_send_message_to(data):
    """Envía un mensaje (con título y cuerpo HTML) a un alumno concreto."""
    sid    = data.get('sid')
    titulo = data.get('title', 'Mensaje del profesor')
    body   = data.get('body', data.get('text', '')).strip()
    if not body or sid not in students:
        return
    socketio.emit('show_message', {'title': titulo, 'body': body}, to=sid)
    print(f"[*] Mensaje → {students[sid]['name']}: {titulo}")


@socketio.on('lock_student')
def on_lock_student(data):
    """El profesor bloquea o desbloquea la pantalla de un alumno."""
    sid = data.get('sid')
    locked = bool(data.get('locked', True))
    if sid not in students:
        return
    students[sid]['locked'] = locked
    evento = 'lock_screen' if locked else 'unlock_screen'
    socketio.emit(evento, {}, to=sid)
    emit('student_lock_state', {'sid': sid, 'locked': locked}, broadcast=True)
    accion = 'BLOQUEADO' if locked else 'desbloqueado'
    print(f"[*] {students[sid]['name']} → {accion}")


@socketio.on('teacher_screenshot')
def on_teacher_screenshot(data):
    """El profesor comparte su pantalla: retransmite a todos los alumnos."""
    activa = data.get('activa', True)
    payload = {
        'activa': activa,
        'image': data.get('image') if activa else None,
    }
    for sid in list(students.keys()):
        socketio.emit('teacher_screen', payload, to=sid)
    if activa:
        print(f"[*] Pantalla del profesor → {len(students)} alumno(s)")


@socketio.on('start_view')
def on_start_view(data):
    """El profesor empieza a ver o controlar la pantalla de un alumno."""
    student_sid = data.get('sid')
    mode = data.get('mode', 'view')   # 'view' | 'control'
    if student_sid not in students:
        return
    viewers[student_sid] = {'prof_sid': request.sid, 'mode': mode}
    socketio.emit('viewer_start', {'mode': mode}, to=student_sid)
    accion = 'controla' if mode == 'control' else 've'
    print(f"[👁] {request.sid[:6]}… {accion}: {students[student_sid]['name']}")


@socketio.on('stop_view')
def on_stop_view(data):
    """El profesor deja de ver o controlar."""
    student_sid = data.get('sid')
    if student_sid in viewers and viewers[student_sid]['prof_sid'] == request.sid:
        viewers.pop(student_sid)
        socketio.emit('viewer_stop', {}, to=student_sid)
        print(f"[👁] Sesión terminada: {students.get(student_sid, {}).get('name', '?')}")


@socketio.on('remote_frame')
def on_remote_frame(data):
    """El alumno envía frame de alta frecuencia al profesor que le observa."""
    if request.sid not in viewers:
        return
    prof_sid = viewers[request.sid]['prof_sid']
    socketio.emit('live_frame', {
        'sid':    request.sid,
        'image':  data.get('image'),
        'orig_w': data.get('orig_w', 1280),
        'orig_h': data.get('orig_h', 720),
    }, to=prof_sid)


@socketio.on('remote_input')
def on_remote_input(data):
    """El profesor envía un evento de ratón/teclado al alumno que controla."""
    student_sid = data.get('sid')
    if student_sid not in viewers:
        return
    session = viewers[student_sid]
    if session['prof_sid'] != request.sid or session['mode'] != 'control':
        return
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

    # Abrir el navegador tras un breve retardo (el servidor tarda un instante en arrancar)
    def _abrir_navegador():
        import time
        time.sleep(1.2)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=_abrir_navegador, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
