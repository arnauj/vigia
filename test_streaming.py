"""Regresiones de perfiles, caudal JPEG y sesiones (sin escritorio real).

python3 test_streaming.py
Las pruebas del servidor requieren flask-socketio.
"""

import unittest

from streaming import PRESETS, FrameWindow, fit_size, normalize_config, profile_encoder


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
