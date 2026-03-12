# AGENTS.md

Este archivo guía a AGENTS Code (AGENTS.ai/code) al trabajar en este repositorio.

## Qué es VIGIA

Software de monitoreo de aulas para Linux (Kubuntu/Ubuntu). El profesor ejecuta un servidor Flask que muestra una cuadrícula en vivo de pantallas. El panel del profesor se abre como **ventana nativa** mediante `vigia-launcher.py` (Chrome/Chromium `--app` como primera opción, GTK+WebKit2GTK como fallback). Cada alumno ejecuta `client.py`, que captura pantalla y la transmite al servidor.

**Restricción crítica:** solo funciona en sesiones X11. La librería `mss` no soporta Wayland.

## Ejecución

```bash
# Servidor — lanzador nativo (Chrome --app → WebKit2GTK → navegador)
python3 vigia-launcher.py [puerto]

# Servidor — solo Flask (sin ventana)
python3 server.py [puerto]

# Cliente (alumno)
python3 client.py [ip_servidor] [puerto]
```

## Instalación y empaquetado

```bash
bash instalar.sh                               # Instalador gráfico tkinter (servidor o cliente)
bash instalar_servidor.sh                      # Deps + desktop + systemd user (profesor)
bash instalar_cliente.sh [IP_DEL_SERVIDOR]     # Deps + desktop + autostart (alumno)
bash build_debs.sh                             # Genera ambos .deb en dist/
```

Paquetes resultantes:
- `dist/vigia-server_1.1_amd64.deb` (servidor/profesor)
- `dist/vigia-client_1.1_all.deb` (cliente/alumno)

## Arquitectura y componentes

```
server.py
  Flask + Flask-SocketIO (eventlet/threading), puerto 5000.
  Estado en memoria: students / viewers. Señalización WebRTC.
  /manifest.json (PWA) y /img/<archivo> (iconos).
  Reenvía eventos de control, clipboard y comandos remotos.

vigia-launcher.py
  Ventana nativa: Chrome/Chromium --app → GTK+WebKit2GTK → navegador.
  Perfil temporal aislado para Chrome. Reutiliza Flask si ya corre (1.5 s).
  Desactiva GPU en WebKit2GTK para evitar pantalla negra en KWin.

templates/dashboard.html
  SPA sin build (JS vanilla + Socket.IO 4.x + Bootstrap 5 por CDN).
  WebRTC P2P con RTCPeerConnection + 2 DataChannels (mouse/keyboard).
  Fallback JPEG por Socket.IO cuando WebRTC falla/no está disponible.
  Incluye terminal remota, gestión de mensajes con adjuntos,
  clipboard remoto y pizarra/overlay de dibujo.

client.py
  Socket.IO client + mss + Tkinter (ventanas flotantes).
  Control remoto: xdotool (X11) → pynput (fallback).
  WebRTC opcional con python3-aiortc (asyncio thread).
  Terminal remota: ejecuta comandos y mantiene cwd del profesor.
  Clipboard remoto: obtiene portapapeles vía xclip/xsel.
  Pizarra overlay: subproceso GTK externo (vigia_overlay.py).

vigia_overlay.py
  Overlay transparente GTK+Cairo con click-through (XFixes).
  Recibe comandos JSON por stdin: toggle, draw, text, clear.

instalar.py
  GUI tkinter con selector Servidor/Cliente, muestra log en tiempo real.
  Logo escalado con PhotoImage.subsample (sin Pillow).

instalar_servidor.sh / instalar_cliente.sh
  Instalan deps y crean accesos directos + systemd (servidor) o autostart (cliente).

test_remote_control.py
  39 tests unittest para mapeo de teclas, input y traducción de coordenadas.

test_client.py
  Cliente mínimo de prueba para registro Socket.IO.

requirements_servidor.txt / requirements_cliente.txt
  Listas de paquetes pip (si existen).

build_deb.sh
  Script legacy para un único .deb del servidor.
  El flujo principal actual usa build_debs.sh (dos paquetes separados).
```

## Flujo Socket.IO (resumen)

| Evento | Dirección | Descripción |
|---|---|---|
| `register` | cliente → servidor | Alumno se anuncia con nombre |
| `screenshot` | cliente → servidor | JPEG base64 cada ~1 s |
| `update_screenshot` | servidor → dashboard | Retransmisión del screenshot |
| `start_view` / `stop_view` | dashboard → servidor | Iniciar/parar observación |
| `viewer_start` / `viewer_stop` | servidor → cliente | Notificación al alumno |
| `remote_frame` / `live_frame` | cliente ↔ servidor ↔ dashboard | Fallback JPEG HD |
| `remote_input` / `do_input` | dashboard ↔ servidor ↔ cliente | Ratón/teclado + overlay |
| `lock_screen` / `unlock_screen` | servidor → cliente | Bloqueo de pantalla X11 |
| `show_message` | servidor → cliente | Popup HTML + adjuntos |
| `send_message` / `send_message_to` / `send_message_to_many` | dashboard → servidor | Enviar mensajes |
| `teacher_screenshot` / `teacher_screen` | dashboard ↔ servidor ↔ clientes | Pantalla del profesor |
| `run_command` / `exec_command` / `command_output` / `command_result` | dashboard ↔ servidor ↔ cliente | Terminal remota |
| `get_clipboard` / `clipboard_data` | dashboard ↔ servidor ↔ cliente | Portapapeles remoto |
| `webrtc_offer` / `webrtc_answer` / `webrtc_ice` | bidireccional vía servidor | Señalización WebRTC |

## Detalles clave

- **Sin base de datos.** Estado en memoria (`students` y `viewers`).
- **JPEG como fallback.** Base64 máx. 8 MB cuando WebRTC no está activo.
- **WebRTC P2P.** Video UDP (H.264/VP9) si `python3-aiortc` está instalado.
- **DataChannels separados.** `vigia-mouse` (unordered) y `vigia-input` (ordered).
- **Pizarra/overlay.** Dibujo en cliente vía `vigia_overlay.py` (GTK+Cairo).
- **Terminal remota.** `exec_command` en cliente con cwd persistente, devuelve stdout/stderr.
- **Portapapeles remoto.** Usa `xclip` o `xsel` en el cliente.
- **Chrome --app prioritario.** Perfil temporal y `--class=vigia` para icono KDE.
- **WebKit2GTK sin GPU.** Variables `WEBKIT_DISABLE_DMABUF_RENDERER`,
  `WEBKIT_DISABLE_COMPOSITING_MODE`, `LIBGL_ALWAYS_SOFTWARE` antes de GTK.
- **instalar_servidor.sh** siempre usa `vigia-launcher.py`.

## Dependencias

| Componente | Python (pip) | Sistema (apt) |
|---|---|---|
| Servidor | `flask flask-socketio eventlet` | — |
| Cliente | `python-socketio[client] websocket-client mss Pillow` | `python3-tk xdotool` |
| Cliente WebRTC | — | `python3-aiortc python3-numpy` |
| Ventana nativa fallback | — | `python3-gi gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0 libgtk-3-0` |

## Tests

```bash
python3 test_remote_control.py
python3 test_client.py
```

## REGLA OBLIGATORIA: último paso = regenerar los .deb

**Al finalizar cualquier tarea, el ÚLTIMO paso siempre debe ser ejecutar `./build_debs.sh` desde la raíz del repo para regenerar los paquetes `.deb` en `./dist/`:**

```bash
./build_debs.sh
```

### Qué cambios afectan a qué paquete

| Archivo/componente modificado | Paquete a regenerar |
|---|---|
| `server.py`, `vigia-launcher.py`, `templates/`, `instalar_servidor.sh`, `img/` | `vigia-server_1.1_amd64.deb` |
| `client.py`, `instalar_cliente.sh`, `vigia_overlay.py` | `vigia-client_1.1_all.deb` |
| Cualquier archivo compartido o cambio global | **Ambos** paquetes |

> Nunca entregar ni documentar un cambio sin haber ejecutado `./build_debs.sh` y verificado que los `.deb` de `dist/` se han actualizado correctamente.
