#!/usr/bin/env python3
"""Configuración condicional de KDE, ejecutada como el usuario del profesor."""

import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys

import desktop_session


def _run(args, env=None):
    return subprocess.run(args, env=env, capture_output=True, text=True, timeout=5)


def installation_user():
    """sudo/Polkit o la única sesión gráfica local activa (Discover/PackageKit)."""
    candidates = [os.environ.get('SUDO_USER')]
    try:
        candidates.append(pwd.getpwuid(int(os.environ.get('PKEXEC_UID', '-1'))).pw_name)
    except (KeyError, ValueError):
        pass
    for name in candidates:
        try:
            if name and pwd.getpwnam(name).pw_uid != 0:
                return name
        except KeyError:
            pass
    if os.getuid() != 0:
        return pwd.getpwuid(os.getuid()).pw_name
    try:
        sessions = _run(['loginctl', 'list-sessions', '--no-legend', '--no-pager'])
    except (OSError, subprocess.TimeoutExpired):
        return ''  # chroot/instalación sin systemd: configurar al abrir VIGIA
    users = set()
    for line in sessions.stdout.splitlines():
        session = line.split()[0]
        result = _run(['loginctl', 'show-session', session, '-p', 'Active',
                       '-p', 'Remote', '-p', 'Type', '-p', 'Name'])
        props = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        if props.get('Active') == 'yes' and props.get('Remote') == 'no' and \
                props.get('Type') in ('wayland', 'x11') and props.get('Name') not in (None, 'root'):
            users.add(props['Name'])
    return users.pop() if len(users) == 1 else ''


def configure_kde_capture():
    """Retira QPainter SOLO si está forzado. No reinicia KWin ni la sesión."""
    if not sys.platform.startswith('linux') or os.getuid() == 0:
        return False
    reader = shutil.which('kreadconfig6') or shutil.which('kreadconfig5')
    writer = shutil.which('kwriteconfig6') or shutil.which('kwriteconfig5')
    if not reader or not writer or not shutil.which('kwin_wayland'):
        return False
    env = {**os.environ, **desktop_session.capture_environment()}
    sources = [env, desktop_session.manager_environment(env),
               *desktop_session.desktop_environments()]
    desktops = [source['XDG_CURRENT_DESKTOP'].lower() for source in sources
                if source.get('XDG_CURRENT_DESKTOP')]
    if desktops and not any('kde' in name or 'plasma' in name for name in desktops):
        return False
    forced = any(source.get('KWIN_COMPOSE', '').startswith('Q') for source in sources)
    result = _run([reader, '--file', 'kwinrc', '--group', 'Compositing',
                   '--key', 'Backend'], env)
    if not forced and result.stdout.strip() != 'QPainter':
        return False
    config = Path(env.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    dropin = config / 'systemd/user/plasma-kwin_wayland.service.d/90-vigia-opengl.conf'
    content = '[Service]\nUnsetEnvironment=KWIN_COMPOSE\n'
    changed = not dropin.exists() or dropin.read_text() != content or \
        result.stdout.strip() != 'OpenGL'
    if not changed:
        return False
    # kwriteconfig conserva las demás opciones, comentarios y grupos de kwinrc.
    result = _run([writer, '--file', 'kwinrc', '--group', 'Compositing',
                   '--key', 'Backend', 'OpenGL'], env)
    if result.returncode:
        raise RuntimeError('No se pudo seleccionar OpenGL en kwinrc')
    dropin.parent.mkdir(parents=True, exist_ok=True)
    dropin.write_text(content)
    _run(['systemctl', '--user', 'unset-environment', 'KWIN_COMPOSE'], env)
    _run(['systemctl', '--user', 'daemon-reload'], env)
    if changed:
        print('[VIGIA] Se ha corregido QPainter forzado en KDE. Guarda tu trabajo y '
              'reinicia el equipo para poder compartir pantalla.')
    return changed


if __name__ == '__main__':
    try:
        if '--installation-user' in sys.argv:
            print(installation_user())
        else:
            configure_kde_capture()
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f'[VIGIA] No se pudo preparar la sesión gráfica: {error}', file=sys.stderr)
        sys.exit(1)
