"""Panel del profesor en Chrome: tema claro/oscuro guardado, atajos y menú.

Ejecutar: python3 test_panel_browser.py
Requiere dependencias del servidor, playwright y Chrome/Chromium.
VIGIA_TEST_CHROME permite indicar el ejecutable. Los alumnos son clientes
Socket.IO sintéticos y las preferencias van a una carpeta temporal: no se
toca ~/.config/vigia ni ningún equipo del aula.
"""

import logging
import os
import queue
import shutil
import socket
import tempfile
import threading
import time
import urllib.request
from unittest.mock import patch

from playwright.sync_api import sync_playwright
import socketio

import server


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    tmp = tempfile.mkdtemp()
    peers, errors = [], []
    with patch.object(server, '_PANEL_SETTINGS_FILE', os.path.join(tmp, 'panel.json')), \
         patch.object(server, '_STUDENT_ORDER_FILE', os.path.join(tmp, 'orden.json')), \
         patch.object(server, '_STUDENT_ALIASES_FILE', os.path.join(tmp, 'nombres.json')), \
         patch.object(server, '_panel_settings', dict(server._PANEL_SETTINGS_DEFAULT)), \
         patch.object(server, '_student_order', []), \
         patch.object(server, '_student_groups', server._empty_student_groups()):
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
            locks = queue.Queue()
            for name in ('ana - pc01', 'bea - pc02'):
                peer = socketio.Client()
                peer.on('lock_screen', lambda *_: locks.put('lock'))
                peer.connect(url, transports=['websocket'])
                peer.emit('register', {'name': name})
                peers.append(peer)

            # Primera visita: tema oscuro por defecto, ya pintado por el servidor.
            assert 'data-theme="dark"' in urllib.request.urlopen(url).read().decode()

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path=os.environ.get('VIGIA_TEST_CHROME') or
                    shutil.which('google-chrome') or shutil.which('chromium'),
                    headless=True, args=['--no-sandbox'])
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                other = browser.new_page(viewport={'width': 1440, 'height': 900})
                for pg in (page, other):
                    pg.on('pageerror', lambda error: errors.append(str(error)))
                    pg.goto(url, wait_until='networkidle')
                    pg.wait_for_function('Object.keys(students).length === 2 && socket.connected')
                assert page.evaluate('document.documentElement.dataset.theme') == 'dark'
                assert page.get_attribute('#sidebar [data-theme-choice="dark"]', 'aria-pressed') == 'true'

                # Tema claro desde la barra lateral: se aplica, llega al otro
                # panel abierto y se guarda en el servidor.
                page.click('#sidebar [data-theme-choice="light"]')
                assert page.evaluate('document.documentElement.dataset.theme') == 'light'
                assert page.evaluate('document.documentElement.dataset.bsTheme') == 'light'
                other.wait_for_function('document.documentElement.dataset.theme === "light"')
                page.click('[data-density="l"]')
                other.wait_for_function(
                    'document.getElementById("grid").style.getPropertyValue("--card-w") === "400px"')
                assert server._load_panel_settings() == {'theme': 'light', 'density': 'l'}
                # Al volver a abrir el panel sale ya en claro (sin parpadeo).
                assert 'data-theme="light"' in urllib.request.urlopen(url).read().decode()
                page.reload(wait_until='networkidle')
                page.wait_for_function('Object.keys(students).length === 2')
                assert page.evaluate('document.documentElement.dataset.theme') == 'light'
                assert page.get_attribute('[data-density="l"]', 'aria-pressed') == 'true'
                # Configuración ofrece el mismo selector y vuelve a oscuro.
                page.evaluate('abrirSettings()')
                page.click('#settings-box [data-theme-choice="dark"]')
                page.evaluate('cerrarSettings()')
                assert page.evaluate('document.documentElement.dataset.theme') == 'dark'
                other.wait_for_function('document.documentElement.dataset.theme === "dark"')

                # Atajos: M abre el mensaje; escribir dentro no dispara otros.
                page.keyboard.press('m')
                assert page.is_visible('#compose-overlay')
                page.keyboard.type('vtm')
                assert not page.is_visible('#terminal-overlay')
                page.keyboard.press('Escape')
                assert not page.is_visible('#compose-overlay')
                # En el buscador las letras son texto, no atajos.
                page.keyboard.press('Control+k')
                assert page.evaluate('document.activeElement.id') == 'search-input'
                page.keyboard.type('tm')
                assert not page.is_visible('#terminal-overlay')
                assert not page.is_visible('#compose-overlay')
                page.fill('#search-input', '')
                page.keyboard.press('Escape')
                # V entra en selección; cerrar un modal con Esc NO la cancela.
                page.keyboard.press('v')
                assert page.evaluate('_selectionMode')
                page.keyboard.press('t')
                assert page.is_visible('#terminal-overlay')
                page.keyboard.press('Escape')
                assert not page.is_visible('#terminal-overlay')
                assert page.evaluate('_selectionMode')
                page.keyboard.press('Escape')
                assert not page.evaluate('_selectionMode')

                # Menú «más» de una tarjeta: mensaje a ese alumno y renombrar.
                first = page.locator('#grid .student-card').first
                name = first.locator('.card-name').inner_text()
                first.locator('.more-btn').click()
                assert page.is_visible('#card-menu')
                page.click('#card-menu [data-accion="mensaje"]')
                assert not page.is_visible('#card-menu')
                assert page.inner_text('#compose-para') == name
                page.evaluate('cerrarCompose()')
                first.locator('.more-btn').click()
                page.keyboard.press('Escape')
                assert not page.is_visible('#card-menu')
                first.locator('.more-btn').click()
                page.click('#card-menu [data-accion="renombrar"]')
                assert first.locator('.card-name-input').count() == 1
                page.keyboard.press('Escape')
                assert first.locator('.card-name-input').count() == 0

                # Grupos de nombres: un grupo nuevo empieza con los nombres del
                # equipo; volver al anterior recupera los suyos.
                assert page.evaluate('[...document.querySelectorAll("#group-select option")].map(o => o.value)') == ['General']
                page.evaluate('_renombrar("ana - pc01", "Ana")')
                page.wait_for_function('students[Object.keys(students).find(k => students[k].key === "ana - pc01")].name === "Ana"')
                page.once('dialog', lambda dialog: dialog.accept('1º ESO A'))
                page.evaluate('abrirSettings()')
                page.click('#settings-box button:has-text("Nuevo grupo")')
                page.wait_for_function('_studentGroups.current === "1º ESO A"')
                other.wait_for_function('document.getElementById("group-select").value === "1º ESO A"')
                page.wait_for_function('document.querySelector("#cfg-names-list .name-input").value === ""')
                assert 'ana - pc01' in page.inner_text('#grid')
                page.evaluate('cerrarSettings()')
                page.select_option('#group-select', 'General')
                page.wait_for_function('[...document.querySelectorAll("#grid .card-name")].some(e => e.textContent === "Ana")')
                assert server._load_student_groups()['actual'] == 'General'

                # Bloquear desde la tarjeta: llega al alumno y cuenta en la cabecera.
                first.locator('.lock-btn').click()
                assert locks.get(timeout=5) == 'lock'
                assert page.inner_text('#stat-locked') == '1 bloqueado'
                assert 'locked' in first.get_attribute('class')
                first.locator('.lock-btn').click()
                assert page.inner_text('#stat-locked') == '0 bloqueados'
                assert page.inner_text('#stat-online') == '2 conectados'

                # «Solo ver»: sin los botones de pizarra/portapapeles (antes
                # .d-flex de Bootstrap impedía ocultarlos y no hacían nada).
                page.evaluate('(sid) => abrirLiveView(sid, "view")', peers[0].get_sid())
                assert page.is_visible('#liveview-overlay')
                for boton in ('#lv-overlay-toggle', '#lv-draw-toggle', '#lv-clipboard-btn'):
                    assert not page.is_visible(boton), boton
                page.evaluate('cerrarLiveView()')

                assert not errors, errors
                browser.close()
        finally:
            for peer in peers:
                if peer.connected:
                    peer.disconnect()
    print('PASS: tema claro/oscuro guardado y sincronizado, densidad, grupos de nombres, atajos, menú de tarjeta y bloqueo; sin errores JavaScript.')


if __name__ == '__main__':
    main()
