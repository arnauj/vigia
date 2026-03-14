#!/usr/bin/env python3
"""
VIGIA — Lanzador del panel del profesor (Windows).

Orden de preferencia para mostrar el dashboard:
  1. Chrome / Edge en modo --app (sin barra de herramientas,
     getDisplayMedia nativo)
  2. Navegador predeterminado del sistema (fallback)

Equivalente exacto de vigia-launcher.py para Windows.
"""
import os
import sys
import shutil
import socket
import tempfile
import subprocess
import time
import winreg

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Candidatos de Chrome/Edge/Chromium en Windows
_CHROMIUM_CANDIDATES = [
    # Chrome
    os.path.join(os.environ.get('PROGRAMFILES', 'C:\\Program Files'),
                 'Google', 'Chrome', 'Application', 'chrome.exe'),
    os.path.join(os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)'),
                 'Google', 'Chrome', 'Application', 'chrome.exe'),
    os.path.join(os.environ.get('LOCALAPPDATA', ''),
                 'Google', 'Chrome', 'Application', 'chrome.exe'),
    # Edge (basado en Chromium)
    os.path.join(os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)'),
                 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    os.path.join(os.environ.get('PROGRAMFILES', 'C:\\Program Files'),
                 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    # Chromium
    os.path.join(os.environ.get('LOCALAPPDATA', ''),
                 'Chromium', 'Application', 'chrome.exe'),
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
    """Busca Chrome, Edge o Chromium en las rutas estándar de Windows."""
    # Primero intentar en PATH
    for name in ('chrome', 'msedge', 'chromium'):
        path = shutil.which(name)
        if path:
            return path

    # Luego rutas conocidas
    for path in _CHROMIUM_CANDIDATES:
        if os.path.isfile(path):
            return path

    # Buscar en el registro de Windows
    try:
        for key_path in [
            r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe',
            r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe',
        ]:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                path, _ = winreg.QueryValueEx(key, '')
                winreg.CloseKey(key)
                if os.path.isfile(path):
                    return path
            except (WindowsError, FileNotFoundError):
                continue
    except Exception:
        pass

    return None


def run_chrome_app(url: str, proc) -> bool:
    """
    Intenta abrir el dashboard en Chrome/Edge modo app (sin toolbar).
    Devuelve True si se lanzó y completó su ciclo de vida.
    """
    browser = _find_chromium()
    if not browser:
        return False

    tmpdir = tempfile.mkdtemp(prefix='vigia-chrome-')
    name = os.path.basename(browser).replace('.exe', '')
    print(f'[VIGIA] Abriendo con {name} en modo app...')
    try:
        chrome = subprocess.Popen([
            browser,
            f'--app={url}',
            f'--user-data-dir={tmpdir}',
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
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmpdir, ignore_errors=True)

    return True


def run_browser_fallback(url: str, proc) -> None:
    """Fallback: abrir en el navegador predeterminado del sistema."""
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


def _check_service_running(port: int) -> bool:
    """Comprueba si el servidor ya está corriendo (como servicio o proceso)."""
    return wait_for_port(port, timeout=1.5)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    server_py = os.path.join(SCRIPT_DIR, 'server.py')

    # Si Flask ya está corriendo, reutilizarlo
    if _check_service_running(port):
        print(f'[VIGIA] Servidor detectado en :{port}, reutilizando...')
        proc = None
    else:
        proc = subprocess.Popen(
            [sys.executable, server_py, str(port)],
            cwd=SCRIPT_DIR,
        )
        if not wait_for_port(port, 30):
            print('[VIGIA] Flask no respondio en 30 s', file=sys.stderr)
            proc.kill()
            sys.exit(1)

    # 1) Chrome/Edge app mode
    base_url = f'http://localhost:{port}/'
    if run_chrome_app(base_url, proc):
        return

    # 2) Navegador del sistema como fallback
    print('[VIGIA] Chrome/Edge no encontrado, abriendo navegador del sistema...',
          file=sys.stderr)
    run_browser_fallback(base_url, proc)


if __name__ == '__main__':
    main()
