#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
#  VIGIA — Instalación del CLIENTE (v1.3 - Control Remoto Fijo)
# ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IP_SERVIDOR="${1:-}"

# Si no se pasa IP, calcular X.X.X.2 a partir de la red local
if [ -z "$IP_SERVIDOR" ]; then
  _IP_LOCAL="$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')"
  if [ -n "$_IP_LOCAL" ]; then
    IP_SERVIDOR="$(echo "$_IP_LOCAL" | awk -F. '{print $1"."$2"."$3".2"}')"
  fi
fi

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
sudo apt-get install -y python3-pip python3-tk python3-pil.imagetk python3-pynput \
    xdotool xclip xsel curl wget scrot python3-aiortc python3-numpy -qq 2>/dev/null || true

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

# ── Acceso directo en el menú inicio ─────────────────────────
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
DESKTOP="$APPS_DIR/vigia-alumno.desktop"
cat > "$DESKTOP" <<DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=VIGIA (Alumno)
Comment=Cliente de supervisión de aula
Exec=bash -c '$PYTHON3 "$SCRIPT_DIR/client.py" $IP_SERVIDOR; read -rp "Pulsa Enter para cerrar..."'
Icon=$SCRIPT_DIR/img/logo2_mini.png
Terminal=true
Categories=Education;
DESKTOP_EOF
chmod +x "$DESKTOP" 2>/dev/null || true

if [ -n "$IP_SERVIDOR" ]; then
  echo "$IP_SERVIDOR" > "$SCRIPT_DIR/.server_ip"
fi

# ── Autostart XDG (arranque automático al iniciar sesión) ────
# Se usa XDG autostart en lugar de systemd porque el cliente necesita
# DISPLAY disponible (Tkinter + captura mss), lo que solo ocurre
# después de que la sesión gráfica esté completamente activa.
echo "[*] Configurando inicio automático del cliente..."

AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

# Matar instancia previa si estaba corriendo para que el nuevo reemplace
pkill -f "python.*client\.py" 2>/dev/null || true

cat > "$AUTOSTART_DIR/vigia-alumno.desktop" <<AUTOSTART_EOF
[Desktop Entry]
Type=Application
Name=VIGIA Cliente
Comment=Cliente de supervisión VIGIA — inicio automático de sesión
Exec=$PYTHON3 $SCRIPT_DIR/client.py $IP_SERVIDOR
Terminal=false
Categories=Education;
Hidden=false
X-GNOME-Autostart-enabled=true
AUTOSTART_EOF
chmod +x "$AUTOSTART_DIR/vigia-alumno.desktop" 2>/dev/null || true

echo "[✓] Autostart configurado en $AUTOSTART_DIR/vigia-alumno.desktop"
echo "    El cliente arrancará automáticamente al iniciar sesión."

# Arrancar el cliente ya ahora (sin esperar al próximo reinicio)
echo "[*] Iniciando cliente VIGIA..."
nohup "$PYTHON3" "$SCRIPT_DIR/client.py" $IP_SERVIDOR >/tmp/vigia-cliente.log 2>&1 &
echo "[✓] Cliente iniciado (PID $!). Log: /tmp/vigia-cliente.log"

echo ""
echo "═══════════════════════════════════════════════"
echo "  [✓] Instalación completada."
echo "═══════════════════════════════════════════════"
echo ""
