#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
#  VIGIA — Generador del paquete .deb
#  Uso: bash build_deb.sh
#  Resultado: dist/vigia_1.0_amd64.deb
# ────────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_NAME="vigia-server"
PKG_VER="1.0"
TAURI_BINARY="$SCRIPT_DIR/vigia-dashboard/src-tauri/target/release/vigia"

# ── Comprobar dpkg-deb ────────────────────────────────────────
if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "[!] dpkg-deb no encontrado. Instálalo con:"
  echo "    sudo apt install dpkg"
  exit 1
fi

# ── Compilar binario Tauri si no existe (opcional) ────────────
if [ -f "$TAURI_BINARY" ]; then
  echo "[✓] Binario Tauri: $TAURI_BINARY"
elif bash "$SCRIPT_DIR/vigia-dashboard/build.sh" 2>/dev/null; then
  echo "[✓] Binario Tauri compilado"
else
  echo "[i] Binario Tauri no disponible — el paquete usará vigia-launcher.py (GTK/WebKit2)"
fi

# ── Arquitectura: amd64 si hay binario Tauri, all si solo Python ──
if [ -f "$TAURI_BINARY" ]; then
  PKG_ARCH="amd64"
else
  PKG_ARCH="all"
fi
PKG_FULL="${PKG_NAME}_${PKG_VER}_${PKG_ARCH}"
BUILD_DIR="$SCRIPT_DIR/dist/build/$PKG_FULL"
VIGIA_DST="$BUILD_DIR/opt/vigia-server"

echo ""
echo "═══════════════════════════════════════════════"
echo "  Construyendo $PKG_FULL.deb"
echo "═══════════════════════════════════════════════"
echo ""

# ── Estructura de directorios ─────────────────────────────────
rm -rf "$BUILD_DIR"
mkdir -p \
  "$VIGIA_DST/templates" \
  "$VIGIA_DST/img" \
  "$BUILD_DIR/DEBIAN" \
  "$BUILD_DIR/usr/share/pixmaps"

# ── Copiar archivos de la aplicación ─────────────────────────
cp "$SCRIPT_DIR/client.py"            "$VIGIA_DST/"
cp "$SCRIPT_DIR/server.py"            "$VIGIA_DST/"
cp "$SCRIPT_DIR/instalar.py"          "$VIGIA_DST/"
cp "$SCRIPT_DIR/instalar.sh"          "$VIGIA_DST/"
cp "$SCRIPT_DIR/instalar_servidor.sh" "$VIGIA_DST/"
cp "$SCRIPT_DIR/instalar_cliente.sh"  "$VIGIA_DST/"
cp "$SCRIPT_DIR/templates/"*          "$VIGIA_DST/templates/"
cp "$SCRIPT_DIR/img/logo2.png"        "$VIGIA_DST/img/"
cp "$SCRIPT_DIR/img/logo2_mini.png"   "$VIGIA_DST/img/"
cp "$SCRIPT_DIR/img/logo2_mini.png"   "$BUILD_DIR/usr/share/pixmaps/vigia.png"
[ -f "$SCRIPT_DIR/img/icon-192.png" ] && cp "$SCRIPT_DIR/img/icon-192.png" "$VIGIA_DST/img/"
[ -f "$SCRIPT_DIR/img/icon-512.png" ] && cp "$SCRIPT_DIR/img/icon-512.png" "$VIGIA_DST/img/"
[ -f "$SCRIPT_DIR/requirements_cliente.txt"  ] && \
  cp "$SCRIPT_DIR/requirements_cliente.txt"  "$VIGIA_DST/"
[ -f "$SCRIPT_DIR/requirements_servidor.txt" ] && \
  cp "$SCRIPT_DIR/requirements_servidor.txt" "$VIGIA_DST/"

# ── Copiar lanzador Python nativo ────────────────────────────
cp "$SCRIPT_DIR/vigia-launcher.py" "$VIGIA_DST/"

# ── Copiar binario Tauri si existe (mejora opcional) ─────────
if [ -f "$TAURI_BINARY" ]; then
  cp "$TAURI_BINARY" "$VIGIA_DST/vigia"
  chmod +x "$VIGIA_DST/vigia"
fi
chmod +x "$VIGIA_DST"/*.sh "$VIGIA_DST"/*.py

# ── DEBIAN/control ────────────────────────────────────────────
cat > "$BUILD_DIR/DEBIAN/control" <<EOF
Package: $PKG_NAME
Version: $PKG_VER
Architecture: $PKG_ARCH
Maintainer: VIGIA
Section: education
Priority: optional
Depends: python3 (>= 3.10), python3-pip, python3-gi, python3-tk, gir1.2-gtk-3.0, gir1.2-webkit2-4.1, libwebkit2gtk-4.1-0, libgtk-3-0, x11-utils, xdotool
Description: Sistema de supervisión de aula para Linux
 VIGIA permite al profesor ver en tiempo real las pantallas de los
 alumnos conectados en la misma red local. Incluye servidor (equipo
 del profesor) y cliente (equipo del alumno).
 .
 El panel del profesor se muestra como ventana nativa (Tauri/WebKit).
 .
 Sólo compatible con sesiones X11.
EOF

# ── DEBIAN/postinst ───────────────────────────────────────────
cat > "$BUILD_DIR/DEBIAN/postinst" <<'POSTINST'
#!/bin/bash
set -e
VIGIA_DIR=/opt/vigia-server

# Detectar el usuario real (quien ejecutó sudo)
REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo "$USER")}"
REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"

chmod +x "$VIGIA_DIR"/*.sh "$VIGIA_DIR"/*.py "$VIGIA_DIR/vigia" 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  VIGIA instalado en /opt/vigia-server           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Instalar dependencias Python del servidor ─────────────────
echo "[*] Instalando dependencias Python del servidor..."
if su - "$REAL_USER" -c \
     "pip3 install --break-system-packages --user -q flask flask-socketio eventlet mss Pillow 2>/dev/null"; then
  echo "[✓] Dependencias Python instaladas"
else
  # Fallback: instalar globalmente si el usuario no puede usar pip
  pip3 install --break-system-packages -q flask flask-socketio eventlet mss Pillow 2>/dev/null || true
  echo "[✓] Dependencias Python instaladas (modo sistema)"
fi

# ── Crear acceso directo en el menú inicio ────────────────────
echo "[*] Creando acceso directo..."
if su - "$REAL_USER" -c "bash $VIGIA_DIR/instalar_servidor.sh" 2>/dev/null; then
  echo "[✓] Acceso directo creado"
else
  echo "[!] No se pudo crear el acceso directo automáticamente."
  echo "    Ejecuta manualmente: bash /opt/vigia-server/instalar_servidor.sh"
fi
echo ""
POSTINST
chmod 755 "$BUILD_DIR/DEBIAN/postinst"

# ── DEBIAN/prerm ──────────────────────────────────────────────
cat > "$BUILD_DIR/DEBIAN/prerm" <<'PRERM'
#!/bin/bash
REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo "$USER")}"
REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
# Detener y deshabilitar el servicio systemd del servidor
su - "$REAL_USER" -c "systemctl --user stop vigia-servidor 2>/dev/null; systemctl --user disable vigia-servidor 2>/dev/null" 2>/dev/null || true
rm -f "$REAL_HOME/.config/systemd/user/vigia-servidor.service" 2>/dev/null || true
# Eliminar accesos directos
rm -f \
  "$REAL_HOME/.local/share/applications/vigia-servidor.desktop" \
  "$REAL_HOME/.local/share/applications/vigia-alumno.desktop" 2>/dev/null || true
PRERM
chmod 755 "$BUILD_DIR/DEBIAN/prerm"

# ── Construir .deb ────────────────────────────────────────────
OUT_DIR="$SCRIPT_DIR/dist"
mkdir -p "$OUT_DIR"
dpkg-deb --root-owner-group --build "$BUILD_DIR" "$OUT_DIR/$PKG_FULL.deb"

echo ""
echo "[✓] Paquete listo: dist/$PKG_FULL.deb"
echo ""
echo "  Instalar:    sudo apt install ./dist/$PKG_FULL.deb"
echo "  Desinstalar: sudo dpkg -r vigia"
echo ""
