#!/usr/bin/env python3
"""
VIGIA — Lanzador con ventana nativa (GTK + WebKit2GTK).
Arranca Flask en subproceso y abre una ventana WebKit sin chrome de navegador.
Requiere: python3-gi, gir1.2-webkit2-4.1, libwebkit2gtk-4.1-0
"""
import os
import sys
import socket
import subprocess
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def wait_for_port(port: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def run_webview(url: str, proc: subprocess.Popen) -> None:
    import gi
    # Intentar WebKit2 4.1 (Ubuntu 22.04+), luego 4.0
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

    # WM_CLASS = 'vigia' → el taskbar lo asocia con el .desktop y muestra el icono
    GLib.set_prgname('vigia')
    GLib.set_application_name('VIGIA')

    win = Gtk.Window(title='VIGIA — Panel del Profesor')
    win.set_default_size(1280, 800)

    icon_path = os.path.join(SCRIPT_DIR, 'img', 'logo2_mini.png')
    if os.path.exists(icon_path):
        win.set_icon_from_file(icon_path)

    webview = WebKit2.WebView()

    # Configurar WebKit para permitir MediaStream y WebRTC
    settings = webview.get_settings()
    settings.set_enable_media_stream(True)
    settings.set_enable_mediasource(True)
    settings.set_media_playback_requires_user_gesture(False)

    webview.load_uri(url)
    win.add(webview)

    def _on_destroy(*_):
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        Gtk.main_quit()

    win.connect('destroy', _on_destroy)
    win.show_all()
    Gtk.main()


def run_browser_fallback(url: str, proc: subprocess.Popen) -> None:
    import webbrowser
    webbrowser.open(url)
    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    proc.terminate()


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    server_py = os.path.join(SCRIPT_DIR, 'server.py')

    # Arrancar Flask (VIGIA_TAURI suprime apertura de navegador desde server.py)
    proc = subprocess.Popen(
        [sys.executable, server_py, str(port)],
        env={**os.environ, 'VIGIA_TAURI': '1'},
        cwd=SCRIPT_DIR,
    )

    if not wait_for_port(port, 30):
        print('[VIGIA] Flask no respondió en 30 s', file=sys.stderr)
        proc.kill()
        sys.exit(1)

    url = f'http://localhost:{port}/?launcher=1'
    try:
        run_webview(url, proc)
    except Exception as exc:
        print(f'[VIGIA] Ventana nativa no disponible ({exc}), abriendo navegador…',
              file=sys.stderr)
        run_browser_fallback(url, proc)


if __name__ == '__main__':
    main()
