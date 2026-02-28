# VIGIA - Classroom Monitoring System

VIGIA (Vigilancia e Integración para la Gestión Inteligente de Aulas) is a real-time classroom monitoring tool that allows teachers to view and control students' screens within a local network. It is inspired by tools like Epoptes and is designed to work on Linux environments (specifically Ubuntu/Kubuntu).

## Project Architecture

- **Server (`server.py`):** A Flask and Flask-SocketIO application that runs on the teacher's computer. It provides a web-based dashboard (`templates/dashboard.html`) to monitor all connected students. It also relays WebRTC signaling messages (offer/answer/ICE) between the dashboard and each student client using the existing `viewers` dict for authorization.
- **Client (`client.py`):** A Python application that runs on each student's computer. It captures the screen and sends it to the server via Socket.IO (JPEG fallback). When `python3-aiortc` is available, it streams video directly to the teacher's browser via WebRTC P2P (H.264/VP9, UDP) and receives input events through a WebRTC DataChannel. It also handles remote control commands, messages, and screen locking.
- **Dashboard (`templates/dashboard.html`):** Vanilla JS SPA with Socket.IO 4.x and Bootstrap 5, all via CDN. No build step — edit directly.

## Key Technologies

- **Python 3.10+**
- **Web Framework:** Flask, Flask-SocketIO (Server)
- **Real-time Communication:** Socket.IO (signaling, fallback JPEG transport)
- **WebRTC (optional):** `aiortc` (client-side), browser `RTCPeerConnection` (dashboard). P2P video stream + DataChannel for input. Requires `python3-aiortc python3-numpy` via apt on the student machine.
- **Screen Capture:** `mss` (Requires X11 session; Wayland is not supported)
- **Image Processing:** `Pillow` (PIL), `numpy` (WebRTC frame conversion)
- **GUI Components:** `tkinter` (Client-side messages, screen locking, and teacher screen view)
- **Remote Control:** `xdotool` (preferred, X11) or `pynput` (fallback)

## Environment Requirements

- **Operating System:** Ubuntu/Kubuntu 22.04 or 24.04 recommended.
- **Graphic Session:** **X11 is mandatory** for screen capture. Verify with `echo $XDG_SESSION_TYPE`. Wayland is not supported by `mss`.
- **Network:** All devices must be on the same local network. The server uses port **5000 (TCP)**. WebRTC uses ephemeral UDP ports for P2P streams. AP isolation on WiFi will block WebRTC P2P (JPEG fallback still works).

## Building and Running

### Server (Teacher)
```bash
bash instalar_servidor.sh
# or manually:
pip3 install flask flask-socketio --break-system-packages
python3 server.py
```
Dashboard at `http://localhost:5000`.

### Client (Student)
```bash
bash instalar_cliente.sh <TEACHER_IP>
# or manually:
sudo apt install python3-pip python3-tk xdotool python3-aiortc python3-numpy
pip3 install "python-socketio[client]" websocket-client mss Pillow --break-system-packages
python3 client.py <TEACHER_IP>
```

`python3-aiortc` is optional. Without it, the client falls back to JPEG-over-Socket.IO automatically.

## Socket.IO Event Flow

| Event | Direction | Description |
|---|---|---|
| `register` | client → server | Student announces with name |
| `screenshot` | client → server | JPEG base64 every ~1 s |
| `update_screenshot` | server → dashboard | Broadcast screenshot |
| `start_view` / `stop_view` | dashboard → server | Start/stop remote viewing |
| `viewer_start` / `viewer_stop` | server → client | Notify student |
| `remote_frame` | client → server | HD JPEG frame (JPEG fallback only) |
| `live_frame` | server → dashboard | Relay HD frame (JPEG fallback only) |
| `remote_input` | dashboard → server → client | Mouse/keyboard events (Socket.IO fallback) |
| `lock_screen` / `unlock_screen` | server → client | X11 global grab |
| `show_message` | server → client | Rich HTML popup |
| `teacher_screenshot` | dashboard → server → clients | Share teacher screen |
| `webrtc_offer` | dashboard → server → client | SDP offer for WebRTC |
| `webrtc_answer` | client → server → dashboard | SDP answer for WebRTC |
| `webrtc_ice` | bidirectional via server | ICE candidates |

After signaling, the WebRTC stream is **P2P** (does not pass through the server):
- **Video:** client → dashboard (H.264/VP9, UDP)
- **Input events:** dashboard → client (RTCDataChannel, unordered UDP)

## Development Conventions

- **No database.** All state lives in the `students` and `viewers` dicts in `server.py`. State is lost on server restart.
- **WebRTC P2P transport.** When `aiortc` is available, video travels client→browser directly over UDP. Input events go through an unordered DataChannel (`maxRetransmits:0`) for minimum latency. `_enviarInput()` in the dashboard automatically picks DataChannel or Socket.IO based on `_dc?.readyState`.
- **`_webrtcActivo` flag.** Set to `true` on the dashboard side when the video track arrives (`ontrack`), for both view and control modes. This suppresses the 8s JPEG fallback timer and switches coordinate translation to use the `<video>` element's bounding rect.
- **Video element sizing.** The `<video>` uses `max-width:100%;max-height:100%` (not `width:100%;height:100%`) so that `getBoundingClientRect()` returns the actual rendered content area, enabling correct mouse coordinate translation.
- **`_webrtc_activo` in client.** Set to `True` when ICE connects. Suppresses JPEG frame sending in `bucle_capturas` (`if _en_observacion and not _webrtc_activo`).
- **Asyncio thread.** The client runs a dedicated asyncio event loop (`_asyncio_runner`) in a daemon thread for `aiortc`. All coroutines are submitted from sync threads via `asyncio.run_coroutine_threadsafe`.
- **`ScreenStreamTrack`.** Captures screen with `mss` in a thread pool executor (non-blocking), converts BGRA→RGB with numpy, scales to max 1920px wide, returns `av.VideoFrame` at 15 fps.
- **Threading model:** The client uses daemon threads for connection, capture loop, and asyncio (WebRTC). The main thread runs Tkinter if available.
- **JPEG fallback.** If WebRTC is not available or fails within 8s, the dashboard automatically switches back to displaying JPEG frames from `live_frame` Socket.IO events.
- **Security:** Communication is intended for local networks only. No encryption on the stream.

## Key Files

- `server.py`: Server entry point, Socket.IO event handlers, WebRTC signaling relay.
- `client.py`: Student client — capture loop, WebRTC (aiortc), UI handlers.
- `templates/dashboard.html`: Teacher's control panel (HTML/JS, WebRTC peer).
- `instalar_servidor.sh` / `instalar_cliente.sh`: Automated environment setup scripts.
