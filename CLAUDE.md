# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is VIGIA

Classroom monitoring software for Linux (Kubuntu/Ubuntu). The teacher runs a server that displays a live grid of student screens in a browser. Each student runs a client that captures and streams their screen. Inspired by Epoptes.

**Critical constraint:** Only works under X11 sessions. The `mss` screen-capture library does not support Wayland. Always keep this limitation in mind.

## Running the application

```bash
# Servidor (equipo del profesor) — abre el navegador en http://localhost:5000
python3 server.py [puerto]

# Cliente (equipo del alumno)
python3 client.py [ip_servidor] [puerto]
```

## Installation scripts

```bash
bash instalar_servidor.sh                      # Instala dependencias y crea acceso directo
bash instalar_cliente.sh [IP_DEL_SERVIDOR]     # Idem para alumnos; fija la IP en el acceso directo
```

## Architecture

```
server.py ──────────────────────────────────────────────────────────
  Flask + Flask-SocketIO (threading mode, puerto 5000)
  Estado en memoria:
    students = {sid: {name, ip, screenshot, last_seen, locked, …}}
    viewers  = {student_sid: {prof_sid, mode}}   # sesiones activas view/control

templates/dashboard.html ───────────────────────────────────────────
  SPA con JS vanilla + Socket.IO 4.x + Bootstrap 5 (todo por CDN).
  Sin proceso de build. Editar directamente el HTML.

client.py ──────────────────────────────────────────────────────────
  Socket.IO client + captura mss + Tkinter (ventanas flotantes)
  Hilo daemon unificado `bucle_capturas`: gestiona tanto los
  screenshots normales (~2,5 s) como los frames de alta frecuencia
  (~0,4 s) cuando el profesor observa/controla.
  Control remoto: xdotool (preferido, X11) → pynput (fallback).
  Auto-instala sus dependencias pip al arrancar si faltan.
```

## Socket.IO event flow

| Evento | Dirección | Descripción |
|---|---|---|
| `register` | cliente → servidor | Alumno se anuncia con nombre |
| `screenshot` | cliente → servidor | JPEG base64 cada ~2,5 s |
| `update_screenshot` | servidor → dashboard | Retransmisión del screenshot |
| `start_view` / `stop_view` | dashboard → servidor | Iniciar/parar observación remota |
| `viewer_start` / `viewer_stop` | servidor → cliente | Notificación al alumno |
| `remote_frame` | cliente → servidor | Frame HD (~0,4 s) durante observación |
| `live_frame` | servidor → dashboard | Retransmisión del frame HD |
| `remote_input` | dashboard → servidor → cliente | Eventos ratón/teclado |
| `lock_screen` / `unlock_screen` | servidor → cliente | Bloqueo de pantalla (grab X11 global) |
| `show_message` | servidor → cliente | Popup con HTML enriquecido |
| `teacher_screenshot` | dashboard → servidor → clientes | Pantalla del profesor en alumnos |

## Key implementation details

- **Sin base de datos.** Todo el estado vive en los dicts `students` y `viewers` de `server.py`. Al reiniciar el servidor se pierde.
- **Imágenes como base64.** Los frames se envían como `data:image/jpeg;base64,…` directamente por Socket.IO (máx. 8 MB por mensaje en el servidor).
- **`_instalar()` en client.py** detecta si pip falta, lo instala vía `apt-get python3-pip` y hace fallback a `pip3` si `python -m pip` falla.
- **Tkinter en client.py** se usa solo para ventanas flotantes (pantalla del profesor, mensajes, bloqueo). Si no está disponible el cliente sigue funcionando pero sin UI.
- **Bloqueo de pantalla** usa `grab_set_global()` de Tkinter (XGrabPointer + XGrabKeyboard) para capturar todos los eventos X11.
- **xdotool vs pynput:** xdotool es el backend principal de control remoto por ser más fiable en X11/Xwayland. pynput es el fallback automático si xdotool no está instalado.

## Dependencies

| Componente | Python | Sistema (apt) |
|---|---|---|
| Servidor | `flask flask-socketio` | — |
| Cliente | `python-socketio[client] websocket-client mss Pillow` | `python3-tk xdotool` |
