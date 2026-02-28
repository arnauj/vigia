# VIGIA
### Vigilancia e Integración para la Gestión Inteligente de Aulas

Software de monitoreo de aula para ver en tiempo real las pantallas de los alumnos desde el equipo del profesor. Inspirado en Epoptes.

---

## Cómo funciona

```
[Alumno 1] ─┐
[Alumno 2] ─┤──► Servidor (profesor) ──► Navegador web con cuadrícula de pantallas
[Alumno 3] ─┘
```

- El **servidor** corre en el equipo del profesor y muestra un panel web.
- El **cliente** corre en cada equipo de alumno y envía capturas de pantalla cada ~2 segundos.
- Todo ocurre dentro de la red local (no necesita internet).

---

## Funcionalidades

- **Cuadrícula de pantallas** — vista en tiempo real de todos los alumnos conectados.
- **Observación remota** — el profesor puede ver la pantalla de un alumno en alta resolución.
- **Control remoto** — el profesor puede manejar el ratón y teclado del alumno.
- **Control remoto WebRTC** — stream de vídeo H.264/VP9 directo P2P (UDP) con latencia < 150 ms en LAN. Los eventos de ratón y teclado se envían por un DataChannel WebRTC (también UDP, sin pasar por el servidor). Fallback automático a JPEG+Socket.IO si WebRTC no está disponible.
- **Bloqueo de pantalla** — bloquea el teclado y ratón del alumno con un overlay.
- **Mensajes** — el profesor puede enviar mensajes emergentes a uno o todos los alumnos.
- **Pantalla del profesor** — comparte la pantalla del profesor en una ventana flotante en todos los alumnos.

---

## Requisitos del sistema

### Sistema operativo
- **Kubuntu 22.04 / 24.04** (o cualquier Ubuntu/Debian moderno)
- Python 3.10 o superior (viene instalado por defecto)

### Sesión gráfica
> ⚠️ **IMPORTANTE — Wayland vs X11**
>
> La captura de pantalla (`mss`) **solo funciona en sesión X11**.
> En Kubuntu 24.04 con KDE Plasma 6, el inicio de sesión por defecto puede ser Wayland.
>
> **Cómo verificar tu sesión:**
> ```bash
> echo $XDG_SESSION_TYPE
> ```
> Si muestra `wayland`, debes cambiar a X11:
> 1. Cierra sesión.
> 2. En la pantalla de login, haz clic en el icono de sesión (esquina inferior).
> 3. Selecciona **"Plasma (X11)"**.
> 4. Inicia sesión normalmente.
>
> En Kubuntu 22.04 la sesión es X11 por defecto, sin problemas.

---

## Instalación — Equipo del profesor (servidor)

### Opción 1: script automático (recomendado)

```bash
bash instalar_servidor.sh
```

Instala las dependencias y crea un acceso directo en el Escritorio.

### Opción 2: manual

```bash
sudo apt install python3-pip
pip3 install flask flask-socketio
```

> Si `pip3` da error de "externally-managed-environment":
> ```bash
> pip3 install --break-system-packages flask flask-socketio
> ```

---

## Instalación — Equipos de los alumnos (cliente)

### Opción 1: script automático (recomendado)

```bash
bash instalar_cliente.sh 192.168.X.X
```

Sustituye `192.168.X.X` por la **IP del equipo del profesor**.
El script instala todo (incluido WebRTC) y crea un acceso directo en el Escritorio.

### Opción 2: manual

```bash
sudo apt install python3-pip python3-tk xdotool python3-aiortc python3-numpy
pip3 install "python-socketio[client]" websocket-client mss Pillow
```

> `python3-aiortc` instala automáticamente las dependencias de WebRTC del sistema:
> `python3-av`, `python3-aioice`, `libopus0`, `libvpx9`, `python3-pylibsrtp`, etc.
>
> Sin `python3-aiortc`, el control remoto funciona igualmente en modo JPEG (fallback automático).

---

## Uso

### 1. Averigua la IP del equipo del profesor

```bash
ip a | grep "inet " | grep -v 127
```

Anota la IP de tu red local, por ejemplo `192.168.0.119`.

### 2. Inicia el servidor (equipo del profesor)

```bash
python3 server.py
```

Se abre el navegador automáticamente con el panel en `http://localhost:5000`.

### 3. Inicia el cliente (cada equipo de alumno)

```bash
python3 client.py 192.168.0.119
```

O, si se instaló con el script, el alumno hace **doble clic** en `VIGIA (Alumno)` del Escritorio.

### 4. Observar / controlar un alumno

En el panel del profesor, cada tarjeta de alumno tiene dos botones:

| Botón | Acción |
|---|---|
| 👁 | Abre la pantalla del alumno en modo **solo ver** (WebRTC si está disponible, JPEG si no) |
| 🖱 | Abre la pantalla en modo **control remoto** (ratón y teclado desde el navegador) |

El badge en la esquina superior del visor indica el transporte activo:
- **WebRTC P2P** (verde) — stream de vídeo directo, baja latencia
- **JPEG** (gris) — frames JPEG por Socket.IO, fallback automático

---

## Control remoto WebRTC

Cuando `python3-aiortc` está instalado en el cliente, el control remoto usa WebRTC:

```
T=0ms   Clic "👁 Ver" en el panel
T=30ms  Intercambio de señalización (offer/answer/ICE) vía Socket.IO
T=100ms ICE conectado — stream P2P establecido por UDP en la LAN
T=120ms Vídeo H.264/VP9 en tiempo real, DataChannel abierto para el input
```

**Ventajas frente al modo JPEG:**
- Vídeo codificado (H.264/VP9) con adaptación automática de bitrate
- Stream de vídeo por UDP directo alumno→profesor (sin pasar por el servidor)
- Eventos de ratón/teclado por DataChannel WebRTC (UDP, `maxRetransmits:0`) en modo 🖱, también sin pasar por el servidor
- Latencia típica < 150 ms en LAN frente a 500–1000 ms con JPEG

**Fallback automático:** si WebRTC no se establece en 8 segundos (o si `aiortc` no está instalado), el visor cambia automáticamente a JPEG+Socket.IO sin intervención del usuario.

---

## Red y firewall

El servidor escucha en el **puerto 5000 TCP** (señalización Socket.IO + dashboard).
WebRTC usa puertos UDP efímeros para el stream P2P directo entre equipos.

```bash
# Abrir el puerto del servidor si hay firewall
sudo ufw allow 5000/tcp
```

Todos los equipos deben estar en la **misma red local**. Si la WiFi del aula tiene aislamiento de clientes (AP isolation), el stream WebRTC P2P no funcionará — el fallback JPEG seguirá operativo ya que pasa por el servidor.

---

## Resumen de paquetes

| Paquete | Quién lo necesita | Cómo instalarlo |
|---|---|---|
| `python3` | Todos | Ya instalado en Kubuntu |
| `python3-pip` | Todos | `sudo apt install python3-pip` |
| `flask` | Solo profesor | `pip3 install flask` |
| `flask-socketio` | Solo profesor | `pip3 install flask-socketio` |
| `python3-tk` | Solo alumnos | `sudo apt install python3-tk` |
| `xdotool` | Solo alumnos | `sudo apt install xdotool` |
| `python-socketio[client]` | Solo alumnos | `pip3 install "python-socketio[client]"` |
| `websocket-client` | Solo alumnos | `pip3 install websocket-client` |
| `mss` | Solo alumnos | `pip3 install mss` |
| `Pillow` | Solo alumnos | `pip3 install Pillow` |
| `python3-aiortc` | Solo alumnos (WebRTC) | `sudo apt install python3-aiortc` |
| `python3-numpy` | Solo alumnos (WebRTC) | `sudo apt install python3-numpy` |

---

## Solución de problemas

**"No module named pip"**
pip no está instalado. Ejecuta: `sudo apt install python3-pip`

**"externally-managed-environment"**
Ubuntu 24.04 protege los paquetes del sistema. Añade `--break-system-packages`:
`pip3 install --break-system-packages <paquete>`

**La pantalla del alumno no aparece / pantalla negra**
- Comprueba que la sesión es X11: `echo $XDG_SESSION_TYPE`
- Si muestra `wayland`, cierra sesión y selecciona "Plasma (X11)" al entrar.

**El visor siempre muestra "JPEG" en lugar de "WebRTC P2P"**
- Comprueba que `python3-aiortc` está instalado en el equipo del alumno: `python3 -c "import aiortc; print('ok')"`
- Comprueba que la red no tiene AP isolation (aislamiento de clientes WiFi).
- Revisa la consola del navegador para ver el motivo del fallback.

**El alumno no consigue conectar**
- Verifica que el servidor está en marcha en el equipo del profesor.
- Comprueba que la IP es correcta.
- Comprueba que están en la misma red.
- Abre el puerto: `sudo ufw allow 5000/tcp`

**El cliente se desconecta constantemente**
Puede ser que la WiFi del aula tenga aislamiento de clientes (AP isolation). Habla con el administrador de red para desactivarlo, o usa cable ethernet.

---

## Estructura de archivos

```
VIGIA/
├── server.py               ← Servidor del profesor
├── client.py               ← Cliente del alumno
├── templates/
│   └── dashboard.html      ← Panel web del profesor
├── instalar_servidor.sh    ← Script de instalación (profesor)
├── instalar_cliente.sh     ← Script de instalación (alumnos)
└── README.md               ← Este archivo
```
