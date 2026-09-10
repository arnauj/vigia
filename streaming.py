"""Perfiles y control de caudal compartidos por servidor y cliente."""

import math
import threading


PRESETS = {
    'light': dict(thumb_interval=3.0, thumb_quality=35, thumb_width=480,
                  live_fps=12, webrtc_fps=15, live_quality=45,
                  live_width=960, webrtc_bitrate=1_000_000),
    'balanced': dict(thumb_interval=1.0, thumb_quality=55, thumb_width=720,
                     live_fps=25, webrtc_fps=30, live_quality=70,
                     live_width=1600, webrtc_bitrate=3_000_000),
    'quality': dict(thumb_interval=0.5, thumb_quality=75, thumb_width=960,
                    live_fps=30, webrtc_fps=60, live_quality=90,
                    live_width=1920, webrtc_bitrate=8_000_000),
}
LIMITS = {
    'thumb_interval': (0.5, 5.0), 'thumb_quality': (20, 90),
    'thumb_width': (320, 1280), 'live_fps': (5, 30),
    'webrtc_fps': (10, 60), 'live_quality': (30, 95),
    'live_width': (640, 1920), 'webrtc_bitrate': (500_000, 8_000_000),
}


def normalize_config(data, current=None):
    """Valida cambios parciales sin perder los ajustes que ya estaban activos."""
    config = dict(PRESETS['balanced'] if current is None else current)
    if not isinstance(data, dict):
        return config
    for key, (minimum, maximum) in LIMITS.items():
        try:
            value = float(data[key])
            if not math.isfinite(value) or isinstance(data[key], bool):
                continue
            value = max(minimum, min(maximum, value))
            config[key] = value if key == 'thumb_interval' else int(value)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return config


def fit_size(width, height, max_width, even=False):
    """Reduce sin ampliar y conserva la proporción y las coordenadas originales."""
    scale = min(1.0, max_width / width)
    width, height = max(1, int(width * scale)), max(1, int(height * scale))
    if even:
        width, height = max(2, width & ~1), max(2, height & ~1)
    return width, height


class FrameWindow:
    """Como máximo dos JPEG en tránsito hasta que el panel los descodifique.

    Sin caducidad: reintentar mientras el receptor está parado volvería a
    llenar la cola TCP. La reconexión o una nueva vista reinicia la ventana.
    Los identificadores no se reutilizan para ignorar confirmaciones tardías.
    """

    def __init__(self, limit=2):
        self.limit = limit
        self._pending = set()
        self._sequence = 0
        self._lock = threading.Lock()

    def reserve(self):
        with self._lock:
            if len(self._pending) >= self.limit:
                return None
            self._sequence += 1
            self._pending.add(self._sequence)
            return self._sequence

    def acknowledge(self, sequence):
        with self._lock:
            self._pending.discard(sequence)

    def reset(self):
        with self._lock:
            self._pending.clear()


def profile_encoder(base, bitrate):
    """Aplica el perfil a los encoders aiortc sin anular su adaptación REMB.

    aiortc expone target_bitrate en sus encoders; RTCRtpSender no ofrece la
    API getParameters/setParameters de JavaScript. El límite se consulta en
    cada frame, por lo que cambiar de perfil funciona sin renegociar vídeo.
    """
    class ProfileEncoder(base):
        @property
        def target_bitrate(self):
            limit = bitrate()
            if getattr(self, '_vigia_limit', None) != limit:
                self._vigia_limit = limit
                base.target_bitrate.fset(self, int(limit * 0.75))
            return min(limit, base.target_bitrate.fget(self))

        @target_bitrate.setter
        def target_bitrate(self, value):
            limit = bitrate()
            self._vigia_limit = limit
            base.target_bitrate.fset(self, min(limit, value))

    return ProfileEncoder
