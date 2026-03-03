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
APPS_DIR=/usr/share/applications
DESKTOP="$APPS_DIR/vigia-server.desktop"

# Instalar dependencias de Python faltantes
echo "Instalando dependencias de Python para el servidor..."
pip3 install --break-system-packages flask flask-socketio eventlet 2>/dev/null || true

chmod +x "$VIGIA_DIR"/*.py 2>/dev/null || true

# Create desktop entry
cat > "$DESKTOP" <<EOD
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
chmod 644 "$DESKTOP"

echo "VIGIA Server installed successfully."
EOF
chmod 755 "$SERVER_BUILD_DIR/DEBIAN/postinst"

cat > "$SERVER_BUILD_DIR/DEBIAN/prerm" <<'EOF'
#!/bin/bash
rm -f /usr/share/applications/vigia-server.desktop
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
Default: 192.168.1.2
_Description: IP address of the VIGIA Server:
 Please enter the IP address of the teacher's computer running VIGIA Server.
EOF

# Config script for debconf
cat > "$CLIENT_BUILD_DIR/DEBIAN/config" <<'EOF'
#!/bin/bash
set -e
. /usr/share/debconf/confmodule

# Try to guess the default IP (x.x.x.2)
# We look for the default route interface IP
_IP_LOCAL="$(ip route get 8.8.8.8 2>/dev/null | grep -oP 'src \K\S+' || ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K\S+' || hostname -I | awk '{print $1}')"

if [ -n "$_IP_LOCAL" ]; then
    DEFAULT_IP="$(echo "$_IP_LOCAL" | awk -F. '{print $1"."$2"."$3".2"}')"
    db_set vigia-client/server_ip "$DEFAULT_IP"
fi

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
APPS_DIR=/usr/share/applications
DESKTOP="$APPS_DIR/vigia-client.desktop"

# Instalar dependencias de Python faltantes
echo "Instalando dependencias de Python para el alumno..."
pip3 install --break-system-packages mss pynput aiortc "python-socketio[client]" websocket-client 2>/dev/null || true

chmod +x "$VIGIA_DIR"/*.py 2>/dev/null || true

# Save config
mkdir -p /etc/vigia
echo "$SERVER_IP" > /etc/vigia/client.conf

# Create desktop entry
cat > "$DESKTOP" <<EOD
[Desktop Entry]
Type=Application
Name=VIGIA Alumno
Comment=Cliente de supervisión de aula
Exec=python3 /opt/vigia-client/client.py $SERVER_IP
Icon=vigia-client
Terminal=true
Categories=Education;
EOD
chmod 644 "$DESKTOP"

echo "VIGIA Client installed successfully. Server IP set to $SERVER_IP"
EOF
chmod 755 "$CLIENT_BUILD_DIR/DEBIAN/postinst"

cat > "$CLIENT_BUILD_DIR/DEBIAN/prerm" <<'EOF'
#!/bin/bash
rm -f /usr/share/applications/vigia-client.desktop
EOF
chmod 755 "$CLIENT_BUILD_DIR/DEBIAN/prerm"

dpkg-deb --root-owner-group --build "$CLIENT_BUILD_DIR" "$DIST_DIR/${CLIENT_PKG_NAME}_${VERSION}_all.deb"

echo "Build finished. Packages are in $DIST_DIR"
