#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="1.1"
DIST_DIR="$SCRIPT_DIR/dist"
mkdir -p "$DIST_DIR"

# Check for dpkg-deb
if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "[!] dpkg-deb not found."
  exit 1
fi

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
cp "$SCRIPT_DIR/templates/"* "$SERVER_BUILD_DIR/opt/vigia-server/templates/"
cp "$SCRIPT_DIR/img/logo2.png" "$SERVER_BUILD_DIR/opt/vigia-server/img/"
cp "$SCRIPT_DIR/img/logo2_mini.png" "$SERVER_BUILD_DIR/opt/vigia-server/img/"
cp "$SCRIPT_DIR/img/logo2_mini.png" "$SERVER_BUILD_DIR/usr/share/pixmaps/vigia-server.png"
[ -f "$SCRIPT_DIR/img/icon-192.png" ] && cp "$SCRIPT_DIR/img/icon-192.png" "$SERVER_BUILD_DIR/opt/vigia-server/img/"
[ -f "$SCRIPT_DIR/img/icon-512.png" ] && cp "$SCRIPT_DIR/img/icon-512.png" "$SERVER_BUILD_DIR/opt/vigia-server/img/"

# Copy Tauri binary if exists
TAURI_BINARY="$SCRIPT_DIR/vigia-dashboard/src-tauri/target/release/vigia"
if [ -f "$TAURI_BINARY" ]; then
  cp "$TAURI_BINARY" "$SERVER_BUILD_DIR/opt/vigia-server/vigia"
  chmod +x "$SERVER_BUILD_DIR/opt/vigia-server/vigia"
fi

cat > "$SERVER_BUILD_DIR/DEBIAN/control" <<EOF
Package: $SERVER_PKG_NAME
Version: $VERSION
Architecture: amd64
Maintainer: VIGIA
Section: education
Priority: optional
Depends: python3, python3-pip, python3-gi, python3-tk, gir1.2-gtk-3.0, gir1.2-webkit2-4.1, libwebkit2gtk-4.1-0, libgtk-3-0
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
PYTHON3="$(command -v python3 || echo python3)"

chmod +x "$VIGIA_DIR"/*.py 2>/dev/null || true

# ── Dependencias Python ───────────────────────────────────────
echo "Instalando dependencias Python del servidor..."
su - "$REAL_USER" -c \
  "pip3 install --break-system-packages --user -q flask flask-socketio eventlet mss Pillow 2>/dev/null" \
  || pip3 install --break-system-packages -q flask flask-socketio eventlet mss Pillow 2>/dev/null || true

# ── Acceso directo en el menú inicio ─────────────────────────
APPS_DIR=/usr/share/applications
cat > "$APPS_DIR/vigia-server.desktop" <<EOD
[Desktop Entry]
Type=Application
Name=VIGIA Servidor
Comment=Panel del profesor — supervisión de aula
Exec=python3 /opt/vigia-server/vigia-launcher.py
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
Environment=VIGIA_TAURI=1
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
EOF
chmod 755 "$SERVER_BUILD_DIR/DEBIAN/prerm"

dpkg-deb --root-owner-group --build "$SERVER_BUILD_DIR" "$DIST_DIR/${SERVER_PKG_NAME}_${VERSION}_amd64.deb"


# --- BUILD CLIENT PACKAGE ---
echo "Building vigia-client..."
CLIENT_PKG_NAME="vigia-client"
CLIENT_BUILD_DIR="$DIST_DIR/build/${CLIENT_PKG_NAME}_${VERSION}_all"
rm -rf "$CLIENT_BUILD_DIR"
mkdir -p "$CLIENT_BUILD_DIR/DEBIAN"
mkdir -p "$CLIENT_BUILD_DIR/opt/vigia-client/img"
mkdir -p "$CLIENT_BUILD_DIR/usr/share/pixmaps"

cp "$SCRIPT_DIR/client.py" "$CLIENT_BUILD_DIR/opt/vigia-client/"
cp "$SCRIPT_DIR/img/logo2_mini.png" "$CLIENT_BUILD_DIR/opt/vigia-client/img/"
cp "$SCRIPT_DIR/img/logo2_mini.png" "$CLIENT_BUILD_DIR/usr/share/pixmaps/vigia-client.png"

# Control file
cat > "$CLIENT_BUILD_DIR/DEBIAN/control" <<EOF
Package: $CLIENT_PKG_NAME
Version: $VERSION
Architecture: all
Maintainer: VIGIA
Section: education
Priority: optional
Depends: python3, python3-pip, python3-tk, python3-pil, python3-pil.imagetk, xdotool, python3-numpy, debconf
Description: VIGIA Client - Classroom Monitoring System (Student)
 VIGIA allows teachers to monitor student screens in real-time.
 This package installs the student client.
EOF

# Templates for debconf
cat > "$CLIENT_BUILD_DIR/DEBIAN/templates" <<EOF
Template: vigia-client/server_ip
Type: string
_Description: IP del Servidor VIGIA:
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
PYTHON3="$(command -v python3 || echo python3)"

chmod +x "$VIGIA_DIR"/*.py 2>/dev/null || true

# ── Guardar IP del servidor (config global) ───────────────────
mkdir -p /etc/vigia
echo "$SERVER_IP" > /etc/vigia/client.conf

# ── Dependencias Python ───────────────────────────────────────
echo "Instalando dependencias Python del cliente..."
pip3 install --break-system-packages mss pynput "python-socketio[client]" websocket-client Pillow 2>/dev/null || true

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

  # Detectar el DISPLAY activo del usuario leyendo el entorno de sus procesos
  _XDISPLAY=""
  for _pid in $(pgrep -u "$REAL_USER" 2>/dev/null | head -30); do
    _XDISPLAY=$(tr '\0' '\n' < "/proc/$_pid/environ" 2>/dev/null \
                | grep "^DISPLAY=" | cut -d= -f2 | grep -v "^$" | head -1)
    [ -n "$_XDISPLAY" ] && break
  done
  [ -z "$_XDISPLAY" ] && _XDISPLAY=":0"

  su - "$REAL_USER" -c \
    "DISPLAY='$_XDISPLAY' XAUTHORITY='$REAL_HOME/.Xauthority' \
     python3 -c \"import subprocess; subprocess.Popen(['/usr/local/bin/vigia-client'], stdin=open('/dev/null'), stdout=open('/tmp/vigia-cliente.log','w'), stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)\"" \
    </dev/null 2>/dev/null || true
  echo "Cliente VIGIA iniciado para $REAL_USER (DISPLAY=$_XDISPLAY)."
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
EOF
chmod 755 "$CLIENT_BUILD_DIR/DEBIAN/prerm"

dpkg-deb --root-owner-group --build "$CLIENT_BUILD_DIR" "$DIST_DIR/${CLIENT_PKG_NAME}_${VERSION}_all.deb"

echo "Build finished. Packages are in $DIST_DIR"
