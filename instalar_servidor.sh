#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
#  VIGIA — Instalación del SERVIDOR (equipo del profesor)
# ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "═══════════════════════════════════════════════"
echo "  VIGIA — Instalando servidor del profesor"
echo "═══════════════════════════════════════════════"
echo ""

# ── Detener servidor anterior (si está en ejecución) ──────────
if pkill -f "python.*server\.py" 2>/dev/null; then
  echo "[*] Servidor anterior detenido."
  sleep 1
fi
# Por si quedó algún proceso ocupando el puerto 5000
if command -v fuser >/dev/null 2>&1; then
  fuser -k 5000/tcp 2>/dev/null && sleep 1
fi

# ── Detectar Python 3 ─────────────────────────────────────────
PYTHON3=""
for candidato in python3 python3.12 python3.11 python3.10 \
                 /usr/bin/python3 /usr/local/bin/python3; do
  if command -v "$candidato" >/dev/null 2>&1 || [ -x "$candidato" ]; then
    PYTHON3="$candidato"
    break
  fi
done

if [ -z "$PYTHON3" ]; then
  echo "[!] Python 3 no encontrado. Instálalo con:"
  echo "    sudo apt install python3"
  echo ""
  read -rp "Pulsa Enter para cerrar..."
  exit 1
fi

echo "[✓] Python: $PYTHON3  ($($PYTHON3 --version 2>&1))"

# ── Detectar o instalar pip ───────────────────────────────────
PIP=""

if "$PYTHON3" -m pip --version >/dev/null 2>&1; then
  PIP="$PYTHON3 -m pip"
elif [ -x "$HOME/.local/bin/pip3" ]; then
  PIP="$HOME/.local/bin/pip3"
elif [ -x "$HOME/.local/bin/pip" ]; then
  PIP="$HOME/.local/bin/pip"
elif command -v pip3 >/dev/null 2>&1; then
  PIP="pip3"
fi

if [ -z "$PIP" ]; then
  echo "[*] pip no encontrado. Descargando get-pip.py..."
  curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/_vigia_getpip.py
  "$PYTHON3" /tmp/_vigia_getpip.py --user --break-system-packages -q
  PIP="$HOME/.local/bin/pip"
fi

echo "[✓] pip: $PIP"

# ── Instalar dependencias Python ──────────────────────────────
echo "[*] Instalando Flask y Flask-SocketIO..."
"$PYTHON3" -m pip install --break-system-packages --user -q flask flask-socketio 2>&1 \
  || $PIP install --break-system-packages --user -q flask flask-socketio

echo ""
echo "[✓] Instalación completada."
echo ""

# ── Acceso directo en el Escritorio ──────────────────────────
DESKTOP="$HOME/Escritorio/VIGIA-Servidor.desktop"

cat > "$DESKTOP" <<DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=VIGIA Servidor
Comment=Inicia el servidor de monitoreo del aula (abre el navegador automáticamente)
Exec=bash -c '$PYTHON3 "$SCRIPT_DIR/server.py"; read -rp "Pulsa Enter para cerrar..."'
Icon=preferences-system
Terminal=true
Categories=Education;
DESKTOP_EOF

chmod +x "$DESKTOP"
gio set "$DESKTOP" metadata::trusted true 2>/dev/null || true

echo "  Acceso directo creado: '$DESKTOP'"
echo "  O ejecuta manualmente: $PYTHON3 \"$SCRIPT_DIR/server.py\""
echo ""
