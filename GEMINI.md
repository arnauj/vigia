# GEMINI.md

This file provides guidance to Gemini CLI when working with code in this repository.

## What is VIGIA

Classroom monitoring software for Linux (Kubuntu/Ubuntu). The teacher runs a Flask server that displays a live grid of student screens in a native desktop window. The window is opened by `vigia-launcher.py`, which prefers Chrome/Chromium in `--app` mode and falls back to GTK+WebKit2GTK (with GPU disabled). Each student runs `client.py`, which captures the screen and streams it to the server. Inspired by Epoptes.

**Critical constraint:** Only works under X11 sessions. The `mss` screen-capture library does not support Wayland.

## Running the application

```bash
# Teacher (server + native window)
python3 vigia-launcher.py [port]

# Teacher (server only, no window)
python3 server.py [port]

# Student (client)
python3 client.py [server_ip] [port]
```

## Installation

```bash
# Recommended — .deb packages (dist/ folder)
sudo apt install ./dist/vigia-server_1.1_amd64.deb   # teacher machine
sudo apt install ./dist/vigia-client_1.1_all.deb      # student machines (asks for server IP)

# Alternative — shell scripts
bash instalar_servidor.sh                  # teacher: deps + desktop shortcut + systemd autostart
bash instalar_cliente.sh [server_ip]       # student: deps + desktop shortcut + XDG autostart

# Build packages from source
bash build_debs.sh                         # produces both .deb files in dist/
```

## Architecture overview

```
server.py           Flask + Flask-SocketIO, port 5000.
                    In-memory state: students dict, viewers dict.
                    Relays WebRTC signaling (offer/answer/ICE).
                    Serves /manifest.json (PWA) and /img/<file> (icons).

vigia-launcher.py   Native window launcher (teacher side).
                    Priority: Chrome/Chromium --app → GTK+WebKit2GTK → system browser.
                    Detects if Flask is already running (reuses it, does not kill on close).
                    GPU vars set before GTK import to avoid black screen on KWin.

templates/dashboard.html
                    Single-page app: JS vanilla + Socket.IO 4.x + Bootstrap 5 (CDN).
                    No build step. Edit the file directly.
                    WebRTC via RTCPeerConnection + DataChannel 'vigia-input'.

client.py           Socket.IO client + mss capture + Tkinter (floating windows).
                    Unified daemon thread `bucle_capturas` for screenshots.
                    Remote control: xdotool (primary) → pynput (fallback).
                    Optional WebRTC via python3-aiortc (asyncio thread + ScreenStreamTrack).

instalar_servidor.sh
                    Installs Python deps, creates desktop entry pointing to vigia-launcher.py,
                    creates and enables ~/.config/systemd/user/vigia-servidor.service.

instalar_cliente.sh
                    Installs Python + system deps, creates desktop entry,
                    creates ~/.config/autostart/vigia-alumno.desktop,
                    starts client immediately without waiting for reboot.

build_debs.sh       Builds vigia-server_1.1_amd64.deb and vigia-client_1.1_all.deb.
                    Server postinst: pip deps + /usr/share/applications desktop + systemd service.
                    Client postinst: debconf for server IP + pip deps + desktop + XDG autostart.
```

## Key facts to keep in mind

- **No database.** All state lives in `students` and `viewers` dicts in `server.py`. Restarting the server clears all connected clients.
- **JPEG over Socket.IO is the fallback.** Frames are base64-encoded (max 8 MB). WebRTC P2P (H.264/VP9 over UDP) is used when `python3-aiortc` is installed on the client.
- **WebRTC fallback timeout:** 8 seconds. If ICE does not connect, the viewer switches automatically to JPEG mode.
- **Chrome --app is the preferred UI.** It supports `getDisplayMedia()` natively and avoids GPU/KWin conflicts. An isolated temporary profile is used so it does not interfere with the user's Chrome.
- **WebKit2GTK GPU must be disabled** (`WEBKIT_DISABLE_DMABUF_RENDERER=1`, `WEBKIT_DISABLE_COMPOSITING_MODE=1`, `LIBGL_ALWAYS_SOFTWARE=1`) before initializing GTK; otherwise KWin/KDE deadlocks the compositor causing a black screen.
- **`instalar_servidor.sh` always uses `vigia-launcher.py`**, never the Tauri binary, even if it exists.
- **Tkinter in client.py** is used only for floating windows (messages, lock screen, teacher screen). The client works without it but has no UI.
- **xdotool** is the primary remote-control backend; `pynput` is the automatic fallback if xdotool is not installed.
- **Attachments in messages** are base64-encoded (10 MB total limit), sent with `show_message`, saved to `~/Descargas` on the student machine, and opened with `xdg-open`.
- **Default server IP for clients:** last octet replaced with `.2` (detected via `ip route get 1.1.1.1`).

## Socket.IO events (summary)

| Event | Direction | Purpose |
|---|---|---|
| `register` | client → server | Student announces itself |
| `screenshot` | client → server | JPEG thumbnail every ~1 s |
| `update_screenshot` | server → dashboard | Relay thumbnail |
| `start_view` / `stop_view` | dashboard → server | Start/stop remote view |
| `viewer_start` / `viewer_stop` | server → client | Notify student |
| `remote_frame` / `live_frame` | client ↔ server ↔ dashboard | HD JPEG fallback stream |
| `remote_input` | dashboard → server → client | Mouse/keyboard fallback |
| `lock_screen` / `unlock_screen` | server → client | X11 grab/ungrab |
| `show_message` | server → client | Popup with HTML + attachments |
| `send_message` / `send_message_to` | dashboard → server | Send to all / one student |
| `teacher_screenshot` | dashboard → server → clients | Share teacher screen |
| `webrtc_offer` / `webrtc_answer` / `webrtc_ice` | bidirectional via server | WebRTC signaling |

## Dependencies

| Component | Python packages | System (apt) |
|---|---|---|
| Server | `flask flask-socketio eventlet` | — |
| Client | `python-socketio[client] websocket-client mss Pillow` | `python3-tk xdotool` |
| Client WebRTC | — | `python3-aiortc python3-numpy` |
| Native window fallback | — | `python3-gi gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0 libgtk-3-0` |
