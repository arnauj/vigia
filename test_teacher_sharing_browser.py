"""Regresión de compartir pantalla: Chrome, Flask y dos alumnos Socket.IO.

Ejecutar: python3 test_teacher_sharing_browser.py
Requiere dependencias del servidor, Pillow, playwright y Chrome/Chromium.
VIGIA_TEST_CHROME permite indicar el ejecutable. Todas las capturas son
sintéticas; no se transmite el escritorio real ni se usan clientes del aula.
"""

import logging
import os
import queue
import shutil
import socket
import threading
import time
from unittest.mock import patch

from PIL import Image
from playwright.sync_api import sync_playwright
import socketio

import server


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    capture_options = []
    captures = []

    class SyntheticCapture:
        name = 'spectacle'

        def __init__(self):
            self.closed = False
            captures.append(self)

        def grab(self):
            return Image.new('RGB', (640, 360), 'red')

        def close(self):
            self.closed = True

    def create_capture(**options):
        capture_options.append(options)
        assert options.get('allow_portal') is False, 'Se volvió a abrir el portal'
        return SyntheticCapture()

    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    students = []
    errors = []
    # El servicio puede arrancar antes del login y desconocer la sesión KDE.
    # La URL del lanzador debe bastar para evitar el selector nativo bloqueado.
    with patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': ''}), \
         patch.object(server.screen_capture, 'is_wayland', return_value=False), \
         patch.object(server.screen_capture, 'create_capturer', side_effect=create_capture):
        threading.Thread(target=lambda: server.socketio.run(
            server.app, host='127.0.0.1', port=port,
            allow_unsafe_werkzeug=True, use_reloader=False), daemon=True).start()
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        try:
            for name in ('Alumno elegido', 'Otro alumno'):
                peer = socketio.Client()
                frames = queue.Queue()
                peer.on('teacher_screen', frames.put)
                peer.connect(url, transports=['websocket'])
                peer.emit('register', {'name': name})
                students.append((peer, frames))

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path=os.environ.get('VIGIA_TEST_CHROME') or
                    shutil.which('google-chrome') or shutil.which('chromium'),
                    headless=True,
                    args=['--no-sandbox', '--autoplay-policy=no-user-gesture-required'])
                page = browser.new_page(ignore_https_errors=True)
                page.on('pageerror', lambda error: errors.append(str(error)))
                # Reproducir un selector nativo bloqueado: la promesa nunca
                # termina. El botón habitual debe compartir sin invocarlo.
                page.add_init_script('''
                    window.nativePickerCalls = 0;
                    navigator.mediaDevices.getDisplayMedia = () => {
                        window.nativePickerCalls++;
                        return new Promise(() => {});
                    };
                ''')
                page.goto(url, wait_until='networkidle')
                assert not page.evaluate('PREFER_SERVER_CAPTURE')
                page.goto(url + '/?capture=server', wait_until='networkidle')
                page.wait_for_function('Object.keys(students).length === 2 && socket.connected')
                assert page.evaluate('PREFER_SERVER_CAPTURE')
                page.click('#btn-compartir')
                page.wait_for_selector('#screen-list .screen-option')
                assert page.evaluate('nativePickerCalls') == 0
                assert all(frames.empty() for _, frames in students), 'Listar ya transmite'
                page.click('#screen-list .screen-option')
                for _, frames in students:
                    frame = frames.get(timeout=5)
                    assert frame['activa'] and frame['image'].startswith('data:image/jpeg;base64,')
                page.wait_for_selector('#share-preview.show')
                assert page.is_enabled('#btn-compartir')
                assert 'Dejar de compartir' in page.inner_text('#btn-compartir')
                page.click('#btn-compartir')
                for _, frames in students:
                    assert frames.get(timeout=5)['activa'] is False
                page.wait_for_function('!_sharing')

                # Envío únicamente a la selección del profesor.
                chosen = students[0][0].get_sid()
                page.evaluate('(sid) => { _selectedSids.clear(); _selectedSids.add(sid); compartirConSeleccionados(); }', chosen)
                page.click('#screen-list .screen-option')
                assert students[0][1].get(timeout=5)['activa']
                assert students[1][1].empty(), 'Se compartió con un alumno no seleccionado'
                page.click('#btn-compartir')
                for _, frames in students:
                    assert frames.get(timeout=5)['activa'] is False

                # Cancelar mientras llega la lista no debe reabrir el diálogo.
                page.evaluate('abrirScreenModal(); cerrarScreenModal();')
                page.wait_for_timeout(250)
                assert not page.is_visible('#screen-overlay')
                assert all(frames.empty() for _, frames in students)

                # La opción de pestaña/ventana sigue disponible; cancelar el
                # permiso no activa la captura del escritorio del servidor.
                page.evaluate('''() => {
                    navigator.mediaDevices.getDisplayMedia = async () => {
                        nativePickerCalls++;
                        throw new DOMException('Cancelado', 'NotAllowedError');
                    };
                }''')
                page.click('#btn-compartir')
                page.wait_for_selector('#screen-list .screen-option')
                before = len(capture_options)
                page.click('#screen-browser')
                page.wait_for_function('nativePickerCalls === 1 && !_sharePicking')
                assert not page.evaluate('_sharing')
                assert not page.is_visible('#screen-overlay')
                assert len(capture_options) == before

                # El camino del navegador sigue enviando frames cuando el
                # usuario sí obtiene una fuente (aquí un canvas sintético).
                page.evaluate('''() => {
                    navigator.mediaDevices.getDisplayMedia = async () => {
                        const canvas = document.createElement('canvas');
                        canvas.width = 640; canvas.height = 360;
                        const ctx = canvas.getContext('2d');
                        ctx.fillStyle = 'blue'; ctx.fillRect(0, 0, 640, 360);
                        return canvas.captureStream(10);
                    };
                }''')
                page.click('#btn-compartir')
                page.click('#screen-browser')
                for _, frames in students:
                    assert frames.get(timeout=5)['activa']
                page.wait_for_function('_shareRunning')
                page.click('#btn-compartir')
                for _, frames in students:
                    assert frames.get(timeout=5)['activa'] is False
                assert not errors, errors
                browser.close()
        finally:
            server._teacher_capture['running'] = False
            for peer, _ in students:
                if peer.connected:
                    peer.disconnect()
    assert captures and all(c.closed for c in captures)
    print('PASS: selector bloqueado evitado, recepción en alumnos, selección, '
          'parada, cancelación y captura del navegador; sin errores JavaScript.')


if __name__ == '__main__':
    main()
