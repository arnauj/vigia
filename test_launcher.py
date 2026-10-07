"""Regresiones del lanzador reutilizando el servicio del profesor.

python3 test_launcher.py
No abre navegadores ni inicia/detiene el servicio real.
"""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import screen_capture
import desktop_setup


class TestLauncher(unittest.TestCase):
    def setUp(self):
        setup = patch.object(desktop_setup, 'configure_kde_capture', return_value=False)
        self.desktop_setup = setup.start()
        self.addCleanup(setup.stop)
        aliases = patch.object(self.launcher, 'install_pin_aliases')
        self.pin_aliases = aliases.start()
        self.addCleanup(aliases.stop)
        share = patch.object(self.launcher, 'share_session_env')
        self.share_env = share.start()
        self.addCleanup(share.stop)
        ready = patch.object(self.launcher, 'wait_for_current_server', return_value=True)
        self.server_ready = ready.start()
        self.addCleanup(ready.stop)

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            'vigia_launcher', Path(__file__).with_name('vigia-launcher.py'))
        cls.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.launcher)

    def test_chrome_inherits_capture_choice_when_reusing_service(self):
        with patch.dict('os.environ', {'XDG_CURRENT_DESKTOP': 'KDE'}), \
             patch.object(screen_capture, 'is_wayland', return_value=True), \
             patch.object(self.launcher.platform_utils, 'IS_LINUX', True), \
             patch.object(self.launcher.sys, 'argv', ['vigia-launcher.py', '5001']), \
             patch.object(self.launcher, 'wait_for_port', return_value=True), \
             patch.object(self.launcher, 'run_chrome_app', return_value=True) as chrome, \
             patch.object(self.launcher.subprocess, 'Popen') as start:
            self.launcher.main()
        chrome.assert_called_once_with('http://localhost:5001/?capture=server', None)
        self.pin_aliases.assert_called_once_with('http://localhost:5001/?capture=server', 5001)
        # El servicio arrancó antes del login: recibe el entorno de la sesión.
        self.share_env.assert_called_once_with(5001)
        start.assert_not_called()
        self.desktop_setup.assert_called_once_with()
        self.server_ready.assert_called_once_with(5001, timeout=3)

    def test_server_started_outside_session_is_replaced(self):
        info = {'app': 'vigia-server', 'version': 'x', 'graphical': False, 'session': ''}
        with patch.object(self.launcher.platform_utils, 'IS_LINUX', True), \
             patch.object(self.launcher.sys, 'argv', ['vigia-launcher.py']), \
             patch.object(self.launcher, 'wait_for_port', return_value=True), \
             patch.object(self.launcher, 'server_info', return_value=info), \
             patch.object(self.launcher, 'retire_outside_server', return_value=True) as retire, \
             patch.object(self.launcher, 'run_chrome_app', return_value=True) as chrome, \
             patch.object(self.launcher.subprocess, 'Popen') as start:
            self.launcher.main()
        retire.assert_called_once_with(5000, info)
        start.assert_called_once()
        self.assertIs(chrome.call_args[0][1], start.return_value)

    def test_server_of_user_still_logged_in_is_reused_with_browser_capture(self):
        import os
        info = {'app': 'vigia-server', 'version': 'x', 'graphical': True,
                'session': '9', 'uid': os.getuid() + 1, 'user': 'profesor'}
        with patch.object(self.launcher.platform_utils, 'IS_LINUX', True), \
             patch.object(self.launcher.sys, 'argv', ['vigia-launcher.py']), \
             patch.object(self.launcher, 'wait_for_port', return_value=True), \
             patch.object(self.launcher, 'server_info', return_value=info), \
             patch.object(self.launcher, 'retire_outside_server', return_value=False), \
             patch.object(self.launcher, 'run_chrome_app', return_value=True) as chrome, \
             patch.object(self.launcher.subprocess, 'Popen') as start:
            self.launcher.main()
        start.assert_not_called()
        chrome.assert_called_once_with('http://localhost:5000/?capture=browser', None)
        self.share_env.assert_not_called()

    def test_launcher_started_server_dies_with_launcher(self):
        import os
        with patch.object(self.launcher.platform_utils, 'IS_LINUX', True), \
             patch.object(self.launcher.platform_utils, 'IS_WINDOWS', False), \
             patch.object(self.launcher.sys, 'argv', ['vigia-launcher.py']), \
             patch.object(self.launcher, 'wait_for_port', return_value=False), \
             patch.object(self.launcher, 'run_chrome_app', return_value=True), \
             patch.object(self.launcher.subprocess, 'Popen') as start:
            self.launcher.main()
        self.assertEqual(start.call_args.kwargs['env']['VIGIA_PARENT_PID'], str(os.getpid()))

    def test_old_server_on_port_is_not_reused(self):
        self.server_ready.return_value = False
        with patch.object(self.launcher.sys, 'argv', ['vigia-launcher.py']), \
             patch.object(self.launcher, 'wait_for_port', return_value=True), \
             patch.object(self.launcher, 'report_server_mismatch') as report, \
             patch.object(self.launcher, 'run_chrome_app') as chrome, \
             self.assertRaises(SystemExit):
            self.launcher.main()
        report.assert_called_once_with(5000)
        chrome.assert_not_called()

    def test_webview_and_browser_fallback_preserve_capture_choice(self):
        with patch.dict('os.environ', {'XDG_CURRENT_DESKTOP': 'KDE'}), \
             patch.object(screen_capture, 'is_wayland', return_value=True), \
             patch.object(self.launcher.platform_utils, 'IS_LINUX', True), \
             patch.object(self.launcher.sys, 'argv', ['vigia-launcher.py']), \
             patch.object(self.launcher, 'wait_for_port', return_value=True), \
             patch.object(self.launcher, 'run_chrome_app', return_value=False), \
             patch.object(self.launcher, 'run_webview', side_effect=ImportError('Sin WebKit')) as webview, \
             patch.object(self.launcher, 'run_browser_fallback') as browser:
            self.launcher.main()
        webview.assert_called_once_with('http://localhost:5000/?capture=server&launcher=1', None)
        browser.assert_called_once_with('http://localhost:5000/?capture=server', None)

    def test_other_platforms_and_x11_keep_browser_capture(self):
        for linux, wayland in [(False, True), (True, False)]:
            with self.subTest(linux=linux, wayland=wayland), \
                 patch.dict('os.environ', {'XDG_CURRENT_DESKTOP': 'KDE'}), \
                 patch.object(self.launcher.platform_utils, 'IS_LINUX', linux), \
                 patch.object(screen_capture, 'is_wayland', return_value=wayland):
                self.assertEqual(self.launcher.dashboard_url(5000), 'http://localhost:5000/')


if __name__ == '__main__':
    unittest.main()
