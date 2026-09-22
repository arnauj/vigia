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
        start.assert_not_called()
        self.desktop_setup.assert_called_once_with()

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
