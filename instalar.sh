#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
#  VIGIA — Instalador unificado
#  Lanza la interfaz gráfica de instalación (instalar.py).
#  Uso: bash instalar.sh
# ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Detectar Python 3 ─────────────────────────────────────────
PYTHON3=""
for c in python3 python3.12 python3.11 python3.10 \
          /usr/bin/python3 /usr/local/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then
    PYTHON3="$c"; break
  fi
done

if [ -z "$PYTHON3" ]; then
  echo "[!] Python 3 no encontrado. Instálelo con:"
  echo "    sudo apt update && sudo apt install python3"
  read -rp "Pulsa Enter para cerrar…"; exit 1
fi

# ── Asegurar tkinter ──────────────────────────────────────────
if ! "$PYTHON3" -c "import tkinter" 2>/dev/null; then
  echo "[*] Instalando python3-tk…"
  sudo apt-get install -y python3-tk -qq 2>/dev/null || true
fi

# ── Lanzar instalador gráfico ─────────────────────────────────
exec "$PYTHON3" "$SCRIPT_DIR/instalar.py"
