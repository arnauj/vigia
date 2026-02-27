#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
#  VIGIA — Instalación del CLIENTE (v1.1 - Mejorada)
# ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IP_SERVIDOR="${1:-}"

echo ""
echo "═══════════════════════════════════════════════"
echo "  VIGIA v1.1 — Instalando cliente del alumno"
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
  echo "[!] Python 3 no encontrado. Instálalo con:"
  echo "    sudo apt update && sudo apt install python3"
  echo ""
  read -rp "Pulsa Enter para cerrar..."
  exit 1
fi

echo "[✓] Python: $PYTHON3  ($($PYTHON3 --version 2>&1))"

# ── Detectar o instalar pip ───────────────────────────────────
PIP=""

verificar_pip() {
  [ -n "$1" ] && $1 --version >/dev/null 2>&1
}

# Intentar detectar pip funcional
if verificar_pip "$PYTHON3 -m pip"; then
  PIP="$PYTHON3 -m pip"
elif verificar_pip "pip3"; then
  PIP="pip3"
elif verificar_pip "$HOME/.local/bin/pip3"; then
  PIP="$HOME/.local/bin/pip3"
fi

# Si no hay pip, intentar instalarlo vía apt
if [ -z "$PIP" ]; then
  echo "[*] pip no encontrado. Intentando instalar python3-pip..."
  sudo apt-get update -qq 2>/dev/null || true
  sudo apt-get install -y python3-pip curl wget -qq 2>/dev/null || true
  
  if verificar_pip "$PYTHON3 -m pip"; then
    PIP="$PYTHON3 -m pip"
  elif verificar_pip "pip3"; then
    PIP="pip3"
  fi
fi

# Si sigue sin haber pip, intentar con get-pip.py
if [ -z "$PIP" ]; then
  echo "[*] pip sigue sin aparecer. Intentando con get-pip.py..."
  URL="https://bootstrap.pypa.io/get-pip.py"
  if command -v curl >/dev/null 2>&1; then
    curl -sS "$URL" -o /tmp/get-pip.py
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$URL" -O /tmp/get-pip.py
  fi

  if [ -f /tmp/get-pip.py ]; then
    "$PYTHON3" /tmp/get-pip.py --user --break-system-packages -q 2>/dev/null || true
    if verificar_pip "$PYTHON3 -m pip"; then
      PIP="$PYTHON3 -m pip"
    elif verificar_pip "$HOME/.local/bin/pip"; then
      PIP="$HOME/.local/bin/pip"
    fi
  fi
fi

if [ -z "$PIP" ]; then
  echo ""
  echo "[!] No se pudo encontrar un comando 'pip' funcional."
  echo "    Por favor, instala pip manualmente:"
  echo "    sudo apt update && sudo apt install python3-pip"
  echo ""
  read -rp "Pulsa Enter para cerrar..."
  exit 1
fi

echo "[✓] pip: $PIP"

# ── Instalar dependencias Python ──────────────────────────────
echo "[*] Instalando dependencias Python..."
# Usamos -m pip si es posible para asegurar que se instala en el Python correcto
if [[ "$PIP" == *" -m pip" ]]; then
  $PIP install --break-system-packages --user -q "python-socketio[client]" websocket-client mss Pillow
else
  # Si PIP es un ejecutable directo (ej: pip3)
  $PIP install --break-system-packages --user -q "python-socketio[client]" websocket-client mss Pillow
fi

# ── Instalar tkinter ──────────────────────────────────────────
if ! "$PYTHON3" -c "import tkinter" 2>/dev/null; then
  echo "[*] Instalando python3-tk..."
  sudo apt-get install -y python3-tk -qq 2>/dev/null || true
fi

# ── Instalar herramientas de control remoto ───────────────────
echo "[*] Instalando xdotool..."
sudo apt-get install -y xdotool -qq 2>/dev/null || true

# ── Guardar IP del servidor ───────────────────────────────────
if [ -n "$IP_SERVIDOR" ]; then
  echo "$IP_SERVIDOR" > "$SCRIPT_DIR/.server_ip"
  echo "[✓] IP del servidor guardada: $IP_SERVIDOR"
fi

# ── Acceso directo ────────────────────────────────────────────
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

echo ""
echo "═══════════════════════════════════════════════"
echo "  [✓] Instalación completada con éxito."
echo "═══════════════════════════════════════════════"
echo ""
