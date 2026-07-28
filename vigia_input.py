#!/usr/bin/env python3
"""
VIGIA — Inyección de input y bloqueo en Wayland vía uinput (demonio root).

Problema que resuelve: el dispositivo virtual de ydotoold solo tiene ejes
RELATIVOS (EV_REL), no absolutos. Por eso `ydotool mousemove -a` (absoluto) no
funciona en Wayland: hace un «homing» a (0,0) y el cursor se queda en la esquina
superior izquierda (disparando además los hot-corners de KDE: el escritorio
«cambia y descambia»). La solución —la que usa RustDesk— es crear nuestro propio
dispositivo uinput con eje ABSOLUTO (ABS_X/ABS_Y), cuyo rango 0..32767 KWin mapea
a toda la pantalla: las coordenadas mapean 1:1 y el cursor va donde toca.

Además, el bloqueo de pantalla en Wayland no puede hacerse con XGrabKeyboard
(solo X11). Aquí se bloquea de verdad haciendo EVIOCGRAB de los dispositivos de
entrada FÍSICOS del alumno (su teclado/ratón quedan inertes), mientras el ratón
virtual del profesor —que NO se agarra— sigue inyectando.

Este módulo es a la vez:
  • Demonio (corre como root, crea el uinput y escucha en un socket UNIX):
        python3 vigia_input.py --daemon
  • Cliente importable (lo usa client.py para enviar eventos):
        from vigia_input import VigiaInput

Protocolo: líneas JSON sobre /run/vigia-input.sock (0666). Comandos:
  {"t":"m","x":0..32767,"y":0..32767}     mover (absoluto)
  {"t":"b","btn":"left|right|middle","s":0|1}  botón (1=down,0=up)
  {"t":"s","dy":N,"dx":N}                  rueda (clicks; +arriba/-abajo)
  {"t":"k","code":N,"s":0|1}               tecla por código de kernel (KEY_*)
  {"t":"grab","on":true|false}             bloquear/desbloquear input físico
  {"t":"hello"}                            → responde {"ok":1,"feat":["kb"]}
El teclado («k») evita lanzar un proceso `ydotool` por pulsación: cada tecla
costaba ~20-30 ms de fork+exec, y escribir con el control remoto se notaba
pegajoso. Un demonio antiguo no responde a «hello» y el cliente sigue usando
ydotool automáticamente.
El grab se libera AUTOMÁTICAMENTE si la conexión que lo pidió se cierra
(seguridad: si el cliente del profesor muere, el alumno no queda bloqueado).
"""

import json
import os
import socket
import sys
import threading

SOCK_PATH = '/run/vigia-input.sock'
ABS_MAX = 32767
_DEV_NAME = 'vigia-virtual-pointer'
# Códigos de tecla declarados por el dispositivo virtual (igual que ydotoold):
# KEY_ESC(1) .. KEY_MICMUTE(248) cubre todo el teclado estándar.
_KEY_MIN, _KEY_MAX = 1, 248


# ── Cliente (lo importa client.py) ────────────────────────────────────────────

class VigiaInput:
    """Conexión persistente al demonio. Reabre sola si se cae."""

    def __init__(self, path=SOCK_PATH):
        self.path = path
        self._sock = None
        self._lock = threading.Lock()

    def _ensure(self):
        if self._sock is None:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect(self.path)
            self._sock = s
        return self._sock

    def _send(self, obj):
        with self._lock:
            try:
                s = self._ensure()
                s.sendall((json.dumps(obj) + '\n').encode())
                return True
            except OSError:
                try:
                    if self._sock:
                        self._sock.close()
                except OSError:
                    pass
                self._sock = None
                return False

    def available(self):
        with self._lock:
            try:
                self._ensure()
                return True
            except OSError:
                self._sock = None
                return False

    def move(self, xn, yn):
        return self._send({'t': 'm', 'x': int(xn), 'y': int(yn)})

    def button(self, btn, state):
        return self._send({'t': 'b', 'btn': btn, 's': 1 if state else 0})

    def scroll(self, dy, dx=0):
        return self._send({'t': 's', 'dy': int(dy), 'dx': int(dx)})

    def key(self, code, state):
        return self._send({'t': 'k', 'code': int(code), 's': 1 if state else 0})

    def grab(self, on):
        return self._send({'t': 'grab', 'on': bool(on)})

    def features(self, timeout=0.8):
        """Capacidades del demonio, p.ej. {'kb'}. Vacío si es una versión
        antigua (no responde) o no está disponible."""
        with self._lock:
            try:
                s = self._ensure()
                s.sendall(b'{"t":"hello"}\n')
                s.settimeout(timeout)
                try:
                    data = s.recv(512)
                finally:
                    s.settimeout(2.0)
                if not data:
                    return set()
                return set(json.loads(data.split(b'\n', 1)[0]).get('feat', []))
            except (OSError, ValueError):
                return set()


# ── Demonio (corre como root) ─────────────────────────────────────────────────

def _build_uinput():
    from evdev import UInput, ecodes as e, AbsInfo
    cap = {
        # Botones de ratón + todo el teclado estándar: así el teclado del
        # profesor se inyecta por este mismo dispositivo, sin lanzar un proceso
        # ydotool por pulsación.
        e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE] +
                  list(range(_KEY_MIN, _KEY_MAX + 1)),
        e.EV_ABS: [
            (e.ABS_X, AbsInfo(value=0, min=0, max=ABS_MAX,
                              fuzz=0, flat=0, resolution=0)),
            (e.ABS_Y, AbsInfo(value=0, min=0, max=ABS_MAX,
                              fuzz=0, flat=0, resolution=0)),
        ],
        e.EV_REL: [e.REL_WHEEL, e.REL_HWHEEL],
    }
    return UInput(cap, name=_DEV_NAME, version=0x1)


class _Grabber:
    """Agarra (EVIOCGRAB) los dispositivos de entrada físicos del alumno."""

    def __init__(self):
        self._grabbed = []   # InputDevice agarrados
        self._lock = threading.Lock()

    def _is_physical_input(self, dev):
        from evdev import ecodes as e
        if dev.name == _DEV_NAME:
            return False     # nunca agarrar nuestro propio dispositivo virtual
        try:
            caps = dev.capabilities()
        except OSError:
            return False
        keys = set(caps.get(e.EV_KEY, []))
        # Teclado real: tiene teclas de escritura (no solo botones de encendido).
        is_keyboard = bool(keys & {e.KEY_A, e.KEY_SPACE, e.KEY_ENTER, e.KEY_ESC})
        # Ratón: botón izquierdo, o ejes relativos (REL_X/Y).
        rel = set(caps.get(e.EV_REL, []))
        is_mouse = (e.BTN_LEFT in keys) or (e.REL_X in rel) or (e.REL_Y in rel)
        # Touchpad / pantalla táctil.
        is_touch = (e.BTN_TOUCH in keys) or (e.BTN_TOOL_FINGER in keys)
        return is_keyboard or is_mouse or is_touch

    def grab(self):
        from evdev import InputDevice, list_devices
        with self._lock:
            if self._grabbed:
                return
            grabbed_names, failed = [], []
            for path in list_devices():
                try:
                    dev = InputDevice(path)
                except OSError:
                    continue
                if not self._is_physical_input(dev):
                    dev.close()
                    continue
                try:
                    dev.grab()
                    self._grabbed.append(dev)
                    grabbed_names.append('%s (%s)' % (dev.name, path))
                except OSError as ex:
                    failed.append('%s (%s): %s' % (dev.name, path, ex))
                    dev.close()
            sys.stderr.write('vigia_input: BLOQUEO — %d dispositivos agarrados: %s\n'
                             % (len(self._grabbed), '; '.join(grabbed_names) or 'NINGUNO'))
            if failed:
                sys.stderr.write('vigia_input: no se pudieron agarrar: %s\n'
                                 % '; '.join(failed))
            sys.stderr.flush()

    def ungrab(self):
        with self._lock:
            n = len(self._grabbed)
            for dev in self._grabbed:
                try:
                    dev.ungrab()
                except OSError:
                    pass
                try:
                    dev.close()
                except OSError:
                    pass
            self._grabbed = []
            if n:
                sys.stderr.write('vigia_input: DESBLOQUEO — %d dispositivos liberados\n' % n)
                sys.stderr.flush()


def _run_daemon():
    from evdev import ecodes as e
    try:
        ui = _build_uinput()
    except Exception as ex:
        sys.stderr.write('vigia_input: no se pudo crear uinput (%s). '
                         '¿/dev/uinput accesible? ¿corriendo como root?\n' % ex)
        sys.exit(1)

    grabber = _Grabber()
    ui_lock = threading.Lock()
    _BTN = {'left': e.BTN_LEFT, 'right': e.BTN_RIGHT, 'middle': e.BTN_MIDDLE}

    def handle(obj):
        t = obj.get('t')
        with ui_lock:
            if t == 'm':
                x = max(0, min(ABS_MAX, int(obj.get('x', 0))))
                y = max(0, min(ABS_MAX, int(obj.get('y', 0))))
                ui.write(e.EV_ABS, e.ABS_X, x)
                ui.write(e.EV_ABS, e.ABS_Y, y)
                ui.syn()
            elif t == 'b':
                code = _BTN.get(obj.get('btn', 'left'))
                if code is not None:
                    ui.write(e.EV_KEY, code, 1 if obj.get('s') else 0)
                    ui.syn()
            elif t == 'k':
                code = int(obj.get('code', 0))
                if _KEY_MIN <= code <= _KEY_MAX:
                    ui.write(e.EV_KEY, code, 1 if obj.get('s') else 0)
                    ui.syn()
            elif t == 's':
                dy = int(obj.get('dy', 0))
                dx = int(obj.get('dx', 0))
                if dy:
                    ui.write(e.EV_REL, e.REL_WHEEL, dy)
                if dx:
                    ui.write(e.EV_REL, e.REL_HWHEEL, dx)
                if dy or dx:
                    ui.syn()

    if os.path.exists(SOCK_PATH):
        try:
            os.remove(SOCK_PATH)
        except OSError:
            pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK_PATH)
    os.chmod(SOCK_PATH, 0o666)
    srv.listen(8)
    sys.stderr.write('vigia_input: demonio listo en %s (dispositivo %s)\n'
                     % (SOCK_PATH, _DEV_NAME))

    def serve(conn):
        holds_grab = False
        buf = b''
        try:
            conn.settimeout(None)
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if obj.get('t') == 'hello':
                        # Anuncio de capacidades: el cliente usa el teclado por
                        # uinput solo si el demonio (esta versión) lo soporta.
                        try:
                            conn.sendall(b'{"ok":1,"feat":["kb"]}\n')
                        except OSError:
                            break
                    elif obj.get('t') == 'grab':
                        try:
                            if obj.get('on'):
                                grabber.grab()
                                holds_grab = True
                            else:
                                grabber.ungrab()
                                holds_grab = False
                        except Exception as ex:
                            sys.stderr.write('vigia_input: error en grab: %s\n' % ex)
                            sys.stderr.flush()
                    else:
                        try:
                            handle(obj)
                        except Exception:
                            pass
        finally:
            # Seguridad: si quien bloqueó se desconecta, liberar el input.
            if holds_grab:
                grabber.ungrab()
            try:
                conn.close()
            except OSError:
                pass

    while True:
        try:
            conn, _ = srv.accept()
        except OSError:
            break
        threading.Thread(target=serve, args=(conn,), daemon=True).start()


if __name__ == '__main__':
    if '--daemon' in sys.argv:
        _run_daemon()
    else:
        sys.stderr.write('Uso: python3 vigia_input.py --daemon (correr como root)\n')
        sys.exit(2)
