"""Regresiones del servicio sin entorno y del instalador KDE, sin tocar la sesión real."""

import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import desktop_session as session
import desktop_setup as setup
import screen_capture


class TestSessionEnvironment(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.runtime = Path(temp.name)
        env = patch.dict(os.environ, {'XDG_RUNTIME_DIR': str(self.runtime)}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        manager = patch.object(session, 'manager_environment', return_value={})
        self.manager = manager.start()
        self.addCleanup(manager.stop)
        desktops = patch.object(session, 'desktop_environments', return_value=[])
        self.desktops = desktops.start()
        self.addCleanup(desktops.stop)

    def socket(self, name):
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(self.runtime / name))
        self.addCleanup(sock.close)

    def test_service_started_before_login_recovers_session_and_bus_later(self):
        self.assertEqual(screen_capture.session_type(), 'unknown')
        self.socket('bus')
        self.socket('wayland-1')
        self.manager.return_value = {
            'WAYLAND_DISPLAY': 'wayland-1', 'DISPLAY': ':1',
            'XAUTHORITY': '/tmp/xauth-test', 'XDG_CURRENT_DESKTOP': 'KDE',
            'XDG_SESSION_TYPE': 'wayland', 'KWIN_COMPOSE': 'Q',
        }
        self.assertEqual(screen_capture.session_type(), 'wayland')
        self.assertEqual(os.environ['DISPLAY'], ':1')
        self.assertEqual(os.environ['XAUTHORITY'], '/tmp/xauth-test')
        self.assertEqual(os.environ['DBUS_SESSION_BUS_ADDRESS'],
                         f'unix:path={self.runtime}/bus')
        self.assertNotIn('KWIN_COMPOSE', os.environ)
        self.assertEqual(screen_capture._cli_tool_order()[0], 'spectacle')

    def test_recovers_x11_authority_from_desktop_when_manager_has_no_display(self):
        self.desktops.return_value = [{
            'DISPLAY': ':2', 'XAUTHORITY': '/run/user/1000/xauth',
            'XDG_SESSION_TYPE': 'x11', 'XDG_CURRENT_DESKTOP': 'KDE',
        }]
        self.assertEqual(screen_capture.session_type(), 'x11')
        self.assertEqual(os.environ['DISPLAY'], ':2')
        self.assertEqual(os.environ['XAUTHORITY'], '/run/user/1000/xauth')

    def test_explicit_x11_is_preserved_even_with_wayland_socket(self):
        self.socket('wayland-0')
        os.environ.update(DISPLAY=':3', XDG_SESSION_TYPE='x11', XDG_CURRENT_DESKTOP='KDE')
        self.assertEqual(screen_capture.session_type(), 'x11')
        self.manager.assert_not_called()

    def test_explicit_x11_without_desktop_name_keeps_its_display(self):
        self.socket('wayland-0')
        self.manager.return_value = {'DISPLAY': ':1', 'WAYLAND_DISPLAY': 'wayland-0',
                                     'XDG_CURRENT_DESKTOP': 'KDE'}
        os.environ.update(DISPLAY=':3', XDG_SESSION_TYPE='x11')
        self.assertEqual(screen_capture.session_type(), 'x11')
        self.assertEqual(os.environ['DISPLAY'], ':3')

    def test_manager_without_xauthority_is_completed_from_matching_desktop(self):
        self.manager.return_value = {'DISPLAY': ':2', 'XDG_SESSION_TYPE': 'x11'}
        self.desktops.return_value = [{'DISPLAY': ':2', 'XAUTHORITY': '/tmp/xauth-plasma',
                                      'XDG_CURRENT_DESKTOP': 'KDE'}]
        self.assertEqual(screen_capture.session_type(), 'x11')
        self.assertEqual(os.environ['XAUTHORITY'], '/tmp/xauth-plasma')

    def test_ignores_lockfiles_and_ambiguous_wayland_sockets(self):
        (self.runtime / 'wayland-0.lock').touch()
        (self.runtime / 'wayland-0').touch()
        self.assertEqual(screen_capture.session_type(), 'unknown')
        (self.runtime / 'wayland-0').unlink()
        self.socket('wayland-0')
        self.socket('wayland-1')
        self.assertEqual(screen_capture.session_type(), 'unknown')

    def test_recovers_new_socket_after_logout(self):
        os.environ.update(WAYLAND_DISPLAY='wayland-old', XDG_SESSION_TYPE='wayland')
        self.socket('wayland-2')
        self.assertEqual(screen_capture.session_type(), 'wayland')
        self.assertEqual(os.environ['WAYLAND_DISPLAY'], 'wayland-2')

    def test_launcher_session_wins_over_stale_service_environment(self):
        self.socket('bus')
        self.socket('wayland-0')
        self.socket('wayland-1')        # dos sockets: el servicio no sabría cuál
        self.assertEqual(screen_capture.session_type(), 'unknown')
        self.assertTrue(session.set_session_override({
            'WAYLAND_DISPLAY': 'wayland-1', 'XDG_CURRENT_DESKTOP': 'KDE',
            'XDG_RUNTIME_DIR': '/run/user/otro', 'PATH': '/malo'}))
        self.assertEqual(screen_capture.session_type(), 'wayland')
        self.assertEqual(os.environ['WAYLAND_DISPLAY'], 'wayland-1')
        self.assertEqual(os.environ['XDG_RUNTIME_DIR'], str(self.runtime))
        self.assertNotEqual(os.environ.get('PATH'), '/malo')
        self.addCleanup(session._session_override.clear)

    def test_launcher_session_without_own_socket_is_rejected(self):
        self.assertFalse(session.set_session_override({'WAYLAND_DISPLAY': 'wayland-9'}))
        self.assertEqual(session._session_override, {})

    def test_missing_session_does_not_launch_crashing_tools(self):
        with patch.object(screen_capture, 'CliBackend') as cli, \
                patch.object(screen_capture, 'MssBackend') as mss:
            with self.assertRaisesRegex(screen_capture.CaptureError, 'sesión gráfica'):
                screen_capture.create_capturer(allow_portal=False)
        cli.assert_not_called()
        mss.assert_not_called()


class TestWaylandMonitors(unittest.TestCase):
    KSCREEN = {'outputs': [
        {'name': 'HDMI-A-1', 'enabled': True, 'connected': True, 'priority': 2,
         'pos': {'x': 1536, 'y': 0}, 'scale': 1, 'rotation': 1,
         'size': {'width': 1920, 'height': 1080}},
        {'name': 'eDP-1', 'enabled': True, 'connected': True, 'priority': 1,
         'pos': {'x': 0, 'y': 0}, 'scale': 1.25, 'rotation': 1,
         'currentModeId': '3', 'modes': [{'id': '3', 'size': {'width': 1920, 'height': 1200}}]},
        {'name': 'DP-2', 'enabled': False, 'connected': True,
         'pos': {'x': 0, 'y': 0}, 'scale': 1, 'size': {'width': 800, 'height': 600}},
    ]}

    def test_kscreen_logical_geometry_sorted_left_to_right(self):
        import json
        done = subprocess.CompletedProcess([], 0, json.dumps(self.KSCREEN), '')
        with patch.object(screen_capture.shutil, 'which', return_value='/usr/bin/kscreen-doctor'), \
             patch.object(screen_capture.subprocess, 'run', return_value=done):
            mons = screen_capture.wayland_monitors()
        self.assertEqual([(m['name'], m['left'], m['width'], m['height'], m['primary']) for m in mons],
                         [('eDP-1', 0, 1536, 960, True), ('HDMI-A-1', 1536, 1920, 1080, False)])

    def test_xrandr_fallback(self):
        out = ('Monitors: 2\n 0: +*XWAYLAND0 1920/510x1080/290+0+0  XWAYLAND0\n'
               ' 1: +XWAYLAND1 1280/340x1024/270+1920+0  XWAYLAND1\n')
        done = subprocess.CompletedProcess([], 0, out, '')
        with patch.dict(os.environ, {'DISPLAY': ':0'}), \
             patch.object(screen_capture, '_monitores_kscreen', return_value=[]), \
             patch.object(screen_capture.shutil, 'which', return_value='/usr/bin/xrandr'), \
             patch.object(screen_capture.subprocess, 'run', return_value=done):
            mons = screen_capture.wayland_monitors()
        self.assertEqual([(m['left'], m['width'], m['height'], m['primary']) for m in mons],
                         [(0, 1920, 1080, True), (1920, 1280, 1024, False)])

    def test_selected_monitor_is_cropped_from_hidpi_desktop(self):
        from PIL import Image
        full = Image.new('RGB', (2 * 3456, 2 * 1080))   # escritorio a escala 2
        full.paste((255, 0, 0), (2 * 1536, 0, full.width, full.height))
        cap = object.__new__(screen_capture.CliBackend)
        cap.index = 0; cap._geom = None
        cap._grab_full = lambda max_age=0.0: full
        mons = [{'left': 0, 'top': 0, 'width': 1536, 'height': 960},
                {'left': 1536, 'top': 0, 'width': 1920, 'height': 1080}]
        with patch.object(screen_capture, 'wayland_monitors', return_value=mons):
            cap.set_monitor(2)
            img = cap.grab()
            self.assertEqual(img.size, (3840, 2160))
            self.assertEqual(img.getpixel((10, 10)), (255, 0, 0))
            self.assertEqual(cap.monitor()['width'], 3840)
            cap.set_monitor(7)          # fuera de rango → todo el escritorio
            self.assertEqual(cap.grab().size, full.size)


class TestKdeSetup(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = Path(temp.name)
        self.backend = 'OpenGL'
        self.commands = []
        self.env = {'XDG_CONFIG_HOME': str(self.config), 'XDG_CURRENT_DESKTOP': 'KDE'}
        for mocked in (
            patch.dict(os.environ, self.env, clear=True),
            patch.object(setup.os, 'getuid', return_value=1000),
            patch.object(setup.shutil, 'which', side_effect=lambda name: '/usr/bin/' + name),
            patch.object(session, 'capture_environment', return_value=self.env),
            patch.object(session, 'manager_environment', return_value={}),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)
        desktops = patch.object(session, 'desktop_environments', return_value=[])
        self.desktops = desktops.start()
        self.addCleanup(desktops.stop)
        runner = patch.object(setup, '_run', side_effect=self.run_command)
        runner.start()
        self.addCleanup(runner.stop)

    def run_command(self, args, env=None):
        self.commands.append(args)
        if 'kreadconfig' in args[0]:
            return subprocess.CompletedProcess(args, 0, self.backend + '\n', '')
        if 'kwriteconfig' in args[0]:
            self.backend = args[-1]
        return subprocess.CompletedProcess(args, 0, '', '')

    @property
    def dropin(self):
        return self.config / 'systemd/user/plasma-kwin_wayland.service.d/90-vigia-opengl.conf'

    def test_forced_q_in_kwin_process_is_fixed_persistently_and_idempotently(self):
        self.desktops.return_value = [{'KWIN_COMPOSE': 'Q'}]
        self.assertTrue(setup.configure_kde_capture())
        self.assertEqual(self.backend, 'OpenGL')
        self.assertIn('UnsetEnvironment=KWIN_COMPOSE', self.dropin.read_text())
        self.assertFalse(setup.configure_kde_capture())
        self.assertTrue(all('restart' not in cmd and 'stop' not in cmd for cmd in self.commands))

    def test_backend_qpainter_is_fixed_without_forced_environment(self):
        self.backend = 'QPainter'
        self.assertTrue(setup.configure_kde_capture())
        self.assertEqual(self.backend, 'OpenGL')
        self.assertTrue(self.dropin.exists())

    def test_healthy_or_driver_fallback_configuration_is_unchanged(self):
        for backend in ('OpenGL', ''):
            self.backend = backend
            self.assertFalse(setup.configure_kde_capture())
        self.assertFalse(self.dropin.exists())
        self.assertFalse(any('kwriteconfig' in cmd[0] for cmd in self.commands))

    def test_no_root_configuration_is_written(self):
        with patch.object(setup.os, 'getuid', return_value=0):
            self.assertFalse(setup.configure_kde_capture())
        self.assertFalse(self.commands)

    def test_missing_kde_tools_is_a_noop(self):
        with patch.object(setup.shutil, 'which', return_value=None):
            self.assertFalse(setup.configure_kde_capture())
        self.assertFalse(self.commands)

    def test_other_desktop_is_not_reconfigured(self):
        self.env['XDG_CURRENT_DESKTOP'] = 'GNOME'
        self.backend = 'QPainter'
        self.assertFalse(setup.configure_kde_capture())
        self.assertFalse(self.dropin.exists())


class TestInstallerUser(unittest.TestCase):
    def test_installation_without_systemd_can_finish_without_a_graphical_user(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(setup.os, 'getuid', return_value=0), \
             patch.object(setup, '_run', side_effect=FileNotFoundError):
            self.assertEqual(setup.installation_user(), '')

    def test_discover_selects_active_local_graphical_user(self):
        responses = [
            subprocess.CompletedProcess([], 0, '3 1000 profesor seat0\n4 1001 remoto\n', ''),
            subprocess.CompletedProcess([], 0, 'Name=profesor\nActive=yes\nRemote=no\nType=wayland\n', ''),
            subprocess.CompletedProcess([], 0, 'Name=remoto\nActive=yes\nRemote=yes\nType=x11\n', ''),
        ]
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(setup.os, 'getuid', return_value=0), \
             patch.object(setup, '_run', side_effect=responses):
            self.assertEqual(setup.installation_user(), 'profesor')


class TestPinAliases(unittest.TestCase):
    """KDE: fijar la ventana Chrome --app del panel debe sobrevivir al reinicio."""

    def test_app_id_matches_chrome_wayland_naming(self):
        self.assertEqual(setup.chrome_app_ids('http://localhost:5000/?capture=server'),
                         ['chrome-localhost__-Default', 'chromium-localhost__-Default'])

    def test_aliases_are_hidden_launchers_matching_the_window(self):
        with tempfile.TemporaryDirectory() as home, \
             patch.object(setup.shutil, 'which', return_value=None):
            written = setup.install_chrome_app_aliases(
                'http://localhost:5000/', '"/usr/bin/python3" "/opt/v/vigia-launcher.py"',
                '/opt/v/logo.png', data_home=home, system_dirs=[])
            self.assertEqual(len(written), 2)
            entry = (Path(home) / 'applications/chrome-localhost__-Default.desktop').read_text()
            self.assertIn('Exec="/usr/bin/python3" "/opt/v/vigia-launcher.py"\n', entry)
            self.assertIn('NoDisplay=true\n', entry)
            self.assertIn('StartupWMClass=chrome-localhost__-Default\n', entry)
            # Idempotente: no reescribe ni refresca la caché de KDE en cada arranque.
            self.assertEqual(setup.install_chrome_app_aliases(
                'http://localhost:5000/', '"/usr/bin/python3" "/opt/v/vigia-launcher.py"',
                '/opt/v/logo.png', data_home=home, system_dirs=[]), [])

    def test_package_alias_is_not_duplicated_per_user(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as system:
            apps = Path(system) / 'applications'
            apps.mkdir()
            for app_id in setup.chrome_app_ids('http://localhost:5000/'):
                (apps / f'{app_id}.desktop').write_text('[Desktop Entry]\n')
            self.assertEqual(setup.install_chrome_app_aliases(
                'http://localhost:5000/', 'x', 'y', data_home=home, system_dirs=[system]), [])
            self.assertFalse((Path(home) / 'applications').exists())


if __name__ == '__main__':
    unittest.main()
