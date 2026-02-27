#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
#  VIGIA — Instalación del CLIENTE (v1.3 - Control Remoto Fijo)
# ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IP_SERVIDOR="${1:-}"

echo ""
echo "═══════════════════════════════════════════════"
echo "  VIGIA v1.3 — Instalando cliente del alumno"
echo "═══════════════════════════════════════════════"
echo ""

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
  echo "[!] Python 3 no encontrado. Instálelo con: sudo apt install python3"
  read -rp "Pulsa Enter para cerrar..."
  exit 1
fi

echo "[✓] Python: $PYTHON3"

# ── Actualizar e instalar dependencias de sistema ──────────────
echo "[*] Instalando dependencias del sistema (xdotool, tk, pip)..."
sudo apt-get update -qq 2>/dev/null || true
sudo apt-get install -y python3-pip python3-tk python3-pynput xdotool curl wget scrot -qq 2>/dev/null || true

# ── Detectar o instalar pip ───────────────────────────────────
PIP=""
verificar_pip() { [ -n "$1" ] && $1 --version >/dev/null 2>&1; }

if verificar_pip "$PYTHON3 -m pip"; then
  PIP="$PYTHON3 -m pip"
elif verificar_pip "pip3"; then
  PIP="pip3"
fi

if [ -z "$PIP" ]; then
  echo "[*] Instalando pip con get-pip.py..."
  URL="https://bootstrap.pypa.io/get-pip.py"
  curl -sS "$URL" -o /tmp/get-pip.py || wget -q "$URL" -O /tmp/get-pip.py
  "$PYTHON3" /tmp/get-pip.py --user --break-system-packages -q 2>/dev/null || true
  PIP="$PYTHON3 -m pip"
fi

echo "[✓] pip: $PIP"

# ── Instalar dependencias Python ──────────────────────────────
echo "[*] Instalando librerías Python..."
$PIP install --break-system-packages --user -q "python-socketio[client]" websocket-client mss Pillow pynput 2>/dev/null

# ── Configurar acceso directo ─────────────────────────────────
DESKTOP="$HOME/Escritorio/VIGIA-Alumno.desktop"
cat > "$DESKTOP" <<DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=VIGIA (Alumno)
Exec=bash -c '$PYTHON3 "$SCRIPT_DIR/client.py" $IP_SERVIDOR; read -rp "Pulsa Enter para cerrar..."'
Icon=network-workgroup
Terminal=true
Categories=Education;
DESKTOP_EOF
chmod +x "$DESKTOP" 2>/dev/null || true

if [ -n "$IP_SERVIDOR" ]; then
  echo "$IP_SERVIDOR" > "$SCRIPT_DIR/.server_ip"
fi

echo ""
echo "═══════════════════════════════════════════════"
echo "  [✓] Instalación completada."
echo "═══════════════════════════════════════════════"
echo ""
