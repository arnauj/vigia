"""Actualización con un servidor anterior vivo y detección de versiones por HTTP."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import unittest

import server_runtime as runtime
from vigia_version import VERSION


class TestVersionCheck(unittest.TestCase):
    def setUp(self):
        self.status = 200
        self.payload = {'app': 'vigia-server', 'version': VERSION}
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                case.assertEqual(self.path, '/api/version')
                self.send_response(case.status)
                self.end_headers()
                self.wfile.write(json.dumps(case.payload).encode())

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_only_running_current_vigia_version_is_accepted(self):
        self.assertTrue(runtime.wait_for_current_server(self.port, timeout=0))
        self.payload['version'] = '1.2'
        self.assertFalse(runtime.wait_for_current_server(self.port, timeout=0))
        self.payload = {'app': 'another-application', 'version': VERSION}
        self.assertFalse(runtime.wait_for_current_server(self.port, timeout=0))

    def test_legacy_server_without_endpoint_is_not_reused(self):
        self.status = 404
        self.assertFalse(runtime.wait_for_current_server(self.port, timeout=0))


@unittest.skipUnless(sys.platform.startswith('linux'), 'Identificación de procesos Linux')
class TestProcessIdentity(unittest.TestCase):
    def test_only_python_executing_exact_installed_script_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install = root / 'install'
            install.mkdir()
            procs = root / 'proc'
            procs.mkdir()
            cases = [
                (['python3', str(install / 'server.py'), '5000'], True),
                (['python3', '-u', 'server.py', '5000'], True),
                (['python3', '/another-install/server.py', '5000'], False),
                (['python3', '-c', str(install / 'server.py')], False),
                (['python3', 'editor.py', str(install / 'server.py')], False),
                (['bash', '-c', 'python3 ' + str(install / 'server.py')], False),
                (['python3', str(install / 'server.py.backup')], False),
            ]
            expected = []
            for pid, (args, matches) in enumerate(cases, 990001):
                proc = procs / str(pid)
                proc.mkdir()
                (proc / 'cwd').symlink_to(install)
                (proc / 'cmdline').write_bytes(b'\0'.join(os.fsencode(arg) for arg in args))
                if matches:
                    expected.append(pid)
            self.assertEqual(sorted(runtime.installed_server_processes(install, procs)), expected)

    def test_update_stops_unmanaged_server_but_preserves_other_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = 'import time\nprint("ready", flush=True)\ntime.sleep(60)\n'
            processes = []
            try:
                for name in ('server.py', 'other.py'):
                    (root / name).write_text(script)
                    process = subprocess.Popen([sys.executable, str(root / name)],
                                               stdout=subprocess.PIPE, text=True)
                    processes.append(process)
                    self.assertEqual(process.stdout.readline().strip(), 'ready')
                self.assertEqual(runtime.stop_installed_servers(root), 1)
                self.assertEqual(processes[0].wait(timeout=3), -signal.SIGTERM)
                self.assertIsNone(processes[1].poll())
                self.assertEqual(runtime.stop_installed_servers(root), 0)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=3)
                    process.stdout.close()


if __name__ == '__main__':
    unittest.main()
