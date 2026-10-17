"""
VIGIA — Monitores y ventanas según KWin (KDE Plasma, sobre todo en Wayland).

En Wayland una aplicación no puede listar las ventanas de las demás ni saber
dónde está cada una (xprop/xdotool solo ven las de XWayland), y la geometría
que dan kscreen-doctor/xrandr no siempre coincide con la que usa KWin (réplicas
en modo espejo, monitores girados, versiones nuevas de libkscreen…). KWin sí lo
sabe: se le carga un script por D-Bus (API de scripting de KWin) que devuelve
la geometría LÓGICA de cada monitor y de cada ventana, en el mismo sistema de
coordenadas con el que spectacle compone la captura de todo el escritorio. Con
eso el servidor recorta de esa captura un monitor o una ventana concretos sin
abrir el portal ScreenCast (el selector de Chrome).

El trabajo D-Bus va en un proceso auxiliar persistente (este archivo con
--servir: una consulta por línea de stdin, una línea JSON por respuesta) para no
mezclar el bucle GLib con el del servidor y porque la ventana compartida se
consulta en cada fotograma (arrancar Python + GLib cada vez costaba ~0,1 s de
CPU). Requiere python3-gi. Si no se puede (otro escritorio, sin python3-gi…)
las funciones devuelven None y el servidor sigue con kscreen-doctor/xrandr y
sin ventanas.

    consultar()   → {'screens': [...], 'windows': [...]} o None
    activar(id)   → trae al frente esa ventana (y la desminimiza)

Ejecutable en solitario para probar: `python3 kwin_info.py`.
"""

import itertools
import json
import os
import select
import subprocess
import sys
import tempfile
import threading
import time

_RUTA = '/org/vigia/KWinInfo'
_IFACE = 'org.vigia.KWinInfo'
_INTROSPECCION = f'''<node>
  <interface name="{_IFACE}">
    <method name="Datos"><arg type="s" name="json" direction="in"/></method>
  </interface>
</node>'''

# Script de KWin. Vale para Plasma 6 (windowList, screens, activeWindow) y
# Plasma 5 (clientList, numScreens, activeClient). Las ventanas van de la más
# alta a la más baja del apilamiento.
_SCRIPT = r'''
(function () {
    var DEST = %(dest)s, RUTA = %(ruta)s, IFACE = %(iface)s, ACTIVAR = %(activar)s;
    function rect(g) {
        return {x: Math.round(g.x), y: Math.round(g.y),
                w: Math.round(g.width), h: Math.round(g.height)};
    }
    function enEscritorioActual(w) {
        if (w.onAllDesktops) return true;
        var cur = workspace.currentDesktop;
        if (w.desktops !== undefined && cur && cur.id !== undefined) {
            for (var i = 0; i < w.desktops.length; i++)
                if (w.desktops[i].id === cur.id) return true;
            return false;
        }
        if (typeof w.desktop === 'number') return w.desktop === cur || w.desktop === -1;
        return true;
    }
    var lista = workspace.stackingOrder ||
        (workspace.windowList ? workspace.windowList() : workspace.clientList());
    var res = {screens: [], windows: [], activada: false};
    if (workspace.screens !== undefined) {
        for (var s = 0; s < workspace.screens.length; s++) {
            var o = workspace.screens[s], r = rect(o.geometry);
            r.name = o.name || ''; r.scale = o.devicePixelRatio || 1;
            res.screens.push(r);
        }
    } else if (workspace.numScreens !== undefined) {
        for (var n = 0; n < workspace.numScreens; n++) {
            var r5 = rect(workspace.clientArea(KWin.ScreenArea, n, workspace.currentDesktop));
            r5.name = ''; r5.scale = 1;
            res.screens.push(r5);
        }
    }
    for (var i = lista.length - 1; i >= 0; i--) {
        var w = lista[i];
        if (!w || !w.normalWindow || w.deleted) continue;
        var id = String(w.internalId);
        if (ACTIVAR && id === ACTIVAR) {
            if (w.minimized) w.minimized = false;
            if (workspace.activeWindow !== undefined) workspace.activeWindow = w;
            else workspace.activeClient = w;
            res.activada = true;
        }
        var g = rect(w.frameGeometry || w.geometry);
        res.windows.push({id: id, title: String(w.caption || ''),
            cls: String(w.resourceClass || ''), res: String(w.resourceName || ''),
            app: String(w.desktopFileName || ''), x: g.x, y: g.y, w: g.w, h: g.h,
            min: !!w.minimized, vis: !w.minimized && enEscritorioActual(w),
            skip: !!w.skipTaskbar});
    }
    callDBus(DEST, RUTA, IFACE, 'Datos', JSON.stringify(res));
})();
'''

_cache = None
_cache_ts = 0.0
_avisado = set()
_N_SCRIPT = itertools.count()


def _aviso(msg):
    if msg not in _avisado:
        _avisado.add(msg)
        print(f'[!] KWin: {msg}')


def _es_kde():
    escritorio = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
    # Sin la variable (servicio arrancado fuera de la sesión) se intenta igual.
    return not escritorio or 'kde' in escritorio or 'plasma' in escritorio


class _Ayudante:
    """Proceso auxiliar persistente (`kwin_info.py --servir`)."""

    def __init__(self):
        self._proc = None
        self._lock = threading.RLock()

    def parar(self):
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=2)
                except Exception:
                    pass
            self._proc = None

    def pedir(self, orden, timeout):
        """Envía una orden y devuelve la línea de respuesta ('' si no hay)."""
        with self._lock:
            for _ in range(2):          # un reintento si el auxiliar había muerto
                if self._proc is None or self._proc.poll() is not None:
                    self._proc = subprocess.Popen(
                        [sys.executable, os.path.abspath(__file__), '--servir'],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, text=True, errors='replace', bufsize=1)
                try:
                    self._proc.stdin.write(orden + '\n')
                    self._proc.stdin.flush()
                    listo = select.select([self._proc.stdout], [], [], timeout)[0]
                    if not listo:           # KWin colgado: no insistir
                        self.parar()
                        return ''
                    linea = self._proc.stdout.readline()
                except (OSError, ValueError):
                    linea = ''
                if linea:
                    return linea
                self.parar()
            return ''


_ayudante = _Ayudante()


def _ejecutar(orden, timeout):
    if not sys.platform.startswith('linux') or not _es_kde():
        return None
    try:
        linea = _ayudante.pedir(orden, timeout)
        datos = json.loads(linea or '{}')
    except (OSError, ValueError) as e:
        datos = {'error': f'sin respuesta ({e})'}
    if not isinstance(datos, dict) or 'screens' not in datos:
        error = datos.get('error') if isinstance(datos, dict) else None
        _aviso(error or 'sin respuesta')
        # El próximo intento, con un auxiliar nuevo que herede el entorno de
        # sesión actual (el lanzador puede haberlo corregido mientras tanto).
        _ayudante.parar()
        return None
    return datos


def consultar(max_age=0.0, timeout=6.0):
    """Monitores y ventanas según KWin, o None si no se puede preguntar.

    max_age reutiliza la última respuesta si es más reciente (el selector pide
    ventanas y monitores casi a la vez)."""
    global _cache, _cache_ts
    if max_age > 0 and _cache is not None and time.monotonic() - _cache_ts <= max_age:
        return _cache
    datos = _ejecutar('consultar', timeout)
    if datos is not None:
        _cache, _cache_ts = datos, time.monotonic()
    return datos


def activar(wid, timeout=6.0):
    """Trae al frente la ventana (la desminimiza y cambia de escritorio si
    hace falta). Devuelve True si KWin la encontró."""
    wid = str(wid)
    if not wid or any(c.isspace() for c in wid):
        return False
    datos = _ejecutar(f'activar {wid}', timeout)
    return bool(datos and datos.get('activada'))


def monitores(datos):
    """Monitores en el formato de screen_capture (izquierda → derecha)."""
    mons, vistos = [], set()
    for s in (datos or {}).get('screens', []):
        try:
            caja = (int(s['x']), int(s['y']), int(s['w']), int(s['h']))
        except (KeyError, TypeError, ValueError):
            continue
        if caja[2] < 1 or caja[3] < 1 or caja in vistos:
            continue
        vistos.add(caja)
        mons.append({'left': caja[0], 'top': caja[1], 'width': caja[2], 'height': caja[3],
                     'name': str(s.get('name') or ''), 'primary': False})
    return sorted(mons, key=lambda m: (m['left'], m['top']))


def ventanas(datos, todas=False):
    """Ventanas normales (de la más alta a la más baja) con su zona lógica.
    Sin `todas`, solo las de la barra de tareas (las que se pueden elegir)."""
    res = []
    for w in (datos or {}).get('windows', []):
        try:
            zona = {'left': int(w['x']), 'top': int(w['y']),
                    'width': int(w['w']), 'height': int(w['h'])}
        except (KeyError, TypeError, ValueError):
            continue
        if not w.get('id') or zona['width'] < 1 or zona['height'] < 1:
            continue
        if w.get('skip') and not todas:
            continue
        res.append({'wid': str(w['id']), 'title': str(w.get('title') or w.get('cls') or ''),
                    'classes': [c for c in (w.get('app'), w.get('cls'), w.get('res')) if c],
                    'minimized': bool(w.get('min')), 'visible': bool(w.get('vis', True)),
                    **zona})
    return res


def ventana(datos, wid):
    """La ventana `wid` de una consulta, o None si ya no existe."""
    return next((w for w in ventanas(datos, todas=True) if w['wid'] == str(wid)), None)


def tapada(datos, wid):
    """True si otra ventana visible, MÁS ARRIBA en el apilamiento, se solapa
    con `wid`: al recortarla de la captura del escritorio se vería la de encima
    (p. ej. el panel del profesor con las pantallas de los alumnos)."""
    objetivo = ventana(datos, wid)
    if objetivo is None:
        return False
    for w in ventanas(datos, todas=True):
        if w['wid'] == objetivo['wid']:
            return False
        if not w['visible']:
            continue
        ancho = (min(w['left'] + w['width'], objetivo['left'] + objetivo['width'])
                 - max(w['left'], objetivo['left']))
        alto = (min(w['top'] + w['height'], objetivo['top'] + objetivo['height'])
                - max(w['top'], objetivo['top']))
        # Tolerar roces de borde o sombra (< 0,5 % de la ventana).
        if ancho > 0 and alto > 0 and ancho * alto > 0.005 * objetivo['width'] * objetivo['height']:
            return True
    return False


# ── Proceso auxiliar: habla con KWin por D-Bus ───────────────────────────────

def _llamar_kwin(bus, ruta, iface, metodo, args=None, firma=None):
    from gi.repository import Gio
    return bus.call_sync('org.kde.KWin', ruta, iface, metodo, args, firma,
                         Gio.DBusCallFlags.NONE, 4000, None)


def _consultar_kwin(activar_id=None, timeout=4.0):
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    loop = GLib.MainLoop()
    recibido = []

    def llamada(_conn, _remitente, _ruta, _iface, metodo, params, invocacion):
        if metodo == 'Datos' and not recibido:
            recibido.append(params.unpack()[0])
            loop.quit()
        invocacion.return_value(None)

    nodo = Gio.DBusNodeInfo.new_for_xml(_INTROSPECCION)
    registro = bus.register_object(_RUTA, nodo.interfaces[0], llamada, None, None)
    # Nombre nuevo por consulta: KWin rechaza cargar otro con el mismo nombre
    # si una descarga anterior hubiera fallado.
    plugin = f'vigia-info-{os.getpid()}-{next(_N_SCRIPT)}'
    fd, archivo = tempfile.mkstemp(prefix='vigia-kwin-', suffix='.js')
    cargado = False
    espera = None
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(_SCRIPT % {'dest': json.dumps(bus.get_unique_name()),
                               'ruta': json.dumps(_RUTA), 'iface': json.dumps(_IFACE),
                               'activar': json.dumps(activar_id or '')})
        scripting = ('/Scripting', 'org.kde.kwin.Scripting')
        id_script = _llamar_kwin(bus, *scripting, 'loadScript',
                                 GLib.Variant('(ss)', (archivo, plugin)),
                                 GLib.VariantType('(i)')).unpack()[0]
        cargado = True
        if id_script < 0:
            raise RuntimeError('KWin no pudo cargar el script')
        # Plasma 6: /Scripting/ScriptN — Plasma 5: /N
        for ruta in (f'/Scripting/Script{id_script}', f'/{id_script}'):
            try:
                _llamar_kwin(bus, ruta, 'org.kde.kwin.Script', 'run')
                break
            except GLib.Error:
                continue
        else:
            _llamar_kwin(bus, *scripting, 'start')
        if not recibido:
            espera = GLib.timeout_add(int(timeout * 1000), loop.quit)
            loop.run()
    finally:
        if espera is not None and recibido:
            GLib.source_remove(espera)      # sin respuesta ya disparó y se quitó sola
        if cargado:
            try:
                _llamar_kwin(bus, '/Scripting', 'org.kde.kwin.Scripting', 'unloadScript',
                             GLib.Variant('(s)', (plugin,)))
            except GLib.Error:
                pass
        bus.unregister_object(registro)
        try:
            os.remove(archivo)
        except OSError:
            pass
    if not recibido:
        raise TimeoutError('KWin no respondió al script')
    return json.loads(recibido[0])


def _responder(activar_id):
    try:
        return _consultar_kwin(activar_id)
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}


def _servir():
    """Una orden por línea («consultar» o «activar ID»), una línea JSON por
    respuesta. Termina cuando el servidor cierra stdin (o muere)."""
    for linea in sys.stdin:
        partes = linea.split()
        activar_id = partes[1] if len(partes) == 2 and partes[0] == 'activar' else None
        sys.stdout.write(json.dumps(_responder(activar_id)) + '\n')
        sys.stdout.flush()
    return 0


def _main(argv):
    if argv[:1] == ['--servir']:
        return _servir()
    activar_id = argv[1] if len(argv) >= 2 and argv[0] == '--activar' else None
    datos = _responder(activar_id)
    print(json.dumps(datos))
    if 'error' in datos:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
