#!/usr/bin/env python3
"""
VIGIA — Lanzador del panel del profesor.

Orden de preferencia para mostrar el dashboard:
  1. Chromium / Google Chrome en modo --app  (sin barra de herramientas,
     getDisplayMedia() nativo → compartir pantalla funciona igual que Chrome)
  2. WebKit2GTK (python3-gi + gir1.2-webkit2-4.1) — ventana GTK nativa
  3. Navegador predeterminado del sistema (fallback último recurso)
"""
import os
import sys
import shutil
import socket
import tempfile
import subprocess
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Candidatos de Chromium/Chrome, en orden de preferencia
_CHROMIUM_CANDIDATES = [
    'google-chrome-stable',
    'google-chrome',
    'chromium-browser',
    'chromium',
]


def wait_for_port(port: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def _find_chromium() -> str | None:
    for name in _CHROMIUM_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


def run_chrome_app(url: str, proc) -> bool:  # proc puede ser None si Flask ya corre como servicio
    """
    Intenta abrir el dashboard en Chromium/Chrome modo app (sin toolbar).
    Devuelve True si Chrome se lanzó y completó su ciclo de vida.
    Devuelve False si no se encuentra ningún navegador Chromium instalado.

    Ventajas respecto a WebKit2GTK:
    - getDisplayMedia() funciona igual que en Chrome normal.
    - No hay conflictos GPU/DMA-buf con KWin.
    - El diálogo de compartir pantalla es el nativo del sistema.
    """
    browser = _find_chromium()
    if not browser:
        return False

    # Directorio de perfil temporal aislado para no interferir con el perfil
    # habitual del usuario ni con instancias de Chrome ya abiertas.
    tmpdir = tempfile.mkdtemp(prefix='vigia-chrome-')
    print(f'[VIGIA] Abriendo con {os.path.basename(browser)} en modo app…')
    try:
        chrome = subprocess.Popen([
            browser,
            f'--app={url}',
            f'--user-data-dir={tmpdir}',
            '--class=vigia',          # WM_CLASS → KDE asocia la ventana al .desktop
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-infobars',
            '--disable-translate',
            '--disable-sync',
            '--disable-extensions',
            '--disable-background-networking',
        ])
        try:
            chrome.wait()
        except KeyboardInterrupt:
            chrome.terminate()
            chrome.wait()
    finally:
        # Cerrar Flask solo si lo arrancamos nosotros (proc=None → corre como servicio)
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmpdir, ignore_errors=True)

    return True


def run_webview(url: str, proc) -> None:  # proc puede ser None
    """
    Fallback: ventana GTK nativa con WebKit2GTK.
    NOTA: getDisplayMedia() no funciona en WebKit2GTK; en su lugar el servidor
    captura la pantalla con mss. Las variables de entorno se fuerzan antes de
    inicializar GTK para evitar el deadlock GPU/KWin (pantalla negra).
    """
    # Deshabilitar toda aceleración GPU/DMA-buf de WebKit ANTES de inicializar GTK.
    # WebKit2GTK en KDE/KWin puede deadlockear el compositor al intentar usar
    # DRM/DMA-buf, causando pantalla negra y cuelgue total del sistema.
    os.environ['WEBKIT_DISABLE_COMPOSITING_MODE'] = '1'
    os.environ['WEBKIT_DISABLE_DMABUF_RENDERER'] = '1'
    os.environ['LIBGL_ALWAYS_SOFTWARE'] = '1'
    os.environ['GDK_BACKEND'] = 'x11'

    import gi
    for webkit_ver in ('4.1', '4.0'):
        try:
            gi.require_version('WebKit2', webkit_ver)
            break
        except ValueError:
            continue
    else:
        raise ImportError('WebKit2 no disponible — instala libwebkit2gtk-4.1-0 y gir1.2-webkit2-4.1')

    gi.require_version('Gtk', '3.0')
    from gi.repository import GLib, Gtk, WebKit2

    GLib.set_prgname('vigia')
    GLib.set_application_name('VIGIA')

    win = Gtk.Window(title='VIGIA — Panel del Profesor')
    win.set_default_size(1280, 800)

    icon_path = os.path.join(SCRIPT_DIR, 'img', 'logo2_mini.png')
    if os.path.exists(icon_path):
        win.set_icon_from_file(icon_path)

    webview = WebKit2.WebView()

    settings = webview.get_settings()
    try:
        settings.set_hardware_acceleration_policy(
            WebKit2.HardwareAccelerationPolicy.NEVER
        )
    except AttributeError:
        pass
    settings.set_enable_media_stream(True)
    settings.set_enable_mediasource(True)
    settings.set_media_playback_requires_user_gesture(False)

    webview.load_uri(url)
    win.add(webview)

    def _on_destroy(*_):
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        Gtk.main_quit()

    win.connect('destroy', _on_destroy)
    win.show_all()
    Gtk.main()


def run_browser_fallback(url: str, proc) -> None:  # proc puede ser None
    import webbrowser
    webbrowser.open(url)
    if proc is not None:
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
        proc.terminate()
    else:
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    server_py = os.path.join(SCRIPT_DIR, 'server.py')

    # Si Flask ya está corriendo (p.ej. como servicio systemd), reutilizarlo
    # sin arrancar un segundo proceso.
    if wait_for_port(port, timeout=1.5):
        print(f'[VIGIA] Servidor detectado en :{port}, reutilizando…')
        proc = None
    else:
        proc = subprocess.Popen(
            [sys.executable, server_py, str(port)],
            env={**os.environ, 'VIGIA_TAURI': '1'},
            cwd=SCRIPT_DIR,
        )
        if not wait_for_port(port, 30):
            print('[VIGIA] Flask no respondió en 30 s', file=sys.stderr)
            proc.kill()
            sys.exit(1)

    # 1) Chrome/Chromium app mode — compartir pantalla funciona perfectamente
    base_url = f'http://localhost:{port}/'
    if run_chrome_app(base_url, proc):
        return

    # 2) WebKit2GTK — fallback si no hay Chrome/Chromium instalado
    print('[VIGIA] Chrome/Chromium no encontrado, usando WebKit2GTK…', file=sys.stderr)
    launcher_url = f'{base_url}?launcher=1'
    try:
        run_webview(launcher_url, proc)
    except Exception as exc:
        print(f'[VIGIA] WebKit2GTK no disponible ({exc}), abriendo navegador del sistema…',
              file=sys.stderr)
        run_browser_fallback(base_url, proc)


if __name__ == '__main__':
    main()
