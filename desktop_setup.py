#!/usr/bin/env python3
"""Configuración condicional de KDE, ejecutada como el usuario del profesor."""

import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

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


# ── Fijar VIGIA en el gestor de tareas de KDE ────────────────────────────────
# En Wayland, Chrome/Chromium NO usa --class para las ventanas --app: su app_id
# es «chrome-<host>_<ruta>-<perfil>» (p. ej. chrome-localhost__-Default). Plasma
# no encontraba ningún .desktop con ese nombre ni con ese StartupWMClass, así que
# «Fijar en el gestor de tareas» guardaba un lanzador provisional que desaparecía
# al reiniciar. Un .desktop oculto con ese nombre exacto da a Plasma un lanzador
# estable (applications:<app_id>.desktop) que vuelve a abrir VIGIA.
CHROME_APP_PREFIXES = ('chrome', 'chromium')


def chrome_app_ids(url, profile='Default'):
    """app_id Wayland que Chrome/Chromium asignan a una ventana --app=url."""
    parts = urlsplit(url)
    name = f'{parts.hostname or ""}_{parts.path or "/"}'.replace('/', '_')
    return [f'{prefix}-{name}-{profile}' for prefix in CHROME_APP_PREFIXES]


def chrome_alias_entry(app_id, exec_line, icon):
    return ('[Desktop Entry]\n'
            'Type=Application\n'
            'Name=VIGIA Servidor\n'
            'Comment=Panel del profesor — supervisión de aula\n'
            f'Exec={exec_line}\n'
            f'Icon={icon}\n'
            'Terminal=false\n'
            'NoDisplay=true\n'
            f'StartupWMClass={app_id}\n')


def _xdg_data_dirs():
    dirs = os.environ.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share'
    return [Path(d) for d in dirs.split(':') if d]


def install_chrome_app_aliases(url, exec_line, icon, data_home=None, system_dirs=None):
    """Crea (si faltan) los alias por usuario. Devuelve las rutas escritas.

    Si el paquete ya instala el alias en el sistema no se duplica: el del
    usuario quedaría apuntando a una ruta vieja al desinstalar el .deb.
    """
    if data_home is None:
        data_home = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    apps = Path(data_home) / 'applications'
    system_dirs = _xdg_data_dirs() if system_dirs is None else system_dirs
    written = []
    for app_id in chrome_app_ids(url):
        name = f'{app_id}.desktop'
        if any((Path(d) / 'applications' / name).is_file() for d in system_dirs):
            continue
        path = apps / name
        content = chrome_alias_entry(app_id, exec_line, icon)
        try:
            if path.is_file() and path.read_text(encoding='utf-8') == content:
                continue
            apps.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        except OSError as error:
            print(f'[VIGIA] No se pudo crear {path}: {error}', file=sys.stderr)
            continue
        written.append(path)
    if written:
        # Plasma lee los .desktop de su caché (sycoca); refrescarla sin esperar.
        tool = shutil.which('kbuildsycoca6') or shutil.which('kbuildsycoca5')
        if tool:
            try:
                subprocess.Popen([tool], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
    return written


if __name__ == '__main__':
    try:
        if '--installation-user' in sys.argv:
            print(installation_user())
        else:
            configure_kde_capture()
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f'[VIGIA] No se pudo preparar la sesión gráfica: {error}', file=sys.stderr)
        sys.exit(1)
