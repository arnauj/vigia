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

### 1. Instalar pip y dependencias del sistema

```bash
sudo apt update
sudo apt install python3-pip scrot
```

### 2. Instalar las librerías Python

```bash
pip3 install flask flask-socketio
```

> Si `pip3` da error de "externally-managed-environment", usa:
> ```bash
> pip3 install --break-system-packages flask flask-socketio
> ```

### 3. Usar el script automático (opcional)

```bash
bash instalar_servidor.sh
```

Esto instala todo y crea un acceso directo en el Escritorio.

---

## Instalación — Equipos de los alumnos (cliente)

### 1. Copiar los archivos al equipo del alumno

Copia la carpeta `VIGIA` completa al equipo del alumno (USB, red compartida, etc.).

### 2. Instalar pip y dependencias del sistema

```bash
sudo apt update
sudo apt install python3-pip scrot
```

### 3. Instalar las librerías Python y tkinter

```bash
sudo apt install python3-tk
pip3 install "python-socketio[client]" websocket-client mss Pillow
```

> Si `pip3` da error de "externally-managed-environment":
> ```bash
> pip3 install --break-system-packages "python-socketio[client]" websocket-client mss Pillow
> ```

> `python3-tk` es necesario para que la ventana con la pantalla del profesor aparezca automáticamente. Sin él, la conexión funciona igualmente pero no se mostrará la pantalla compartida.

### 4. Usar el script automático (recomendado)

```bash
bash instalar_cliente.sh 192.168.X.X
```

Sustituye `192.168.X.X` por la **IP del equipo del profesor** (ver sección siguiente).
El script instala todo y crea un acceso directo en el Escritorio del alumno.

---

## Uso

### 1. Averigua la IP del equipo del profesor

En el equipo del profesor:
```bash
ip a | grep "inet " | grep -v 127
```
Anota la IP de tu red local, por ejemplo `192.168.0.119`.

### 2. Inicia el servidor (equipo del profesor)

```bash
python3 server.py
```

Se abre el navegador automáticamente con el panel en `http://localhost:5000`.
La terminal mostrará la IP a la que deben conectarse los alumnos.

### 3. Inicia el cliente (cada equipo de alumno)

```bash
python3 client.py 192.168.0.119
```

O, si se instaló con el acceso directo, el alumno hace **doble clic** en `VIGIA (Alumno)` del Escritorio.

Si no se indica la IP al instalar, el cliente la pedirá al arrancar.

---

## Red y firewall

El servidor escucha en el **puerto 5000 TCP**.
Si hay firewall activo en el equipo del profesor:

```bash
sudo ufw allow 5000/tcp
```

Todos los equipos deben estar en la **misma red local** (misma WiFi o misma red del aula).

---

## Resumen de paquetes

| Paquete | Quién lo necesita | Cómo instalarlo |
|---|---|---|
| `python3` | Todos | Ya instalado en Kubuntu |
| `python3-pip` | Todos | `sudo apt install python3-pip` |
| `scrot` | Alumnos (captura alternativa) | `sudo apt install scrot` |
| `python3-tk` | Solo alumnos | `sudo apt install python3-tk` |
| `flask` | Solo profesor | `pip3 install flask` |
| `flask-socketio` | Solo profesor | `pip3 install flask-socketio` |
| `python-socketio[client]` | Solo alumnos | `pip3 install "python-socketio[client]"` |
| `websocket-client` | Solo alumnos | `pip3 install websocket-client` |
| `mss` | Solo alumnos | `pip3 install mss` |
| `Pillow` | Solo alumnos | `pip3 install Pillow` |

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
├── requirements_servidor.txt
├── requirements_cliente.txt
└── README.md               ← Este archivo
```
