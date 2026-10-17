"""Monitores y ventanas según KWin (kwin_info), sin escritorio real.

python3 test_kwin_info.py
La prueba de integración levanta un KWin simulado en un bus D-Bus privado
(dbus-run-session) y requiere python3-gi; si falta, se omite.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

import kwin_info

DATOS = {
    'screens': [{'x': 1920, 'y': 0, 'w': 1280, 'h': 1024, 'name': 'HDMI-A-1', 'scale': 1},
                {'x': 0, 'y': 0, 'w': 1920, 'h': 1080, 'name': 'DP-1', 'scale': 1.25},
                {'x': 0, 'y': 0, 'w': 1920, 'h': 1080, 'name': 'DP-2', 'scale': 1},
                {'x': 0, 'y': 0, 'w': 0, 'h': 0, 'name': 'roto'}],
    'windows': [
        {'id': '{a}', 'title': 'Documento - Writer', 'cls': 'libreoffice', 'res': 'soffice',
         'app': 'libreoffice-writer', 'x': 100, 'y': 50, 'w': 800, 'h': 600, 'min': False, 'vis': True},
        {'id': '{b}', 'title': '', 'cls': 'kate', 'res': '', 'app': '',
         'x': 0, 'y': 0, 'w': 300, 'h': 200, 'min': True, 'vis': False},
        {'id': '', 'title': 'sin id', 'x': 0, 'y': 0, 'w': 10, 'h': 10},
        {'id': '{c}', 'title': 'mala', 'x': 'x', 'y': 0, 'w': 10, 'h': 10},
    ],
}


class TestNormalizacion(unittest.TestCase):
    def test_monitors_sorted_without_duplicates_or_empty_outputs(self):
        mons = kwin_info.monitores(DATOS)
        self.assertEqual([(m['name'], m['left'], m['width']) for m in mons],
                         [('DP-1', 0, 1920), ('HDMI-A-1', 1920, 1280)])
        self.assertEqual(kwin_info.monitores(None), [])

    def test_windows_keep_stacking_order_and_identifiers(self):
        wins = kwin_info.ventanas(DATOS)
        self.assertEqual([w['wid'] for w in wins], ['{a}', '{b}'])
        a, b = wins
        self.assertEqual((a['left'], a['top'], a['width'], a['height']), (100, 50, 800, 600))
        self.assertEqual(a['classes'], ['libreoffice-writer', 'libreoffice', 'soffice'])
        self.assertEqual((b['title'], b['minimized'], b['visible']), ('kate', True, False))
        self.assertEqual(kwin_info.ventana(DATOS, '{b}')['wid'], '{b}')
        self.assertIsNone(kwin_info.ventana(DATOS, '{zzz}'))

    def test_windows_hidden_from_taskbar_only_count_for_overlap(self):
        datos = {'screens': [], 'windows': [
            {'id': '{osd}', 'title': 'Superpuesta', 'x': 0, 'y': 0, 'w': 400, 'h': 400,
             'vis': True, 'skip': True},
            {'id': '{doc}', 'title': 'Doc', 'x': 200, 'y': 200, 'w': 800, 'h': 600, 'vis': True},
        ]}
        self.assertEqual([w['wid'] for w in kwin_info.ventanas(datos)], ['{doc}'])
        self.assertEqual(len(kwin_info.ventanas(datos, todas=True)), 2)
        self.assertTrue(kwin_info.tapada(datos, '{doc}'))
        self.assertFalse(kwin_info.tapada(datos, '{osd}'))       # la de arriba no está tapada

    def test_overlap_rules(self):
        def con(encima):
            return {'screens': [], 'windows': [
                dict({'id': '{x}', 'title': 'Encima', 'vis': True}, **encima),
                {'id': '{doc}', 'title': 'Doc', 'x': 0, 'y': 0, 'w': 1000, 'h': 1000, 'vis': True}]}
        self.assertFalse(kwin_info.tapada(con({'x': 1000, 'y': 0, 'w': 500, 'h': 500}), '{doc}'))
        self.assertFalse(kwin_info.tapada(con({'x': 995, 'y': 0, 'w': 500, 'h': 500}), '{doc}'))
        self.assertTrue(kwin_info.tapada(con({'x': 900, 'y': 0, 'w': 500, 'h': 500}), '{doc}'))
        self.assertFalse(kwin_info.tapada(con({'x': 0, 'y': 0, 'w': 500, 'h': 500, 'vis': False}),
                                          '{doc}'))
        self.assertFalse(kwin_info.tapada(con({'x': 0, 'y': 0, 'w': 500, 'h': 500}), '{zzz}'))


class TestProcesoAuxiliar(unittest.TestCase):
    def setUp(self):
        kwin_info._cache = None
        kwin_info._avisado.clear()
        env = patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'KDE'})
        env.start()
        self.addCleanup(env.stop)

    def test_query_uses_helper_and_caches(self):
        with patch.object(kwin_info._ayudante, 'pedir', return_value=json.dumps(DATOS) + '\n') as pedir:
            self.assertEqual(kwin_info.consultar(), DATOS)
            self.assertEqual(kwin_info.consultar(max_age=5), DATOS)
        pedir.assert_called_once_with('consultar', 6.0)

    def test_errors_return_none(self):
        for linea in (json.dumps({'error': 'ServiceUnknown'}), '[1]', 'no es json', ''):
            with self.subTest(linea=linea), \
                 patch.object(kwin_info._ayudante, 'pedir', return_value=linea):
                self.assertIsNone(kwin_info.consultar())

    def test_other_desktops_are_not_asked(self):
        with patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'GNOME'}), \
             patch.object(kwin_info._ayudante, 'pedir') as pedir:
            self.assertIsNone(kwin_info.consultar())
            self.assertFalse(kwin_info.activar('{a}'))
        pedir.assert_not_called()

    def test_activate_passes_window_id(self):
        with patch.object(kwin_info._ayudante, 'pedir',
                          return_value=json.dumps(dict(DATOS, activada=True))) as pedir:
            self.assertTrue(kwin_info.activar('{a}'))
            self.assertFalse(kwin_info.activar('{a} consultar'))   # sin inyectar órdenes
        pedir.assert_called_once_with('activar {a}', 6.0)

    def test_persistent_helper_is_restarted_if_it_dies(self):
        # Auxiliar falso: contesta UNA orden y muere; el siguiente pedir() lo
        # vuelve a arrancar sin perder la respuesta.
        with tempfile.TemporaryDirectory() as tmp:
            falso = os.path.join(tmp, 'falso.py')
            with open(falso, 'w') as f:
                f.write('import sys\nlinea = sys.stdin.readline()\n'
                        'print("{\\"screens\\": [], \\"orden\\": \\"%s\\"}" % linea.strip(), flush=True)\n')
            ayudante = kwin_info._Ayudante()
            with patch.object(kwin_info, '__file__', falso):
                primera = json.loads(ayudante.pedir('consultar', 10))
                pid = ayudante._proc.pid
                ayudante._proc.wait(timeout=10)
                segunda = json.loads(ayudante.pedir('activar {a}', 10))
            self.assertEqual((primera['orden'], segunda['orden']), ('consultar', 'activar {a}'))
            self.assertNotEqual(ayudante._proc.pid, pid)
            ayudante.parar()

    def test_hung_helper_is_killed(self):
        with tempfile.TemporaryDirectory() as tmp:
            falso = os.path.join(tmp, 'colgado.py')
            with open(falso, 'w') as f:
                f.write('import time\ntime.sleep(60)\n')
            ayudante = kwin_info._Ayudante()
            with patch.object(kwin_info, '__file__', falso):
                self.assertEqual(ayudante.pedir('consultar', 0.5), '')
            self.assertIsNone(ayudante._proc)


# KWin simulado: implementa loadScript/run/unloadScript y, al ejecutar el
# script, devuelve unos datos por D-Bus igual que haría callDBus().
_FAKE_KWIN = textwrap.dedent('''
    import json, re, sys
    from gi.repository import Gio, GLib
    XML = """<node>
    <interface name="org.kde.kwin.Scripting">
      <method name="loadScript"><arg type="s" direction="in"/><arg type="s" direction="in"/>
        <arg type="i" direction="out"/></method>
      <method name="unloadScript"><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
      <method name="start"/>
    </interface>
    <interface name="org.kde.kwin.Script"><method name="run"/><method name="stop"/></interface>
    </node>"""
    nodo = Gio.DBusNodeInfo.new_for_xml(XML)
    scripts, log = {}, open(sys.argv[1], 'a')

    def responder(bus, archivo):
        texto = open(archivo).read()
        dest, ruta, iface, activar = [json.loads(m) for m in re.search(
            r'var DEST = (".*?"), RUTA = (".*?"), IFACE = (".*?"), ACTIVAR = (".*?");', texto).groups()]
        datos = json.loads(sys.argv[2])
        datos['activada'] = activar == '{a}'
        bus.call(dest, ruta, iface, 'Datos', GLib.Variant('(s)', (json.dumps(datos),)),
                 None, Gio.DBusCallFlags.NONE, 2000, None, None, None)

    def llamada(bus, remitente, ruta, iface, metodo, params, inv):
        args = params.unpack()
        if metodo == 'loadScript':
            n = len(scripts) + 1
            scripts[n] = args[0]
            bus.register_object(f'/Scripting/Script{n}', nodo.interfaces[1], llamada, None, None)
            inv.return_value(GLib.Variant('(i)', (n,)))
        elif metodo == 'unloadScript':
            log.write('unload ' + args[0] + '\\n'); log.flush()
            inv.return_value(GLib.Variant('(b)', (True,)))
        elif metodo == 'run':
            inv.return_value(None)
            n = int(ruta.rsplit('Script', 1)[1])
            GLib.idle_add(lambda: responder(bus, scripts[n]) and False)
        else:
            inv.return_value(None)

    def adquirido(bus, nombre):
        bus.register_object('/Scripting', nodo.interfaces[0], llamada, None, None)
        print('LISTO', flush=True)

    Gio.bus_own_name(Gio.BusType.SESSION, 'org.kde.KWin', Gio.BusNameOwnerFlags.NONE,
                     adquirido, None, None)
    GLib.MainLoop().run()
''')

_CLIENTE = textwrap.dedent('''
    import subprocess, sys, time
    fake, log, datos = sys.argv[1:4]
    p = subprocess.Popen([sys.executable, fake, log, datos], stdout=subprocess.PIPE, text=True)
    p.stdout.readline()
    import kwin_info
    import json
    print(json.dumps({'datos': kwin_info.consultar(), 'activada': kwin_info.activar('{a}'),
                      'otra': kwin_info.activar('{zzz}')}))
    p.terminate()
''')


def _hay_gi():
    try:
        import gi  # noqa: F401
        from gi.repository import Gio  # noqa: F401
        return True
    except Exception:
        return False


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('dbus-run-session')
                     and _hay_gi(), 'requiere Linux, dbus-run-session y python3-gi')
class TestIntegracionDBus(unittest.TestCase):
    def test_round_trip_with_simulated_kwin(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, 'fake_kwin.py')
            cliente = os.path.join(tmp, 'cliente.py')
            log = os.path.join(tmp, 'kwin.log')
            with open(fake, 'w') as f:
                f.write(_FAKE_KWIN)
            with open(cliente, 'w') as f:
                f.write(_CLIENTE)
            env = dict(os.environ, XDG_CURRENT_DESKTOP='KDE',
                       PYTHONPATH=os.path.dirname(os.path.abspath(kwin_info.__file__)))
            r = subprocess.run(['dbus-run-session', '--', sys.executable, cliente, fake, log,
                                json.dumps(DATOS)], capture_output=True, text=True,
                               timeout=60, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            res = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertEqual(kwin_info.monitores(res['datos']), kwin_info.monitores(DATOS))
            self.assertEqual([w['wid'] for w in kwin_info.ventanas(res['datos'])], ['{a}', '{b}'])
            self.assertTrue(res['activada'])
            self.assertFalse(res['otra'])
            # Cada consulta descarga su script (con nombre propio): no se
            # acumulan en KWin. Las tres van por el mismo proceso auxiliar.
            with open(log) as f:
                descargas = [l.split()[1] for l in f if l.startswith('unload ')]
            self.assertEqual(len(descargas), 3)
            self.assertEqual(len(set(descargas)), 3)
            self.assertEqual(len({d.rsplit('-', 1)[0] for d in descargas}), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
