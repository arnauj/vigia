"""Identifica el servidor activo y retira procesos antiguos durante la instalación."""

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from vigia_version import VERSION


def server_version(port):
    try:
        # La comprobación local no debe pasar por un proxy HTTP del aula.
        with build_opener(ProxyHandler({})).open(
                f'http://127.0.0.1:{int(port)}/api/version', timeout=1) as response:
            data = json.loads(response.read(8192))
        if data.get('app') == 'vigia-server':
            return data.get('version')
    except (OSError, ValueError, AttributeError, URLError):
        pass
    return None


def wait_for_current_server(port, timeout=15):
    deadline = time.monotonic() + timeout
    while True:
        if server_version(port) == VERSION:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)


def installed_server_processes(directory, proc_root=Path('/proc')):
    """Solo intérpretes ejecutando el server.py exacto de esta instalación.

    No coincide con comandos que solo mencionan su ruta (un editor, una orden
    shell o el propio instalador), ni con copias del proyecto en otra carpeta.
    """
    target = Path(directory).resolve() / 'server.py'
    found = []
    for proc in proc_root.iterdir():
        if not proc.name.isdecimal() or int(proc.name) == os.getpid():
            continue
        try:
            args = [os.fsdecode(arg) for arg in (proc / 'cmdline').read_bytes().split(b'\0') if arg]
            if len(args) < 2 or not Path(args[0]).name.startswith('python'):
                continue
            script = None
            for arg in args[1:]:
                if arg in ('-c', '-m'):
                    break
                if arg.startswith('-'):
                    continue
                script = Path(arg)
                break
            if script is None:
                continue
            if not script.is_absolute():
                script = (proc / 'cwd').resolve() / script
            if script.resolve() == target:
                found.append(int(proc.name))
        except (OSError, ValueError):
            continue
    return found


def stop_installed_servers(directory, timeout=5):
    pids = installed_server_processes(directory)
    for pid in pids:
        # Volver a comprobar la identidad antes de enviar la señal.
        if pid not in installed_server_processes(directory):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    while installed_server_processes(directory):
        if time.monotonic() >= deadline:
            raise RuntimeError('Un servidor VIGIA anterior sigue activo. Cierra VIGIA '
                               'y vuelve a ejecutar la instalación.')
        time.sleep(0.1)
    return len(pids)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--stop-installed', metavar='DIRECTORIO')
    action.add_argument('--wait-current', type=int, metavar='PUERTO')
    options = parser.parse_args()
    try:
        if options.stop_installed:
            count = stop_installed_servers(options.stop_installed)
            print(f'[VIGIA] Procesos anteriores retirados: {count}')
        elif not wait_for_current_server(options.wait_current):
            raise RuntimeError(f'El puerto {options.wait_current} no responde con VIGIA {VERSION}. '
                               'Comprueba que no siga abierto un servidor de otra instalación.')
    except (OSError, RuntimeError) as error:
        print(f'[VIGIA] {error}', file=sys.stderr)
        sys.exit(1)
