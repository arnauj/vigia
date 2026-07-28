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
# Las librerías con extensiones nativas (Pillow, numpy, pynput, aiortc)
# se instalan vía apt: pip falla al compilarlas en Pythons nuevos
# (Kubuntu 26) y con PEP 668. Cada paquete se instala por separado para
# que uno inexistente no aborte el resto.
echo "[*] Instalando dependencias del sistema (xdotool, tk, Pillow, pip)..."
sudo apt-get update -qq 2>/dev/null || true
sudo apt-get install -y python3-pip python3-tk python3-pil python3-pil.imagetk \
    xdotool xclip xsel curl wget -qq 2>/dev/null || true
for p in python3-pynput python3-numpy python3-aiortc python3-av \
         python3-socketio python3-websocket python3-requests \
         ydotool kde-spectacle python3-evdev \
         python3-gi python3-dbus python3-gst-1.0 gstreamer1.0-pipewire \
         gstreamer1.0-plugins-base gir1.2-gstreamer-1.0 \
         xdg-desktop-portal xdg-desktop-portal-kde; do
  sudo apt-get install -y "$p" -qq 2>/dev/null || true
done

# ── Soporte Wayland (Kubuntu 25.10+/26.04 ya no usa X11) ──────
if [ "${XDG_SESSION_TYPE:-}" = "wayland" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
  echo "[*] Sesión Wayland detectada:"
  echo "    - Captura de pantalla: spectacle/grim (instalado arriba)."
  echo "    - Control remoto: ydotool vía servicio de sistema (uinput como root)."
  # La unidad de USUARIO de ydotool (ydotool.service) falla: /dev/uinput es
  # root:input 0660 y el alumno no está en 'input'. Creamos una unidad de
  # SISTEMA propia con ydotoold como root y socket accesible (igual que el .deb).
  sudo modprobe uinput 2>/dev/null || true
  echo uinput | sudo tee /etc/modules-load.d/vigia-uinput.conf >/dev/null 2>&1 || true
  sudo usermod -aG input "$USER" 2>/dev/null || true
  _YDOTOOLD="$(command -v ydotoold)"
  if [ -n "$_YDOTOOLD" ]; then
    sudo tee /etc/systemd/system/vigia-ydotoold.service >/dev/null <<UNIT
[Unit]
Description=Demonio ydotoold para control remoto VIGIA (Wayland)
Documentation=man:ydotoold(8)

[Service]
Type=simple
RuntimeDirectory=ydotoold
ExecStartPre=-/sbin/modprobe uinput
ExecStart=$_YDOTOOLD --socket-path=/run/ydotoold/socket --socket-perm=0666
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT
    sudo systemctl daemon-reload 2>/dev/null || true
    sudo systemctl enable --now vigia-ydotoold.service 2>/dev/null \
      && echo "    [OK] Servicio vigia-ydotoold habilitado." \
      || echo "    [!] No se pudo habilitar vigia-ydotoold; el control remoto será limitado."
  else
    echo "    [!] ydotoold no encontrado; instala el paquete 'ydotool'."
  fi

  # Demonio vigia-input: dispositivo uinput ABSOLUTO (puntero correcto, no salta
  # a la esquina) + bloqueo del input físico (EVIOCGRAB). Corre como root.
  echo "    - Ratón absoluto + bloqueo: servicio vigia-input (uinput como root)."
  sudo tee /etc/systemd/system/vigia-input.service >/dev/null <<UNIT
[Unit]
Description=Demonio de inyeccion de input y bloqueo VIGIA (Wayland, uinput absoluto)

[Service]
Type=simple
ExecStartPre=-/sbin/modprobe uinput
ExecStart=$PYTHON3 $SCRIPT_DIR/vigia_input.py --daemon
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT
  sudo systemctl daemon-reload 2>/dev/null || true
  sudo systemctl enable vigia-input.service 2>/dev/null || true
  sudo systemctl restart vigia-input.service 2>/dev/null \
    && echo "    [OK] Servicio vigia-input habilitado." \
    || echo "    [!] No se pudo habilitar vigia-input; ratón/bloqueo limitados."
fi

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

# ── Instalar dependencias Python (solo paquetes puros) ────────
# Pillow y pynput vienen de apt (ver arriba); instalarlos con pip puede
# requerir compilación y romper en Pythons nuevos.
echo "[*] Instalando librerías Python..."
$PIP install --break-system-packages --user -q "python-socketio[client]" websocket-client mss 2>/dev/null || true

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

# ── Sudo sin contraseña (necesario para exec_command remoto y apt) ────
# El terminal remoto de VIGIA ejecuta comandos como el alumno sin TTY;
# sudo necesita NOPASSWD para no pedir contraseña en ese contexto.
REAL_USER="$(logname 2>/dev/null || echo "$USER")"
if [ -n "$REAL_USER" ] && [ "$REAL_USER" != "root" ]; then
  SUDOERS_FILE="/etc/sudoers.d/vigia-${REAL_USER}"
  echo "${REAL_USER} ALL=(ALL) NOPASSWD: ALL" | sudo tee "$SUDOERS_FILE" > /dev/null
  sudo chmod 0440 "$SUDOERS_FILE"
  if sudo visudo -c -f "$SUDOERS_FILE" 2>/dev/null; then
    echo "[✓] Sudo sin contraseña configurado para $REAL_USER."
  else
    sudo rm -f "$SUDOERS_FILE"
    echo "[!] Advertencia: no se pudo validar el fichero sudoers; skipping."
  fi
fi

# Arrancar el cliente ya ahora (sin esperar al próximo reinicio)
echo "[*] Iniciando cliente VIGIA..."
nohup "$PYTHON3" "$SCRIPT_DIR/client.py" $IP_SERVIDOR >/tmp/vigia-cliente.log 2>&1 &
echo "[✓] Cliente iniciado (PID $!). Log: /tmp/vigia-cliente.log"

echo ""
echo "═══════════════════════════════════════════════"
echo "  [✓] Instalación completada."
echo "═══════════════════════════════════════════════"
echo ""
