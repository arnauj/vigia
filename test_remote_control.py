#!/usr/bin/env python3
"""
test_remote_control.py — Pruebas de control remoto VIGIA

Verifica que los eventos de ratón y teclado enviados desde el dashboard
se procesan correctamente en el cliente (xdotool/pynput).

Ejecutar:  python3 test_remote_control.py
"""

import sys
import os
import json
import types
import queue
import unittest
from unittest.mock import patch, MagicMock, call

# ── Preparar mocks ANTES de importar client.py ─────────────────────────────

# mss
_mock_mss = types.ModuleType('mss')
_mock_mss.mss = MagicMock(return_value=MagicMock(
    monitors=[{}, {'width': 1920, 'height': 1080}]
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

# socketio — sio.on debe actuar como decorador pass-through para que las
# funciones decoradas (on_do_input, on_viewer_start, etc.) sigan siendo
# las funciones originales y no queden reemplazadas por MagicMock.
_mock_sio_mod = types.ModuleType('socketio')
_fake_client = MagicMock()
_fake_client.on    = lambda event_name: (lambda f: f)  # decorador pass-through
_fake_client.event = lambda f: f                        # @sio.event idem
_mock_sio_mod.Client = MagicMock(return_value=_fake_client)
sys.modules['socketio'] = _mock_sio_mod

# tkinter (simular no disponible → simplifica el test)
sys.modules['tkinter'] = None  # type: ignore

# aiortc (no instalado → WEBRTC_OK = False en el cliente)
# — no añadir a sys.modules: deja que ImportError lo maneje

# ── Importar client.py con xdotool mockeado ─────────────────────────────────

import subprocess as _subprocess_real  # referencia antes del patch

with patch('shutil.which', side_effect=lambda x: '/usr/bin/xdotool' if x == 'xdotool' else None), \
     patch('subprocess.run', return_value=MagicMock(returncode=0)):
    sys.path.insert(0, os.path.dirname(__file__))
    import client

# ── Constantes copiadas/verificadas desde client.py ────────────────────────

_XDO_KEY_MAP_EXPECTED = {
    'space': 'space', 'enter': 'Return', 'esc': 'Escape', 'tab': 'Tab',
    'backspace': 'BackSpace', 'delete': 'Delete', 'insert': 'Insert',
    'home': 'Home', 'end': 'End', 'pageup': 'Page_Up', 'pagedown': 'Page_Down',
    'left': 'Left', 'right': 'Right', 'up': 'Up', 'down': 'Down',
    'ctrl': 'Control_L', 'alt': 'Alt_L', 'shift': 'Shift_L', 'win': 'Super_L',
}

_BTN_MAP_EXPECTED = {'left': 1, 'middle': 2, 'right': 3}

# ══════════════════════════════════════════════════════════════════════════════

class TestKeyMaps(unittest.TestCase):
    """Verifica que los mapas de teclas son correctos."""

    def test_xdo_key_map_completo(self):
        for key, expected in _XDO_KEY_MAP_EXPECTED.items():
            with self.subTest(key=key):
                self.assertEqual(client._XDO_KEY_MAP[key], expected,
                                 f"_XDO_KEY_MAP['{key}'] debería ser '{expected}'")

    def test_boton_map_xdo(self):
        for btn, num in _BTN_MAP_EXPECTED.items():
            with self.subTest(button=btn):
                self.assertEqual(client._BTN_MAP_XDO[btn], num)

    def test_teclas_no_mapeadas_pasan_tal_cual(self):
        """Teclas sin mapeo explícito (p.ej. F1, letras) deben pasar sin cambio."""
        key_in = 'f1'
        result = client._XDO_KEY_MAP.get(key_in, key_in)
        self.assertEqual(result, 'f1')

        key_in2 = 'a'
        result2 = client._XDO_KEY_MAP.get(key_in2, key_in2)
        self.assertEqual(result2, 'a')


class TestProcesarInput(unittest.TestCase):
    """Pruebas de _procesar_input usando xdotool mockeado."""

    def setUp(self):
        # Asegurar que xdotool está disponible y pynput no
        client._XDO_CMD = '/usr/bin/xdotool'
        client._mouse_ctrl = None
        client._kbd_ctrl   = None
        client._PBtn       = None
        client._xdo_env    = dict(os.environ)
        client._xdo_env.setdefault('DISPLAY', ':0')

    def _run(self, data):
        """Ejecuta _procesar_input con xdotool mockeado y devuelve las llamadas."""
        with patch('subprocess.run', return_value=MagicMock(returncode=0)) as mock_run:
            client._procesar_input(data)
        return mock_run.call_args_list

    def _xdo_args(self, calls):
        """Extrae los args de cada llamada a xdotool."""
        return [c.args[0][1:] for c in calls]  # [1:] quita la ruta de xdotool

    # ── Ratón ─────────────────────────────────────────────────────────────

    def test_mousemove(self):
        calls = self._run({'type': 'mousemove', 'x': 640, 'y': 480})
        args = self._xdo_args(calls)
        self.assertIn(['mousemove', '--sync', '640', '480'], args,
                      "mousemove debe llamar xdotool mousemove --sync x y")

    def test_mousedown_izquierdo(self):
        calls = self._run({'type': 'mousedown', 'x': 100, 'y': 200, 'button': 'left'})
        args = self._xdo_args(calls)
        self.assertIn(['mousemove', '--sync', '100', '200'], args)
        self.assertIn(['mousedown', '1'], args,
                      "mousedown left debe llamar xdotool mousedown 1")

    def test_mousedown_derecho(self):
        calls = self._run({'type': 'mousedown', 'x': 100, 'y': 200, 'button': 'right'})
        args = self._xdo_args(calls)
        self.assertIn(['mousedown', '3'], args,
                      "mousedown right debe llamar xdotool mousedown 3")

    def test_mouseup_izquierdo(self):
        calls = self._run({'type': 'mouseup', 'x': 100, 'y': 200, 'button': 'left'})
        args = self._xdo_args(calls)
        self.assertIn(['mouseup', '1'], args,
                      "mouseup left debe llamar xdotool mouseup 1")

    def test_scroll_arriba(self):
        calls = self._run({'type': 'scroll', 'x': 300, 'y': 300, 'dy': 3})
        args = self._xdo_args(calls)
        # dy > 0 → botón 4 (scroll up)
        self.assertTrue(any('click' in a and '4' in a for a in args),
                        f"scroll dy>0 debe usar botón 4; args={args}")

    def test_scroll_abajo(self):
        calls = self._run({'type': 'scroll', 'x': 300, 'y': 300, 'dy': -2})
        args = self._xdo_args(calls)
        # dy < 0 → botón 5 (scroll down)
        self.assertTrue(any('click' in a and '5' in a for a in args),
                        f"scroll dy<0 debe usar botón 5; args={args}")

    # ── Teclado ────────────────────────────────────────────────────────────

    def test_type_caracter(self):
        calls = self._run({'type': 'type', 'char': 'a'})
        args = self._xdo_args(calls)
        self.assertTrue(
            any(a[0] == 'type' and 'a' in a for a in args),
            f"type 'a' debe llamar xdotool type; args={args}"
        )

    def test_type_caracter_especial_unicode(self):
        calls = self._run({'type': 'type', 'char': 'ñ'})
        args = self._xdo_args(calls)
        self.assertTrue(any(a[0] == 'type' for a in args))

    def test_keypress_enter(self):
        calls = self._run({'type': 'keypress', 'key': 'enter'})
        args = self._xdo_args(calls)
        self.assertTrue(
            any(a[0] == 'key' and 'Return' in a for a in args),
            f"keypress enter debe mapear a Return; args={args}"
        )

    def test_keypress_escape(self):
        calls = self._run({'type': 'keypress', 'key': 'esc'})
        args = self._xdo_args(calls)
        self.assertTrue(any(a[0] == 'key' and 'Escape' in a for a in args))

    def test_keypress_flechas(self):
        for key, xdo in [('left', 'Left'), ('right', 'Right'),
                         ('up', 'Up'), ('down', 'Down')]:
            with self.subTest(key=key):
                calls = self._run({'type': 'keypress', 'key': key})
                args = self._xdo_args(calls)
                self.assertTrue(any(a[0] == 'key' and xdo in a for a in args),
                                f"keypress {key} debe mapear a {xdo}")

    def test_keycombo_ctrl_c(self):
        calls = self._run({'type': 'keycombo', 'combo': 'ctrl+c'})
        args = self._xdo_args(calls)
        self.assertTrue(
            any(a[0] == 'key' and 'ctrl+c' in a for a in args),
            f"keycombo ctrl+c debe llamar xdotool key ctrl+c; args={args}"
        )

    def test_keycombo_alt_f4(self):
        calls = self._run({'type': 'keycombo', 'combo': 'alt+f4'})
        args = self._xdo_args(calls)
        self.assertTrue(any(a[0] == 'key' and 'alt+f4' in a for a in args))

    def test_keydown_ctrl(self):
        calls = self._run({'type': 'keydown', 'key': 'ctrl'})
        args = self._xdo_args(calls)
        self.assertTrue(
            any(a[0] == 'keydown' and 'Control_L' in a for a in args),
            f"keydown ctrl debe llamar xdotool keydown Control_L; args={args}"
        )

    def test_keyup_shift(self):
        calls = self._run({'type': 'keyup', 'key': 'shift'})
        args = self._xdo_args(calls)
        self.assertTrue(
            any(a[0] == 'keyup' and 'Shift_L' in a for a in args),
            f"keyup shift debe llamar xdotool keyup Shift_L; args={args}"
        )

    def test_type_sin_char_es_noop(self):
        """type sin 'char' no debe llamar a xdotool."""
        calls = self._run({'type': 'type', 'char': ''})
        self.assertEqual(len(calls), 0, "type con char vacío no debe llamar xdotool")

    def test_evento_desconocido_es_noop(self):
        calls = self._run({'type': 'evento_invalido', 'x': 0, 'y': 0})
        self.assertEqual(len(calls), 0, "evento desconocido no debe llamar xdotool")


class TestInputQueue(unittest.TestCase):
    """
    Pruebas del comportamiento de la cola de entrada.

    on_do_input encola los eventos; el hilo _input_worker los consume
    casi de inmediato (xdotool es mock). En lugar de inspeccionar la cola
    después de encolar (race condition), parcheamos directamente el método
    put/put_nowait de la cola para capturar qué se intentó encolar.
    """

    def test_encola_mousemove(self):
        """on_do_input debe llamar put_nowait en la cola para mousemove."""
        encolados = []
        orig_put_nowait = client._input_q.put_nowait

        def _fake_put_nowait(item):
            encolados.append(item)
            orig_put_nowait(item)  # dejar que el worker lo procese

        with patch.object(client._input_q, 'put_nowait', side_effect=_fake_put_nowait):
            client.on_do_input({'type': 'mousemove', 'x': 10, 'y': 20})

        self.assertTrue(len(encolados) > 0, "mousemove debe intentar encolar en _input_q")
        self.assertEqual(encolados[0]['type'], 'mousemove')

    def test_cola_mousemove_llena_no_bloquea(self):
        """Si put_nowait lanza Full, on_do_input no debe propagar la excepción."""
        import time
        with patch.object(client._input_q, 'put_nowait', side_effect=queue.Full):
            t0 = time.monotonic()
            client.on_do_input({'type': 'mousemove', 'x': 999, 'y': 999})
            elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.1, "mousemove con cola llena no debe bloquear > 100ms")

    def test_clicks_usan_put_con_timeout(self):
        """mousedown/mouseup/keypress usan queue.put con timeout (no put_nowait)."""
        encolados = []
        orig_put = client._input_q.put

        def _fake_put(item, timeout=None):
            encolados.append(item)
            orig_put(item, timeout=timeout)

        with patch.object(client._input_q, 'put', side_effect=_fake_put):
            client.on_do_input({'type': 'mousedown', 'x': 5, 'y': 5, 'button': 'left'})

        self.assertTrue(len(encolados) > 0, "mousedown debe intentar encolar en _input_q")
        self.assertEqual(encolados[0]['type'], 'mousedown')

    def test_keypress_usa_put_con_timeout(self):
        """keypress usan queue.put con timeout para no perder eventos."""
        encolados = []
        orig_put = client._input_q.put

        def _fake_put(item, timeout=None):
            encolados.append(item)
            orig_put(item, timeout=timeout)

        with patch.object(client._input_q, 'put', side_effect=_fake_put):
            client.on_do_input({'type': 'keypress', 'key': 'enter'})

        types = [i['type'] for i in encolados]
        self.assertIn('keypress', types, "keypress debe encolarse mediante queue.put")


class TestCoordenadas(unittest.TestCase):
    """
    Prueba la lógica de traducción de coordenadas (equivalente a _traducirCoords del dashboard).
    Verifica el mapeo píxel-a-píxel para letterboxing y pillarboxing.
    """

    @staticmethod
    def traducir_coords(client_x, client_y, rect_left, rect_top, rect_w, rect_h,
                        orig_w, orig_h):
        """
        Replica exacta de la función _traducirCoords del dashboard.html.
        rect_* = getBoundingClientRect() del elemento de vídeo/imagen.
        orig_w/orig_h = resolución real de la pantalla del alumno (screen_info).
        """
        content_ar = orig_w / orig_h
        box_ar = rect_w / rect_h
        if box_ar > content_ar:
            # Pillarboxing (barras laterales)
            ch = rect_h
            cw = ch * content_ar
            cx = rect_left + (rect_w - cw) / 2
            cy = rect_top
        else:
            # Letterboxing (barras arriba/abajo)
            cw = rect_w
            ch = cw / content_ar
            cx = rect_left
            cy = rect_top + (rect_h - ch) / 2
        x = round((client_x - cx) / cw * orig_w)
        y = round((client_y - cy) / ch * orig_h)
        return x, y

    def test_centro_pantalla_1920x1080(self):
        """Clic en el centro del vídeo debe mapear al centro de la pantalla."""
        # Elemento ocupa toda la pantalla del monitor del profesor (1920×1080)
        x, y = self.traducir_coords(960, 540, 0, 0, 1920, 1080, 1920, 1080)
        self.assertEqual((x, y), (960, 540))

    def test_centro_pantalla_2560x1440_con_letterbox(self):
        """
        Pantalla del alumno 2560×1440; vídeo del stream 1920×1080 (AR igual).
        El elemento de vídeo tiene 1400×900 (pillarbox dentro del elemento).
        El clic en el centro del contenido debe mapear a (1280, 720).
        """
        # AR original: 2560/1440 = 1.777...
        # Elemento: 1400×900 → box_ar = 1.555... < content_ar → letterboxing
        #   cw = 1400, ch = 1400 / (2560/1440) = 787.5
        #   cy = 0 + (900 - 787.5) / 2 = 56.25
        # Centro del contenido: client_x = 700, client_y = 56.25 + 787.5/2 = 450
        x, y = self.traducir_coords(700, 450, 0, 0, 1400, 900, 2560, 1440)
        self.assertAlmostEqual(x, 1280, delta=2)
        self.assertAlmostEqual(y, 720, delta=2)

    def test_esquina_superior_izquierda(self):
        """Clic en la esquina del contenido debe mapear a (0, 0)."""
        # Pillarboxing: pantalla 4:3 (1024×768), elemento 1400×900
        #   box_ar = 1.555... > content_ar = 1.333... → pillarboxing
        #   ch = 900, cw = 900 * (1024/768) = 1200
        #   cx = (1400 - 1200) / 2 = 100
        x, y = self.traducir_coords(100, 0, 0, 0, 1400, 900, 1024, 768)
        self.assertEqual((x, y), (0, 0))

    def test_esquina_inferior_derecha(self):
        """Clic en la esquina inferior derecha del contenido → (orig_w, orig_h)."""
        # Sin letterbox ni pillarbox: elemento 1920×1080, pantalla 1920×1080
        x, y = self.traducir_coords(1919, 1079, 0, 0, 1920, 1080, 1920, 1080)
        self.assertEqual((x, y), (1919, 1079))

    def test_offset_elemento(self):
        """El elemento no empieza en (0,0) del viewport."""
        # Elemento en (50, 100), sin letterboxing
        x, y = self.traducir_coords(550, 580, 50, 100, 1920, 1080, 1920, 1080)
        self.assertEqual((x, y), (500, 480))

    def test_coordenada_negativa_fuera_del_contenido(self):
        """Clic fuera del área de contenido (barra negra) → coordenada negativa."""
        # Pillarboxing: elemento 1400×900, pantalla 4:3 → cx = 100
        # Clic en x=50 (dentro de la barra izquierda)
        x, y = self.traducir_coords(50, 450, 0, 0, 1400, 900, 1024, 768)
        self.assertLess(x, 0, "Clic en barra negra debe dar coordenada negativa")


class TestDataChannelRouting(unittest.TestCase):
    """
    Verifica la lógica de enrutamiento de _enviarInput del dashboard
    (re-implementada aquí para pruebas unitarias).
    """

    @staticmethod
    def enviar_input_logic(payload, webrtc_activo, dc_mouse_state, dc_kbd_state):
        """
        Replica la lógica de _enviarInput del dashboard.
        Devuelve ('dc_mouse' | 'dc_kbd' | 'socketio').
        """
        tipo = payload.get('type', '')
        es_mouse = tipo in ('mousemove', 'mousedown', 'mouseup', 'scroll')
        if webrtc_activo:
            if es_mouse and dc_mouse_state == 'open':
                return 'dc_mouse'
            if not es_mouse and dc_kbd_state == 'open':
                return 'dc_kbd'
            # fallback: cualquier canal abierto
            if dc_kbd_state == 'open':
                return 'dc_kbd'
            if dc_mouse_state == 'open':
                return 'dc_mouse'
        return 'socketio'

    def test_mousemove_va_por_dc_mouse(self):
        dest = self.enviar_input_logic(
            {'type': 'mousemove'}, True, 'open', 'open')
        self.assertEqual(dest, 'dc_mouse')

    def test_keypress_va_por_dc_kbd(self):
        dest = self.enviar_input_logic(
            {'type': 'keypress'}, True, 'open', 'open')
        self.assertEqual(dest, 'dc_kbd')

    def test_type_va_por_dc_kbd(self):
        dest = self.enviar_input_logic(
            {'type': 'type'}, True, 'open', 'open')
        self.assertEqual(dest, 'dc_kbd')

    def test_mousedown_va_por_dc_mouse(self):
        dest = self.enviar_input_logic(
            {'type': 'mousedown'}, True, 'open', 'open')
        self.assertEqual(dest, 'dc_mouse')

    def test_scroll_va_por_dc_mouse(self):
        dest = self.enviar_input_logic(
            {'type': 'scroll'}, True, 'open', 'open')
        self.assertEqual(dest, 'dc_mouse')

    def test_sin_webrtc_va_por_socketio(self):
        for tipo in ('mousemove', 'mousedown', 'keypress', 'type', 'keycombo'):
            with self.subTest(tipo=tipo):
                dest = self.enviar_input_logic(
                    {'type': tipo}, False, 'open', 'open')
                self.assertEqual(dest, 'socketio')

    def test_dc_mouse_cerrado_mouse_usa_dc_kbd_fallback(self):
        """Si dc_mouse está cerrado, los eventos de ratón van por dc_kbd."""
        dest = self.enviar_input_logic(
            {'type': 'mousemove'}, True, 'connecting', 'open')
        self.assertEqual(dest, 'dc_kbd')

    def test_ambos_canales_cerrados_va_por_socketio(self):
        dest = self.enviar_input_logic(
            {'type': 'mousemove'}, True, 'connecting', 'connecting')
        self.assertEqual(dest, 'socketio')

    def test_webrtc_activo_dc_kbd_cerrado_kbd_usa_dc_mouse(self):
        """Si dc_kbd está cerrado, los eventos de teclado van por dc_mouse."""
        dest = self.enviar_input_logic(
            {'type': 'keypress'}, True, 'open', 'connecting')
        self.assertEqual(dest, 'dc_mouse')


# ── Punto de entrada ──────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("=" * 60)
    print("VIGIA — Test de control remoto (ratón + teclado)")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    for cls in (TestKeyMaps, TestProcesarInput, TestInputQueue,
                TestCoordenadas, TestDataChannelRouting):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
