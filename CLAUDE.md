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
  Señalización WebRTC: relaya webrtc_offer/answer/ice entre dashboard
  y cliente usando viewers para autorización.

templates/dashboard.html ───────────────────────────────────────────
  SPA con JS vanilla + Socket.IO 4.x + Bootstrap 5 (todo por CDN).
  Sin proceso de build. Editar directamente el HTML.
  WebRTC: RTCPeerConnection con _iniciarWebRTC(sid, mode). En modo
  control crea un DataChannel 'vigia-input' (ordered:false) para
  enviar eventos de ratón/teclado directamente al cliente. _enviarInput()
  usa el DataChannel si está abierto, Socket.IO como fallback.
  _webrtcActivo se activa cuando llega el track de vídeo (ontrack),
  tanto en modo ver como en modo control.

client.py ──────────────────────────────────────────────────────────
  Socket.IO client + captura mss + Tkinter (ventanas flotantes)
  Hilo daemon unificado `bucle_capturas`: screenshots normales (~1 s);
  frames JPEG HD solo cuando _en_observacion y NOT _webrtc_activo.
  Control remoto: xdotool (preferido, X11) → pynput (fallback).
  Auto-instala sus dependencias pip al arrancar si faltan.
  WebRTC (opcional, requiere python3-aiortc):
    - Hilo asyncio dedicado (_asyncio_runner / _webrtc_loop).
    - ScreenStreamTrack: captura mss a 15 fps en thread pool, devuelve
      av.VideoFrame RGB para aiortc.
    - _procesar_offer: crea RTCPeerConnection, añade track, gestiona
      DataChannel entrante (llama a on_do_input con los mensajes JSON).
    - _webrtc_activo = True cuando ICE conecta; suprime envío JPEG.
    - _cerrar_webrtc: llamado al recibir viewer_stop.
```

## Socket.IO event flow

| Evento | Dirección | Descripción |
|---|---|---|
| `register` | cliente → servidor | Alumno se anuncia con nombre |
| `screenshot` | cliente → servidor | JPEG base64 cada ~1 s |
| `update_screenshot` | servidor → dashboard | Retransmisión del screenshot |
| `start_view` / `stop_view` | dashboard → servidor | Iniciar/parar observación remota |
| `viewer_start` / `viewer_stop` | servidor → cliente | Notificación al alumno |
| `remote_frame` | cliente → servidor | Frame HD JPEG durante observación (fallback) |
| `live_frame` | servidor → dashboard | Retransmisión del frame HD (fallback) |
| `remote_input` | dashboard → servidor → cliente | Eventos ratón/teclado (fallback Socket.IO) |
| `lock_screen` / `unlock_screen` | servidor → cliente | Bloqueo de pantalla (grab X11 global) |
| `show_message` | servidor → cliente | Popup con HTML enriquecido |
| `teacher_screenshot` | dashboard → servidor → clientes | Pantalla del profesor en alumnos |
| `webrtc_offer` | dashboard → servidor → cliente | SDP offer para WebRTC |
| `webrtc_answer` | cliente → servidor → dashboard | SDP answer para WebRTC |
| `webrtc_ice` | bidireccional vía servidor | ICE candidates |

**Flujo WebRTC (P2P tras señalización):**
```
Dashboard → servidor → cliente : webrtc_offer (SDP)
Cliente → servidor → dashboard : webrtc_answer (SDP)
Ambos ↔ servidor ↔ ambos      : webrtc_ice (candidates)
Cliente → Dashboard            : stream vídeo H.264/VP9 (RTCPeerConnection, UDP)
Dashboard → Cliente            : eventos input (RTCDataChannel, unordered)
```

## Key implementation details

- **Sin base de datos.** Todo el estado vive en los dicts `students` y `viewers` de `server.py`. Al reiniciar el servidor se pierde.
- **Imágenes como base64.** Los frames JPEG se envían como `data:image/jpeg;base64,…` por Socket.IO (máx. 8 MB). Solo se usan como fallback cuando WebRTC no está activo.
- **WebRTC P2P.** Si `python3-aiortc` está instalado en el cliente, el stream de vídeo viaja directamente alumno→profesor por UDP (H.264/VP9). Los eventos de input van por el DataChannel (UDP sin reordenación). Fallback automático a JPEG en 8 s si WebRTC falla.
- **`_instalar()` en client.py** detecta si pip falta, lo instala vía `apt-get python3-pip` y hace fallback a `pip3` si `python -m pip` falla. aiortc NO se auto-instala (requiere apt por las libs nativas).
- **Tkinter en client.py** se usa solo para ventanas flotantes (pantalla del profesor, mensajes, bloqueo). Si no está disponible el cliente sigue funcionando pero sin UI.
- **Bloqueo de pantalla** usa `grab_set_global()` de Tkinter (XGrabPointer + XGrabKeyboard) para capturar todos los eventos X11.
- **xdotool vs pynput:** xdotool es el backend principal de control remoto por ser más fiable en X11/Xwayland. pynput es el fallback automático si xdotool no está instalado.
- **Coordenadas en modo control WebRTC:** el `<video>` usa `max-width:100%;max-height:100%` (no `width:100%;height:100%`) para que `getBoundingClientRect()` devuelva el área real del contenido, igual que el `<img>`.

## Dependencies

| Componente | Python | Sistema (apt) |
|---|---|---|
| Servidor | `flask flask-socketio` | — |
| Cliente | `python-socketio[client] websocket-client mss Pillow` | `python3-tk xdotool` |
| Cliente (WebRTC) | — | `python3-aiortc python3-numpy` |
