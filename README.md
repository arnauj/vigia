# VIGIA
### Vigilancia e Integración para la Gestión Inteligente de Aulas

<div align="center">
  <img src="img/logo2.png" alt="VIGIA Logo" width="100">
</div>

> Software de monitoreo de aula en tiempo real para Linux. El profesor ve, controla y gestiona todos los equipos del aula desde una sola ventana.

<div align="center">

[![Descargar Servidor](https://img.shields.io/badge/⬇%20%20VIGIA%20Servidor-vigia--server__1.1__amd64.deb-0073e6?style=for-the-badge&logo=debian&logoColor=white)](https://github.com/arnauj/vigia/raw/master/dist/vigia-server_1.1_amd64.deb)
&nbsp;
[![Descargar Cliente](https://img.shields.io/badge/⬇%20%20VIGIA%20Cliente-vigia--client__1.1__all.deb-E95420?style=for-the-badge&logo=debian&logoColor=white)](https://github.com/arnauj/vigia/raw/master/dist/vigia-client_1.1_all.deb)

</div>

---

## ¿Qué es VIGIA?

VIGIA es una herramienta para profesores que permite **ver y controlar en tiempo real las pantallas de todos los alumnos del aula** desde un único panel. Sin servidores externos, sin internet, sin configuración compleja. Funciona completamente dentro de la red local del aula.

```
  Alumno 1 ──┐
  Alumno 2 ──┼──►  Servidor VIGIA (equipo del profesor)  ──►  Panel nativo
  Alumno 3 ──┘          Flask + Socket.IO + WebRTC               Chrome --app
  Alumno N ──┘                                                  GTK / WebKit
```

---

## Funcionalidades

### Monitoreo

- **Cuadrícula en tiempo real** — el panel muestra una miniatura actualizada de la pantalla de cada alumno conectado. Las miniaturas se refrescan automáticamente.
- **Nombre e IP de cada alumno** — cada tarjeta muestra el nombre con el que se registró el cliente y su dirección IP en la red local.
- **Estado de conexión** — los alumnos desconectados desaparecen automáticamente del panel.

### Observación y control remoto

- **Modo solo ver** — amplía la pantalla de un alumno concreto a pantalla completa en el panel del profesor, con calidad alta.
- **Modo control remoto** — el profesor toma el control total del ratón y el teclado del equipo del alumno directamente desde su propio escritorio.
- **WebRTC P2P** — cuando `python3-aiortc` está instalado en el cliente, el stream de vídeo viaja directamente por UDP (H.264/VP9) con latencia menor a 150 ms en LAN. Los eventos de ratón van por un DataChannel sin orden (máxima velocidad) y los de teclado por un canal fiable y en orden.
- **Fallback automático a JPEG** — si WebRTC no está disponible o falla (incluso tras haberse establecido), el sistema vuelve automáticamente a transmisión JPEG vía Socket.IO sin interrumpir la sesión.
- **Indicador de transporte** — un badge en el visor muestra en todo momento si el stream activo es **WebRTC P2P** (verde) o **JPEG** (gris).
- **Terminal remota** — el profesor puede abrir una terminal en el equipo del alumno y ejecutar comandos de forma remota, con directorio de trabajo persistente entre comandos.

### Gestión del aula

- **Bloqueo de pantalla** — bloquea teclado y ratón del alumno con un overlay a pantalla completa. El alumno no puede interactuar con su equipo mientras dura el bloqueo. El desbloqueo lo activa el profesor.
- **Mensajes emergentes** — envía mensajes de texto enriquecido a un alumno concreto o a toda la clase. Los mensajes aparecen en una ventana flotante en el equipo del alumno.
- **Adjuntos en mensajes** — los mensajes pueden incluir archivos adjuntos (límite 10 MB total). Los adjuntos se guardan automáticamente en `~/Descargas` del alumno y se pueden abrir con un solo clic.
- **Pantalla del profesor en alumnos** — comparte la pantalla del profesor en todos los equipos del aula simultáneamente, útil para explicaciones o demostraciones.
- **Envío a uno o a todos** — cualquier acción (mensaje, bloqueo, pantalla del profesor) puede dirigirse a un alumno específico o lanzarse a todos a la vez.

### Infraestructura y automatización

- **Sin base de datos** — todo el estado es en memoria. Sin ficheros de configuración ni tablas que mantener.
- **Autostart del servidor** — el servicio Flask arranca automáticamente con la sesión del profesor gracias a un unit de systemd de usuario.
- **Autostart del cliente** — el cliente del alumno arranca con la sesión gráfica mediante XDG autostart. No requiere intervención manual.
- **Ventana nativa** — el lanzador (`vigia-launcher.py`) abre el panel en modo aplicación nativa. Orden de preferencia: Chrome/Chromium `--app` → GTK + WebKit2GTK → navegador del sistema.
- **Detección de Flask activo** — si el servidor ya está corriendo como servicio systemd, el lanzador lo reutiliza sin arrancar un proceso duplicado ni matarlo al cerrar la ventana.
- **Perfil Chrome aislado** — el modo `--app` usa un perfil temporal para no interferir con el Chrome personal del profesor.
- **PWA / icono correcto** — VIGIA sirve un Web App Manifest con iconos propios para que Chrome muestre el icono de VIGIA en lugar del genérico de Chrome.

### Instalación

- **Paquetes `.deb` listos** — un paquete para el servidor y otro para el cliente, generados con `build_debs.sh`.
- **Instalador gráfico** — una ventana tkinter (`instalar.sh`) permite elegir entre instalar servidor o cliente y muestra el progreso en tiempo real.
- **Scripts de línea de comandos** — `instalar_servidor.sh` e `instalar_cliente.sh` para entornos sin GUI o despliegue masivo.
- **Autodetección de IP** — el instalador del cliente detecta la IP local y propone automáticamente la IP del servidor (`x.x.x.2` por convención).
- **Auto-instalación de dependencias** — el cliente detecta si faltan módulos pip al arrancar y los instala sin intervención manual.

---

## Instalación rápida (recomendada)

Los paquetes `.deb` están en [`dist/`](dist/). Descárgalos desde los botones al inicio de este documento.

### En el equipo del profesor (servidor)

```bash
sudo apt install ./vigia-server_1.1_amd64.deb
```

Aparece **VIGIA Servidor** en el menú de inicio. El servidor arranca automáticamente al iniciar sesión.

### En los equipos de los alumnos (cliente)

```bash
sudo apt install ./vigia-client_1.1_all.deb
```

Durante la instalación se pedirá la IP del servidor (se sugiere automáticamente). El cliente arranca solo al iniciar sesión.

---

## Instalación alternativa

### Servidor

```bash
# Script automatizado
bash instalar_servidor.sh

# Manual
sudo apt install python3-pip python3-gi gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0
pip3 install --break-system-packages flask flask-socketio eventlet
python3 vigia-launcher.py
```

### Cliente

```bash
# Script automatizado (IP auto-detectada)
bash instalar_cliente.sh

# Script con IP manual
bash instalar_cliente.sh 192.168.X.X

# Manual
sudo apt install python3-pip python3-tk xdotool python3-aiortc python3-numpy
pip3 install --break-system-packages "python-socketio[client]" websocket-client mss Pillow
python3 client.py 192.168.X.X
```

### Instalador gráfico

```bash
bash instalar.sh
```

---

## Uso

### 1 — Averigua la IP del servidor

```bash
ip a | grep "inet " | grep -v 127
```

### 2 — Inicia el servidor (profesor)

Haz doble clic en **VIGIA Servidor** en el menú de inicio, o desde terminal:

```bash
python3 vigia-launcher.py
```

### 3 — Los alumnos se conectan

El cliente arranca solo al iniciar sesión. También puede lanzarse manualmente:

```bash
python3 client.py 192.168.X.X
```

### 4 — Acciones del panel

| Acción | Cómo |
|---|---|
| Ver pantalla de un alumno | Clic en la miniatura → modo **solo ver** |
| Tomar el control | Botón de control en el visor → modo **control remoto** |
| Abrir terminal remota | Botón de terminal en el visor |
| Bloquear / desbloquear | Botón de candado en la tarjeta del alumno |
| Enviar mensaje | Botón de mensaje → escribe texto y adjunta archivos si quieres |
| Compartir tu pantalla | Botón "Pantalla del profesor" → se muestra en todos los alumnos |
| Enviar mensaje a toda la clase | Icono de broadcast en la barra superior |

---

## Requisitos del sistema

| | Requisito |
|---|---|
| **Sistema operativo** | Kubuntu 22.04 / 24.04 o cualquier Ubuntu/Debian moderno |
| **Python** | 3.10 o superior |
| **Sesión gráfica** | **X11** (no Wayland) |
| **Red** | Misma red local para profesor y alumnos |

> **La captura de pantalla (`mss`) solo funciona en X11.**
>
> Comprueba tu sesión con `echo $XDG_SESSION_TYPE`
>
> Si muestra `wayland`, cierra sesión, selecciona **"Plasma (X11)"** en la pantalla de login y vuelve a entrar.

### Dependencias por componente

| Componente | Python (pip) | Sistema (apt) |
|---|---|---|
| Servidor | `flask flask-socketio eventlet` | — |
| Cliente | `python-socketio[client] websocket-client mss Pillow` | `python3-tk xdotool` |
| Cliente (WebRTC, opcional) | — | `python3-aiortc python3-numpy` |
| Ventana nativa fallback | — | `python3-gi gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0` |

---

## Red y firewall

El servidor escucha en el **puerto 5000 TCP**. WebRTC usa puertos UDP efímeros para el stream P2P.

```bash
sudo ufw allow 5000/tcp
```

Todos los equipos deben estar en la **misma red local**. Si la WiFi tiene AP isolation activado, el stream WebRTC no funcionará, pero el fallback JPEG seguirá operativo.

---

## Solución de problemas

**Pantalla negra al abrir el panel**
- Si Chrome/Chromium está instalado, el lanzador lo usa automáticamente (sin pantalla negra).
- Si no, verifica que tienes instalado `gir1.2-webkit2-4.1` y `libwebkit2gtk-4.1-0`.
- Comprueba que la sesión es X11: `echo $XDG_SESSION_TYPE`

**La pantalla del alumno no aparece**
- Confirma que la sesión del alumno es X11: `echo $XDG_SESSION_TYPE`
- Verifica que la IP del servidor es correcta y el puerto 5000 está accesible.

**El visor siempre muestra JPEG en lugar de WebRTC P2P**
- Instala aiortc en el equipo del alumno: `sudo apt install python3-aiortc python3-numpy`
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

## Estructura del proyecto

```
vigia-master/
├── server.py                  — Servidor Flask + Socket.IO (profesor)
├── client.py                  — Cliente del alumno (captura + Tkinter)
├── vigia-launcher.py          — Lanzador: Chrome --app → GTK/WebKit2GTK → navegador
├── instalar.py                — Instalador gráfico (tkinter)
├── instalar.sh                — Lanzador del instalador gráfico
├── instalar_servidor.sh       — Instalación servidor (deps + desktop + systemd)
├── instalar_cliente.sh        — Instalación cliente (deps + desktop + autostart)
├── build_debs.sh              — Genera ambos .deb en dist/
├── test_remote_control.py     — Suite de 39 tests para el control remoto
├── templates/
│   └── dashboard.html         — Panel SPA del profesor (JS vanilla + Socket.IO)
├── img/
│   ├── logo2.png
│   ├── logo2_mini.png
│   ├── icon-192.png           — Icono PWA/Chrome app
│   └── icon-512.png
└── dist/
    ├── vigia-server_1.1_amd64.deb
    └── vigia-client_1.1_all.deb
```

---

## Generar los paquetes .deb

```bash
bash build_debs.sh
```

Genera en `dist/`:
- `vigia-server_1.1_amd64.deb` — paquete del profesor
- `vigia-client_1.1_all.deb` — paquete del alumno

---

*Desarrollado para aulas Linux con Kubuntu.*
