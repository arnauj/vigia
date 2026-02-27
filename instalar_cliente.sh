#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
#  VIGIA — Instalación del CLIENTE (equipos de los alumnos)
#
#  Uso:  bash instalar_cliente.sh [IP_DEL_SERVIDOR]
#  Ej.:  bash instalar_cliente.sh 192.168.1.50
# ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IP_SERVIDOR="${1:-}"

echo ""
echo "═══════════════════════════════════════════════"
echo "  VIGIA — Instalando cliente del alumno"
echo "═══════════════════════════════════════════════"
echo ""

# ── Detectar Python 3 ─────────────────────────────────────────
# Buscamos en rutas fijas además de usar PATH, por si el script
# se lanza desde un lanzador gráfico con PATH reducido.
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

# Probamos distintas formas de encontrar pip, sin mezclar
# mensajes de diagnóstico con la detección del comando
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
echo "[*] Instalando dependencias Python..."
"$PYTHON3" -m pip install --break-system-packages --user -q \
  "python-socketio[client]" websocket-client mss Pillow 2>&1 \
  || $PIP install --break-system-packages --user -q \
       "python-socketio[client]" websocket-client mss Pillow

# ── Instalar tkinter ──────────────────────────────────────────
if ! "$PYTHON3" -c "import tkinter" 2>/dev/null; then
  echo "[*] Instalando python3-tk (ventana de pantalla del profesor)..."
  sudo apt-get install -y python3-tk
  if ! "$PYTHON3" -c "import tkinter" 2>/dev/null; then
    echo "[!] python3-tk no pudo instalarse para $PYTHON3."
    echo "    Instálalo manualmente: sudo apt install python3-tk"
  else
    echo "[✓] tkinter instalado correctamente"
  fi
else
  echo "[✓] tkinter disponible"
fi

# ── Instalar herramientas de control remoto ───────────────────
echo "[*] Instalando xdotool y python3-pynput (control remoto)..."
sudo apt-get install -y xdotool python3-pynput -qq 2>/dev/null || true
if command -v xdotool >/dev/null 2>&1; then
  echo "[✓] xdotool disponible (control remoto habilitado)"
elif "$PYTHON3" -c "import pynput" 2>/dev/null; then
  echo "[✓] pynput disponible (control remoto habilitado)"
else
  echo "[!] Control remoto no disponible. Instala manualmente: sudo apt install xdotool"
fi

# ── Guardar IP del servidor ───────────────────────────────────
if [ -n "$IP_SERVIDOR" ]; then
  echo "$IP_SERVIDOR" > "$SCRIPT_DIR/.server_ip"
  echo "[✓] IP del servidor guardada: $IP_SERVIDOR"
fi

echo ""
echo "[✓] Instalación completada."
echo ""

# ── Acceso directo en el Escritorio ──────────────────────────
DESKTOP="$HOME/Escritorio/VIGIA-Alumno.desktop"
EXEC_ARG="${IP_SERVIDOR:-}"

cat > "$DESKTOP" <<DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=VIGIA (Alumno)
Comment=Conecta el equipo al servidor del profesor para monitoreo
Exec=bash -c '$PYTHON3 "$SCRIPT_DIR/client.py" $EXEC_ARG; read -rp "Pulsa Enter para cerrar..."'
Icon=network-workgroup
Terminal=true
Categories=Education;
DESKTOP_EOF

chmod +x "$DESKTOP"
gio set "$DESKTOP" metadata::trusted true 2>/dev/null || true

echo "  Acceso directo creado en el Escritorio: 'VIGIA (Alumno)'"
if [ -z "$IP_SERVIDOR" ]; then
  echo ""
  echo "  [!] No se indicó IP del servidor."
  echo "      Al abrir, pedirá la IP del equipo del profesor."
  echo "      Para fijarlo, reinstala indicando la IP:"
  echo "        bash \"$SCRIPT_DIR/instalar_cliente.sh\" 192.168.1.XX"
fi
echo ""
