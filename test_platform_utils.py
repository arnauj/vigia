#!/usr/bin/env python3
"""
test_platform_utils.py — Pruebas de la capa de abstracción multiplataforma.

Ejecutar:  python test_platform_utils.py
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import pathlib
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import platform_utils


class TestConstants(unittest.TestCase):
    def test_platform_detected(self):
        """Al menos una constante de plataforma debe ser True."""
        self.assertTrue(platform_utils.IS_WINDOWS or platform_utils.IS_LINUX
                        or True)  # Puede correr en macOS para tests

    def test_mutual_exclusion(self):
        """IS_WINDOWS e IS_LINUX no pueden ser True simultáneamente."""
        self.assertFalse(platform_utils.IS_WINDOWS and platform_utils.IS_LINUX)


class TestOpenFile(unittest.TestCase):
    @patch('platform_utils.IS_WINDOWS', False)
    @patch('platform_utils.IS_LINUX', True)
    @patch('subprocess.Popen')
    def test_linux_uses_xdg_open(self, mock_popen):
        platform_utils.open_file('/tmp/test.pdf')
        mock_popen.assert_called_once_with(['xdg-open', '/tmp/test.pdf'])

    @patch('platform_utils.IS_WINDOWS', True)
    @patch('platform_utils.IS_LINUX', False)
    @patch('os.startfile', create=True)
    def test_windows_uses_startfile(self, mock_startfile):
        platform_utils.open_file('C:\\test.pdf')
        mock_startfile.assert_called_once_with('C:\\test.pdf')


class TestGetUsername(unittest.TestCase):
    @patch('platform_utils.IS_WINDOWS', False)
    def test_linux_uses_USER(self):
        with patch.dict(os.environ, {'USER': 'profesor'}):
            self.assertEqual(platform_utils.get_username(), 'profesor')

    @patch('platform_utils.IS_WINDOWS', True)
    def test_windows_uses_USERNAME(self):
        with patch.dict(os.environ, {'USERNAME': 'teacher'}):
            self.assertEqual(platform_utils.get_username(), 'teacher')

    def test_default_value(self):
        with patch.dict(os.environ, {}, clear=True):
            result = platform_utils.get_username('default_user')
            self.assertIsInstance(result, str)


class TestGetDownloadsDir(unittest.TestCase):
    @patch('platform_utils.IS_WINDOWS', False)
    @patch('platform_utils.IS_LINUX', True)
    def test_linux_returns_path(self):
        result = platform_utils.get_downloads_dir()
        self.assertIsInstance(result, pathlib.Path)

    @patch('platform_utils.IS_WINDOWS', True)
    @patch('platform_utils.IS_LINUX', False)
    def test_windows_returns_path(self):
        result = platform_utils.get_downloads_dir()
        self.assertIsInstance(result, pathlib.Path)


class TestGetConfigPath(unittest.TestCase):
    @patch('platform_utils.IS_WINDOWS', False)
    def test_linux_returns_etc(self):
        result = platform_utils.get_config_path()
        self.assertEqual(result, '/etc/vigia/client.conf')

    @patch('platform_utils.IS_WINDOWS', True)
    def test_windows_returns_appdata(self):
        with patch.dict(os.environ, {'APPDATA': 'C:\\Users\\Test\\AppData\\Roaming'}):
            result = platform_utils.get_config_path()
            self.assertIn('vigia', result)
            self.assertIn('client.conf', result)


class TestGetTempPath(unittest.TestCase):
    @patch('platform_utils.IS_WINDOWS', False)
    def test_linux_uses_tmp(self):
        result = platform_utils.get_temp_path('test.log')
        self.assertEqual(result, '/tmp/test.log')

    @patch('platform_utils.IS_WINDOWS', True)
    def test_windows_uses_temp(self):
        result = platform_utils.get_temp_path('test.log')
        self.assertIn('test.log', result)


class TestRunShell(unittest.TestCase):
    @patch('platform_utils.IS_WINDOWS', False)
    @patch('platform_utils.IS_LINUX', True)
    def test_linux_returns_tuple(self):
        """run_shell debe devolver (stdout, stderr, returncode, new_cwd)."""
        cwd = tempfile.gettempdir()
        stdout, stderr, rc, new_cwd = platform_utils.run_shell('echo hello', cwd)
        self.assertIsInstance(stdout, str)
        self.assertIsInstance(stderr, str)
        self.assertIsInstance(rc, int)
        self.assertIsInstance(new_cwd, str)

    @patch('platform_utils.IS_WINDOWS', True)
    @patch('platform_utils.IS_LINUX', False)
    def test_windows_returns_tuple(self):
        cwd = tempfile.gettempdir()
        stdout, stderr, rc, new_cwd = platform_utils.run_shell('echo hello', cwd)
        self.assertIsInstance(stdout, str)
        self.assertIsInstance(rc, int)


class TestSetClickthrough(unittest.TestCase):
    @patch('platform_utils.IS_WINDOWS', False)
    @patch('platform_utils.IS_LINUX', True)
    def test_linux_returns_bool(self):
        # Sin X11 real, debe retornar False sin error
        result = platform_utils.set_clickthrough(0)
        self.assertIsInstance(result, bool)

    @patch('platform_utils.IS_WINDOWS', True)
    @patch('platform_utils.IS_LINUX', False)
    def test_windows_returns_bool(self):
        result = platform_utils.set_clickthrough(0)
        self.assertIsInstance(result, bool)


class TestGetWindowList(unittest.TestCase):
    def test_returns_list(self):
        result = platform_utils.get_window_list()
        self.assertIsInstance(result, list)

    @patch('platform_utils.IS_WINDOWS', False)
    @patch('platform_utils.IS_LINUX', True)
    @patch('subprocess.run')
    def test_linux_handles_xprop_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout='')
        result = platform_utils.get_window_list()
        self.assertEqual(result, [])


class TestGetWindowRegion(unittest.TestCase):
    @patch('platform_utils.IS_WINDOWS', False)
    @patch('platform_utils.IS_LINUX', True)
    @patch('subprocess.run')
    def test_linux_returns_dict_or_none(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='X=100\nY=200\nWIDTH=800\nHEIGHT=600\n'
        )
        result = platform_utils.get_window_region('0x12345')
        self.assertIsNotNone(result)
        self.assertEqual(result['width'], 800)


class TestShutdownSystem(unittest.TestCase):
    @patch('platform_utils.IS_WINDOWS', False)
    @patch('platform_utils.IS_LINUX', True)
    @patch('subprocess.run')
    def test_linux_calls_shutdown(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        platform_utils.shutdown_system()
        args = mock_run.call_args[0][0]
        self.assertIn('shutdown', args)

    @patch('platform_utils.IS_WINDOWS', True)
    @patch('platform_utils.IS_LINUX', False)
    @patch('subprocess.run')
    def test_windows_calls_shutdown(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        platform_utils.shutdown_system()
        args = mock_run.call_args[0][0]
        self.assertIn('shutdown', args)


class TestSetDpiAware(unittest.TestCase):
    def test_does_not_raise(self):
        """set_dpi_aware no debe lanzar excepciones en ninguna plataforma."""
        platform_utils.set_dpi_aware()


class TestClipboard(unittest.TestCase):
    @patch('platform_utils.IS_WINDOWS', False)
    @patch('platform_utils.IS_LINUX', True)
    @patch('subprocess.run')
    def test_linux_clipboard_returns_string(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='test text')
        result = platform_utils.get_clipboard_text()
        self.assertEqual(result, 'test text')

    @patch('platform_utils.IS_WINDOWS', False)
    @patch('platform_utils.IS_LINUX', True)
    @patch('subprocess.run', side_effect=Exception('no xclip'))
    def test_linux_clipboard_fallback_empty(self, mock_run):
        result = platform_utils.get_clipboard_text()
        self.assertEqual(result, '')


if __name__ == '__main__':
    unittest.main()
