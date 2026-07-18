# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is VIGIA

Classroom monitoring software for Linux (Kubuntu/Ubuntu). The teacher runs a server (Flask) that displays a live grid of student screens. The teacher's dashboard appears as a **native desktop window** launched by `vigia-launcher.py` (Chrome/Chromium `--app` mode as primary, GTK+WebKit2GTK as fallback). Each student runs a client that captures and streams their screen.

**Critical constraint (sesiones gráficas):** `mss` (captura) y `xdotool`/`pynput` (control remoto) solo funcionan en X11. Kubuntu 25.10+/26.04 usa **Wayland como única sesión por defecto**, así que existe una capa de compatibilidad:
- **Captura:** `screen_capture.py` abstrae el backend — `mss` en X11/Windows; en Wayland se prefiere **PipeWire vía el portal ScreenCast** (`pipewire_capture.py`, ~30-60 fps, fluido como RustDesk) y, si el portal no está/se deniega, cae a `spectacle -b -n -f -o` (KDE), `grim` (wlroots) o `gnome-screenshot` (GNOME) (~1-3 fps). El portal PipeWire muestra UN diálogo de permiso la primera vez por usuario; con `restore_token` (guardado en `~/.config/vigia/screencast.token`) las siguientes sesiones son silenciosas.
- **Detección de sesión robusta:** `session_type()` detecta Wayland aunque el proceso se lance sin `WAYLAND_DISPLAY` (sondea el socket `wayland-*` en `XDG_RUNTIME_DIR`) y fija el entorno para los hijos (spectacle/ydotool). Sin esto, el cliente veía solo `DISPLAY=:0` (XWayland), usaba `mss` y capturaba el root vacío de XWayland = **pantalla negra**.
- **Control remoto:** en Wayland el **puntero** (mover/clic/scroll) va por `vigia_input.py` — un demonio root propio que crea un dispositivo uinput con eje **ABSOLUTO** (servicio `vigia-input`). Es imprescindible: el dispositivo de ydotool solo tiene ejes RELATIVOS, así que `ydotool mousemove -a` deja el cursor pegado en la esquina superior izquierda (disparando además los hot-corners de KDE). El **teclado** sigue por `ydotool` (servicio `vigia-ydotoold`). xdotool/pynput son el backend X11.
- **Bloqueo de pantalla:** en Wayland `grab_set_global()` (XGrabKeyboard) NO funciona. El bloqueo real lo hace el demonio `vigia-input` con `EVIOCGRAB` sobre los dispositivos de entrada FÍSICOS del alumno (su teclado/ratón quedan inertes), mientras el ratón virtual del profesor sigue inyectando. Se libera automáticamente si la conexión del cliente se cae (fail-safe: el alumno nunca queda bloqueado permanentemente).
- Captura de ventanas individuales, bloqueo global de pantalla y captura a ~30 fps siguen requiriendo X11 (`plasma-session-x11` sigue en el archive de Ubuntu 26.04, sin soporte oficial de Kubuntu).

## Running the application

```bash
# Servidor — lanzador nativo (Chrome --app → WebKit2GTK → navegador)
python3 vigia-launcher.py [puerto]

# Servidor — solo el servidor Flask (sin ventana)
python3 server.py [puerto]

# Cliente (equipo del alumno)
python3 client.py [ip_servidor] [puerto]
```

## Installation scripts

```bash
bash instalar.sh                               # Instalador gráfico tkinter (servidor o cliente)
bash instalar_servidor.sh                      # Instala deps Python + desktop + servicio systemd de usuario
bash instalar_cliente.sh [IP_DEL_SERVIDOR]     # Idem para alumnos; auto-detecta X.X.X.2 si no se pasa IP
bash build_debs.sh                             # Genera dist/vigia-server_1.2_amd64.deb y vigia-client_1.2_all.deb
```

## Architecture

```
server.py ──────────────────────────────────────────────────────────
  Flask + Flask-SocketIO (puerto 5000). async_mode: eventlet si está
  instalado, si no threading (con simple-websocket para WS). En los .deb
  ya NO se instala eventlet (greenlet es una extensión C que se rompe
  con cada versión nueva de Python — p.ej. Kubuntu 26).
  IMPORTANTE: no pasar broadcast=True a socketio.emit() — provoca
  TypeError con python-socketio/flask-socketio modernos de apt; emitir
  sin 'to' ya difunde a todos.
  Estado en memoria:
    students = {sid: {name, ip, screenshot, last_seen, locked, …}}
    viewers  = {student_sid: {prof_sid, mode}}   # sesiones activas view/control
  Señalización WebRTC: relaya webrtc_offer/answer/ice entre dashboard
  y cliente usando viewers para autorización.
  Ruta /manifest.json: Web App Manifest para PWA/Chrome app (icono VIGIA).
  Ruta /img/<filename>: sirve iconos estáticos (icon-192.png, icon-512.png).
  _teacher_capture_loop: usa socketio.start_background_task + socketio.sleep;
  captura vía screen_capture (mss en X11, spectacle/grim en Wayland).
  Captura de ventana individual: solo X11 (mss + xdotool).

screen_capture.py ──────────────────────────────────────────────────
  Abstracción de captura compartida por server.py y client.py.
  session_type() → 'x11' | 'wayland' | 'windows' | 'unknown'
  create_capturer() → MssBackend (X11/Win) o CliBackend (Wayland:
  spectacle/grim/gnome-screenshot, orden según XDG_CURRENT_DESKTOP).
  API: .grab() → PIL.Image RGB, .monitor() → {left,top,width,height},
  .close(). MssBackend además: .set_monitor(i), .monitors().
  Importa mss/PIL de forma perezosa (los tests los mockean).
  En Wayland prueba PRIMERO PipeWireBackend (pipewire_capture) compartido por
  refcount (un solo stream/sesión del portal para miniaturas + WebRTC); si falla
  se marca _pw_disabled y no se reintenta (evita repetir diálogos).

pipewire_capture.py ─────────────────────────────────────────────────
  Captura fluida en Wayland vía PipeWire + xdg-desktop-portal ScreenCast
  (la vía de RustDesk). PortalScreenCast hace el handshake D-Bus
  (CreateSession → SelectSources → Start → OpenPipeWireRemote) bombeando el
  contexto GLib EN EL MISMO HILO (libdbus no es thread-safe con un loop en
  otro hilo). PipeWireBackend tira frames con GStreamer
  (pipewiresrc fd=.. path=.. ! videoconvert ! BGRx ! appsink, drop=true,
  max-buffers=1). BGRx es el formato NATIVO de KWin → videoconvert queda en
  passthrough (forzar RGB convertía el frame completo por software a 30-60
  fps y ralentizaba todo el equipo del alumno). API extra: .grab_raw() →
  (data BGRx, w, h, stride) sin pasar por PIL (vía rápida WebRTC).
  persist_mode=2 → restore_token persistido en
  ~/.config/vigia/screencast.token (1 diálogo por usuario, luego silencioso).
  cursor_mode=2 (embedded) para que el cursor del alumno viaje en el vídeo.
  Deps (apt): python3-gi, python3-dbus, python3-gst-1.0, gstreamer1.0-pipewire,
  gstreamer1.0-plugins-base, gir1.2-gstreamer-1.0, xdg-desktop-portal-kde.
  Ejecutable en solitario para probar: `python3 pipewire_capture.py`.

vigia_input.py ──────────────────────────────────────────────────────
  Inyección de input ABSOLUTO + bloqueo en Wayland (demonio root + cliente).
  Demonio (`python3 vigia_input.py --daemon`, servicio `vigia-input`):
  crea un uinput con ABS_X/ABS_Y (0..32767 → toda la pantalla, mapeo 1:1),
  BTN_LEFT/RIGHT/MIDDLE y REL_WHEEL/HWHEEL. Escucha JSON por líneas en
  /run/vigia-input.sock (0666): {"t":"m","x","y"} mover abs,
  {"t":"b","btn","s"} botón, {"t":"s","dy"} rueda, {"t":"grab","on"} bloquear
  (EVIOCGRAB de los dispositivos físicos del alumno excepto el virtual). El
  grab se libera SOLO si la conexión que lo pidió se cierra (fail-safe).
  Cliente: clase VigiaInput (la usa client.py). Requiere python3-evdev (apt).
  Coordenadas: client.py normaliza x_px/ancho_monitor*32767 antes de enviar.

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
  Socket.IO client + captura screen_capture + Tkinter (ventanas flotantes)
  Hilo daemon unificado `bucle_capturas`: screenshots normales (~1 s);
  frames JPEG HD solo cuando _en_observacion y NOT _webrtc_activo.
  Control remoto: en Wayland ydotool (_YDO_CMD, mapa _YDO_KEY_MAP con
  códigos del kernel); en X11 xdotool (preferido) → pynput (fallback).
  Auto-instala sus dependencias pip al arrancar si faltan.
  _VentanaMensaje: muestra texto enriquecido + archivos adjuntos recibidos.
    Los adjuntos (base64) se guardan en ~/Descargas y se abren con xdg-open.
  WebRTC (opcional, requiere python3-aiortc):
    - Hilo asyncio dedicado (_asyncio_runner / _webrtc_loop).
    - ScreenStreamTrack: captura vía screen_capture en un executor propio de
      1 hilo. Vía rápida: .grab_raw() (PipeWire/mss) entrega BGRx crudo y
      swscale hace escala+conversión a yuv420p en UN paso SIMD
      (frame.reformat con FAST_BILINEAR); el encoder VP8 recibe yuv420p y no
      reconvierte. Los topes de bitrate de aiortc (VP8/H264) se elevan de
      1.5 a 8 Mbps al importar (a 1080p el capado por defecto emborronaba la
      imagen y hundía los fps).
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
  Instala deps de sistema (python3-flask, python3-flask-socketio,
  python3-pil, kde-spectacle) con apt y deps Python puras con pip
  (flask, flask-socketio, simple-websocket, mss). Sin eventlet.
  Crea ~/.local/share/applications/vigia-servidor.desktop con
  Exec apuntando a vigia-launcher.py.
  Crea ~/.config/systemd/user/vigia-servidor.service y lo habilita
  (arranca automáticamente con la sesión del usuario).
  loginctl enable-linger permite arranque sin sesión gráfica activa.

instalar_cliente.sh ────────────────────────────────────────────────
  Instala deps de sistema vía apt (python3-tk, python3-pil[.imagetk],
  python3-pynput, xdotool, ydotool, kde-spectacle, python3-aiortc,
  python3-numpy — las nativas SIEMPRE por apt, nunca pip) y deps
  Python puras con pip (python-socketio[client], websocket-client, mss).
  En Wayland habilita el servicio ydotoold.
  Crea desktop entry en el menú de inicio.
  Crea ~/.config/autostart/vigia-alumno.desktop (XDG autostart).
  Arranca el cliente inmediatamente sin esperar al siguiente reinicio.

test_remote_control.py ─────────────────────────────────────────────
  Suite de tests (unittest) para el control remoto. 55 tests. Ejecutar:
    python3 test_remote_control.py
  Cubre: mapas de teclas xdotool, _procesar_input (ratón + teclado),
  backend ydotool (Wayland), detección de sesión de screen_capture,
  encolado en _input_q, traducción de coordenadas (letterbox/pillarbox),
  enrutamiento DataChannel (_enviarInput). No requiere servidor ni X11.

build_debs.sh ──────────────────────────────────────────────────────
  Script principal de empaquetado. Genera dos .deb en dist/:
  - vigia-server_1.2_amd64.deb  → instala en /opt/vigia-server/
      postinst: recrea el venv (--system-site-packages), instala solo lo
      que falte (wheels puros → red → aviso, nunca aborta), crea desktop
      en /usr/share/applications/ y servicio systemd del usuario real.
  - vigia-client_1.2_all.deb   → instala en /opt/vigia-client/
      usa debconf para preguntar la IP del servidor durante la instalación.
      postinst: idem venv + deps, habilita ydotoold (Wayland), crea
      desktop + XDG autostart, arranca cliente con el entorno de la
      sesión real (DISPLAY/WAYLAND_DISPLAY detectados de /proc).
      prerm: para el cliente y elimina autostart.
  REGLAS CLAVE de empaquetado (Kubuntu 26):
  - Librerías nativas (Pillow, numpy, pynput, aiortc) SIEMPRE por apt
    (Depends); jamás wheels pip (un wheel cp312 no instala en Python
    nuevo y rompía el postinst).
  - Los wheels embebidos son solo py3-none-any (se borran los binarios).
  - WebKit2GTK/chromium/spectacle/ydotool van en Recommends, no Depends,
    para que un rename de paquete no haga el .deb «no instalable».
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
- **`_instalar()` en client.py** detecta si pip falta, lo instala vía `apt-get python3-pip` y hace fallback a `pip3` si `python -m pip` falla. aiortc NO se auto-instala (requiere apt por las libs nativas).
- **Tkinter en client.py** se usa solo para ventanas flotantes (pantalla del profesor, mensajes, bloqueo). Si no está disponible el cliente sigue funcionando pero sin UI.
- **Bloqueo de pantalla** usa `grab_set_global()` de Tkinter (XGrabPointer + XGrabKeyboard) para capturar todos los eventos X11.
- **Backends de control remoto:** en Wayland, ydotool (uinput) es el único que inyecta en todo el escritorio; `_procesar_input` lo usa en exclusiva si `_YDO_CMD` está definido. En X11, xdotool es el backend principal y pynput el fallback automático.
- **Captura en Wayland:** spectacle/grim escriben un PNG por frame (~0,5 s), así que la observación en vivo baja a ~1-3 fps y WebRTC se autorregula a ese ritmo. Las miniaturas de 1 s no se ven afectadas.
- **Coordenadas en modo control WebRTC:** el `<video>` usa `max-width:100%;max-height:100%` (no `width:100%;height:100%`) para que `getBoundingClientRect()` devuelva el área real del contenido, igual que el `<img>`.
- **Adjuntos en mensajes:** el dashboard codifica los archivos en base64 (límite 10 MB total) y los envía junto al mensaje. El cliente los decodifica y guarda en `~/Descargas`, con botón para abrir cada uno con `xdg-open`.
- **IP por defecto del cliente:** `instalar_cliente.sh` auto-detecta la IP local con `ip route get 1.1.1.1` y sustituye el último octeto por `.2` para apuntar al servidor por convención.
- **Web App Manifest.** `server.py` sirve `/manifest.json` con iconos `icon-192.png` e `icon-512.png` para que Chrome muestre el icono de VIGIA en lugar del icono genérico de Chrome en modo `--app`.
- **instalar.sh / instalar.py:** lanzador bash + GUI tkinter que permite elegir servidor/cliente. Usa `PhotoImage.subsample(5,5)` para escalar el logo sin Pillow.

## Dependencies

| Componente | Python (pip, solo puros) | Sistema (apt) |
|---|---|---|
| Servidor | `flask flask-socketio simple-websocket mss` | `python3-flask python3-flask-socketio python3-pil` |
| Cliente | `python-socketio[client] websocket-client mss` | `python3-tk python3-pil python3-pil.imagetk python3-pynput xdotool` |
| Cliente (WebRTC) | — | `python3-aiortc python3-numpy` |
| Cliente (Wayland) | — | `ydotool` + `kde-spectacle`/`grim`/`gnome-screenshot` |
| Ventana nativa fallback (profesor) | — | `python3-gi gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0 libgtk-3-0` |

Regla general: **cualquier librería con extensión nativa va por apt**; pip solo
para paquetes Python puros (sus wheels `py3-none-any` valen en cualquier Python).

## Packaging

```bash
bash build_debs.sh   # genera dist/vigia-server_1.2_amd64.deb y vigia-client_1.2_all.deb

# Instalar
sudo apt install ./dist/vigia-server_1.2_amd64.deb
sudo apt install ./dist/vigia-client_1.2_all.deb

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

Esto garantiza que `dist/vigia-server_1.2_amd64.deb` y `dist/vigia-client_1.2_all.deb` estén siempre sincronizados con el código fuente.

### Qué cambios afectan a qué paquete

| Archivo/componente modificado | Paquete a regenerar |
|---|---|
| `server.py`, `vigia-launcher.py`, `templates/`, `instalar_servidor.sh`, `img/` | `vigia-server_1.2_amd64.deb` |
| `client.py`, `vigia_overlay.py`, `vigia_input.py`, `instalar_cliente.sh` | `vigia-client_1.2_all.deb` |
| `platform_utils.py`, `screen_capture.py`, `pipewire_capture.py` o cualquier cambio global | **Ambos** paquetes |

> Nunca entregar ni documentar un cambio sin haber ejecutado `bash build_debs.sh` y verificado que los `.deb` de `dist/` se han actualizado correctamente.
