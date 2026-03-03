#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
#  VIGIA — Compilar el binario Tauri
#  Uso: bash vigia-dashboard/build.sh
#  Resultado: vigia-dashboard/src-tauri/target/release/vigia
# ────────────────────────────────────────────────────────────────
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "═══════════════════════════════════════════════"
echo "  VIGIA — Compilando ventana nativa (Tauri 2)"
echo "═══════════════════════════════════════════════"
echo ""

# ── 1. Rust ──────────────────────────────────────────────────────
if ! command -v cargo >/dev/null 2>&1; then
  echo "[*] Rust no encontrado. Instalando con rustup…"
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
  # Añadir al PATH de esta sesión
  # shellcheck source=/dev/null
  source "$HOME/.cargo/env"
fi
echo "[✓] Rust: $(rustc --version)"

# ── 2. Dependencias de sistema para Tauri (libwebkit2gtk, etc.) ──
echo "[*] Comprobando dependencias del sistema…"
MISSING_PKGS=""
for pkg in libwebkit2gtk-4.1-dev libgtk-3-dev libssl-dev \
            pkg-config build-essential; do
  dpkg -s "$pkg" >/dev/null 2>&1 || MISSING_PKGS="$MISSING_PKGS $pkg"
done

if [ -n "$MISSING_PKGS" ]; then
  echo "[*] Instalando:$MISSING_PKGS"
  sudo apt-get update -qq
  # shellcheck disable=SC2086
  sudo apt-get install -y $MISSING_PKGS -qq
fi
echo "[✓] Dependencias del sistema OK"

# ── 3. Compilar ──────────────────────────────────────────────────
echo "[*] Compilando (esto puede tardar varios minutos la primera vez)…"
cd "$SCRIPT_DIR/src-tauri"
cargo build --release 2>&1

BINARY="$SCRIPT_DIR/src-tauri/target/release/vigia"
if [ -f "$BINARY" ]; then
  echo ""
  echo "[✓] Binario listo: $BINARY"
  echo ""
  echo "  Para ejecutar en desarrollo:"
  echo "    cd $(dirname "$SCRIPT_DIR") && $BINARY"
  echo ""
  echo "  Para incluirlo en el .deb:"
  echo "    bash $(dirname "$SCRIPT_DIR")/build_deb.sh"
  echo ""
else
  echo "[!] La compilación finalizó pero no se encontró el binario."
  exit 1
fi
