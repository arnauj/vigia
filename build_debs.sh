#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="1.2"
DIST_DIR="$SCRIPT_DIR/dist"
mkdir -p "$DIST_DIR"

# Check for dpkg-deb
if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "[!] dpkg-deb not found."
  exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# NOTA DE COMPATIBILIDAD (Kubuntu 26.04 / Wayland / Python moderno):
#  - Las dependencias Python con extensiones nativas (Pillow, numpy, pynput,
#    aiortc) se resuelven SIEMPRE vía apt (Depends), nunca via wheels pip:
#    un wheel binario construido para cp312 no instala en el Python de
#    Kubuntu 26 y rompía el postinst ("problema con Pillow").
#  - Los wheels empaquetados son solo paquetes Python PUROS (py3-none-any),
#    válidos para cualquier versión de Python y utilizables sin red.
#  - eventlet se eliminó (depende de greenlet, extensión C frágil);
#    el servidor usa threading + simple-websocket.
# ─────────────────────────────────────────────────────────────────────────────

# --- BUILD SERVER PACKAGE ---
echo "Building vigia-server..."
SERVER_PKG_NAME="vigia-server"
SERVER_BUILD_DIR="$DIST_DIR/build/${SERVER_PKG_NAME}_${VERSION}_amd64"
rm -rf "$SERVER_BUILD_DIR"
mkdir -p "$SERVER_BUILD_DIR/DEBIAN"
mkdir -p "$SERVER_BUILD_DIR/opt/vigia-server/templates"
mkdir -p "$SERVER_BUILD_DIR/opt/vigia-server/img"
mkdir -p "$SERVER_BUILD_DIR/usr/share/pixmaps"
mkdir -p "$SERVER_BUILD_DIR/usr/bin"

cp "$SCRIPT_DIR/server.py" "$SERVER_BUILD_DIR/opt/vigia-server/"
cp "$SCRIPT_DIR/vigia-launcher.py" "$SERVER_BUILD_DIR/opt/vigia-server/"
cp "$SCRIPT_DIR/platform_utils.py" "$SERVER_BUILD_DIR/opt/vigia-server/"
cp "$SCRIPT_DIR/screen_capture.py" "$SERVER_BUILD_DIR/opt/vigia-server/"
cp "$SCRIPT_DIR/templates/"* "$SERVER_BUILD_DIR/opt/vigia-server/templates/"
cp "$SCRIPT_DIR/img/logo2.png" "$SERVER_BUILD_DIR/opt/vigia-server/img/"
cp "$SCRIPT_DIR/img/logo2_mini.png" "$SERVER_BUILD_DIR/opt/vigia-server/img/"
cp "$SCRIPT_DIR/img/logo2_mini.png" "$SERVER_BUILD_DIR/usr/share/pixmaps/vigia-server.png"
[ -f "$SCRIPT_DIR/img/icon-192.png" ] && cp "$SCRIPT_DIR/img/icon-192.png" "$SERVER_BUILD_DIR/opt/vigia-server/img/"
[ -f "$SCRIPT_DIR/img/icon-512.png" ] && cp "$SCRIPT_DIR/img/icon-512.png" "$SERVER_BUILD_DIR/opt/vigia-server/img/"

# Wheels Python PUROS para instalación offline (válidos en cualquier Python 3)
echo "Construyendo wheels Python puros para servidor (instalación offline)..."
mkdir -p "$SERVER_BUILD_DIR/opt/vigia-server/wheels"
pip3 wheel --wheel-dir "$SERVER_BUILD_DIR/opt/vigia-server/wheels/" \
    mss simple-websocket flask-socketio python-socketio python-engineio bidict \
    2>/dev/null || echo "[!] Aviso: no se pudieron pre-construir wheels; los paquetes apt cubrirán las dependencias."
# Eliminar cualquier wheel binario (cpXXX) que se haya colado: solo py puros
find "$SERVER_BUILD_DIR/opt/vigia-server/wheels/" -name '*.whl' \
    ! -name '*-py2.py3-none-any.whl' ! -name '*-py3-none-any.whl' -delete 2>/dev/null || true

cat > "$SERVER_BUILD_DIR/DEBIAN/control" <<EOF
Package: $SERVER_PKG_NAME
Version: $VERSION
Architecture: amd64
Maintainer: VIGIA
Section: education
Priority: optional
Depends: python3, python3-venv, python3-flask, python3-flask-socketio, python3-socketio, python3-engineio, python3-pil
Recommends: python3-simple-websocket, python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1, libwebkit2gtk-4.1-0, libgtk-3-0, chromium-browser | chromium | google-chrome-stable, kde-spectacle | grim | gnome-screenshot
Description: VIGIA Server - Classroom Monitoring System (Teacher)
 VIGIA allows teachers to monitor student screens in real-time.
 This package installs the teacher's dashboard and relay server.
EOF

cat > "$SERVER_BUILD_DIR/DEBIAN/postinst" <<'EOF'
#!/bin/bash
set -e
VIGIA_DIR=/opt/vigia-server

REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo "$USER")}"
REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
PYTHON3="/opt/vigia-server/venv/bin/python3"

chmod +x "$VIGIA_DIR"/*.py 2>/dev/null || true

# ── Entorno Python ────────────────────────────────────────────
# Se recrea SIEMPRE el venv: un venv heredado de otra versión de Python
# (p.ej. tras actualizar a Kubuntu 26) queda roto. --system-site-packages
# permite usar los paquetes apt (python3-flask, python3-pil, …).
echo "Configurando entorno Python del servidor..."
rm -rf "$VIGIA_DIR/venv"
python3 -m venv --system-site-packages "$VIGIA_DIR/venv"
VPY="$VIGIA_DIR/venv/bin/python3"
VPIP="$VIGIA_DIR/venv/bin/pip"

# Instalar SOLO lo que falte; nunca abortar la instalación del paquete.
# pip escribe sus "ERROR:" por stdout: silenciar AMBOS flujos para que los
# intentos fallidos (p.ej. --no-index sin wheel) no asusten durante apt install.
_pip_install() {
    "$VPIP" install -q --no-warn-script-location --no-index \
        --find-links "$VIGIA_DIR/wheels/" "$1" >/dev/null 2>&1 \
    || "$VPIP" install -q --no-warn-script-location "$1" >/dev/null 2>&1 \
    || echo "[!] Aviso: no se pudo instalar $1 (se usará el paquete del sistema si existe)."
}
# Solo paquetes Python PUROS. Pillow es NATIVA y va por apt (Depends:
# python3-pil); intentar instalarla con pip aquí producía
# "No matching distribution found for Pillow" en Kubuntu 26.
for spec in "flask:flask" "flask_socketio:flask-socketio" \
            "socketio:python-socketio" "engineio:python-engineio" \
            "simple_websocket:simple-websocket" "mss:mss"; do
    mod="${spec%%:*}"; pkg="${spec#*:}"
    "$VPY" -c "import $mod" 2>/dev/null || _pip_install "$pkg"
done
if "$VPY" -c "import flask, flask_socketio, PIL" 2>/dev/null; then
    echo "[OK] Dependencias Python del servidor verificadas."
else
    echo "[!] AVISO: faltan dependencias Python del servidor."
    echo "    Instala manualmente: sudo apt install python3-flask python3-flask-socketio python3-pil"
fi

# ── Acceso directo en el menú inicio ─────────────────────────
APPS_DIR=/usr/share/applications
cat > "$APPS_DIR/vigia-server.desktop" <<EOD
[Desktop Entry]
Type=Application
Name=VIGIA Servidor
Comment=Panel del profesor — supervisión de aula
Exec=$PYTHON3 /opt/vigia-server/vigia-launcher.py
Icon=vigia-server
Terminal=false
Categories=Education;
StartupWMClass=vigia
StartupNotify=true
EOD
chmod 644 "$APPS_DIR/vigia-server.desktop"

# ── Servicio systemd de usuario (arranque automático) ────────
if [ -n "$REAL_USER" ] && [ "$REAL_USER" != "root" ]; then
  SYSTEMD_DIR="$REAL_HOME/.config/systemd/user"
  su - "$REAL_USER" -c "mkdir -p '$SYSTEMD_DIR'"
  cat > "$SYSTEMD_DIR/vigia-servidor.service" <<EOD
[Unit]
Description=VIGIA — Servidor del Panel del Profesor
After=network.target

[Service]
Type=simple
ExecStart=$PYTHON3 $VIGIA_DIR/server.py 5000
WorkingDirectory=$VIGIA_DIR
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOD
  chown "$REAL_USER:" "$SYSTEMD_DIR/vigia-servidor.service"
  su - "$REAL_USER" -c \
    "systemctl --user daemon-reload && systemctl --user enable --now vigia-servidor" 2>/dev/null || true
  loginctl enable-linger "$REAL_USER" 2>/dev/null || true
  echo "Servicio 'vigia-servidor' habilitado para $REAL_USER."
fi

# ── Sudo sin contraseña (necesario para exec_command remoto) ──
# Crea /etc/sudoers.d/vigia-<usuario> con NOPASSWD:ALL para el usuario real.
if [ -n "$REAL_USER" ] && [ "$REAL_USER" != "root" ]; then
  SUDOERS_FILE="/etc/sudoers.d/vigia-${REAL_USER}"
  echo "${REAL_USER} ALL=(ALL) NOPASSWD: ALL" > "$SUDOERS_FILE"
  chmod 0440 "$SUDOERS_FILE"
  if visudo -c -f "$SUDOERS_FILE" 2>/dev/null; then
    echo "Sudo sin contraseña configurado para $REAL_USER."
  else
    rm -f "$SUDOERS_FILE"
    echo "Advertencia: no se pudo validar el fichero sudoers; skipping."
  fi
fi

echo "VIGIA Server installed successfully."
EOF
chmod 755 "$SERVER_BUILD_DIR/DEBIAN/postinst"

cat > "$SERVER_BUILD_DIR/DEBIAN/prerm" <<'EOF'
#!/bin/bash
REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo "$USER")}"
REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
# Detener y deshabilitar el servicio
su - "$REAL_USER" -c \
  "systemctl --user stop vigia-servidor 2>/dev/null; systemctl --user disable vigia-servidor 2>/dev/null" \
  2>/dev/null || true
rm -f "$REAL_HOME/.config/systemd/user/vigia-servidor.service" 2>/dev/null || true
rm -f /usr/share/applications/vigia-server.desktop 2>/dev/null || true
# Eliminar regla sudoers de vigia
rm -f "/etc/sudoers.d/vigia-${REAL_USER}" 2>/dev/null || true
EOF
chmod 755 "$SERVER_BUILD_DIR/DEBIAN/prerm"

cat > "$SERVER_BUILD_DIR/DEBIAN/postrm" <<'EOF'
#!/bin/bash
case "$1" in
    remove|purge)
        rm -rf /opt/vigia-server 2>/dev/null || true
        ;;
esac
EOF
chmod 755 "$SERVER_BUILD_DIR/DEBIAN/postrm"

dpkg-deb --root-owner-group --build "$SERVER_BUILD_DIR" "$DIST_DIR/${SERVER_PKG_NAME}_${VERSION}_amd64.deb"


# --- BUILD CLIENT PACKAGE ---
echo "Building vigia-client..."
CLIENT_PKG_NAME="vigia-client"
CLIENT_BUILD_DIR="$DIST_DIR/build/${CLIENT_PKG_NAME}_${VERSION}_all"
rm -rf "$CLIENT_BUILD_DIR"
mkdir -p "$CLIENT_BUILD_DIR/DEBIAN"
mkdir -p "$CLIENT_BUILD_DIR/opt/vigia-client/img"
mkdir -p "$CLIENT_BUILD_DIR/usr/share/pixmaps"

cp "$SCRIPT_DIR/client.py"          "$CLIENT_BUILD_DIR/opt/vigia-client/"
cp "$SCRIPT_DIR/vigia_overlay.py"   "$CLIENT_BUILD_DIR/opt/vigia-client/"
cp "$SCRIPT_DIR/platform_utils.py"  "$CLIENT_BUILD_DIR/opt/vigia-client/"
cp "$SCRIPT_DIR/screen_capture.py"  "$CLIENT_BUILD_DIR/opt/vigia-client/"
cp "$SCRIPT_DIR/img/logo2_mini.png" "$CLIENT_BUILD_DIR/opt/vigia-client/img/"
cp "$SCRIPT_DIR/img/logo2_mini.png" "$CLIENT_BUILD_DIR/usr/share/pixmaps/vigia-client.png"

# Wheels Python PUROS para instalación offline (válidos en cualquier Python 3)
echo "Construyendo wheels Python puros para cliente (instalación offline)..."
mkdir -p "$CLIENT_BUILD_DIR/opt/vigia-client/wheels"
pip3 wheel --wheel-dir "$CLIENT_BUILD_DIR/opt/vigia-client/wheels/" \
    mss python-socketio python-engineio websocket-client bidict simple-websocket \
    2>/dev/null || echo "[!] Aviso: no se pudieron pre-construir wheels; los paquetes apt cubrirán las dependencias."
find "$CLIENT_BUILD_DIR/opt/vigia-client/wheels/" -name '*.whl' \
    ! -name '*-py2.py3-none-any.whl' ! -name '*-py3-none-any.whl' -delete 2>/dev/null || true

# Control file
cat > "$CLIENT_BUILD_DIR/DEBIAN/control" <<EOF
Package: $CLIENT_PKG_NAME
Version: $VERSION
Architecture: all
Maintainer: VIGIA
Section: education
Priority: optional
Depends: python3, python3-venv, python3-tk, python3-pil, python3-pil.imagetk, python3-socketio, python3-engineio, python3-websocket, python3-requests, python3-pynput, python3-numpy, xdotool, debconf
Recommends: python3-aiortc, ydotool, kde-spectacle | grim | gnome-screenshot, xclip, python3-gi, python3-gi-cairo, gir1.2-gtk-3.0
Description: VIGIA Client - Classroom Monitoring System (Student)
 VIGIA allows teachers to monitor student screens in real-time.
 This package installs the student client.
EOF

# Templates for debconf
cat > "$CLIENT_BUILD_DIR/DEBIAN/templates" <<EOF
Template: vigia-client/server_ip
Type: string
Description: IP del Servidor VIGIA:
 Por favor, introduce la dirección IP del equipo del profesor.
EOF

# Config script for debconf
cat > "$CLIENT_BUILD_DIR/DEBIAN/config" <<'EOF'
#!/bin/bash
set -e
. /usr/share/debconf/confmodule

# Intentar calcular la IP por defecto (x.x.x.2) cada vez que se configura
_IP_LOCAL="$(ip route get 8.8.8.8 2>/dev/null | grep -oP 'src \K\S+' || ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K\S+' || hostname -I | awk '{print $1}')"

if [ -n "$_IP_LOCAL" ]; then
    DEFAULT_IP="$(echo "$_IP_LOCAL" | awk -F. '{print $1"."$2"."$3".2"}')"

    # Solo establecemos el valor si no hay uno previo o queremos sugerir el nuevo
    db_get vigia-client/server_ip || true
    if [ -z "$RET" ]; then
        db_set vigia-client/server_ip "$DEFAULT_IP"
    fi
fi

# Forzar que se muestre la pregunta (marcar como no vista)
db_fset vigia-client/server_ip seen false
db_input high vigia-client/server_ip || true
db_go
EOF
chmod 755 "$CLIENT_BUILD_DIR/DEBIAN/config"

# Postinst script
cat > "$CLIENT_BUILD_DIR/DEBIAN/postinst" <<'EOF'
#!/bin/bash
set -e
. /usr/share/debconf/confmodule

db_get vigia-client/server_ip
SERVER_IP="$RET"

VIGIA_DIR=/opt/vigia-client
REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo "$USER")}"
REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
PYTHON3="/opt/vigia-client/venv/bin/python3"

chmod +x "$VIGIA_DIR"/*.py 2>/dev/null || true

# ── Guardar IP del servidor (config global) ───────────────────
mkdir -p /etc/vigia
echo "$SERVER_IP" > /etc/vigia/client.conf

# ── Entorno Python ────────────────────────────────────────────
# Recrear SIEMPRE el venv (un venv de otra versión de Python queda roto).
# --system-site-packages reutiliza los paquetes apt (python3-pil, numpy…).
echo "Configurando entorno Python del cliente..."
rm -rf "$VIGIA_DIR/venv"
python3 -m venv --system-site-packages "$VIGIA_DIR/venv"
VPY="$VIGIA_DIR/venv/bin/python3"
VPIP="$VIGIA_DIR/venv/bin/pip"

# pip escribe sus "ERROR:" por stdout: silenciar AMBOS flujos.
_pip_install() {
    "$VPIP" install -q --no-warn-script-location --no-index \
        --find-links "$VIGIA_DIR/wheels/" "$1" >/dev/null 2>&1 \
    || "$VPIP" install -q --no-warn-script-location "$1" >/dev/null 2>&1 \
    || echo "[!] Aviso: no se pudo instalar $1 (se usará el paquete del sistema si existe)."
}
# Solo paquetes Python PUROS. Pillow y pynput son NATIVOS y van por apt
# (Depends: python3-pil, python3-pil.imagetk, python3-pynput); con pip
# fallaban en Kubuntu 26 ("No matching distribution found for Pillow").
for spec in "socketio:python-socketio" "engineio:python-engineio" \
            "websocket:websocket-client" "requests:requests" \
            "simple_websocket:simple-websocket" "mss:mss"; do
    mod="${spec%%:*}"; pkg="${spec#*:}"
    "$VPY" -c "import $mod" 2>/dev/null || _pip_install "$pkg"
done
if "$VPY" -c "import socketio, PIL" 2>/dev/null; then
    echo "[OK] Dependencias Python del cliente verificadas."
else
    echo "[!] AVISO: faltan dependencias Python del cliente."
    echo "    Instala manualmente: sudo apt install python3-socketio python3-pil python3-pil.imagetk"
fi

# ── ydotool (control remoto en Wayland — Kubuntu 26 es solo Wayland) ──
# El paquete 'ydotool' de Ubuntu NO trae unidad de sistema: solo una unidad
# de USUARIO (/usr/lib/systemd/user/ydotool.service) que además falla porque
# /dev/uinput es root:input 0660 y el alumno no está en el grupo 'input'
# (y meterle requeriría re-login). Solución: unidad de SISTEMA propia con
# ydotoold como root y socket accesible para la sesión del alumno.
if command -v ydotoold >/dev/null 2>&1; then
  _YDOTOOLD="$(command -v ydotoold)"
  cat > /etc/systemd/system/vigia-ydotoold.service <<UNIT
[Unit]
Description=Demonio ydotoold para control remoto VIGIA (Wayland)
Documentation=man:ydotoold(8)

[Service]
Type=simple
RuntimeDirectory=ydotoold
ExecStart=$_YDOTOOLD --socket-path=/run/ydotoold/socket --socket-perm=0666
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload 2>/dev/null || true
  if systemctl enable --now vigia-ydotoold.service 2>/dev/null; then
    echo "[OK] Servicio vigia-ydotoold habilitado (control remoto Wayland)."
  else
    echo "[!] Aviso: no se pudo habilitar vigia-ydotoold (control remoto Wayland limitado)."
  fi
elif command -v ydotool >/dev/null 2>&1; then
  echo "[!] Aviso: ydotoold no encontrado (control remoto Wayland limitado)."
fi

# ── Script lanzador global ────────────────────────────────────
# Lee la IP del servidor en tiempo de ejecución desde /etc/vigia/client.conf,
# de modo que funciona para cualquier usuario sin necesitar la IP en el .desktop
cat > /usr/local/bin/vigia-client <<LAUNCHER
#!/bin/bash
SERVER_IP="\$(cat /etc/vigia/client.conf 2>/dev/null | tr -d '[:space:]')"
exec $PYTHON3 $VIGIA_DIR/client.py "\$SERVER_IP"
LAUNCHER
chmod 755 /usr/local/bin/vigia-client

# ── Acceso directo en el menú inicio (global, todos los usuarios) ─
cat > /usr/share/applications/vigia-client.desktop <<EOD
[Desktop Entry]
Type=Application
Name=VIGIA Alumno
Comment=Cliente de supervisión de aula
Exec=/usr/local/bin/vigia-client
Icon=vigia-client
Terminal=false
Categories=Education;
EOD
chmod 644 /usr/share/applications/vigia-client.desktop

# ── XDG autostart global (todos los usuarios de la máquina) ──
# /etc/xdg/autostart/ es procesado por KDE/GNOME/XFCE para CUALQUIER usuario
# que inicie sesión gráfica, no solo el que instaló el paquete.
mkdir -p /etc/xdg/autostart
cat > /etc/xdg/autostart/vigia-alumno.desktop <<EOD
[Desktop Entry]
Type=Application
Name=VIGIA Alumno
Comment=Cliente de supervisión VIGIA — inicio automático de sesión
Exec=/usr/local/bin/vigia-client
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
Categories=Education;
EOD
chmod 644 /etc/xdg/autostart/vigia-alumno.desktop

# ── Arrancar el cliente inmediatamente para el usuario activo ─
if [ -n "$REAL_USER" ] && [ "$REAL_USER" != "root" ]; then
  # Detener cualquier instancia previa
  pkill -u "$REAL_USER" -f "python.*client\.py" 2>/dev/null || true
  sleep 0.3

  # Detectar el entorno gráfico del usuario (X11 o Wayland) leyendo el
  # entorno de sus procesos. En Kubuntu 26 (Wayland) DISPLAY puede ser el
  # de XWayland y WAYLAND_DISPLAY/XDG_RUNTIME_DIR son imprescindibles para
  # que spectacle/ydotool funcionen.
  _SESS_ENV=""
  for _pid in $(pgrep -u "$REAL_USER" 2>/dev/null | head -40); do
    [ -r "/proc/$_pid/environ" ] || continue
    _CAND="$(tr '\0' '\n' < "/proc/$_pid/environ" 2>/dev/null \
             | grep -E '^(DISPLAY|WAYLAND_DISPLAY|XDG_SESSION_TYPE|XDG_RUNTIME_DIR|XDG_CURRENT_DESKTOP|DBUS_SESSION_BUS_ADDRESS|XAUTHORITY)=' || true)"
    if echo "$_CAND" | grep -qE '^(DISPLAY|WAYLAND_DISPLAY)='; then
      _SESS_ENV="$_CAND"
      break
    fi
  done
  _ENV_PREFIX="$(echo "$_SESS_ENV" | tr '\n' ' ')"
  [ -z "$_ENV_PREFIX" ] && _ENV_PREFIX="DISPLAY=:0"

  # IMPORTANTE: cerrar los descriptores heredados de apt/dpkg/debconf antes
  # de lanzar el cliente en segundo plano. Si el cliente mantiene abiertos
  # esos pipes, apt se queda esperando su EOF y la barra de progreso se
  # congela (~96%) aunque el postinst ya haya terminado.
  db_stop 2>/dev/null || true
  su "$REAL_USER" -c "
    for _fd in /proc/self/fd/*; do
      _n=\"\${_fd##*/}\"
      [ \"\$_n\" -gt 2 ] 2>/dev/null && eval \"exec \$_n>&-\" || true
    done
    env $_ENV_PREFIX setsid /usr/local/bin/vigia-client \
        >/tmp/vigia-cliente.log 2>&1 </dev/null &
  " 2>/dev/null || true
  echo "Cliente VIGIA iniciado para $REAL_USER."
fi

# ── Sudo sin contraseña (necesario para exec_command remoto y apt) ──
# Permite al alumno ejecutar comandos del terminal remoto sin prompt de contraseña.
if [ -n "$REAL_USER" ] && [ "$REAL_USER" != "root" ]; then
  SUDOERS_FILE="/etc/sudoers.d/vigia-${REAL_USER}"
  echo "${REAL_USER} ALL=(ALL) NOPASSWD: ALL" > "$SUDOERS_FILE"
  chmod 0440 "$SUDOERS_FILE"
  if visudo -c -f "$SUDOERS_FILE" 2>/dev/null; then
    echo "Sudo sin contraseña configurado para $REAL_USER."
  else
    rm -f "$SUDOERS_FILE"
    echo "Advertencia: no se pudo validar el fichero sudoers; skipping."
  fi
fi

echo "VIGIA Client installed successfully. Server IP: $SERVER_IP"
EOF
chmod 755 "$CLIENT_BUILD_DIR/DEBIAN/postinst"

cat > "$CLIENT_BUILD_DIR/DEBIAN/prerm" <<'EOF'
#!/bin/bash
# Matar instancias del cliente por ruta exacta (evitar matar a dpkg mismo)
pkill -f "/opt/vigia-client/client\.py" 2>/dev/null || true
pkill -f "python.*client\.py" 2>/dev/null || true
rm -f /etc/xdg/autostart/vigia-alumno.desktop 2>/dev/null || true
rm -f /usr/share/applications/vigia-client.desktop 2>/dev/null || true
rm -f /usr/local/bin/vigia-client 2>/dev/null || true
# Eliminar regla sudoers de vigia
REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo "$USER")}"
rm -f "/etc/sudoers.d/vigia-${REAL_USER}" 2>/dev/null || true
EOF
chmod 755 "$CLIENT_BUILD_DIR/DEBIAN/prerm"

cat > "$CLIENT_BUILD_DIR/DEBIAN/postrm" <<'EOF'
#!/bin/bash
case "$1" in
    remove|purge)
        rm -rf /opt/vigia-client 2>/dev/null || true
        ;;
esac
EOF
chmod 755 "$CLIENT_BUILD_DIR/DEBIAN/postrm"

dpkg-deb --root-owner-group --build "$CLIENT_BUILD_DIR" "$DIST_DIR/${CLIENT_PKG_NAME}_${VERSION}_all.deb"

chmod 644 "$DIST_DIR"/*.deb

# Copiar los .deb a /tmp para que apt pueda acceder a ellos sin el aviso
# «_apt no puede leer el archivo en home/» (el sandbox _apt no puede
# atravesar directorios de usuario con permisos 750).
TMP_VIGIA="/tmp/vigia-dist"
mkdir -p "$TMP_VIGIA"
cp "$DIST_DIR/${SERVER_PKG_NAME}_${VERSION}_amd64.deb" "$TMP_VIGIA/"
cp "$DIST_DIR/${CLIENT_PKG_NAME}_${VERSION}_all.deb"   "$TMP_VIGIA/"
chmod 644 "$TMP_VIGIA"/*.deb

echo "Build finished. Packages are in $DIST_DIR"
echo ""
echo "Para instalar sin avisos de permisos:"
echo "  sudo apt install $TMP_VIGIA/${SERVER_PKG_NAME}_${VERSION}_amd64.deb"
echo "  sudo apt install $TMP_VIGIA/${CLIENT_PKG_NAME}_${VERSION}_all.deb"
