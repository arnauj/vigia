# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is VIGIA

Classroom monitoring software for Linux (Kubuntu/Ubuntu). The teacher runs a server (Flask) that displays a live grid of student screens. The teacher's dashboard appears as a **native desktop window** launched by `vigia-launcher.py` (Chrome/Chromium `--app` mode as primary, GTK+WebKit2GTK as fallback). Each student runs a client that captures and streams their screen. Inspired by Epoptes.

**Critical constraint:** Only works under X11 sessions. The `mss` screen-capture library does not support Wayland. Always keep this limitation in mind.

## Running the application

```bash
# Servidor — lanzador nativo (Chrome --app → WebKit2GTK → navegador)
python3 vigia-launcher.py [puerto]

# Servidor — solo el servidor Flask (sin ventana, abre http://localhost:5000)
python3 server.py [puerto]

# Cliente (equipo del alumno)
python3 client.py [ip_servidor] [puerto]
```

## Installation scripts

```bash
bash instalar.sh                               # Instalador gráfico tkinter (servidor o cliente)
bash instalar_servidor.sh                      # Instala deps Python + desktop + servicio systemd de usuario
bash instalar_cliente.sh [IP_DEL_SERVIDOR]     # Idem para alumnos; auto-detecta X.X.X.2 si no se pasa IP
bash build_debs.sh                             # Genera dist/vigia-server_1.1_amd64.deb y vigia-client_1.1_all.deb
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
  Ruta /manifest.json: Web App Manifest para PWA/Chrome app (icono VIGIA).
  Ruta /img/<filename>: sirve iconos estáticos (icon-192.png, icon-512.png).
  _teacher_capture_loop: usa socketio.start_background_task + socketio.sleep
  para integración correcta con eventlet.

vigia-launcher.py ──────────────────────────────────────────────────
  Lanzador principal del panel del profesor. Orden de preferencia:
  1. Chrome/Chromium en modo --app (getDisplayMedia nativo, sin toolbar,
     --class=vigia para icono correcto en KDE). Perfil temporal aislado.
  2. GTK + WebKit2GTK con GPU/DMA-buf desactivado (WEBKIT_DISABLE_DMABUF_RENDERER,
     WEBKIT_DISABLE_COMPOSITING_MODE, LIBGL_ALWAYS_SOFTWARE) para evitar
     pantalla negra en KWin.
  3. Navegador del sistema (webbrowser.open) como último recurso.
  Detecta si Flask ya corre como servicio systemd (wait_for_port 1.5 s) y lo
  reutiliza sin arrancar un segundo proceso ni matarlo al cerrar la ventana.

templates/dashboard.html ───────────────────────────────────────────
  SPA con JS vanilla + Socket.IO 4.x + Bootstrap 5 (todo por CDN).
  Sin proceso de build. Editar directamente el HTML.
  WebRTC: RTCPeerConnection con _iniciarWebRTC(sid, mode). En modo
  control crea DOS DataChannels con priority:'high':
    - 'vigia-mouse' (ordered:false, maxRetransmits:0) → ratón (UDP-like)
    - 'vigia-input' (ordered:true) → teclado (fiable, en orden)
  _enviarInput() enruta ratón a vigia-mouse y teclado a vigia-input;
  usa Socket.IO como fallback si los canales no están abiertos.
  _webrtcActivo se activa cuando llega el track de vídeo (ontrack),
  tanto en modo ver como en modo control.
  _fallbackJPEG: resetea _webrtcActivo=false + limpia _dc_mouse/_dc_kbd
  antes de volver a JPEG. También se activa si ICE falla tras P2P activo.
  Resolución de pantalla: viene de screen_info (Socket.IO); onloadedmetadata
  solo actúa como fallback si screen_info aún no llegó (valores 1280×720).
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

instalar_servidor.sh ───────────────────────────────────────────────
  Instala deps Python (flask, flask-socketio, eventlet…) con pip.
  Crea ~/.local/share/applications/vigia-servidor.desktop con
  Exec apuntando a vigia-launcher.py (nunca al binario Tauri).
  Crea ~/.config/systemd/user/vigia-servidor.service y lo habilita
  (arranca automáticamente con la sesión del usuario).
  loginctl enable-linger permite arranque sin sesión gráfica activa.

instalar_cliente.sh ────────────────────────────────────────────────
  Instala deps Python (python-socketio, mss, Pillow…) y de sistema
  (python3-tk, xdotool, python3-aiortc, python3-numpy).
  Crea desktop entry en el menú de inicio.
  Crea ~/.config/autostart/vigia-alumno.desktop (XDG autostart).
  Arranca el cliente inmediatamente sin esperar al siguiente reinicio.

test_remote_control.py ─────────────────────────────────────────────
  Suite de tests (unittest) para el control remoto. 39 tests. Ejecutar:
    python3 test_remote_control.py
  Cubre: mapas de teclas xdotool, _procesar_input (ratón + teclado),
  encolado en _input_q, traducción de coordenadas (letterbox/pillarbox),
  enrutamiento DataChannel (_enviarInput). No requiere servidor ni X11.

build_debs.sh ──────────────────────────────────────────────────────
  Script principal de empaquetado. Genera dos .deb en dist/:
  - vigia-server_1.1_amd64.deb  → instala en /opt/vigia-server/
      postinst: instala deps Python, crea desktop en /usr/share/applications/,
      crea servicio systemd de usuario para el usuario real (SUDO_USER).
  - vigia-client_1.1_all.deb   → instala en /opt/vigia-client/
      usa debconf para preguntar la IP del servidor durante la instalación.
      postinst: instala deps, crea desktop + XDG autostart, arranca cliente.
      prerm: para el cliente y elimina autostart.
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
Dashboard → Cliente            : eventos ratón  (RTCDataChannel 'vigia-mouse', unordered, priority:high)
Dashboard → Cliente            : eventos teclado (RTCDataChannel 'vigia-input', ordered,   priority:high)
```

## Key implementation details

- **Sin base de datos.** Todo el estado vive en los dicts `students` y `viewers` de `server.py`. Al reiniciar el servidor se pierde.
- **Imágenes como base64.** Los frames JPEG se envían como `data:image/jpeg;base64,…` por Socket.IO (máx. 8 MB). Solo se usan como fallback cuando WebRTC no está activo.
- **WebRTC P2P.** Si `python3-aiortc` está instalado en el cliente, el stream de vídeo viaja directamente alumno→profesor por UDP (H.264/VP9). Los eventos de input van por dos DataChannels con `priority:'high'`: `vigia-mouse` (unordered, sin retransmisiones) para ratón y `vigia-input` (ordered, fiable) para teclado. Fallback automático a JPEG si WebRTC falla (incluido tras P2P establecido).
- **Lanzador Chrome --app.** `vigia-launcher.py` usa un perfil temporal aislado (`tempfile.mkdtemp`) para no interferir con el Chrome del usuario. `--class=vigia` hace que KDE asocie la ventana al `.desktop` y muestre el icono correcto.
- **Detección de Flask ya activo.** `vigia-launcher.py` sondea el puerto 5000 durante 1,5 s antes de arrancar Flask. Si ya corre (servicio systemd), lo reutiliza y no lo mata al cerrar la ventana.
- **GPU desactivado en WebKit2GTK.** Las variables `WEBKIT_DISABLE_DMABUF_RENDERER=1`, `WEBKIT_DISABLE_COMPOSITING_MODE=1`, `LIBGL_ALWAYS_SOFTWARE=1` se fijan antes de importar GTK para evitar el deadlock con KWin/KDE que produce pantalla negra.
- **instalar_servidor.sh siempre usa vigia-launcher.py.** No usa el binario Tauri aunque exista, ya que Tauri puede causar pantalla negra en KWin.
- **`_instalar()` en client.py** detecta si pip falta, lo instala vía `apt-get python3-pip` y hace fallback a `pip3` si `python -m pip` falla. aiortc NO se auto-instala (requiere apt por las libs nativas).
- **Tkinter en client.py** se usa solo para ventanas flotantes (pantalla del profesor, mensajes, bloqueo). Si no está disponible el cliente sigue funcionando pero sin UI.
- **Bloqueo de pantalla** usa `grab_set_global()` de Tkinter (XGrabPointer + XGrabKeyboard) para capturar todos los eventos X11.
- **xdotool vs pynput:** xdotool es el backend principal de control remoto por ser más fiable en X11/Xwayland. pynput es el fallback automático si xdotool no está instalado.
- **Coordenadas en modo control WebRTC:** el `<video>` usa `max-width:100%;max-height:100%` (no `width:100%;height:100%`) para que `getBoundingClientRect()` devuelva el área real del contenido, igual que el `<img>`.
- **Adjuntos en mensajes:** el dashboard codifica los archivos en base64 (límite 10 MB total) y los envía junto al mensaje. El cliente los decodifica y guarda en `~/Descargas`, con botón para abrir cada uno con `xdg-open`.
- **IP por defecto del cliente:** `instalar_cliente.sh` auto-detecta la IP local con `ip route get 1.1.1.1` y sustituye el último octeto por `.2` para apuntar al servidor por convención.
- **Web App Manifest.** `server.py` sirve `/manifest.json` con iconos `icon-192.png` e `icon-512.png` para que Chrome muestre el icono de VIGIA en lugar del icono genérico de Chrome en modo `--app`.
- **instalar.sh / instalar.py:** lanzador bash + GUI tkinter que permite elegir servidor/cliente. Usa `PhotoImage.subsample(5,5)` para escalar el logo sin Pillow.

## Dependencies

| Componente | Python | Sistema (apt) |
|---|---|---|
| Servidor | `flask flask-socketio eventlet` | — |
| Cliente | `python-socketio[client] websocket-client mss Pillow` | `python3-tk xdotool` |
| Cliente (WebRTC) | — | `python3-aiortc python3-numpy` |
| Ventana nativa fallback (profesor) | — | `python3-gi gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0 libgtk-3-0` |

## Packaging

```bash
bash build_debs.sh   # genera dist/vigia-server_1.1_amd64.deb y vigia-client_1.1_all.deb

# Instalar
sudo apt install ./dist/vigia-server_1.1_amd64.deb
sudo apt install ./dist/vigia-client_1.1_all.deb

# Desinstalar
sudo dpkg -r vigia-server
sudo dpkg -r vigia-client
```

El servidor se instala en `/opt/vigia-server/`. El cliente en `/opt/vigia-client/`.
`postinst` del servidor crea el servicio systemd de usuario y el desktop entry.
`postinst` del cliente usa debconf para preguntar la IP, crea autostart XDG y arranca el cliente.
`prerm` del servidor para y deshabilita el servicio systemd.
`prerm` del cliente mata el proceso y elimina el autostart.

## REGLA OBLIGATORIA: regenerar los .deb tras cada cambio

**Cada vez que se modifique cualquier archivo del proyecto, es OBLIGATORIO regenerar los paquetes `.deb` afectados en `./dist/` ejecutando:**

```bash
bash build_debs.sh
```

Esto garantiza que `dist/vigia-server_1.1_amd64.deb` y `dist/vigia-client_1.1_all.deb` estén siempre sincronizados con el código fuente.

### Qué cambios afectan a qué paquete

| Archivo/componente modificado | Paquete a regenerar |
|---|---|
| `server.py`, `vigia-launcher.py`, `templates/`, `instalar_servidor.sh`, `img/` | `vigia-server_1.1_amd64.deb` |
| `client.py`, `instalar_cliente.sh` | `vigia-client_1.1_all.deb` |
| Cualquier archivo compartido o cambio global | **Ambos** paquetes |

> Nunca entregar ni documentar un cambio sin haber ejecutado `bash build_debs.sh` y verificado que los `.deb` de `dist/` se han actualizado correctamente.
