"""Real local child fixtures: never inspect or stop existing user services."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import rebuild
from _process import (OwnedProcess, child_env, parse_argv, read_record,
                      require_process_support, validate_argv, write_record)

PYTHON = str(Path(getattr(sys, '_base_executable', sys.executable)).resolve())
FIXTURE = '''import json,os,sys
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
Path('observed.txt').write_text(json.dumps({'pid':os.getpid(),'secret_present':'REBUILD_TEST_SECRET' in os.environ,'allowed':os.getenv('REBUILD_TEST_ALLOWED')}))
print('DO_NOT_ECHO_SERVICE_LOG_SECRET',flush=True)
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(503 if sys.argv[2]=='unready' else 200);self.end_headers();self.wfile.write(b'ok')
 def log_message(self,*args):pass
HTTPServer(('127.0.0.1',int(sys.argv[1])),Handler).serve_forever()
'''


def available_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class RebuildSecurity(unittest.TestCase):
    def setUp(self):
        try:
            require_process_support()
        except ValueError as exc:
            self.skipTest(str(exc))
        self.temp = tempfile.TemporaryDirectory(prefix='owned-rebuild-test-')
        self.project = Path(self.temp.name)
        self.fixture = self.project / 'fixture.py'
        self.fixture.write_text(FIXTURE, encoding='utf-8')
        self.artifact = self.project / 'artifact.bin'
        self.artifact.write_bytes(b'build output')
        now = time.time()
        os.utime(self.fixture, (now - 2, now - 2))
        os.utime(self.artifact, (now, now))
        self.record_path = self.project / '.rebuild-process.json'
        self.port = available_port()
        self.known_records = []
        self.external = []

    def tearDown(self):
        # Cleanup only records/process handles created by this test, never a
        # forged record or a numeric PID selected by a port lookup.
        for record in self.known_records:
            try:
                with OwnedProcess(record['pid']) as process:
                    process.verify(record, self.project)
                    process.stop()
            except (ValueError, OSError):
                pass
            proc = rebuild._CHILDREN.pop(record['pid'], None)
            if proc is not None:
                proc.wait(timeout=6)
        for proc in self.external:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=6)
        self.temp.cleanup()

    def arguments(self, mode='ready', timeout='3'):
        return ['--project-dir', str(self.project), '--artifact', str(self.artifact),
                '--start-argv', json.dumps([PYTHON, str(self.fixture), str(self.port), mode]),
                '--health-url', f'http://127.0.0.1:{self.port}/health',
                '--port', str(self.port), '--timeout', timeout, '--skip-build']

    def call(self, arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = rebuild.main(arguments)
        if self.record_path.exists():
            try:
                record = read_record(self.record_path, self.project)
                if record and record not in self.known_records:
                    self.known_records.append(record)
            except ValueError:
                pass
        return code, output.getvalue()

    def test_real_start_record_replace_stop_and_minimal_environment(self):
        with patch.dict(os.environ, {'REBUILD_TEST_SECRET': 'must-not-inherit',
                                     'REBUILD_TEST_ALLOWED': 'explicit-value'}):
            code, output = self.call(self.arguments())
            self.assertEqual(code, 0, output)
            first = read_record(self.record_path, self.project)
            self.assertTrue({'pid', 'start_time', 'executable', 'project', 'instance_id'} <= set(first))
            observed = json.loads((self.project / 'observed.txt').read_text())
            self.assertEqual(observed['pid'], first['pid'])
            self.assertFalse(observed['secret_present'])
            self.assertIsNone(observed['allowed'])
            code, output = self.call(self.arguments() + ['--pass-env', 'REBUILD_TEST_ALLOWED'])
            self.assertEqual(code, 0, output)
            second = read_record(self.record_path, self.project)
            self.assertNotEqual(first['instance_id'], second['instance_id'])
            self.assertNotEqual(first['pid'], second['pid'])
            self.assertEqual(json.loads((self.project / 'observed.txt').read_text())['allowed'], 'explicit-value')
            self.assertNotIn('explicit-value', output)
        code, output = self.call(['--project-dir', str(self.project), '--stop'])
        self.assertEqual(code, 0, output)
        self.assertFalse(self.record_path.exists())
        self.assertFalse(rebuild.port_occupied(self.port))

    def test_build_failure_keeps_existing_owned_service(self):
        self.assertEqual(self.call(self.arguments())[0], 0)
        before = read_record(self.record_path, self.project)
        args = self.arguments(); args.remove('--skip-build')
        args += ['--build-argv', json.dumps([PYTHON, '-c', 'raise SystemExit(7)'])]
        code, _ = self.call(args)
        self.assertEqual(code, 1)
        self.assertEqual(read_record(self.record_path, self.project), before)
        with OwnedProcess(before['pid']) as process:
            process.verify(before, self.project)
            self.assertTrue(process.alive())
        self.assertTrue(rebuild.port_occupied(self.port))

    def test_timeout_cleans_new_process_without_echoing_log(self):
        code, output = self.call(self.arguments('unready', '0.6'))
        self.assertEqual(code, 1)
        self.assertFalse(self.record_path.exists())
        self.assertFalse(rebuild.port_occupied(self.port))
        self.assertIn('cleaned up', output)
        self.assertNotIn('DO_NOT_ECHO_SERVICE_LOG_SECRET', output)
        self.assertIn('DO_NOT_ECHO_SERVICE_LOG_SECRET', (self.project / 'service.log').read_text())
        pid = json.loads((self.project / 'observed.txt').read_text())['pid']
        try:
            with OwnedProcess(pid) as process:
                self.assertFalse(process.alive())
        except ValueError:
            pass  # No longer exists, also the intended result.

    def test_successful_build_checks_old_health_before_replacing(self):
        self.assertEqual(self.call(self.arguments())[0], 0)
        before = read_record(self.record_path, self.project)
        build_script = ("import json,os,socket;from pathlib import Path;"
                        f"s=socket.create_connection(('127.0.0.1',{self.port}),1);s.close();"
                        "Path('build-observed.txt').write_text(json.dumps({'secret_present':'REBUILD_TEST_SECRET' in os.environ}));"
                        "Path('artifact.bin').write_bytes(b'rebuilt')")
        args = self.arguments(); args.remove('--skip-build')
        args += ['--build-argv', json.dumps([PYTHON, '-c', build_script])]
        with patch.dict(os.environ, {'REBUILD_TEST_SECRET': 'do-not-inherit'}):
            code, output = self.call(args)
        self.assertEqual(code, 0, output)
        self.assertEqual(self.artifact.read_bytes(), b'rebuilt')
        self.assertFalse(json.loads((self.project / 'build-observed.txt').read_text())['secret_present'])
        self.assertNotEqual(read_record(self.record_path, self.project)['instance_id'], before['instance_id'])

    def test_start_exits_without_readiness_and_cleans_record(self):
        args = self.arguments(timeout='0.6')
        args[args.index('--start-argv') + 1] = json.dumps([PYTHON, '-c', 'raise SystemExit(3)'])
        code, output = self.call(args)
        self.assertEqual(code, 1, output)
        self.assertFalse(self.record_path.exists())
        self.assertFalse(rebuild.port_occupied(self.port))

    def test_invalid_timeout_and_command_retain_old_service(self):
        self.assertEqual(self.call(self.arguments())[0], 0)
        before = read_record(self.record_path, self.project)
        for arguments in (self.arguments(timeout='nan'), self.arguments(timeout='inf')):
            self.assertEqual(self.call(arguments)[0], 1)
        args = self.arguments()
        args[args.index('--start-argv') + 1] = json.dumps(['unavailable-executable-for-rebuild-test'])
        self.assertEqual(self.call(args)[0], 1)
        self.assertEqual(read_record(self.record_path, self.project), before)
        self.assertTrue(rebuild.port_occupied(self.port))

    def test_existing_foreign_listener_is_not_stopped(self):
        with (self.project / 'foreign.log').open('ab') as stream:
            proc = subprocess.Popen([PYTHON, str(self.fixture), str(self.port), 'ready'],
                                    cwd=self.project, env=child_env(), shell=False,
                                    stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                    **rebuild._launch_options())
        self.external.append(proc)
        deadline = time.monotonic() + 3
        while not rebuild.port_occupied(self.port) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(rebuild.port_occupied(self.port))
        code, _ = self.call(self.arguments())
        self.assertEqual(code, 1)
        self.assertIsNone(proc.poll())
        self.assertFalse(self.record_path.exists())

    def test_changing_to_occupied_port_keeps_old_service(self):
        self.assertEqual(self.call(self.arguments())[0], 0)
        before = read_record(self.record_path, self.project)
        old_port = self.port
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(8)
            self.port = listener.getsockname()[1]
            code, _ = self.call(self.arguments())
            self.assertEqual(code, 1)
            self.assertEqual(read_record(self.record_path, self.project), before)
            self.assertTrue(rebuild.port_occupied(old_port))
            self.assertTrue(rebuild.port_occupied(self.port))

    def test_ipv6_existing_health_cannot_certify_new_nonlistener(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
            def log_message(self, *_):
                pass
        class V6(ThreadingHTTPServer):
            address_family = socket.AF_INET6
        try:
            server = V6(('::1', 0), Handler)
        except OSError as exc:
            self.skipTest('IPv6 loopback unavailable: ' + str(exc))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            args = self.arguments()
            args[args.index('--health-url') + 1] = f'http://[::1]:{server.server_port}/health'
            i = args.index('--port'); del args[i:i + 2]
            args[args.index('--start-argv') + 1] = json.dumps([PYTHON, '-c', 'import time;time.sleep(30)'])
            code, output = self.call(args)
            self.assertEqual(code, 1, output)
            self.assertFalse(self.record_path.exists())
            self.assertTrue(rebuild.port_occupied(server.server_port, '::1'))
        finally:
            server.shutdown(); worker.join(2); server.server_close()

    def test_same_port_other_loopback_host_does_not_match_record(self):
        self.assertEqual(self.call(self.arguments())[0], 0)
        before = read_record(self.record_path, self.project)
        with socket.socket() as listener:
            try:
                listener.bind(('127.0.0.2', self.port))
            except OSError as exc:
                self.skipTest('alternate loopback unavailable: ' + str(exc))
            listener.listen(8)
            args = self.arguments()
            args[args.index('--health-url') + 1] = f'http://127.0.0.2:{self.port}/health'
            code, output = self.call(args)
            self.assertEqual(code, 1, output)
            self.assertEqual(read_record(self.record_path, self.project), before)
            self.assertTrue(rebuild.port_occupied(self.port))
            self.assertTrue(rebuild.port_occupied(self.port, '127.0.0.2'))

    def test_health_policy_error_fails_immediately(self):
        started = time.monotonic()
        with patch('_network.safe_health', side_effect=ValueError('redirect forbidden')):
            with self.assertRaisesRegex(ValueError, 'redirect forbidden'):
                rebuild.wait_ready('http://127.0.0.1:1/health', 10)
        self.assertLess(time.monotonic() - started, 1)

    def test_integer_forged_identity_and_stale_records_refuse_stop(self):
        self.assertEqual(self.call(self.arguments())[0], 0)
        good = read_record(self.record_path, self.project)
        for field in ('start_time', 'executable', 'project'):
            forged = copy.deepcopy(good)
            forged[field] = str(self.project / 'not-the-owned-value')
            self.record_path.write_text(json.dumps(forged), encoding='utf-8')
            code, _ = self.call(['--project-dir', str(self.project), '--stop'])
            self.assertEqual(code, 1)
            self.assertTrue(rebuild.port_occupied(self.port))
        self.record_path.write_text(str(good['pid']))
        self.assertEqual(self.call(['--project-dir', str(self.project), '--stop'])[0], 1)
        self.assertTrue(rebuild.port_occupied(self.port))
        write_record(self.record_path, good)
        self.assertEqual(self.call(['--project-dir', str(self.project), '--stop'])[0], 0)
        write_record(self.record_path, good)
        self.assertEqual(self.call(['--project-dir', str(self.project), '--stop'])[0], 1)
        self.assertTrue(self.record_path.exists())

    def test_argv_shell_rejection_and_environment_names(self):
        for command in ('cmd.exe', 'powershell.exe', 'pwsh', 'bash', 'sh', 'mvn.cmd', 'run.bat'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                validate_argv([command, '/c', 'echo unsafe'], self.project, child_env())
        self.assertEqual(parse_argv(json_argv=json.dumps([PYTHON, 'an argument with spaces'])), [PYTHON, 'an argument with spaces'])
        self.assertEqual(parse_argv(command='"' + PYTHON + '" "argument with spaces"'), [PYTHON, 'argument with spaces'])
        with self.assertRaises(ValueError):
            child_env(['TOKEN=value'])

    def test_guard_rejects_remote_before_build_or_stop(self):
        self.assertEqual(self.call(self.arguments())[0], 0)
        before = read_record(self.record_path, self.project)
        args = self.arguments()
        args[args.index('--health-url') + 1] = 'http://example.com/health'
        self.assertEqual(self.call(args)[0], 1)
        self.assertEqual(read_record(self.record_path, self.project), before)
        self.assertTrue(rebuild.port_occupied(self.port))


if __name__ == '__main__':
    unittest.main()
