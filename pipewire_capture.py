"""
VIGIA — Captura fluida en Wayland vía PipeWire + xdg-desktop-portal ScreenCast.

En KDE Wayland (Kubuntu 26) no se puede capturar el escritorio a buen ritmo con
herramientas que arrancan un proceso por frame (spectacle ~2 fps) ni con
`org.kde.KWin.ScreenShot2` (KWin solo autoriza apps de su allowlist). La vía
correcta —y la que usa RustDesk— es el portal `org.freedesktop.portal.ScreenCast`:

  1. Handshake D-Bus con el portal: CreateSession → SelectSources → Start →
     OpenPipeWireRemote. Devuelve un nodo PipeWire + un fd.
  2. Se tira de los frames con GStreamer (`pipewiresrc fd=.. path=.. ! appsink`),
     a la tasa del compositor (típicamente 30-60 fps).

La PRIMERA vez el portal muestra un diálogo de KDE («¿compartir pantalla?»). Con
`persist_mode=2` el portal devuelve un `restore_token` que guardamos en disco;
las siguientes ejecuciones restauran la sesión SIN diálogo. Es el mismo
comportamiento de RustDesk: una autorización por equipo y ya.

Si algo falla (sin portal, sin GStreamer, denegado, timeout) se lanza una
excepción y `screen_capture` cae automáticamente al backend spectacle.

Ejecutar en solitario para probar:
    python3 pipewire_capture.py
"""

import itertools
import os
import threading
import time

MAX_FPS = 30                 # tope de tasa negociada con el compositor
CURSOR_EMBEDDED = 2          # el cursor del alumno viaja dentro del vídeo
PERSIST_UNTIL_REVOKED = 2    # restore_token válido hasta que el usuario lo revoque
SOURCE_MONITOR = 1           # capturar un monitor completo

_PORTAL_BUS = 'org.freedesktop.portal.Desktop'
_PORTAL_OBJ = '/org/freedesktop/portal/desktop'
_SC_IFACE = 'org.freedesktop.portal.ScreenCast'
_REQ_IFACE = 'org.freedesktop.portal.Request'

_token_counter = itertools.count(1)


def _token_path():
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')
    return os.path.join(base, 'vigia', 'screencast.token')


def _load_token():
    try:
        with open(_token_path(), 'r') as f:
            t = f.read().strip()
            return t or None
    except OSError:
        return None


def _save_token(tok):
    if not tok:
        return
    try:
        p = _token_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w') as f:
            f.write(tok)
    except OSError:
        pass


class PortalScreenCast:
    """Gestiona la sesión ScreenCast del portal y entrega (node_id, fd).

    Todo el handshake D-Bus ocurre en el hilo que construye esta clase: las
    señales Response se despachan bombeando el contexto GLib en ese mismo hilo
    (`MainContext.iteration`), evitando el bucle de eventos en un hilo aparte
    —que con libdbus no es thread-safe y hacía que nunca llegara la respuesta—.
    """

    def __init__(self, timeout=30):
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib
        DBusGMainLoop(set_as_default=True)
        self._dbus = dbus
        self._ctx = GLib.MainContext.default()
        self.bus = dbus.SessionBus()
        self.timeout = timeout
        self.portal = self.bus.get_object(_PORTAL_BUS, _PORTAL_OBJ)
        self.sc = dbus.Interface(self.portal, _SC_IFACE)
        self._sender = self.bus.get_unique_name()[1:].replace('.', '_')
        self.session_handle = None
        self.restore_token = None

    def _request(self, make_call, extra_opts=None):
        """Llama a un método del portal que devuelve un objeto Request y espera
        su señal Response, bombeando el contexto GLib. Devuelve los resultados."""
        token = 'vigia_%d' % next(_token_counter)
        opts = {'handle_token': self._dbus.String(token)}
        if extra_opts:
            opts.update(extra_opts)
        req_path = '/org/freedesktop/portal/desktop/request/%s/%s' % (
            self._sender, token)
        box = {}

        def on_response(code, results):
            box['code'] = int(code)
            box['results'] = results

        from gi.repository import GLib
        match = self.bus.add_signal_receiver(
            on_response, signal_name='Response', dbus_interface=_REQ_IFACE,
            bus_name=_PORTAL_BUS, path=req_path)
        # Fuente periódica: despierta el contexto cada 200 ms para reevaluar el
        # deadline aunque no lleguen señales D-Bus.
        waker = GLib.timeout_add(200, lambda: True)
        try:
            make_call(opts)
            deadline = time.monotonic() + self.timeout
            while 'code' not in box:
                if time.monotonic() > deadline:
                    raise TimeoutError('portal ScreenCast: sin respuesta')
                self._ctx.iteration(may_block=True)
        finally:
            GLib.source_remove(waker)
            match.remove()
        if box.get('code') != 0:
            raise RuntimeError('portal ScreenCast: cancelado/denegado (code=%s)'
                               % box.get('code'))
        return box.get('results', {})

    def open(self):
        """Realiza el handshake completo y devuelve (node_id:int, fd:int)."""
        d = self._dbus
        dbg = os.environ.get('VIGIA_PW_DEBUG')

        def log(m):
            if dbg:
                print('  [portal] ' + m, flush=True)

        # 1) CreateSession
        log('CreateSession...')
        sess_token = 'vigiasess_%d' % next(_token_counter)
        res = self._request(
            lambda opts: self.sc.CreateSession(opts),
            extra_opts={'session_handle_token': d.String(sess_token)})
        self.session_handle = str(res['session_handle'])
        log('session_handle=%s' % self.session_handle)

        # 2) SelectSources (con restore_token si lo teníamos guardado)
        log('SelectSources (restore_token=%s)...' % bool(_load_token()))
        sel = {
            'types': d.UInt32(SOURCE_MONITOR),
            'multiple': d.Boolean(False),
            'cursor_mode': d.UInt32(CURSOR_EMBEDDED),
            'persist_mode': d.UInt32(PERSIST_UNTIL_REVOKED),
        }
        prev = _load_token()
        if prev:
            sel['restore_token'] = d.String(prev)
        self._request(
            lambda opts: self.sc.SelectSources(self.session_handle,
                                               {**opts, **sel}))
        log('SelectSources OK')

        # 3) Start (muestra el diálogo la 1ª vez; silencioso con token válido)
        log('Start (puede mostrar diálogo)...')
        res = self._request(
            lambda opts: self.sc.Start(self.session_handle, '', opts))
        log('Start OK; streams=%s' % (res.get('streams') is not None))
        self.restore_token = str(res.get('restore_token', '') or '') or None
        if self.restore_token:
            _save_token(self.restore_token)
        streams = res.get('streams')
        if not streams:
            raise RuntimeError('portal ScreenCast: sin streams')
        node_id = int(streams[0][0])

        # 4) OpenPipeWireRemote → fd del socket PipeWire
        fd_obj = self.sc.OpenPipeWireRemote(self.session_handle, {})
        fd = fd_obj.take() if hasattr(fd_obj, 'take') else int(fd_obj)
        return node_id, fd

    def close(self):
        try:
            if self.session_handle:
                self.bus.get_object(_PORTAL_BUS, self.session_handle)
        except Exception:
            pass


class PipeWireBackend:
    """Backend de captura para screen_capture: API .grab()/.monitor()/.close()."""

    name = 'pipewire'

    def __init__(self, timeout=30, max_fps=MAX_FPS):
        import gi
        gi.require_version('Gst', '1.0')
        from gi.repository import Gst
        Gst.init(None)
        self._Gst = Gst

        self._portal = PortalScreenCast(timeout=timeout)
        node_id, fd = self._portal.open()
        self._fd = fd
        self._pipe = None
        self._sink = self._pipe_fd = None
        self._geom = None
        # Caché del último frame crudo: permite que varios consumidores
        # (miniaturas + WebRTC) compartan el MISMO frame en lugar de pedir dos
        # capturas al compositor. Ver grab_raw(max_age=...).
        self._cache = None      # (data, w, h, stride)
        self._cache_ts = 0.0

        # Se intenta primero limitando la tasa a max_fps: así KWin compone y
        # copia la mitad de frames (a 60 Hz) y baja mucho el consumo de CPU/GPU
        # del alumno. Si esa negociación falla (compositor que solo ofrece su
        # tasa nativa), se reintenta sin límite.
        errors = []
        for fps in ([max_fps, None] if max_fps else [None]):
            try:
                self._build_pipeline(node_id, fps)
                self.grab_raw()   # valida que realmente llegan frames
                self._fps_cap = fps
                break
            except Exception as e:
                errors.append('fps=%s: %s' % (fps, e))
                self._teardown_pipeline()
        else:
            try:
                os.close(self._fd)
            except OSError:
                pass
            raise RuntimeError('pipewire: no se pudo abrir el stream (%s)'
                               % '; '.join(errors))

    def _build_pipeline(self, node_id, fps=None):
        """Crea la tubería GStreamer y espera al preroll.

        drop=true + max-buffers=1: appsink siempre sirve el frame más reciente.
        Se negocia BGRx: es el formato nativo que entrega KWin/PipeWire, así
        videoconvert queda en passthrough (coste 0 por frame). Con RGB se
        forzaba una conversión software del frame COMPLETO a 30-60 fps, que
        cargaba la CPU del alumno y hacía ir lento todo el sistema.

        `fps` se expresa como RANGO [0/1, fps/1] (no como valor fijo): así la
        negociación no falla si el compositor no ofrece exactamente esa tasa.
        """
        Gst = self._Gst
        # Sin espacios: gst_parse_launch trocea la descripción por espacios y
        # partiría el caps en varios «elementos».
        rate = ',framerate=(fraction)[0/1,%d/1]' % int(fps) if fps else ''
        # fd duplicado por intento: al poner la tubería en NULL, pipewiresrc
        # puede cerrar el descriptor y dejaría inservible el reintento.
        self._pipe_fd = os.dup(self._fd)
        desc = (
            'pipewiresrc fd=%d path=%d do-timestamp=true keepalive-time=1000 ! '
            'videoconvert n-threads=0 ! video/x-raw,format=BGRx%s ! '
            'appsink name=sink emit-signals=false max-buffers=1 drop=true sync=false'
            % (self._pipe_fd, node_id, rate))
        self._pipe = Gst.parse_launch(desc)
        self._sink = self._pipe.get_by_name('sink')
        self._pipe.set_state(Gst.State.PLAYING)
        # Esperar al preroll (primer frame negociado) para conocer el tamaño.
        self._pipe.get_state(5 * Gst.SECOND)

    def _teardown_pipeline(self):
        try:
            if self._pipe is not None:
                self._pipe.set_state(self._Gst.State.NULL)
        except Exception:
            pass
        self._pipe = self._sink = None
        if self._pipe_fd is not None:
            try:
                os.close(self._pipe_fd)
            except OSError:
                pass
            self._pipe_fd = None

    def _pull(self):
        Gst = self._Gst
        sample = self._sink.emit('try-pull-sample', 2 * Gst.SECOND)
        if sample is None:
            raise RuntimeError('pipewire: sin frames (timeout)')
        caps = sample.get_caps().get_structure(0)
        w = caps.get_value('width')
        h = caps.get_value('height')
        buf = sample.get_buffer()
        ok, minfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            raise RuntimeError('pipewire: no se pudo mapear el buffer')
        try:
            data = bytes(minfo.data)
        finally:
            buf.unmap(minfo)
        self._geom = {'left': 0, 'top': 0, 'width': w, 'height': h}
        return w, h, data

    def monitor(self):
        if self._geom is None:
            self.grab()
        return self._geom

    def grab(self, max_age=0.0):
        from PIL import Image
        data, w, h, stride = self.grab_raw(max_age=max_age)
        # El decoder raw 'BGRX' de PIL descarta el canal de relleno y acepta el
        # stride real (séptimo argumento) por si GStreamer añade padding.
        return Image.frombuffer('RGB', (w, h), data, 'raw', 'BGRX', stride, 1)

    def grab_raw(self, max_age=0.0):
        """Frame crudo BGRx sin pasar por PIL: (data, w, h, stride_bytes).

        Es la vía rápida para WebRTC: el cliente lo convierte/escala con
        swscale (libav) en un único paso SIMD, sin PIL ni copias extra.

        `max_age` (segundos) permite reutilizar el último frame capturado si
        aún es reciente. Las miniaturas (1 fps) aprovechan así el frame que ya
        tiró WebRTC: ni se pide otro frame al compositor ni se compite por el
        appsink (con max-buffers=1 dos consumidores se roban los frames).
        """
        if max_age > 0 and self._cache is not None and \
                (time.monotonic() - self._cache_ts) <= max_age:
            return self._cache
        w, h, data = self._pull()
        if h <= 0 or len(data) < w * h * 4:
            raise RuntimeError('pipewire: frame incompleto')
        self._cache = (data, w, h, len(data) // h)
        self._cache_ts = time.monotonic()
        return self._cache

    def close(self):
        self._teardown_pipeline()
        self._cache = None
        try:
            os.close(self._fd)
        except OSError:
            pass
        try:
            self._portal.close()
        except Exception:
            pass


def create_backend(timeout=30, max_fps=MAX_FPS):
    """Crea un PipeWireBackend o lanza si no es posible."""
    return PipeWireBackend(timeout=timeout, max_fps=max_fps)


if __name__ == '__main__':
    import sys
    print('VIGIA — prueba de captura PipeWire (portal ScreenCast)')
    print('Si aparece un diálogo de KDE, acepta y marca «recordar».')
    try:
        be = create_backend(timeout=60)
    except Exception as e:
        print('FALLO al abrir el screencast:', type(e).__name__, e)
        sys.exit(1)
    mon = be.monitor()
    print('Monitor:', mon, '| tope de tasa negociado:', be._fps_cap or 'nativo')
    n = 60
    t0 = time.time()
    black = 0
    for _ in range(n):
        img = be.grab()
        ex = img.getextrema()
        if all(a == 0 and b == 0 for a, b in ex):
            black += 1
    dt = time.time() - t0
    print('%d frames en %.2fs => %.1f fps (negros: %d)' % (n, dt, n / dt, black))
    be.close()
