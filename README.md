# VIGIA
### Vigilancia e Integración para la Gestión Inteligente de Aulas

Software de monitoreo de aula para ver en tiempo real las pantallas de los alumnos desde el equipo del profesor. Inspirado en Epoptes.

---

## Descargas

Los paquetes `.deb` listos para instalar están en la carpeta `dist/` de este repositorio:

| Paquete | Destinatario | Archivo |
|---|---|---|
| **VIGIA Servidor** | Equipo del profesor | [`dist/vigia-server_1.1_amd64.deb`](dist/vigia-server_1.1_amd64.deb) |
| **VIGIA Cliente** | Equipos de los alumnos | [`dist/vigia-client_1.1_all.deb`](dist/vigia-client_1.1_all.deb) |

> Los paquetes se regeneran automáticamente con `bash build_debs.sh` cada vez que se actualiza el código fuente.

---

## Instalación rápida

VIGIA se distribuye en dos paquetes `.deb` separados: uno para el profesor y otro para los alumnos.

### Equipo del profesor (servidor)

```bash
sudo apt install ./vigia-server_1.1_amd64.deb
```

Al terminar, aparece **VIGIA Servidor** en el menú de inicio. El servidor arranca automáticamente al iniciar sesión (systemd de usuario).

### Equipos de los alumnos (cliente)

```bash
sudo apt install ./vigia-client_1.1_all.deb
```

Durante la instalación **se pedirá la IP del servidor** (por defecto se sugiere `x.x.x.2` detectada automáticamente). El cliente arranca solo al iniciar sesión (XDG autostart).

> Los paquetes `.deb` están en la carpeta [`dist/`](dist/) del repositorio. Consulta la sección [Descargas](#descargas) al inicio de este documento.

---

## Instalación alternativa (sin .deb)

### Servidor — scripts de línea de comandos

```bash
bash instalar_servidor.sh          # instala deps Python + acceso directo + autostart systemd
```

O de forma completamente manual:

```bash
sudo apt install python3-pip python3-gi gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0
pip3 install --break-system-packages flask flask-socketio eventlet
python3 vigia-launcher.py          # lanza el servidor con ventana nativa
```

### Cliente — scripts de línea de comandos

```bash
bash instalar_cliente.sh                  # IP del servidor auto-detectada como x.x.x.2
bash instalar_cliente.sh 192.168.X.X      # o especifica la IP manualmente
```

O de forma completamente manual:

```bash
sudo apt install python3-pip python3-tk xdotool python3-aiortc python3-numpy
pip3 install --break-system-packages "python-socketio[client]" websocket-client mss Pillow
python3 client.py 192.168.X.X
```

### Instalador gráfico (alternativa)

```bash
bash instalar.sh
```

Abre una ventana tkinter donde elegir Servidor o Cliente y pulsar *Instalar*.

---

## Cómo funciona

```
[Alumno 1] ─┐
[Alumno 2] ─┤──► Servidor Flask (profesor) ──► Ventana VIGIA (Chrome --app o GTK)
[Alumno 3] ─┘
```

- El **servidor** corre en el equipo del profesor y muestra el panel en una ventana nativa. El lanzador (`vigia-launcher.py`) intenta primero abrir Chrome/Chromium en modo `--app` (sin barra de herramientas); si no está disponible, usa GTK + WebKit2GTK con GPU desactivado; como último recurso abre el navegador del sistema.
- El **cliente** corre en cada equipo de alumno, captura la pantalla y la envía al servidor.
- Todo ocurre dentro de la red local (no necesita internet).

---

## Generar los paquetes .deb

```bash
bash build_debs.sh
```

Genera en `dist/`:
- `vigia-server_1.1_amd64.deb` — paquete del profesor
- `vigia-client_1.1_all.deb` — paquete del alumno

---

## Funcionalidades

- **Cuadrícula de pantallas** — vista en tiempo real de todos los alumnos conectados.
- **Observación remota** — el profesor ve la pantalla de un alumno en alta resolución.
- **Control remoto** — el profesor maneja ratón y teclado del alumno.
- **WebRTC P2P** — stream de vídeo H.264/VP9 directo alumno→profesor (UDP, < 150 ms en LAN). Eventos de input por DataChannel. Fallback automático a JPEG+Socket.IO si WebRTC no está disponible.
- **Bloqueo de pantalla** — bloquea teclado y ratón del alumno con un overlay.
- **Mensajes con adjuntos** — mensajes emergentes con texto enriquecido y archivos adjuntos a uno o todos los alumnos. Los adjuntos se guardan en `~/Descargas`.
- **Pantalla del profesor** — comparte la pantalla del profesor en todos los alumnos.
- **Autostart** — servidor arranca con la sesión del profesor (systemd); cliente arranca con la sesión del alumno (XDG autostart).

---

## Requisitos del sistema

- **Kubuntu 22.04 / 24.04** (o cualquier Ubuntu/Debian moderno)
- Python 3.10 o superior
- Sesión **X11** (no Wayland)

> ⚠️ **La captura de pantalla (`mss`) solo funciona en X11.**
>
> Comprueba tu sesión con: `echo $XDG_SESSION_TYPE`
>
> Si muestra `wayland`, cierra sesión, selecciona **"Plasma (X11)"** en la pantalla de login y vuelve a entrar.

---

## Uso

### 1. Averigua la IP del profesor

```bash
ip a | grep "inet " | grep -v 127
```

### 2. Inicia el servidor (profesor)

Haz doble clic en **VIGIA Servidor** en el menú de inicio, o desde terminal:

```bash
python3 vigia-launcher.py
```

### 3. Inicia el cliente (alumnos)

El cliente arranca solo al iniciar sesión si se instaló con el `.deb`. También puede lanzarse manualmente:

```bash
python3 client.py 192.168.X.X
```

### 4. Observar / controlar un alumno

| Botón | Acción |
|---|---|
| 👁 | Pantalla del alumno en modo **solo ver** |
| 🖱 | Pantalla en modo **control remoto** (ratón y teclado) |

El badge del visor indica el transporte activo: **WebRTC P2P** (verde) o **JPEG** (gris).

---

## Red y firewall

El servidor escucha en el **puerto 5000 TCP**. WebRTC usa puertos UDP efímeros para el stream P2P.

```bash
sudo ufw allow 5000/tcp
```

Todos los equipos deben estar en la **misma red local**. Si la WiFi tiene AP isolation, el stream WebRTC no funcionará — el fallback JPEG sigue operativo.

---

## Solución de problemas

**Pantalla negra al abrir el panel**
- Si Chrome/Chromium está instalado, el lanzador lo usa automáticamente (sin pantalla negra).
- Si no, usa GTK+WebKit2GTK con GPU desactivado. Verifica que tienes `gir1.2-webkit2-4.1` y `libwebkit2gtk-4.1-0`.
- Comprueba que la sesión es X11: `echo $XDG_SESSION_TYPE`

**La pantalla del alumno no aparece**
- Comprueba que la sesión del alumno es X11: `echo $XDG_SESSION_TYPE`
- Verifica que la IP del servidor es correcta y el puerto 5000 está accesible.

**El visor siempre muestra "JPEG" en lugar de "WebRTC P2P"**
- Instala `python3-aiortc` en el alumno: `sudo apt install python3-aiortc python3-numpy`
- Comprueba que la red no tiene AP isolation.

**El alumno no consigue conectar**
- Verifica que el servidor está en marcha: `systemctl --user status vigia-servidor`
- Abre el puerto: `sudo ufw allow 5000/tcp`

**"No module named pip"**
```bash
sudo apt install python3-pip
```

**"externally-managed-environment"**
```bash
pip3 install --break-system-packages <paquete>
```

---

## Estructura de archivos

```
VIGIA/
├── server.py                  ← Servidor Flask + SocketIO (profesor)
├── client.py                  ← Cliente del alumno (captura + Tkinter)
├── vigia-launcher.py          ← Lanzador: Chrome --app → GTK/WebKit2GTK → navegador
├── instalar.py                ← Instalador gráfico (tkinter)
├── instalar.sh                ← Lanzador del instalador gráfico
├── instalar_servidor.sh       ← Instalación servidor (deps + desktop + systemd)
├── instalar_cliente.sh        ← Instalación cliente (deps + desktop + autostart)
├── build_debs.sh              ← Genera ambos .deb en dist/
├── templates/
│   └── dashboard.html         ← Panel SPA del profesor (JS vanilla + Socket.IO)
└── img/
    ├── logo2.png
    ├── logo2_mini.png
    ├── icon-192.png           ← Icono PWA/Chrome app
    └── icon-512.png
```
