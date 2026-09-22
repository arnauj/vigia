"""Recupera la sesión gráfica del mismo usuario para servicios iniciados al boot.

No consulta sesiones de otros usuarios ni presupone DISPLAY=:0. El gestor de
systemd se actualiza al iniciar Plasma, pero un proceso ya arrancado conserva
el entorno anterior: hay que consultarlo de nuevo cuando se pide una captura.
"""

import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys


SESSION_KEYS = (
    'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR',
    'DBUS_SESSION_BUS_ADDRESS', 'XDG_SESSION_TYPE', 'XDG_CURRENT_DESKTOP',
    'XDG_CONFIG_HOME',
)
_DESKTOPS = ('plasmashell', 'gnome-shell', 'kwin_wayland', 'kwin_x11',
             'xfce4-session', 'sway')


def _owned(path, *, socket=False):
    try:
        info = Path(path).stat()
        return info.st_uid == os.getuid() and (
            stat.S_ISSOCK(info.st_mode) if socket else stat.S_ISDIR(info.st_mode))
    except (OSError, ValueError):
        return False


def runtime_environment():
    for path in (os.environ.get('XDG_RUNTIME_DIR'), f'/run/user/{os.getuid()}'):
        if path and _owned(path):
            env = {'XDG_RUNTIME_DIR': path}
            bus = str(Path(path) / 'bus')
            if _owned(bus, socket=True):
                env['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path={bus}'
            return env
    return {}


def manager_environment(base):
    """Solo se leen las claves de sesión; nunca se ejecuta/evalúa su contenido."""
    if not base.get('DBUS_SESSION_BUS_ADDRESS'):
        return {}
    try:
        result = subprocess.run(
            ['systemctl', '--user', 'show-environment'],
            env={**os.environ, **base}, capture_output=True, text=True, timeout=3)
        env = {}
        for line in result.stdout.splitlines() if result.returncode == 0 else []:
            fields = shlex.split(line)
            if len(fields) == 1:
                key, sep, value = fields[0].partition('=')
                if sep and key in (*SESSION_KEYS, 'KWIN_COMPOSE'):
                    env[key] = value
        return env
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def desktop_environments():
    """Respaldo para escritorios que no exportan su entorno a systemd."""
    found = []
    try:
        processes = Path('/proc').iterdir()
        for proc in processes:
            if not proc.name.isdecimal():
                continue
            try:
                if proc.stat().st_uid != os.getuid():
                    continue
                name = (proc / 'comm').read_text().strip()
                if name not in _DESKTOPS:
                    continue
                env = {}
                for item in (proc / 'environ').read_bytes().split(b'\0'):
                    key, sep, value = item.partition(b'=')
                    key = os.fsdecode(key)
                    if sep and key in (*SESSION_KEYS, 'KWIN_COMPOSE'):
                        env[key] = os.fsdecode(value)
                found.append((_DESKTOPS.index(name), env))
            except OSError:
                continue
    except OSError:
        pass
    return [env for _, env in sorted(found, key=lambda item: item[0])]


def _wayland_available(env):
    display = env.get('WAYLAND_DISPLAY')
    runtime = env.get('XDG_RUNTIME_DIR')
    return bool(display and runtime and _owned(Path(runtime) / display, socket=True))


def capture_environment():
    """Devuelve únicamente las variables necesarias, sin modificar el escritorio."""
    env = {key: os.environ[key] for key in SESSION_KEYS if os.environ.get(key)}
    if not sys.platform.startswith('linux'):
        return env
    env.update(runtime_environment())
    # Una sesión heredada completa tiene prioridad (incluidas sesiones X11).
    complete = (env.get('XDG_SESSION_TYPE') == 'x11' and env.get('DISPLAY')) or \
        _wayland_available(env)
    if not complete or not env.get('XDG_CURRENT_DESKTOP'):
        manager = manager_environment(env)
        candidates = [manager]
        # Algunos gestores exportan DISPLAY pero omiten la cookie X11. Las
        # aplicaciones del escritorio sí heredan XAUTHORITY de la sesión.
        if not manager.get('XAUTHORITY') or not manager.get('XDG_CURRENT_DESKTOP'):
            desktops = desktop_environments()
            for source in desktops:
                if manager.get('DISPLAY') and source.get('DISPLAY') == manager['DISPLAY']:
                    manager = {**source, **manager}
                    candidates[0] = manager
                    break
            candidates += desktops
        for source in candidates:
            if not source:
                continue
            updates = {k: v for k, v in source.items() if k in SESSION_KEYS}
            if complete:
                updates = {k: v for k, v in updates.items() if k not in env and
                           k not in ('DISPLAY', 'WAYLAND_DISPLAY', 'XDG_SESSION_TYPE')}
            candidate = {**env, **updates}
            # No aceptar rutas runtime pertenecientes a otro usuario.
            candidate.update(runtime_environment())
            if _wayland_available(candidate) or candidate.get('DISPLAY'):
                env = candidate
                break
    if env.get('WAYLAND_DISPLAY') and not _wayland_available(env):
        env.pop('WAYLAND_DISPLAY', None)
    # No convertir una sesión X11 explícita en Wayland por un socket sobrante.
    if not env.get('WAYLAND_DISPLAY') and env.get('XDG_SESSION_TYPE') != 'x11':
        runtime = env.get('XDG_RUNTIME_DIR')
        if runtime:
            try:
                sockets = [p for p in Path(runtime).glob('wayland-*')
                           if _owned(p, socket=True)]
                if len(sockets) == 1:
                    env['WAYLAND_DISPLAY'] = sockets[0].name
            except OSError:
                pass
    if env.get('WAYLAND_DISPLAY'):
        env['XDG_SESSION_TYPE'] = 'wayland'
    elif env.get('DISPLAY'):
        env['XDG_SESSION_TYPE'] = 'x11'
    else:
        env.pop('XDG_SESSION_TYPE', None)
    return env


def ensure_session_env():
    if not sys.platform.startswith('linux'):
        return
    env = capture_environment()
    for key in ('WAYLAND_DISPLAY', 'XDG_SESSION_TYPE'):
        if key not in env:
            os.environ.pop(key, None)
    os.environ.update(env)
