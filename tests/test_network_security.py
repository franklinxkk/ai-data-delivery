"""Network policy and real loopback HTTP tests; never contact external services."""
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import _network
from _contract import guard_endpoint
import capture_case
import plan_stability
import probe_model
import reconcile_paths
import run_eval


@contextmanager
def server():
    state = {'calls': [], 'ask': {'value': 3}, 'redirect': ''}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.do_GET()

        def do_GET(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            state['calls'].append({'path': self.path, 'host': self.headers.get('Host'),
                                   'method': self.command, 'body': body.decode('utf-8')})
            try:
                if self.path.startswith('/redirect'):
                    self.send_response(302); self.send_header('Location', state['redirect']); self.end_headers(); return
                if self.path == '/large-header':
                    self.send_response(200); self.send_header('Content-Length', str(_network.MAX_RESPONSE + 1)); self.end_headers(); return
                if self.path == '/large-body':
                    self.send_response(200); self.end_headers()
                    self.wfile.write(b'x' * (_network.MAX_RESPONSE + 1)); return
                if self.path == '/slow':
                    self.send_response(200); self.send_header('Content-Length', '2'); self.end_headers()
                    time.sleep(0.4); self.wfile.write(b'{}'); return
                if self.path in {'/trickle', '/trickle-close'}:
                    if self.path == '/trickle-close': self.protocol_version = 'HTTP/1.1'
                    self.send_response(200); self.send_header('Content-Length', '20')
                    if self.path == '/trickle-close': self.send_header('Connection', 'close')
                    self.end_headers()
                    for _ in range(20):
                        self.wfile.write(b' '); self.wfile.flush(); time.sleep(0.03)
                    return
                status, value = 200, {'ok': True}
                if self.path == '/invalid': raw = b'not json'
                elif self.path == '/error': status, value = 503, {'error': 'down'}; raw = json.dumps(value).encode()
                elif self.path == '/health': raw = b'healthy'
                elif self.path == '/api/ask': raw = json.dumps(state['ask']).encode()
                elif self.path == '/api/model': raw = json.dumps(state.get('model', {'version': 't', 'metrics': []})).encode()
                elif self.path == '/api/metrics/progress': raw = json.dumps(state.get('progress', {'modelVersion': 't', 'total': 0})).encode()
                elif self.path.startswith('/api/search'): raw = b'[]'
                else: raw = json.dumps(value).encode()
                self.send_response(status); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    httpd.daemon_threads = True
    worker = threading.Thread(target=httpd.serve_forever, daemon=True); worker.start()
    state['base'] = f'http://127.0.0.1:{httpd.server_port}'
    state['port'] = httpd.server_port
    try:
        yield state
    finally:
        httpd.shutdown(); httpd.server_close(); worker.join(timeout=2)


class EndpointPolicy(unittest.TestCase):
    def test_precise_localhost_and_private_literals_without_dns(self):
        with patch('_network.socket.getaddrinfo', side_effect=AssertionError('guard must not resolve')):
            for url in ['http://localhost:9000', 'http://LOCALHOST', 'http://127.0.0.2', 'https://[::1]',
                        'http://10.2.3.4', 'http://172.16.0.1', 'http://192.168.0.1', 'http://[fd12::1]']:
                with self.subTest(url=url): guard_endpoint(url)

    def test_near_localhost_and_public_destinations_need_explicit_opt_in(self):
        for url in ['http://notlocalhost:9000', 'http://localhost.evil.test', 'http://localhost.',
                    'https://engine.example', 'https://8.8.8.8', 'https://[2606:4700:4700::1111]']:
            with self.subTest(url=url):
                with self.assertRaises(ValueError): guard_endpoint(url)
                guard_endpoint(url, allow_remote=True)  # Policy-only; never connects or resolves.

    def test_metadata_linklocal_unspecified_multicast_always_rejected(self):
        for host in ['169.254.169.254', '169.254.1.2', '100.100.100.200', '168.63.129.16',
                     '0.0.0.0', '224.0.0.1', '[::]', '[ff02::1]', '[fe80::1]', '[fd00:ec2::254]',
                     '[::ffff:169.254.169.254]', '[64:ff9b::6464:64c8]', '[2002:a9fe:a9fe::1]',
                     'metadata.google.internal']:
            for remote in [False, True]:
                with self.subTest(host=host, remote=remote), self.assertRaises(ValueError):
                    guard_endpoint('http://' + host, remote)

    def test_credentials_schemes_and_parser_ambiguity_always_rejected(self):
        for url in ['file:///tmp/file', 'ftp://127.0.0.1', 'http://user:secret@127.0.0.1',
                    'http://@127.0.0.1', 'http://127.0.0.1:0', 'http://127.0.0.1:99999',
                    ' http://127.0.0.1', 'http://127.0.0.1/\r\nX:bad', 'http://127.0.0.1\\@evil.test',
                    'http://[fe80::1%25eth0]', 'http://127.0.0.1/#fragment']:
            with self.subTest(url=url), self.assertRaises(ValueError): guard_endpoint(url, True)


class LoopbackTransport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.first = cls.stack.enter_context(server()); cls.second = cls.stack.enter_context(server())
        cls.first['redirect'] = cls.second['base'] + '/destination'

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def setUp(self):
        self.first['calls'].clear(); self.second['calls'].clear()

    def test_direct_json_post_and_plain_health(self):
        result = _network.safe_json(self.first['base'] + '/api/ask', {'question': '企业数'})
        self.assertEqual(result, {'value': 3})
        self.assertEqual(json.loads(self.first['calls'][0]['body']), {'question': '企业数'})
        self.assertTrue(_network.safe_health(self.first['base'] + '/health'))
        self.assertFalse(_network.safe_health(self.first['base'] + '/error'))

    def test_real_redirect_does_not_reach_second_loopback_server(self):
        for fn in [_network.safe_json, _network.safe_health]:
            with self.subTest(fn=fn.__name__), self.assertRaisesRegex(ValueError, '重定向'):
                fn(self.first['base'] + '/redirect')
        self.assertEqual(len(self.first['calls']), 2)
        self.assertEqual(self.second['calls'], [])

    def test_proxy_environment_is_not_inherited(self):
        with patch.dict(os.environ, {'HTTP_PROXY': self.second['base'], 'HTTPS_PROXY': self.second['base'],
                                     'ALL_PROXY': self.second['base'], 'http_proxy': self.second['base'],
                                     'https_proxy': self.second['base'], 'all_proxy': self.second['base'],
                                     'NO_PROXY': '', 'no_proxy': ''}):
            self.assertEqual(_network.safe_json(self.first['base'] + '/json'), {'ok': True})
        self.assertEqual(len(self.first['calls']), 1)
        self.assertEqual(self.second['calls'], [])

    def test_domain_is_resolved_once_and_host_is_preserved(self):
        answer = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', self.first['port']))]
        with patch('_network.socket.getaddrinfo', side_effect=[answer, AssertionError('second resolution')]) as resolve:
            response = _network.safe_json(f"http://engine.example:{self.first['port']}/json", allow_remote=True)
        self.assertEqual(response, {'ok': True})
        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(self.first['calls'][0]['host'], f"engine.example:{self.first['port']}")

    def test_localhost_is_pinned_without_dns(self):
        with patch('_network.socket.getaddrinfo', side_effect=AssertionError('DNS must not override localhost')):
            self.assertEqual(_network.safe_json(f"http://localhost:{self.first['port']}/json"), {'ok': True})

    def test_mixed_dns_answers_fail_before_any_connection(self):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, self.first['port']))
                   for ip in ['127.0.0.1', '169.254.169.254']]
        with patch('_network.socket.getaddrinfo', return_value=answers), patch('_network._connect') as connect:
            with self.assertRaises(ValueError):
                _network.safe_json(f"http://engine.example:{self.first['port']}/json", allow_remote=True)
            connect.assert_not_called()
        self.assertEqual(self.first['calls'], [])

    def test_four_mb_limit_applies_to_declared_and_streamed_bodies(self):
        for path in ['/large-header', '/large-body']:
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, '4 MB'):
                _network.safe_json(self.first['base'] + path)

    def test_timeout_is_overall_deadline_including_trickle_body(self):
        for path in ['/slow', '/trickle', '/trickle-close']:
            start = time.monotonic()
            with self.subTest(path=path), self.assertRaises(TimeoutError):
                _network.safe_json(self.first['base'] + path, timeout=0.1)
            self.assertLess(time.monotonic() - start, 0.35)

    def test_dns_timeout_stops_before_connect(self):
        def slow(*args, **kwargs):
            time.sleep(0.2)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80))]
        with patch('_network.socket.getaddrinfo', side_effect=slow), patch('_network._connect') as connect:
            with self.assertRaises(TimeoutError):
                _network.safe_json('http://engine.example/json', timeout=0.03, allow_remote=True)
            connect.assert_not_called()

    def test_bad_status_and_invalid_json_are_explicit_failures(self):
        with self.assertRaisesRegex(ValueError, '503'): _network.safe_json(self.first['base'] + '/error')
        with self.assertRaisesRegex(ValueError, 'JSON'): _network.safe_json(self.first['base'] + '/invalid')

    def test_https_keeps_original_host_and_verified_default_context(self):
        context = ssl.create_default_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        raw = MagicMock(); wrapped = MagicMock()
        conn = _network._PinnedHTTPS('engine.example', 443, context=context)
        conn.addresses = [(socket.AF_INET, ('127.0.0.1', 443))]; conn.deadline = time.monotonic() + 1
        with patch('_network._connect', return_value=raw), patch.object(ssl.SSLContext, 'wrap_socket', return_value=wrapped) as wrap:
            conn.connect()
            wrap.assert_called_once_with(raw, server_hostname='engine.example', do_handshake_on_connect=False)
            wrapped.do_handshake.assert_called_once_with()
            self.assertGreater(wrapped.settimeout.call_args.args[0], 0)
            self.assertLessEqual(wrapped.settimeout.call_args.args[0], 1)
        conn.close()

    def test_tls_handshake_uses_remaining_total_deadline_after_connect(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(2)
        accepted, release = threading.Event(), threading.Event()
        def no_tls_reply():
            try:
                peer, _ = listener.accept()
                with peer:
                    accepted.set()
                    release.wait(2)  # Accept TCP, deliberately never answer ClientHello.
            except OSError:
                pass
        worker = threading.Thread(target=no_tls_reply, daemon=True); worker.start()
        original_connect = _network._connect
        def slow_connect(addresses, deadline):
            connected = original_connect(addresses, deadline)
            time.sleep(0.25)  # Simulate connection work consuming most of the budget.
            return connected
        try:
            start = time.monotonic()
            with patch('_network._connect', side_effect=slow_connect), self.assertRaises(TimeoutError):
                _network.safe_health(f'https://127.0.0.1:{listener.getsockname()[1]}/health', timeout=0.4)
            elapsed = time.monotonic() - start
            self.assertTrue(accepted.is_set())
            self.assertLess(elapsed, 0.58)  # Old handshake reused ~0.4s after the 0.25s delay.
        finally:
            release.set(); listener.close(); worker.join(timeout=2)


class ConsumerAdapters(unittest.TestCase):
    def test_live_eval_mixed_modes_and_ambiguous_base_urls_never_start(self):
        live = ['run_eval.py', '--cases', 'cases.json', '--endpoint']
        for rest in [
            ['http://127.0.0.1', '--gold', 'cases.json', '--actual', 'actual.jsonl'],
            ['http://127.0.0.1/proxy?mode=read'],
            ['http://127.0.0.1/proxy#'],
            ['https://engine.example'],
        ]:
            with self.subTest(rest=rest), patch.object(sys, 'argv', live + rest), \
                    patch.object(run_eval, 'run_live') as run, redirect_stderr(io.StringIO()):
                self.assertEqual(run_eval.main(), 2)
                run.assert_not_called()
        with patch.object(run_eval, 'safe_json') as send:
            self.assertIn('error', run_eval.ask('http://127.0.0.1/proxy?mode=read', 'q'))
            send.assert_not_called()

    def test_live_eval_sends_only_original_questions_to_explicit_engine(self):
        with server() as state, tempfile.TemporaryDirectory() as td, redirect_stdout(io.StringIO()):
            path = Path(td)
            suite_paths = []
            questions = ['模拟问句一', '模拟多跳问句']
            for index, question in enumerate(questions):
                cases = path / f'cases-{index}.json'
                cases.write_text(json.dumps([
                    {'id': str(index), 'question': question, 'expect': {'type': 'scalar', 'value': 3}},
                ]), encoding='utf-8')
                suite_paths.append(str(cases))
            args = ['run_eval.py', '--endpoint', state['base'], '--cases', suite_paths[0],
                    '--multihop', suite_paths[1], '--out', str(path / 'report.json')]
            with patch.object(sys, 'argv', args):
                self.assertEqual(run_eval.main(), 0)
            self.assertEqual(
                [(call['method'], call['path'], json.loads(call['body'])) for call in state['calls']],
                [('POST', '/api/ask', {'question': question}) for question in questions],
            )

    def test_all_wrappers_preserve_explicit_allow_remote(self):
        for module, invoke in [
            (capture_case, lambda allowed: capture_case.call('POST', 'https://engine.example/api/ask', {'question': 'q'}, allow_remote=allowed)),
            (plan_stability, lambda allowed: plan_stability.ask('https://engine.example', 'q', allow_remote=allowed)),
            (probe_model, lambda allowed: probe_model.get('https://engine.example/api/model', allow_remote=allowed)),
            (reconcile_paths, lambda allowed: reconcile_paths.ask('https://engine.example', 'q', allow_remote=allowed)),
            (run_eval, lambda allowed: run_eval.ask('https://engine.example', 'q', allow_remote=allowed))]:
            for allowed in [False, True]:
                with self.subTest(module=module.__name__, allowed=allowed), patch.object(module, 'safe_json', return_value={'value': 3}) as call:
                    invoke(allowed)
                    self.assertEqual(call.call_args.kwargs['allow_remote'], allowed)

    def test_all_wrappers_reject_remote_without_flag_before_dns(self):
        with patch('_network.socket.getaddrinfo', side_effect=AssertionError('must refuse before DNS')):
            for module in [plan_stability, reconcile_paths, run_eval]:
                self.assertIn('error', module.ask('https://engine.example', 'q'))
            self.assertIsNotNone(capture_case.call('GET', 'https://engine.example')[1])
            self.assertIsNotNone(probe_model.get('https://engine.example')[1])

    def test_cli_flags_are_forwarded_beyond_guard(self):
        with tempfile.TemporaryDirectory() as td, redirect_stdout(io.StringIO()):
            with patch.object(sys, 'argv', ['capture_case.py', '--endpoint', 'https://engine.example', '--question', 'q', '--out', td, '--allow-remote']), \
                    patch.object(capture_case, 'call', side_effect=[({'value': 3}, None), ([], None), ({'modelVersion': 'x'}, None)]) as call:
                self.assertEqual(capture_case.main(), 0)
                self.assertTrue(all(item.kwargs['allow_remote'] for item in call.call_args_list))
            with patch.object(sys, 'argv', ['plan_stability.py', '--endpoint', 'https://engine.example', '--question', 'q', '--allow-remote']), \
                    patch.object(plan_stability, 'ask', return_value={'value': 3}) as call:
                self.assertEqual(plan_stability.main(), 0)
                self.assertTrue(all(item.kwargs['allow_remote'] for item in call.call_args_list))
            with patch.object(sys, 'argv', ['probe_model.py', '--endpoint', 'https://engine.example', '--allow-remote']), \
                    patch.object(probe_model, 'get', side_effect=[({'modelVersion': 'x', 'total': 1}, None), (None, 'not provided')]) as call:
                self.assertEqual(probe_model.main(), 0)
                self.assertTrue(all(item.kwargs['allow_remote'] for item in call.call_args_list))

    def test_error_and_rejected_values_cannot_satisfy_numeric_expectation(self):
        for envelope in [{'error': 'failed', 'value': 3}, {'rejected': True, 'value': 3},
                         {'refused': True, 'value': 3}, {'success': False, 'value': 3},
                         {'status': 'pending', 'value': 3}, {'status': 'error', 'value': 3},
                         {'status': 'fail', 'value': 3}, {'status': 'blocked', 'value': 3},
                         {'status': 'running', 'value': 3}, {'status': 'processing', 'value': 3}]:
            with self.subTest(envelope=envelope):
                self.assertFalse(run_eval.judge_live(envelope, {'kind': 'scalar', 'value': 3})[0])
                self.assertFalse(run_eval.judge_file({'expect': {'type': 'scalar', 'value': 3}}, envelope)[0])
                with patch.object(plan_stability, 'ask', return_value=envelope):
                    stable, _, _ = plan_stability.check_one('http://localhost', 'q', 2)
                    self.assertFalse(stable)
        self.assertTrue(run_eval.judge_live({'rejected': True}, {'kind': 'refusal'})[0])

    def test_plan_requires_real_result_but_preserves_empty_and_null_results(self):
        for envelope in [{}, {'value': None, 'rows': None, 'sql': None}, {'status': 'success'}, {'value': None}]:
            with self.subTest(envelope=envelope), patch.object(plan_stability, 'ask', return_value=envelope):
                self.assertFalse(plan_stability.check_one('http://localhost', 'q', 2)[0])
        for envelope in [{'rows': []}, {'rows': [[None]]}, {'value': 0},
                         {'value': None, 'status': 'completed'}, {'value': None, 'sql': 'SELECT NULL'},
                         {'sql': 'SELECT COUNT(*) FROM facts'}]:
            with self.subTest(envelope=envelope), patch.object(plan_stability, 'ask', return_value=envelope):
                self.assertTrue(plan_stability.check_one('http://localhost', 'q', 2)[0])

    def test_explicit_success_and_null_are_distinct_from_missing_response(self):
        for status in ['ok', 'success', 'completed', 'done']:
            self.assertTrue(run_eval.judge_live({'status': status, 'value': 3}, {'kind': 'scalar', 'value': 3})[0])
        null_expect = {'kind': 'scalar', 'value': None}
        null_case = {'expect': {'type': 'scalar', 'value': None}}
        for actual in [{'value': None, 'status': 'done'}, {'value': None, 'sql': 'SELECT NULL'}, {'rows': [[None]]}]:
            with self.subTest(actual=actual):
                self.assertTrue(run_eval.judge_live(actual, null_expect)[0])
                self.assertTrue(run_eval.judge_file(null_case, actual)[0])
        for actual in [{}, {'value': None}, {'rows': [[3]]}, {'rows': {}}, {'status': 'running', 'value': None}]:
            with self.subTest(actual=actual):
                self.assertFalse(run_eval.judge_live(actual, null_expect)[0])
                self.assertFalse(run_eval.judge_file(null_case, actual)[0])
        self.assertTrue(run_eval.judge_live({'rows': []}, {'kind': 'rows', 'rows': []})[0])
        self.assertTrue(run_eval.judge_file({'expect': {'type': 'rows', 'rows': []}}, {'rows': []})[0])
        self.assertTrue(run_eval.judge_live({'status': 'refused'}, {'kind': 'refusal'})[0])
        self.assertTrue(run_eval.judge_file({'expect': {'type': 'refusal'}}, {'status': 'rejected'})[0])

    def test_reconcile_refusal_and_errors_remain_failures_even_when_values_match(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td); model = path / 'model.json'; db = path / 'db.sqlite'; out = path / 'result.json'
            model.write_text(json.dumps({'datasets': [{'name': 't', 'source': 't', 'fields': [{'name': 'id'}]}],
                                         'metrics': [{'id': 'n', 'name': 'n', 'dataset': 't', 'structured': True,
                                                      'type': 'count', 'expr': 'COUNT(*)'}]}), encoding='utf-8')
            conn = sqlite3.connect(db)
            conn.execute('CREATE TABLE t(id INTEGER)'); conn.executemany('INSERT INTO t VALUES(?)', [(1,), (2,), (3,)]); conn.commit(); conn.close()
            args = SimpleNamespace(model=str(model), db=str(db), metric=[], out=str(out), endpoint='https://engine.example', allow_remote=True)
            for envelope in [{'error': 'failed', 'value': 3}, {'rejected': True, 'value': 3}, {'refused': True, 'value': 3},
                             {'rows': [[3], [999]]}, {'status': 'error', 'value': 3},
                             {'status': 'running', 'value': 3}, {'status': 'processing', 'value': 3}]:
                with self.subTest(envelope=envelope), patch.object(reconcile_paths, 'ask', return_value=envelope) as ask, redirect_stdout(io.StringIO()):
                    self.assertEqual(reconcile_paths.run_active(args), 1)
                    self.assertEqual(json.loads(out.read_text(encoding='utf-8'))[0]['status'], 'error')
                    self.assertTrue(ask.call_args.kwargs['allow_remote'])
            with patch.object(reconcile_paths, 'ask', return_value={'value': 3}), redirect_stdout(io.StringIO()):
                self.assertEqual(reconcile_paths.run_active(args), 0)

    def test_live_eval_forwards_remote_flag_and_transport_failure_fails(self):
        with tempfile.TemporaryDirectory() as td, redirect_stdout(io.StringIO()):
            path = Path(td); cases = path / 'cases.json'
            cases.write_text(json.dumps([{'id': 'q1', 'question': 'q', 'expect': {'type': 'scalar', 'value': 3}}]), encoding='utf-8')
            args = SimpleNamespace(cases=str(cases), gold_results=None, multihop=None, endpoint='https://engine.example',
                                   allow_remote=True, out=str(path / 'report.json'), model=None, db=None, mode=None, actual=None)
            with patch.object(run_eval, 'ask', return_value={'error': 'blocked', 'value': 3}) as call:
                self.assertEqual(run_eval.run_live(args), 1)
                self.assertTrue(call.call_args.kwargs['allow_remote'])

    def test_probe_does_not_treat_an_error_envelope_as_loaded_model(self):
        for response in [{'error': 'not ready', 'version': 'x', 'metrics': []}, {}, {'metrics': 'not a list'}]:
            with self.subTest(response=response), patch.object(probe_model, 'safe_json', return_value=response):
                stats, _, error = probe_model.remote_stats('http://localhost')
                self.assertIsNone(stats); self.assertTrue(error)
        with patch.object(probe_model, 'safe_json', return_value={'metrics': [], 'datasets': []}):
            stats, _, error = probe_model.remote_stats('http://localhost')
            self.assertIsNone(error); self.assertEqual(stats['metrics'], 0)


if __name__ == '__main__':
    unittest.main()
