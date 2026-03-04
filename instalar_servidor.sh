#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
#  VIGIA — Instalación del SERVIDOR (v1.1 - Mejorada)
# ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "═══════════════════════════════════════════════"
echo "  VIGIA v1.1 — Instalando servidor del profesor"
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
$PIP install --break-system-packages --user -q flask flask-socketio eventlet gevent-websocket 2>/dev/null || $PIP install --break-system-packages --user -q flask flask-socketio

# ── Acceso directo en el menú inicio ─────────────────────────
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
DESKTOP="$APPS_DIR/vigia-servidor.desktop"

# Usar el binario nativo Tauri si existe; si no, Python directamente
if [ -x "$SCRIPT_DIR/vigia" ]; then
  # Instalación desde .deb — binario Tauri en /opt/vigia/vigia
  VIGIA_EXEC="$SCRIPT_DIR/vigia"
  VIGIA_TERMINAL=false
elif [ -x "$SCRIPT_DIR/vigia-dashboard/src-tauri/target/release/vigia" ]; then
  # Compilación de desarrollo
  VIGIA_EXEC="$SCRIPT_DIR/vigia-dashboard/src-tauri/target/release/vigia"
  VIGIA_TERMINAL=false
elif [ -f "$SCRIPT_DIR/vigia-launcher.py" ]; then
  # Lanzador Python nativo (GTK + WebKit2GTK, sin necesidad de Rust)
  VIGIA_EXEC="$PYTHON3 $SCRIPT_DIR/vigia-launcher.py"
  VIGIA_TERMINAL=false
else
  # Último recurso: servidor Python en terminal
  VIGIA_EXEC="bash -c '$PYTHON3 \"$SCRIPT_DIR/server.py\"; read -rp \"Pulsa Enter para cerrar...\"'"
  VIGIA_TERMINAL=true
fi

cat > "$DESKTOP" <<DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=VIGIA Servidor
Comment=Panel del profesor — supervisión de aula
Exec=$VIGIA_EXEC
Icon=$SCRIPT_DIR/img/logo2_mini.png
Terminal=$VIGIA_TERMINAL
Categories=Education;
StartupWMClass=vigia
StartupNotify=true
DESKTOP_EOF
chmod +x "$DESKTOP" 2>/dev/null || true

# ── Servicio systemd de usuario (arranque automático) ────────
echo "[*] Configurando inicio automático del servidor..."

SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"

cat > "$SYSTEMD_USER_DIR/vigia-servidor.service" <<SERVICE_EOF
[Unit]
Description=VIGIA — Servidor del Panel del Profesor
After=network.target

[Service]
Type=simple
ExecStart=$PYTHON3 $SCRIPT_DIR/server.py 5000
WorkingDirectory=$SCRIPT_DIR
Environment=VIGIA_TAURI=1
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
SERVICE_EOF

# Detener versión anterior si está corriendo, luego recargar y activar
systemctl --user stop vigia-servidor 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable --now vigia-servidor

# Permitir que el servicio arranque en el boot aunque el usuario no haya iniciado
# sesión gráfica (los alumnos podrán conectar desde el primer momento)
loginctl enable-linger "$USER" 2>/dev/null || true

echo "[✓] Servicio systemd 'vigia-servidor' activo y habilitado."
echo "    Comandos útiles:"
echo "      systemctl --user status vigia-servidor"
echo "      systemctl --user restart vigia-servidor"
echo "      journalctl --user -u vigia-servidor -f"

echo ""
echo "═══════════════════════════════════════════════"
echo "  [✓] Instalación completada con éxito."
echo "═══════════════════════════════════════════════"
echo ""
