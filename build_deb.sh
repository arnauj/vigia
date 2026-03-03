#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
#  VIGIA — Generador del paquete .deb
#  Uso: bash build_deb.sh
#  Resultado: dist/vigia_1.0_all.deb
# ────────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_NAME="vigia"
PKG_VER="1.0"
PKG_ARCH="all"
PKG_FULL="${PKG_NAME}_${PKG_VER}_${PKG_ARCH}"
BUILD_DIR="$SCRIPT_DIR/dist/build/$PKG_FULL"
VIGIA_DST="$BUILD_DIR/opt/vigia"

echo ""
echo "═══════════════════════════════════════════════"
echo "  Construyendo $PKG_FULL.deb"
echo "═══════════════════════════════════════════════"
echo ""

# ── Comprobar dpkg-deb ────────────────────────────────────────
if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "[!] dpkg-deb no encontrado. Instálalo con:"
  echo "    sudo apt install dpkg"
  exit 1
fi

# ── Estructura de directorios ─────────────────────────────────
rm -rf "$BUILD_DIR"
mkdir -p \
  "$VIGIA_DST/templates" \
  "$VIGIA_DST/img" \
  "$BUILD_DIR/DEBIAN" \
  "$BUILD_DIR/usr/share/pixmaps"

# ── Copiar archivos de la aplicación ─────────────────────────
cp "$SCRIPT_DIR/client.py"           "$VIGIA_DST/"
cp "$SCRIPT_DIR/server.py"           "$VIGIA_DST/"
cp "$SCRIPT_DIR/instalar.py"         "$VIGIA_DST/"
cp "$SCRIPT_DIR/instalar.sh"         "$VIGIA_DST/"
cp "$SCRIPT_DIR/instalar_servidor.sh" "$VIGIA_DST/"
cp "$SCRIPT_DIR/instalar_cliente.sh" "$VIGIA_DST/"
cp "$SCRIPT_DIR/templates/"*         "$VIGIA_DST/templates/"
cp "$SCRIPT_DIR/img/logo2.png"       "$VIGIA_DST/img/"
cp "$SCRIPT_DIR/img/logo2_mini.png"  "$VIGIA_DST/img/"
cp "$SCRIPT_DIR/img/logo2_mini.png"  "$BUILD_DIR/usr/share/pixmaps/vigia.png"
[ -f "$SCRIPT_DIR/requirements_cliente.txt"  ] && \
  cp "$SCRIPT_DIR/requirements_cliente.txt"  "$VIGIA_DST/"
[ -f "$SCRIPT_DIR/requirements_servidor.txt" ] && \
  cp "$SCRIPT_DIR/requirements_servidor.txt" "$VIGIA_DST/"

chmod +x "$VIGIA_DST"/*.sh "$VIGIA_DST"/*.py

# ── DEBIAN/control ────────────────────────────────────────────
cat > "$BUILD_DIR/DEBIAN/control" <<EOF
Package: $PKG_NAME
Version: $PKG_VER
Architecture: $PKG_ARCH
Maintainer: VIGIA
Section: education
Priority: optional
Depends: python3 (>= 3.10), python3-tk
Description: Sistema de supervisión de aula para Linux
 VIGIA permite al profesor ver en tiempo real las pantallas de los
 alumnos conectados en la misma red local. Incluye servidor (equipo
 del profesor) y cliente (equipo del alumno).
 .
 Sólo compatible con sesiones X11.
EOF

# ── DEBIAN/postinst ───────────────────────────────────────────
cat > "$BUILD_DIR/DEBIAN/postinst" <<'POSTINST'
#!/bin/bash
set -e
VIGIA_DIR=/opt/vigia

# Detectar el usuario real (quien ejecutó sudo)
REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo "$USER")}"
REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"

chmod +x "$VIGIA_DIR"/*.sh "$VIGIA_DIR"/*.py 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  VIGIA instalado en /opt/vigia           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Lanzar instalador gráfico como el usuario real
_DISPLAY="${DISPLAY:-:0}"
_XAUTH="${XAUTHORITY:-$REAL_HOME/.Xauthority}"

if su - "$REAL_USER" -c \
     "DISPLAY=$_DISPLAY XAUTHORITY=$_XAUTH python3 /opt/vigia/instalar.py" \
     2>/dev/null; then
  :
else
  echo "Para configurar VIGIA, ejecuta:"
  echo "  python3 /opt/vigia/instalar.py"
  echo ""
fi
POSTINST
chmod 755 "$BUILD_DIR/DEBIAN/postinst"

# ── DEBIAN/prerm ──────────────────────────────────────────────
cat > "$BUILD_DIR/DEBIAN/prerm" <<'PRERM'
#!/bin/bash
REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo "$USER")}"
REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
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
echo "  Instalar:    sudo dpkg -i dist/$PKG_FULL.deb"
echo "  Desinstalar: sudo dpkg -r vigia"
echo ""
