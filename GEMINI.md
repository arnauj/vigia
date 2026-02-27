# VIGIA - Classroom Monitoring System

VIGIA (Vigilancia e Integración para la Gestión Inteligente de Aulas) is a real-time classroom monitoring tool that allows teachers to view and control students' screens within a local network. It is inspired by tools like Epoptes and is designed to work on Linux environments (specifically Ubuntu/Kubuntu).

## Project Architecture

- **Server (`server.py`):** A Flask and Flask-SocketIO application that runs on the teacher's computer. It provides a web-based dashboard (`templates/dashboard.html`) to monitor all connected students.
- **Client (`client.py`):** A Python application that runs on each student's computer. It captures the screen and sends it to the server via Socket.IO. It also handles remote control commands, messages, and screen locking.

## Key Technologies

- **Python 3.10+**
- **Web Framework:** Flask, Flask-SocketIO (Server)
- **Real-time Communication:** Socket.IO (Server & Client)
- **Screen Capture:** `mss` (Requires X11 session; Wayland is not supported for capture)
- **Image Processing:** `Pillow` (PIL)
- **GUI Components:** `tkinter` (Client-side messages, screen locking, and teacher screen view)
- **Remote Control:** `xdotool` (preferred) or `pynput` (fallback)

## Environment Requirements

- **Operating System:** Ubuntu/Kubuntu 22.04 or 24.04 recommended.
- **Graphic Session:** **X11 is mandatory** for screen capture. Verify with `echo $XDG_SESSION_TYPE`.
- **Network:** All devices must be on the same local network. The server uses port **5000 (TCP)** by default.

## Building and Running

### Server (Teacher)
1. **Install dependencies:**
   ```bash
   sudo apt update && sudo apt install python3-pip
   pip3 install flask flask-socketio --break-system-packages
   ```
   Or use the provided script:
   ```bash
   bash instalar_servidor.sh
   ```
2. **Run the server:**
   ```bash
   python3 server.py
   ```
   The dashboard will be available at `http://localhost:5000`.

### Client (Student)
1. **Install dependencies:**
   ```bash
   sudo apt update && sudo apt install python3-pip python3-tk xdotool
   pip3 install "python-socketio[client]" websocket-client mss Pillow --break-system-packages
   ```
   Or use the provided script (recommended):
   ```bash
   bash instalar_cliente.sh <TEACHER_IP>
   ```
2. **Run the client:**
   ```bash
   python3 client.py <TEACHER_IP>
   ```

## Development Conventions

- **Real-time Events:** All interactions (screenshots, locking, messaging, remote control) are handled via Socket.IO events.
- **Threading:** The client uses daemon threads for background tasks (connection management and screen capture) to keep the main thread responsive for Tkinter UI updates.
- **UI Management:** The student client uses a hidden `tkinter` root window to manage multiple `Toplevel` windows for messages, screen locking, and viewing the teacher's screen.
- **Screen Capture Fallback:** If `mss` fails, the client attempts to use `scrot` as a fallback.
- **Dependency Management:** The client includes an "amigable" auto-installer that attempts to fix missing dependencies at runtime, although manual installation via `apt` or `pip` is preferred for stability.
- **Security:** The communication is intended for local networks only. No encryption is implemented for the screen stream by default.

## Key Files

- `server.py`: Main server entry point and Socket.IO event handlers.
- `client.py`: Student client implementation, including capture loop and UI handlers.
- `templates/dashboard.html`: The teacher's control panel (HTML/JS).
- `instalar_servidor.sh` / `instalar_cliente.sh`: Bash scripts for automated environment setup.
- `requirements_*.txt`: Lists of Python dependencies for each component.
