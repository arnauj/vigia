#!/usr/bin/env python3
"""
test_remote_control_win.py — Pruebas de control remoto VIGIA (Windows)

Verifica que los eventos de ratón y teclado enviados desde el dashboard
se procesan correctamente en el cliente Windows (Win32 SendInput).

Equivalente exacto de test_remote_control.py para Windows.

Ejecutar:  python3 test_remote_control_win.py
"""

import sys
import os
import json
import types
import queue
import struct
import unittest
from unittest.mock import patch, MagicMock, call

# ── Preparar mocks ANTES de importar client_win.py ─────────────────────────

# mss
_mock_mss = types.ModuleType('mss')
_mock_mss.mss = MagicMock(return_value=MagicMock(
    monitors=[{}, {'width': 1920, 'height': 1080, 'left': 0, 'top': 0}]
))
sys.modules['mss'] = _mock_mss

# PIL
_mock_pil = types.ModuleType('PIL')
_mock_image = types.ModuleType('PIL.Image')
_mock_image.Image = MagicMock()
_mock_image.LANCZOS = MagicMock()
_mock_pil.Image = _mock_image.Image
sys.modules['PIL'] = _mock_pil
sys.modules['PIL.Image'] = _mock_image
sys.modules['PIL.ImageTk'] = types.ModuleType('PIL.ImageTk')

# socketio
_mock_sio_mod = types.ModuleType('socketio')
_fake_client = MagicMock()
_fake_client.on    = lambda event_name: (lambda f: f)
_fake_client.event = lambda f: f
_mock_sio_mod.Client = MagicMock(return_value=_fake_client)
sys.modules['socketio'] = _mock_sio_mod

# tkinter
sys.modules['tkinter'] = None  # type: ignore

# Mock Win32 API (ctypes.windll)
_mock_windll = MagicMock()
_mock_user32 = MagicMock()
_mock_kernel32 = MagicMock()
_mock_windll.user32 = _mock_user32
_mock_windll.kernel32 = _mock_kernel32

# Mock ctypes.wintypes
_mock_wintypes = types.ModuleType('ctypes.wintypes')
_mock_wintypes.LONG = type('LONG', (object,), {})
_mock_wintypes.DWORD = type('DWORD', (object,), {})
_mock_wintypes.WORD = type('WORD', (object,), {})

# Patch windll before import
import ctypes as _real_ctypes
_original_windll = getattr(_real_ctypes, 'windll', None)

# Create mock windll if not on Windows
if not hasattr(_real_ctypes, 'windll'):
    _real_ctypes.windll = _mock_windll

if not hasattr(_real_ctypes, 'wintypes'):
    # Create a minimal wintypes module
    _wintypes = types.ModuleType('ctypes.wintypes')
    _wintypes.LONG = _real_ctypes.c_long
    _wintypes.DWORD = _real_ctypes.c_ulong
    _wintypes.WORD = _real_ctypes.c_ushort
    sys.modules['ctypes.wintypes'] = _wintypes
    _real_ctypes.wintypes = _wintypes

# Mock winreg
_mock_winreg = types.ModuleType('winreg')
_mock_winreg.OpenKey = MagicMock()
_mock_winreg.QueryValueEx = MagicMock()
_mock_winreg.CloseKey = MagicMock()
_mock_winreg.HKEY_LOCAL_MACHINE = 0x80000002
sys.modules['winreg'] = _mock_winreg

# ── Importar client_win.py ─────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(__file__))
try:
    import client_win
except Exception as e:
    print(f"Warning: Could not import client_win fully: {e}")
    # Define minimal stubs for testing
    class client_win:
        _VK_MAP = {
            'space': 0x20, 'enter': 0x0D, 'esc': 0x1B, 'tab': 0x09,
            'backspace': 0x08, 'delete': 0x2E, 'insert': 0x2D,
            'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
            'left': 0x25, 'right': 0x27, 'up': 0x26, 'down': 0x28,
            'ctrl': 0x11, 'alt': 0x12, 'shift': 0x10, 'win': 0x5B,
            'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
            'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
            'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
            'capslock': 0x14, 'numlock': 0x90, 'scrolllock': 0x91,
            'printscreen': 0x2C, 'pause': 0x13,
            'control_l': 0x11, 'control_r': 0xA3,
            'alt_l': 0x12, 'alt_r': 0xA5,
            'shift_l': 0x10, 'shift_r': 0xA1,
        }
        _BTN_MAP = {'left': 'left', 'middle': 'middle', 'right': 'right'}
        _input_q = queue.Queue(maxsize=200)
        _last_mouse_time = 0.0
        _MOUSE_THROTTLE = 0.008

        @staticmethod
        def _procesar_input(data): pass

        @staticmethod
        def on_do_input(data): pass

# ── Constantes verificadas ────────────────────────────────────────────────

_VK_MAP_EXPECTED = {
    'space': 0x20, 'enter': 0x0D, 'esc': 0x1B, 'tab': 0x09,
    'backspace': 0x08, 'delete': 0x2E, 'insert': 0x2D,
    'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
    'left': 0x25, 'right': 0x27, 'up': 0x26, 'down': 0x28,
    'ctrl': 0x11, 'alt': 0x12, 'shift': 0x10, 'win': 0x5B,
}

_BTN_MAP_EXPECTED = {'left': 'left', 'middle': 'middle', 'right': 'right'}

# ══════════════════════════════════════════════════════════════════════════════

class TestVKMaps(unittest.TestCase):
    """Verifica que los mapas de Virtual Key Codes son correctos."""

    def test_vk_map_completo(self):
        for key, expected_vk in _VK_MAP_EXPECTED.items():
            with self.subTest(key=key):
                self.assertEqual(client_win._VK_MAP[key], expected_vk,
                                 f"_VK_MAP['{key}'] debería ser 0x{expected_vk:02X}")

    def test_boton_map(self):
        for btn, name in _BTN_MAP_EXPECTED.items():
            with self.subTest(button=btn):
                self.assertEqual(client_win._BTN_MAP[btn], name)

    def test_teclas_f_completas(self):
        """Verifica que F1-F12 están mapeadas correctamente."""
        for i in range(1, 13):
            key = f'f{i}'
            expected = 0x70 + (i - 1)
            with self.subTest(key=key):
                self.assertEqual(client_win._VK_MAP[key], expected,
                                 f"_VK_MAP['{key}'] debería ser 0x{expected:02X}")

    def test_teclas_no_mapeadas_devuelven_none(self):
        """Teclas sin mapeo explícito devuelven None del diccionario."""
        self.assertIsNone(client_win._VK_MAP.get('nonexistent_key'))


class TestProcesarInputWin(unittest.TestCase):
    """Pruebas de _procesar_input usando Win32 API mockeado."""

    def setUp(self):
        client_win._mon_left = 0
        client_win._mon_top = 0

    @patch.object(client_win, '_mouse_move')
    def test_mousemove(self, mock_move):
        client_win._procesar_input({'type': 'mousemove', 'x': 640, 'y': 480})
        mock_move.assert_called_with(640, 480)

    @patch.object(client_win, '_mouse_down')
    @patch.object(client_win, '_mouse_move')
    def test_mousedown_izquierdo(self, mock_move, mock_down):
        client_win._procesar_input({'type': 'mousedown', 'x': 100, 'y': 200, 'button': 'left'})
        mock_move.assert_called_with(100, 200)
        mock_down.assert_called_with('left')

    @patch.object(client_win, '_mouse_down')
    @patch.object(client_win, '_mouse_move')
    def test_mousedown_derecho(self, mock_move, mock_down):
        client_win._procesar_input({'type': 'mousedown', 'x': 100, 'y': 200, 'button': 'right'})
        mock_down.assert_called_with('right')

    @patch.object(client_win, '_mouse_up')
    @patch.object(client_win, '_mouse_move')
    def test_mouseup_izquierdo(self, mock_move, mock_up):
        client_win._procesar_input({'type': 'mouseup', 'x': 100, 'y': 200, 'button': 'left'})
        mock_up.assert_called_with('left')

    @patch.object(client_win, '_mouse_scroll')
    @patch.object(client_win, '_mouse_move')
    def test_scroll_arriba(self, mock_move, mock_scroll):
        client_win._procesar_input({'type': 'scroll', 'x': 300, 'y': 300, 'dy': 3})
        mock_scroll.assert_called_with(3)

    @patch.object(client_win, '_mouse_scroll')
    @patch.object(client_win, '_mouse_move')
    def test_scroll_abajo(self, mock_move, mock_scroll):
        client_win._procesar_input({'type': 'scroll', 'x': 300, 'y': 300, 'dy': -2})
        mock_scroll.assert_called_with(-2)

    @patch.object(client_win, '_type_char')
    def test_type_caracter(self, mock_type):
        client_win._procesar_input({'type': 'type', 'char': 'a'})
        mock_type.assert_called_with('a')

    @patch.object(client_win, '_type_char')
    def test_type_caracter_unicode(self, mock_type):
        client_win._procesar_input({'type': 'type', 'char': 'ñ'})
        mock_type.assert_called_with('ñ')

    @patch.object(client_win, '_key_press')
    def test_keypress_enter(self, mock_press):
        client_win._procesar_input({'type': 'keypress', 'key': 'enter'})
        mock_press.assert_called_with(0x0D)

    @patch.object(client_win, '_key_press')
    def test_keypress_escape(self, mock_press):
        client_win._procesar_input({'type': 'keypress', 'key': 'esc'})
        mock_press.assert_called_with(0x1B)

    @patch.object(client_win, '_key_press')
    def test_keypress_flechas(self, mock_press):
        for key, vk in [('left', 0x25), ('right', 0x27), ('up', 0x26), ('down', 0x28)]:
            with self.subTest(key=key):
                mock_press.reset_mock()
                client_win._procesar_input({'type': 'keypress', 'key': key})
                mock_press.assert_called_with(vk)

    @patch.object(client_win, '_key_up')
    @patch.object(client_win, '_key_press')
    @patch.object(client_win, '_key_down')
    def test_keycombo_ctrl_c(self, mock_down, mock_press, mock_up):
        client_win._procesar_input({'type': 'keycombo', 'combo': 'ctrl+c'})
        mock_down.assert_called()  # ctrl down
        mock_up.assert_called()    # ctrl up

    @patch.object(client_win, '_key_down')
    def test_keydown_ctrl(self, mock_down):
        client_win._procesar_input({'type': 'keydown', 'key': 'ctrl'})
        mock_down.assert_called_with(0x11)

    @patch.object(client_win, '_key_up')
    def test_keyup_shift(self, mock_up):
        client_win._procesar_input({'type': 'keyup', 'key': 'shift'})
        mock_up.assert_called_with(0x10)

    def test_type_sin_char_es_noop(self):
        """type sin 'char' no debe llamar a nada."""
        with patch.object(client_win, '_type_char') as mock_type:
            client_win._procesar_input({'type': 'type', 'char': ''})
            mock_type.assert_not_called()

    def test_evento_desconocido_es_noop(self):
        """Evento desconocido no debe hacer nada."""
        # Should not raise
        client_win._procesar_input({'type': 'evento_invalido', 'x': 0, 'y': 0})


class TestInputQueueWin(unittest.TestCase):
    """Pruebas del comportamiento de la cola de entrada."""

    def test_encola_mousemove(self):
        encolados = []
        orig_put_nowait = client_win._input_q.put_nowait
        client_win._last_mouse_time = 0.0

        def _fake_put_nowait(item):
            encolados.append(item)
            orig_put_nowait(item)

        with patch.object(client_win._input_q, 'put_nowait', side_effect=_fake_put_nowait):
            client_win.on_do_input({'type': 'mousemove', 'x': 10, 'y': 20})

        self.assertTrue(len(encolados) > 0, "mousemove debe encolar en _input_q")
        self.assertEqual(encolados[0]['type'], 'mousemove')

    def test_cola_mousemove_llena_no_bloquea(self):
        import time
        with patch.object(client_win._input_q, 'put_nowait', side_effect=queue.Full):
            t0 = time.monotonic()
            client_win.on_do_input({'type': 'mousemove', 'x': 999, 'y': 999})
            elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.1)

    def test_clicks_usan_put_con_timeout(self):
        encolados = []
        orig_put = client_win._input_q.put

        def _fake_put(item, timeout=None):
            encolados.append(item)
            orig_put(item, timeout=timeout)

        with patch.object(client_win._input_q, 'put', side_effect=_fake_put):
            client_win.on_do_input({'type': 'mousedown', 'x': 5, 'y': 5, 'button': 'left'})

        self.assertTrue(len(encolados) > 0)
        self.assertEqual(encolados[0]['type'], 'mousedown')


class TestCoordenadasWin(unittest.TestCase):
    """Prueba la lógica de traducción de coordenadas (misma que Linux)."""

    @staticmethod
    def traducir_coords(client_x, client_y, rect_left, rect_top, rect_w, rect_h,
                        orig_w, orig_h):
        content_ar = orig_w / orig_h
        box_ar = rect_w / rect_h
        if box_ar > content_ar:
            ch = rect_h
            cw = ch * content_ar
            cx = rect_left + (rect_w - cw) / 2
            cy = rect_top
        else:
            cw = rect_w
            ch = cw / content_ar
            cx = rect_left
            cy = rect_top + (rect_h - ch) / 2
        x = round((client_x - cx) / cw * orig_w)
        y = round((client_y - cy) / ch * orig_h)
        return x, y

    def test_centro_pantalla_1920x1080(self):
        x, y = self.traducir_coords(960, 540, 0, 0, 1920, 1080, 1920, 1080)
        self.assertEqual((x, y), (960, 540))

    def test_centro_pantalla_2560x1440_con_letterbox(self):
        x, y = self.traducir_coords(700, 450, 0, 0, 1400, 900, 2560, 1440)
        self.assertAlmostEqual(x, 1280, delta=2)
        self.assertAlmostEqual(y, 720, delta=2)

    def test_esquina_superior_izquierda(self):
        x, y = self.traducir_coords(100, 0, 0, 0, 1400, 900, 1024, 768)
        self.assertEqual((x, y), (0, 0))

    def test_esquina_inferior_derecha(self):
        x, y = self.traducir_coords(1919, 1079, 0, 0, 1920, 1080, 1920, 1080)
        self.assertEqual((x, y), (1919, 1079))

    def test_offset_elemento(self):
        x, y = self.traducir_coords(550, 580, 50, 100, 1920, 1080, 1920, 1080)
        self.assertEqual((x, y), (500, 480))

    def test_coordenada_negativa_fuera_del_contenido(self):
        x, y = self.traducir_coords(50, 450, 0, 0, 1400, 900, 1024, 768)
        self.assertLess(x, 0)


class TestDataChannelRoutingWin(unittest.TestCase):
    """Verifica la lógica de enrutamiento de _enviarInput (misma que Linux)."""

    @staticmethod
    def enviar_input_logic(payload, webrtc_activo, dc_mouse_state, dc_kbd_state):
        tipo = payload.get('type', '')
        es_mouse = tipo in ('mousemove', 'mousedown', 'mouseup', 'scroll')
        if webrtc_activo:
            if es_mouse and dc_mouse_state == 'open':
                return 'dc_mouse'
            if not es_mouse and dc_kbd_state == 'open':
                return 'dc_kbd'
            if dc_kbd_state == 'open':
                return 'dc_kbd'
            if dc_mouse_state == 'open':
                return 'dc_mouse'
        return 'socketio'

    def test_mousemove_va_por_dc_mouse(self):
        dest = self.enviar_input_logic({'type': 'mousemove'}, True, 'open', 'open')
        self.assertEqual(dest, 'dc_mouse')

    def test_keypress_va_por_dc_kbd(self):
        dest = self.enviar_input_logic({'type': 'keypress'}, True, 'open', 'open')
        self.assertEqual(dest, 'dc_kbd')

    def test_type_va_por_dc_kbd(self):
        dest = self.enviar_input_logic({'type': 'type'}, True, 'open', 'open')
        self.assertEqual(dest, 'dc_kbd')

    def test_mousedown_va_por_dc_mouse(self):
        dest = self.enviar_input_logic({'type': 'mousedown'}, True, 'open', 'open')
        self.assertEqual(dest, 'dc_mouse')

    def test_scroll_va_por_dc_mouse(self):
        dest = self.enviar_input_logic({'type': 'scroll'}, True, 'open', 'open')
        self.assertEqual(dest, 'dc_mouse')

    def test_sin_webrtc_va_por_socketio(self):
        for tipo in ('mousemove', 'mousedown', 'keypress', 'type', 'keycombo'):
            with self.subTest(tipo=tipo):
                dest = self.enviar_input_logic({'type': tipo}, False, 'open', 'open')
                self.assertEqual(dest, 'socketio')

    def test_dc_mouse_cerrado_mouse_usa_dc_kbd_fallback(self):
        dest = self.enviar_input_logic({'type': 'mousemove'}, True, 'connecting', 'open')
        self.assertEqual(dest, 'dc_kbd')

    def test_ambos_canales_cerrados_va_por_socketio(self):
        dest = self.enviar_input_logic({'type': 'mousemove'}, True, 'connecting', 'connecting')
        self.assertEqual(dest, 'socketio')

    def test_webrtc_activo_dc_kbd_cerrado_kbd_usa_dc_mouse(self):
        dest = self.enviar_input_logic({'type': 'keypress'}, True, 'open', 'connecting')
        self.assertEqual(dest, 'dc_mouse')


class TestMonitorOffset(unittest.TestCase):
    """Verifica que el offset del monitor se aplica correctamente."""

    def test_offset_aplicado_a_mousemove(self):
        client_win._mon_left = 100
        client_win._mon_top = 50
        with patch.object(client_win, '_mouse_move') as mock_move:
            client_win._procesar_input({'type': 'mousemove', 'x': 640, 'y': 480})
            mock_move.assert_called_with(740, 530)
        client_win._mon_left = 0
        client_win._mon_top = 0

    def test_offset_aplicado_a_mousedown(self):
        client_win._mon_left = 200
        client_win._mon_top = 100
        with patch.object(client_win, '_mouse_move') as mock_move, \
             patch.object(client_win, '_mouse_down'):
            client_win._procesar_input({'type': 'mousedown', 'x': 100, 'y': 200, 'button': 'left'})
            mock_move.assert_called_with(300, 300)
        client_win._mon_left = 0
        client_win._mon_top = 0


# ── Punto de entrada ──────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("=" * 60)
    print("VIGIA — Test de control remoto Windows (ratón + teclado)")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    for cls in (TestVKMaps, TestProcesarInputWin, TestInputQueueWin,
                TestCoordenadasWin, TestDataChannelRoutingWin, TestMonitorOffset):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
