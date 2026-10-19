"""Regresiones de perfiles, caudal JPEG y sesiones (sin escritorio real).

python3 test_streaming.py
Las pruebas del servidor requieren flask-socketio.
"""

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from streaming import PRESETS, FrameWindow, fit_size, normalize_config, profile_encoder


class TestTeacherCaptureBackend(unittest.TestCase):
    def test_compatible_capture_does_not_open_wayland_portal(self):
        import screen_capture
        with patch.object(screen_capture, 'session_type', return_value='wayland'), \
             patch.object(screen_capture, '_cli_tool_order', return_value=['spectacle']), \
             patch.object(screen_capture, '_acquire_pipewire') as portal, \
             patch.object(screen_capture, 'CliBackend') as direct:
            capture = screen_capture.create_capturer(verbose=False, allow_portal=False)
        self.assertIs(capture, direct.return_value)
        direct.assert_called_once_with('spectacle')
        portal.assert_not_called()

    def test_student_capture_still_prefers_pipewire(self):
        import screen_capture
        with patch.object(screen_capture, 'session_type', return_value='wayland'), \
             patch.object(screen_capture, '_acquire_pipewire') as portal, \
             patch.object(screen_capture, 'CliBackend') as direct:
            capture = screen_capture.create_capturer(verbose=False)
        self.assertIs(capture, portal.return_value)
        direct.assert_not_called()


class TestProfiles(unittest.TestCase):
    def test_each_profile_changes_resolution_bandwidth_and_cadence(self):
        profiles = [PRESETS[name] for name in ('light', 'balanced', 'quality')]
        for key in ('live_width', 'thumb_width', 'webrtc_bitrate', 'webrtc_fps',
                    'live_fps', 'live_quality', 'thumb_quality'):
            self.assertTrue(profiles[0][key] < profiles[1][key] < profiles[2][key], key)

    def test_invalid_settings_preserve_current_profile(self):
        current = PRESETS['quality']
        cfg = normalize_config({'webrtc_fps': 'NaN', 'live_width': None,
                                'thumb_interval': float('inf'), 'live_fps': False}, current)
        self.assertEqual(cfg, current)
        self.assertEqual(normalize_config(None, current), current)

    def test_partial_settings_are_clamped(self):
        cfg = normalize_config({'live_fps': 1000, 'thumb_interval': -2,
                                'live_quality': '85'}, PRESETS['light'])
        self.assertEqual((cfg['live_fps'], cfg['thumb_interval'], cfg['live_quality']), (30, 0.5, 85))
        self.assertEqual(cfg['live_width'], 960)

    def test_screen_size_preserves_aspect_without_upscaling(self):
        self.assertEqual(fit_size(3840, 2160, 1600, even=True), (1600, 900))
        self.assertEqual(fit_size(800, 600, 1920, even=True), (800, 600))
        self.assertEqual(fit_size(1080, 1920, 960, even=True), (960, 1706))


class TestFrameWindow(unittest.TestCase):
    def test_paused_receiver_cannot_accumulate_frames(self):
        window = FrameWindow()
        first, second = window.reserve(), window.reserve()
        self.assertNotEqual(first, second)
        for _ in range(1000):
            self.assertIsNone(window.reserve())
        window.acknowledge(first)
        self.assertIsNotNone(window.reserve())
        self.assertIsNone(window.reserve())

    def test_late_and_duplicate_ack_do_not_release_new_frames(self):
        window = FrameWindow(limit=1)
        old = window.reserve()
        window.reset()
        current = window.reserve()
        window.acknowledge(old)
        self.assertIsNone(window.reserve())
        window.acknowledge(current)
        self.assertIsNotNone(window.reserve())
        window.acknowledge(current)
        self.assertIsNone(window.reserve())


class TestEncoderProfile(unittest.TestCase):
    def test_change_profile_updates_existing_encoder_and_preserves_remb(self):
        class Encoder:
            def __init__(self): self.value = 3_000_000
            @property
            def target_bitrate(self): return self.value
            @target_bitrate.setter
            def target_bitrate(self, value): self.value = value

        config = dict(PRESETS['balanced'])
        encoder = profile_encoder(Encoder, lambda: config['webrtc_bitrate'])()
        self.assertEqual(encoder.target_bitrate, 2_250_000)
        encoder.target_bitrate = 600_000  # red congestionada
        self.assertEqual(encoder.target_bitrate, 600_000)
        config.update(PRESETS['quality'])
        self.assertEqual(encoder.target_bitrate, 6_000_000)
        config.update(PRESETS['light'])
        self.assertEqual(encoder.target_bitrate, 750_000)
        encoder.target_bitrate = 20_000_000
        self.assertEqual(encoder.target_bitrate, 1_000_000)


class TestServerStreaming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import server
        except ImportError as e:
            raise unittest.SkipTest(str(e))
        cls.server = server

    def setUp(self):
        self.server.students.clear()
        self.server.viewers.clear()
        self.server._teacher_capture['running'] = False
        self.server._performance_config = dict(PRESETS['balanced'])
        self.peers = []
        self.teacher = self.peer()
        self.teacher.emit('register_teacher')
        self.student = self.peer()
        self.student.emit('register', {'name': 'Sintético', 'caps': {'webrtc': True}})
        self.sid = next(iter(self.server.students))
        self.teacher.get_received()
        self.student.get_received()

    def peer(self):
        peer = self.server.socketio.test_client(self.server.app)
        self.peers.append(peer)
        return peer

    def events(self, peer, name):
        return [event['args'][0] for event in peer.get_received() if event['name'] == name]

    def start(self, session='one'):
        self.teacher.emit('start_view', {'sid': self.sid, 'mode': 'control',
                                        'session': session, 'frame_ack': True, 'binary_frames': True})
        return self.events(self.student, 'viewer_start')[0]

    def tearDown(self):
        for peer in self.peers:
            if peer.is_connected(): peer.disconnect()

    def test_profiles_reach_active_and_later_students_and_dashboards(self):
        self.teacher.emit('update_config', PRESETS['light'])
        self.assertEqual(self.events(self.student, 'config_update'), [PRESETS['light']])
        self.assertEqual(self.events(self.teacher, 'config_update'), [PRESETS['light']])
        later = self.peer()
        later.emit('register', {'name': 'Nuevo'})
        self.assertEqual(self.events(later, 'config_update'), [PRESETS['light']])
        dashboard = self.peer()
        dashboard.emit('register_teacher')
        self.assertEqual(self.events(dashboard, 'config_update'), [PRESETS['light']])
        self.assertEqual(self.start()['config'], PRESETS['light'])

    def test_teacher_window_on_top_is_off_by_default_and_reaches_everyone(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(self.server, '_CLASS_SETTINGS_FILE', os.path.join(tmp, 'aula.json')), \
             patch.object(self.server, '_class_settings', {'teacher_on_top': False}):
            fresh = self.peer()
            fresh.emit('register', {'name': 'Nuevo'})
            self.assertEqual(self.events(fresh, 'class_settings'), [{'teacher_on_top': False}])
            self.teacher.emit('update_class_settings', {'teacher_on_top': True})
            self.assertEqual(self.events(self.student, 'class_settings'), [{'teacher_on_top': True}])
            self.assertEqual(self.events(self.teacher, 'class_settings'), [{'teacher_on_top': True}])
            dashboard = self.peer()
            dashboard.emit('register_teacher')
            self.assertEqual(self.events(dashboard, 'class_settings'), [{'teacher_on_top': True}])
            # Persistente: sobrevive a reiniciar el servidor.
            self.server._class_settings = {'teacher_on_top': False}
            self.assertEqual(self.server._load_class_settings(), {'teacher_on_top': True})
            self.teacher.emit('update_class_settings', {'teacher_on_top': 'yes'})
            self.assertEqual(self.events(self.student, 'class_settings'), [{'teacher_on_top': False}])

    def test_student_order_is_saved_and_sent_to_new_dashboards(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(self.server, '_STUDENT_ORDER_FILE', os.path.join(tmp, 'orden.json')), \
             patch.object(self.server, '_student_order', []):
            self.teacher.emit('update_student_order', ['Luis', 'Ana', 'Luis', '', 7, 'Bea'])
            self.assertEqual(self.events(self.teacher, 'student_order'), [['Luis', 'Ana', 'Bea']])
            # Solo a los paneles, no a los alumnos.
            self.assertEqual(self.events(self.student, 'student_order'), [])
            dashboard = self.peer()
            dashboard.emit('register_teacher')
            self.assertEqual(self.events(dashboard, 'student_order'), [['Luis', 'Ana', 'Bea']])
            # Persistente: sobrevive a reiniciar el servidor.
            self.assertEqual(self.server._load_student_order(), ['Luis', 'Ana', 'Bea'])
            self.teacher.emit('update_student_order', 'basura')
            self.assertEqual(self.events(self.teacher, 'student_order'), [[]])

    def test_panel_theme_is_saved_and_only_reaches_dashboards(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(self.server, '_PANEL_SETTINGS_FILE', os.path.join(tmp, 'panel.json')), \
             patch.object(self.server, '_panel_settings', {'theme': 'dark', 'density': 'm'}):
            self.teacher.emit('update_panel_settings', {'theme': 'light'})
            self.assertEqual(self.events(self.teacher, 'panel_settings'),
                             [{'theme': 'light', 'density': 'm'}])
            # Es del panel: los alumnos no lo reciben.
            self.assertEqual(self.events(self.student, 'panel_settings'), [])
            dashboard = self.peer()
            dashboard.emit('register_teacher')
            self.assertEqual(self.events(dashboard, 'panel_settings'),
                             [{'theme': 'light', 'density': 'm'}])
            # Persistente: sobrevive a reiniciar el servidor.
            self.assertEqual(self.server._load_panel_settings(), {'theme': 'light', 'density': 'm'})
            # La página ya sale pintada con el tema guardado (sin parpadeo).
            page = self.server.app.test_client().get('/').get_data(as_text=True)
            self.assertIn('data-theme="light"', page)
            # Valores inválidos: se conserva lo anterior; cada campo por separado.
            self.teacher.emit('update_panel_settings', {'theme': 'rosa', 'density': 'l'})
            self.assertEqual(self.events(self.teacher, 'panel_settings'),
                             [{'theme': 'light', 'density': 'l'}])
            self.teacher.emit('update_panel_settings', 'basura')
            self.assertEqual(self.events(self.teacher, 'panel_settings'),
                             [{'theme': 'light', 'density': 'l'}])

    def test_panel_settings_file_garbage_falls_back_to_dark(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'panel.json')
            with patch.object(self.server, '_PANEL_SETTINGS_FILE', path):
                self.assertEqual(self.server._load_panel_settings(), {'theme': 'dark', 'density': 'm'})
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('{"theme": "light", "density": 7')
                self.assertEqual(self.server._load_panel_settings(), {'theme': 'dark', 'density': 'm'})
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('["light"]')
                self.assertEqual(self.server._load_panel_settings(), {'theme': 'dark', 'density': 'm'})

    def test_student_rename_is_saved_and_applied_on_reconnect(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(self.server, '_STUDENT_ALIASES_FILE', os.path.join(tmp, 'nombres.json')), \
             patch.object(self.server, '_student_aliases', {}):
            key = self.server.students[self.sid]['key']
            self.teacher.emit('rename_student', {'key': key, 'name': '  Lucía   P. '})
            received = self.teacher.get_received()
            pick = lambda name: [e['args'][0] for e in received if e['name'] == name]
            self.assertEqual(pick('student_renamed'), [{'sid': self.sid, 'key': key, 'name': 'Lucía P.'}])
            self.assertEqual(pick('student_aliases'), [{key: 'Lucía P.'}])
            self.assertEqual(self.server._load_student_aliases(), {key: 'Lucía P.'})
            # Al volver a conectarse llega ya con el nombre nuevo (y su clave).
            again = self.peer()
            again.emit('register', {'name': key})
            connected = self.events(self.teacher, 'student_connected')[-1]
            self.assertEqual((connected['name'], connected['key']), ('Lucía P.', key))
            dashboard = self.peer()
            dashboard.emit('register_teacher')
            self.assertEqual(self.events(dashboard, 'student_aliases'), [{key: 'Lucía P.'}])
            # Vacío = vuelve al nombre del equipo.
            self.teacher.emit('rename_student', {'key': key, 'name': ''})
            self.assertEqual(self.server._load_student_aliases(), {})
            self.assertEqual(self.server.students[self.sid]['name'], key)

    def test_binary_jpeg_and_render_confirmation_round_trip(self):
        self.start()
        self.student.emit('remote_frame', {'image': b'\xff\xd8JPEG\xff\xd9', 'seq': 5,
                                          'session': 'one', 'orig_w': 3840, 'orig_h': 2160})
        frame = self.events(self.teacher, 'live_frame')[0]
        self.assertEqual(frame['image'], b'\xff\xd8JPEG\xff\xd9')
        self.assertEqual((frame['orig_w'], frame['orig_h']), (3840, 2160))
        self.teacher.emit('live_frame_ack', {'sid': self.sid, 'session': 'one', 'seq': 5})
        self.assertEqual(self.events(self.student, 'remote_frame_ack'), [{'seq': 5, 'session': 'one'}])

    def test_old_session_cannot_change_transport_or_confirm_new_frames(self):
        self.start('new')
        self.teacher.emit('view_transport', {'sid': self.sid, 'session': 'old', 'transport': 'webrtc'})
        self.teacher.emit('live_frame_ack', {'sid': self.sid, 'session': 'old', 'seq': 1})
        self.assertEqual(self.student.get_received(), [])
        self.student.emit('remote_frame', {'image': 'old', 'session': 'old'})
        self.assertEqual(self.events(self.teacher, 'live_frame'), [])
        self.teacher.emit('view_transport', {'sid': self.sid, 'session': 'new', 'transport': 'jpeg'})
        self.assertEqual(self.events(self.student, 'viewer_transport'), [{'session': 'new', 'transport': 'jpeg'}])

    def test_closing_dashboard_stops_capture(self):
        self.start()
        self.teacher.disconnect()
        self.assertEqual(self.events(self.student, 'viewer_stop'), [{'session': 'one'}])
        self.assertEqual(self.server.viewers, {})

    def test_delayed_stop_does_not_close_a_reopened_view(self):
        self.start('new')
        self.teacher.emit('stop_view', {'sid': self.sid, 'session': 'old'})
        self.assertEqual(self.student.get_received(), [])
        self.assertIn(self.sid, self.server.viewers)

    def test_view_only_does_not_forward_remote_input(self):
        self.teacher.emit('start_view', {'sid': self.sid, 'mode': 'view'})
        self.student.get_received()
        self.teacher.emit('remote_input', {'sid': self.sid, 'type': 'mousedown'})
        self.assertEqual(self.events(self.student, 'do_input'), [])

    def test_direct_share_default_only_for_local_kde_wayland(self):
        for address, desktop, wayland, expected in [
            ('127.0.0.1', 'KDE', True, 'true'),
            ('::1', 'plasma', True, 'true'),
            ('192.0.2.25', 'KDE', True, 'false'),
            ('127.0.0.1', 'KDE', False, 'false'),
            ('127.0.0.1', 'GNOME', True, 'false'),
        ]:
            with self.subTest(address=address, desktop=desktop, wayland=wayland), \
                 patch.dict('os.environ', {'XDG_CURRENT_DESKTOP': desktop}), \
                 patch.object(self.server.screen_capture, 'is_wayland', return_value=wayland):
                response = self.server.app.test_client().get('/', environ_base={'REMOTE_ADDR': address})
                self.assertEqual(response.status_code, 200)
                self.assertIn(f'const PREFER_SERVER_CAPTURE = {expected}', response.text)

    def test_version_identifies_running_server_and_panel(self):
        from vigia_version import VERSION
        client = self.server.app.test_client()
        response = client.get('/api/version')
        self.assertEqual((response.json['app'], response.json['version']), ('vigia-server', VERSION))
        self.assertTrue({'pid', 'uid', 'user', 'graphical', 'session'} <= set(response.json))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertIn(f'<title>VIGIA {VERSION}', client.get('/').text)

    KWIN = {
        'screens': [{'x': 0, 'y': 0, 'w': 1920, 'h': 1080, 'name': 'eDP-1'},
                    {'x': 1920, 'y': 0, 'w': 1920, 'h': 1080, 'name': 'HDMI-A-1'}],
        'windows': [
            {'id': '{doc}', 'title': 'Apuntes - Writer', 'cls': 'libreoffice', 'app': '',
             'x': 2020, 'y': 100, 'w': 800, 'h': 600, 'min': False, 'vis': True},
            {'id': '{min}', 'title': 'Minimizada', 'cls': 'kate', 'app': '',
             'x': 0, 'y': 0, 'w': 800, 'h': 600, 'min': True, 'vis': False},
            {'id': '{panel}', 'title': 'VIGIA 1.2 — Panel', 'cls': 'chrome', 'app': '',
             'x': 0, 'y': 0, 'w': 1920, 'h': 1080, 'min': False, 'vis': True},
        ],
    }

    def desktop_capture(self):
        """Escritorio de dos monitores: el izquierdo rojo, el derecho azul y una
        ventana verde en el derecho."""
        from PIL import Image
        import screen_capture as sc
        full = Image.new('RGB', (3840, 1080), 'red')
        full.paste((0, 0, 255), (1920, 0, 3840, 1080))
        full.paste((0, 255, 0), (2020, 100, 2820, 700))
        capture = object.__new__(sc.CliBackend)
        capture.name = 'spectacle'; capture.index = 0; capture._geom = None
        capture._mons = self.server.kwin_info.monitores(self.KWIN)
        capture._grab_full = lambda max_age=0.0: full
        capture.close = lambda: None
        return capture

    def test_wayland_screen_list_offers_full_desktop_each_monitor_and_windows(self):
        import base64, io
        from PIL import Image
        capture = self.desktop_capture()
        with patch.object(self.server.screen_capture, 'create_capturer', return_value=capture), \
             patch.object(self.server.kwin_info, 'consultar', return_value=self.KWIN):
            self.teacher.emit('get_screens')
        screens = self.events(self.teacher, 'screens_list')[0]['screens']
        monitors = [s for s in screens if s['type'] == 'monitor']
        windows = [s for s in screens if s['type'] == 'window']
        self.assertEqual([s['index'] for s in monitors], [0, 1, 2])
        self.assertEqual(monitors[0]['label'], 'Pantalla completa: los 2 monitores (3840×1080)')
        self.assertEqual(monitors[1]['label'], 'Monitor 1 — eDP-1 (1920×1080)')
        self.assertEqual(monitors[2]['label'], 'Monitor 2 — HDMI-A-1 (1920×1080)')

        def thumb(s):
            return Image.open(io.BytesIO(base64.b64decode(s['thumb'].split(',', 1)[1]))).convert('RGB')

        def rojo(px):
            return px[0] > 200 and px[2] < 60

        # La miniatura completa muestra los dos monitores; cada monitor, el suyo.
        completa = thumb(monitors[0])
        self.assertEqual(completa.size, (192, 54))
        self.assertTrue(rojo(completa.getpixel((5, 27))))
        self.assertFalse(rojo(completa.getpixel((186, 27))))
        self.assertTrue(rojo(thumb(monitors[1]).getpixel((96, 54))))
        self.assertFalse(rojo(thumb(monitors[2]).getpixel((5, 5))))
        # Ventanas: sin el propio panel; la minimizada, sin miniatura.
        self.assertEqual([(w['wid'], w['label']) for w in windows],
                         [('{doc}', 'Apuntes - Writer'), ('{min}', 'Minimizada')])
        doc = thumb(windows[0])
        self.assertEqual(doc.size, (192, 144))
        px = doc.getpixel((96, 72))
        self.assertTrue(px[1] > 200 and px[0] < 60, px)
        self.assertIsNone(windows[1]['thumb'])

    def test_wayland_window_share_sends_only_that_window(self):
        capture = self.desktop_capture()
        with patch.object(self.server.socketio, 'start_background_task') as start:
            self.teacher.emit('start_teacher_capture', {'type': 'window', 'wid': '{doc}'})
        state = self.server._teacher_capture
        with patch.object(self.server.screen_capture, 'create_capturer', return_value=capture), \
             patch.object(self.server.screen_capture, 'is_wayland', return_value=True), \
             patch.object(self.server.kwin_info, 'consultar', return_value=self.KWIN), \
             patch.object(self.server.kwin_info, 'activar', return_value=True) as activar, \
             patch.object(self.server.socketio, 'sleep', side_effect=lambda _: state.update(running=False)):
            start.call_args.args[0](*start.call_args.args[1:])
        activar.assert_called_once_with('{doc}')
        frames = self.events(self.student, 'teacher_screen')
        self.assertEqual(len(frames), 1)
        import base64, io
        from PIL import Image
        img = Image.open(io.BytesIO(base64.b64decode(frames[0]['image'].split(',', 1)[1])))
        self.assertEqual(img.size, (800, 600))

    def test_wayland_window_minimized_or_closed(self):
        ventana = self.server._VentanaWayland('{min}')
        with patch.object(self.server.kwin_info, 'consultar', return_value=self.KWIN):
            self.assertTrue(ventana.actualizar())
        self.assertIsNone(ventana.recortar(self.desktop_capture().grab()))
        with patch.object(self.server.kwin_info, 'consultar', return_value=None):
            self.assertFalse(ventana.actualizar())       # KWin no contesta: no se da por cerrada
        self.assertFalse(ventana.cerrada)
        # Cerrada durante la clase: se avisa al panel y se para.
        with patch.object(self.server.socketio, 'start_background_task'):
            self.teacher.emit('start_teacher_capture', {'type': 'window', 'wid': '{doc}'})
        state = self.server._teacher_capture
        respuestas = iter([self.KWIN, {'screens': self.KWIN['screens'], 'windows': []}])
        with patch.object(self.server.screen_capture, 'create_capturer', return_value=self.desktop_capture()), \
             patch.object(self.server.screen_capture, 'is_wayland', return_value=True), \
             patch.object(self.server.kwin_info, 'consultar', side_effect=lambda: next(respuestas)), \
             patch.object(self.server.kwin_info, 'activar', return_value=True), \
             patch.object(self.server.socketio, 'sleep'):
            self.server._teacher_capture_loop(state)
        self.assertFalse(state['running'])
        self.assertEqual(self.events(self.teacher, 'teacher_screen_preview'),
                         [{'ended': 'La ventana compartida se ha cerrado'}])
        self.assertEqual(self.events(self.student, 'teacher_screen'), [])

    def test_wayland_window_covered_by_another_is_not_sent(self):
        # El panel (u otra ventana) encima de la compartida: el recorte lo
        # mostraría a los alumnos. Se avisa una vez y no se envía nada.
        tapada = {'screens': self.KWIN['screens'], 'windows': [
            {'id': '{chat}', 'title': 'Chat', 'cls': 'x', 'x': 2400, 'y': 300, 'w': 600, 'h': 600,
             'min': False, 'vis': True}] + self.KWIN['windows']}
        with patch.object(self.server.socketio, 'start_background_task'):
            self.teacher.emit('start_teacher_capture', {'type': 'window', 'wid': '{doc}'})
        state = self.server._teacher_capture
        vueltas = []

        def sleep(_):
            vueltas.append(1)
            if len(vueltas) >= 3:
                state['running'] = False

        with patch.object(self.server.screen_capture, 'create_capturer', return_value=self.desktop_capture()), \
             patch.object(self.server.screen_capture, 'is_wayland', return_value=True), \
             patch.object(self.server.kwin_info, 'consultar', return_value=tapada), \
             patch.object(self.server.kwin_info, 'activar', return_value=True), \
             patch.object(self.server.socketio, 'sleep', side_effect=sleep):
            self.server._teacher_capture_loop(state)
        self.assertEqual(self.events(self.student, 'teacher_screen'), [])
        avisos = [e for e in self.events(self.teacher, 'teacher_screen_preview') if 'aviso' in e]
        self.assertEqual(len(avisos), 1)

    def test_share_size_is_limited_by_area_not_only_width(self):
        from PIL import Image
        escalar = self.server._escalar_para_compartir
        self.assertEqual(escalar(Image.new('RGB', (1920, 1080)), 1600).size, (1600, 900))
        self.assertEqual(escalar(Image.new('RGB', (3840, 1080)), 1600).size, (2263, 636))
        self.assertEqual(escalar(Image.new('RGB', (800, 600)), 1600).size, (800, 600))

    def test_direct_capture_retries_while_desktop_starts(self):
        capture = Mock(name='capture')
        fallo = self.server.screen_capture.CaptureError('spectacle devolvió 1')
        with patch.object(self.server.screen_capture, 'create_capturer',
                          side_effect=[fallo, fallo, capture]) as create, \
             patch.object(self.server.socketio, 'sleep') as sleep:
            self.assertIs(self.server._crear_capturador_profesor(), capture)
        self.assertEqual(create.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        with patch.object(self.server.screen_capture, 'create_capturer', side_effect=fallo), \
             patch.object(self.server.socketio, 'sleep'):
            with self.assertRaises(self.server.screen_capture.CaptureError):
                self.server._crear_capturador_profesor()

    def test_session_env_only_from_local_launcher(self):
        import desktop_session
        client = self.server.app.test_client()
        with patch.object(desktop_session, 'set_session_override', return_value=True) as adopt:
            r = client.post('/api/session-env', json={'WAYLAND_DISPLAY': 'wayland-0'},
                            environ_base={'REMOTE_ADDR': '192.0.2.25'})
            self.assertEqual(r.status_code, 403)
            adopt.assert_not_called()
            r = client.post('/api/session-env', json={'WAYLAND_DISPLAY': 'wayland-0'},
                            environ_base={'REMOTE_ADDR': '127.0.0.1'})
        self.assertTrue(r.json['ok'])
        adopt.assert_called_once_with({'WAYLAND_DISPLAY': 'wayland-0'})

    def test_screen_list_does_not_open_portal_or_share_with_students(self):
        from PIL import Image
        capture = Mock(name='capture')
        capture.name = 'spectacle'
        capture.grab.return_value = Image.new('RGB', (640, 360), 'red')
        with patch.object(self.server.screen_capture, 'create_capturer', return_value=capture) as create, \
             patch.object(self.server.kwin_info, 'consultar', return_value=None):
            self.teacher.emit('get_screens')
        create.assert_called_once_with(verbose=False, allow_portal=False)
        screens = self.events(self.teacher, 'screens_list')[0]['screens']
        self.assertEqual(len(screens), 1)
        self.assertTrue(screens[0]['thumb'].startswith('data:image/jpeg;base64,'))
        self.assertEqual(self.events(self.student, 'teacher_screen'), [])
        capture.close.assert_called_once()

    def test_service_without_desktop_environment_uses_installed_kde_capture(self):
        with patch.dict('os.environ', {'XDG_CURRENT_DESKTOP': ''}), \
             patch.object(self.server.screen_capture, 'is_wayland', return_value=True), \
             patch.object(self.server.shutil, 'which', return_value='/usr/bin/spectacle'):
            response = self.server.app.test_client().get('/', environ_base={'REMOTE_ADDR': '127.0.0.1'})
        self.assertIn('const PREFER_SERVER_CAPTURE = true', response.text)

    def test_launcher_can_choose_capture_independently_of_service_environment(self):
        for address, query, expected in [
            ('127.0.0.1', 'server', 'true'),
            ('::1', 'server', 'true'),
            ('192.0.2.25', 'server', 'false'),
            ('127.0.0.1', 'browser', 'false'),
        ]:
            with self.subTest(address=address, query=query), \
                 patch.dict('os.environ', {'XDG_CURRENT_DESKTOP': ''}), \
                 patch.object(self.server.screen_capture, 'is_wayland', return_value=False):
                response = self.server.app.test_client().get(
                    f'/?capture={query}', environ_base={'REMOTE_ADDR': address})
                self.assertIn(f'const PREFER_SERVER_CAPTURE = {expected}', response.text)

    def test_direct_capture_delivers_only_to_selected_students(self):
        from PIL import Image
        other = self.peer()
        other.emit('register', {'name': 'No seleccionado'})
        other.get_received()
        capture = Mock()
        capture.grab.return_value = Image.new('RGB', (640, 360), 'red')
        with patch.object(self.server.socketio, 'start_background_task') as start:
            self.teacher.emit('start_teacher_capture', {'sids': [self.sid]})
        state = self.server._teacher_capture
        with patch.object(self.server.screen_capture, 'create_capturer', return_value=capture) as create, \
             patch.object(self.server.socketio, 'sleep', side_effect=lambda _: state.update(running=False)):
            start.call_args.args[0](*start.call_args.args[1:])
        create.assert_called_once_with(allow_portal=False)
        frames = self.events(self.student, 'teacher_screen')
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0]['activa'])
        self.assertEqual(self.events(other, 'teacher_screen'), [])
        preview = self.events(self.teacher, 'teacher_screen_preview')[0]
        self.assertEqual(frames[0]['image'], preview['image'])
        capture.close.assert_called_once()

    def test_stop_discards_in_flight_capture_before_restart(self):
        from PIL import Image
        with patch.object(self.server.socketio, 'start_background_task'):
            self.teacher.emit('start_teacher_capture')
            old = self.server._teacher_capture
            capture = Mock()

            def stop_and_restart():
                self.teacher.emit('stop_teacher_capture')
                self.teacher.emit('start_teacher_capture')
                return Image.new('RGB', (640, 360), 'red')

            capture.grab.side_effect = stop_and_restart
            with patch.object(self.server.screen_capture, 'create_capturer', return_value=capture):
                self.server._teacher_capture_loop(old)
        self.assertFalse(old['running'])
        self.assertIsNot(old, self.server._teacher_capture)
        self.assertTrue(self.server._teacher_capture['running'])
        self.assertEqual(self.events(self.student, 'teacher_screen'), [{'activa': False}])
        self.assertEqual(self.events(self.teacher, 'teacher_screen_preview'), [])
        capture.close.assert_called_once()

    def test_failed_capture_reports_error_and_releases_resources(self):
        with patch.object(self.server.socketio, 'start_background_task'):
            self.teacher.emit('start_teacher_capture')
        capture = Mock()
        capture.grab.side_effect = RuntimeError('No hay imagen')
        with patch.object(self.server.screen_capture, 'create_capturer', return_value=capture):
            self.server._teacher_capture_loop(self.server._teacher_capture)
        self.assertFalse(self.server._teacher_capture['running'])
        self.assertIn('No hay imagen', self.events(self.teacher, 'teacher_screen_preview')[0]['error'])
        self.assertEqual(self.events(self.student, 'teacher_screen'), [])
        capture.close.assert_called_once()

    def test_old_capture_failure_does_not_stop_new_share(self):
        with patch.object(self.server.socketio, 'start_background_task'):
            self.teacher.emit('start_teacher_capture')
            old = self.server._teacher_capture

            def fail_after_restart(**kwargs):
                self.teacher.emit('start_teacher_capture')
                raise RuntimeError('La captura anterior falló')

            with patch.object(self.server.screen_capture, 'create_capturer', side_effect=fail_after_restart):
                self.server._teacher_capture_loop(old)
        self.assertFalse(old['running'])
        self.assertTrue(self.server._teacher_capture['running'])
        self.assertEqual(self.events(self.teacher, 'teacher_screen_preview'), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
