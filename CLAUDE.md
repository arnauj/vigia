# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is VIGIA

Classroom monitoring software for Linux (Kubuntu/Ubuntu). The teacher runs a server (Flask) that displays a live grid of student screens. The teacher's dashboard appears as a **native desktop window** powered by Tauri 2.0 (WebKit). Each student runs a client that captures and streams their screen. Inspired by Epoptes.

**Critical constraint:** Only works under X11 sessions. The `mss` screen-capture library does not support Wayland. Always keep this limitation in mind.

## Running the application

```bash
# Servidor — ventana nativa Tauri (compilar primero con vigia-dashboard/build.sh)
./vigia-dashboard/src-tauri/target/release/vigia

# Servidor — alternativa sin compilar Tauri (abre navegador en http://localhost:5000)
python3 server.py [puerto]

# Cliente (equipo del alumno)
python3 client.py [ip_servidor] [puerto]
```

## Installation scripts

```bash
bash instalar.sh                               # Instalador gráfico tkinter (servidor o cliente)
bash instalar_servidor.sh                      # Instala dependencias y crea acceso directo
bash instalar_cliente.sh [IP_DEL_SERVIDOR]     # Idem para alumnos; auto-detecta X.X.X.2 si no se pasa IP
bash build_deb.sh                              # Genera dist/vigia_1.0_amd64.deb (compila Tauri si falta)
bash vigia-dashboard/build.sh                  # Instala Rust y compila el binario Tauri
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

vigia-dashboard/ ───────────────────────────────────────────────────
  Proyecto Tauri 2.0 (Rust). Arranca server.py como subproceso, sondea
  localhost:5000 cada 250 ms, abre WebviewWindowBuilder con
  WebviewUrl::External("http://localhost:5000"). Al cerrar la ventana,
  RunEvent::Exit mata el subproceso Flask.
  Compilar: bash vigia-dashboard/build.sh
  Binario:  vigia-dashboard/src-tauri/target/release/vigia

templates/dashboard.html ───────────────────────────────────────────
  SPA con JS vanilla + Socket.IO 4.x + Bootstrap 5 (todo por CDN).
  Sin proceso de build. Editar directamente el HTML.
  WebRTC: RTCPeerConnection con _iniciarWebRTC(sid, mode). En modo
  control crea un DataChannel 'vigia-input' (ordered:false) para
  enviar eventos de ratón/teclado directamente al cliente. _enviarInput()
  usa el DataChannel si está abierto, Socket.IO como fallback.
  _webrtcActivo se activa cuando llega el track de vídeo (ontrack),
  tanto en modo ver como en modo control.
  Adjuntos en mensajes: _composeFiles [], _addFiles(), _renderFileList().
  IMPORTANTE: declarar `let _composeFiles` antes de cualquier código
  que pueda lanzar excepciones (riesgo de TDZ en JS).

client.py ──────────────────────────────────────────────────────────
  Socket.IO client + captura mss + Tkinter (ventanas flotantes)
  Hilo daemon unificado `bucle_capturas`: screenshots normales (~1 s);
  frames JPEG HD solo cuando _en_observacion y NOT _webrtc_activo.
  Control remoto: xdotool (preferido, X11) → pynput (fallback).
  Auto-instala sus dependencias pip al arrancar si faltan.
  _VentanaMensaje: muestra texto enriquecido + archivos adjuntos recibidos.
    Los adjuntos (base64) se guardan en ~/Descargas y se abren con xdg-open.
  WebRTC (opcional, requiere python3-aiortc):
    - Hilo asyncio dedicado (_asyncio_runner / _webrtc_loop).
    - ScreenStreamTrack: captura mss a 15 fps en thread pool, devuelve
      av.VideoFrame RGB para aiortc.
    - _procesar_offer: crea RTCPeerConnection, añade track, gestiona
      DataChannel entrante (llama a on_do_input con los mensajes JSON).
    - _webrtc_activo = True cuando ICE conecta; suprime envío JPEG.
    - _cerrar_webrtc: llamado al recibir viewer_stop.

instalar.py ────────────────────────────────────────────────────────
  Instalador gráfico tkinter. Radiobuttons Servidor/Cliente.
  En modo cliente muestra campo IP (auto-detectado como X.X.X.2).
  scrolledtext para output en tiempo real del script bash.
  Logo: logo2.png subsample(5,5) → ~153×153 px sin Pillow.

build_deb.sh ───────────────────────────────────────────────────────
  Genera dist/vigia_1.0_amd64.deb.
  Si el binario Tauri no existe, llama a vigia-dashboard/build.sh.
  Instala en /opt/vigia/: server.py, client.py, vigia (binario), …
  Depends: python3, python3-tk, libwebkit2gtk-4.1-0, libgtk-3-0
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
| `show_message` | servidor → cliente | Popup con HTML + adjuntos base64 |
| `send_message` | dashboard → servidor | Enviar mensaje a todos (title, body, attachments) |
| `send_message_to` | dashboard → servidor | Enviar mensaje a un alumno (sid, title, body, attachments) |
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
- **Adjuntos en mensajes:** el dashboard codifica los archivos en base64 (límite 10 MB total) y los envía junto al mensaje. El cliente los decodifica y guarda en `~/Descargas`, con botón para abrir cada uno con `xdg-open`.
- **IP por defecto del cliente:** `instalar_cliente.sh` auto-detecta la IP local con `ip route get 1.1.1.1` y sustituye el último octeto por `.2` para apuntar al servidor por convención.
- **Ventana nativa Tauri:** `vigia-dashboard/src-tauri/src/lib.rs` gestiona el ciclo de vida completo: spawn de Flask, polling de puerto, `WebviewWindowBuilder`, y kill en `RunEvent::Exit`.
- **instalar.sh / instalar.py:** lanzador bash + GUI tkinter que permite elegir servidor/cliente. Usa `PhotoImage.subsample(5,5)` para escalar el logo sin Pillow.

## Dependencies

| Componente | Python | Sistema (apt) |
|---|---|---|
| Servidor | `flask flask-socketio` | — |
| Cliente | `python-socketio[client] websocket-client mss Pillow` | `python3-tk xdotool` |
| Cliente (WebRTC) | — | `python3-aiortc python3-numpy` |
| Ventana nativa (profesor) | — | `libwebkit2gtk-4.1-0 libgtk-3-0` |
| Compilar ventana nativa | — | `rust/cargo` (via rustup), `libwebkit2gtk-4.1-dev libgtk-3-dev libssl-dev` |

## Packaging

```bash
bash build_deb.sh        # genera dist/vigia_1.0_amd64.deb
sudo dpkg -i dist/vigia_1.0_amd64.deb
sudo dpkg -r vigia       # desinstalar
```

El `.deb` instala todo en `/opt/vigia/` e incluye el binario `vigia` (Tauri).
`postinst` lanza `instalar.py` como el usuario real para crear los accesos directos.
`prerm` elimina `~/.local/share/applications/vigia-servidor.desktop` y `vigia-alumno.desktop`.
