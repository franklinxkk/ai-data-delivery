"""Independent expectations for bounded expressions and metric/detail snapshots."""
from contextlib import ExitStack, closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from _contract import object_digest, snapshot
from _sql import compile_single, metric_dependencies
from query_bundle import run_bundle


def model():
    return {'version': 'synthetic-v012', 'datasets': [{
        'name': 'companies', 'source': 'companies', 'grain': 'one input row', 'primary_key': ['row_id'],
        'fields': [{'name': name} for name in ['row_id', 'company_id', 'tenant', 'state', 'industry', 'amount']]}],
        'metrics': [{'id': 'companies', 'type': 'count', 'dataset': 'companies',
                     'expr': 'COUNT(DISTINCT company_id)',
                     'filters': [{'field': 'tenant', 'values': ['T1']}],
                     'extra_where': "state = 'active' AND (industry = 'freight' OR industry = 'passenger')"}]}


def seed(conn):
    conn.execute('CREATE TABLE companies(row_id INTEGER, company_id TEXT, tenant TEXT, state TEXT, industry TEXT, amount REAL)')
    conn.executemany('INSERT INTO companies VALUES(?,?,?,?,?,?)', [
        (2, 'A', 'T1', 'active', 'freight', 20), (1, 'A', 'T1', 'active', 'freight', 10),
        (3, None, 'T1', 'active', 'passenger', 5), (4, 'B', 'T2', 'active', 'freight', 100),
        (5, 'C', 'T1', 'closed', 'freight', 200), (6, 'D', 'T1', 'active', 'taxi', 300)])
    conn.commit()


class BoundedCompiler(unittest.TestCase):
    def setUp(self):
        self.model = model(); self.ds = self.model['datasets'][0]
        self.mt = self.model['metrics'][0]

    def test_refuse_row_max_and_aggregate_bare_field(self):
        for expr in ['MAX(amount,0)', 'SUM(amount)+row_id', 'CASE WHEN row_id=1 THEN SUM(amount) ELSE 0 END',
                     'SUM(SUM(amount))', "row_id + LENGTH('SUM(')"]:
            with self.subTest(expr=expr):
                self.mt['expr'] = expr
                sql, error = compile_single(self.mt, self.ds)
                self.assertIsNone(sql); self.assertTrue(error)
                self.assertEqual(metric_dependencies(self.mt, self.ds)['error_kind'], 'invalid_aggregate')

    def test_undeclared_fields_in_expression_and_scope_refuse(self):
        for change in [{'expr': 'SUM(secret)'}, {'extra_where': 'secret=1'},
                       {'filters': [{'field': 'secret', 'values': [1]}]}]:
            with self.subTest(change=change):
                metric = {**self.mt, **change}
                self.assertIsNone(compile_single(metric, self.ds)[0])
                self.assertEqual(metric_dependencies(metric, self.ds)['error_kind'], 'unknown_field')

    def test_quoted_field_is_not_sqlite_missing_column_string_literal(self):
        self.mt['expr'] = 'SUM("secret")'
        self.assertIsNone(compile_single(self.mt, self.ds)[0])

    def test_quoted_literals_and_supported_case_arithmetic(self):
        self.mt['expr'] = "ROUND(SUM(CASE WHEN company_id = 'A' THEN amount ELSE 0 END), 2) + COUNT(*)"
        with sqlite3.connect(':memory:') as conn:
            seed(conn)
            sql, error = compile_single(self.mt, self.ds)
            self.assertIsNone(error)
            self.assertEqual(conn.execute(sql).fetchone()[0], 33)
        self.assertEqual(metric_dependencies(self.mt, self.ds)['fields'], ['amount', 'company_id', 'industry', 'state', 'tenant'])

    def test_current_dataset_prefix_and_cast_remain_supported(self):
        self.mt['expr'] = 'CAST(SUM(companies.amount) AS REAL) / NULLIF(COUNT(*), 0)'
        with sqlite3.connect(':memory:') as conn:
            seed(conn)
            sql, error = compile_single(self.mt, self.ds)
            self.assertIsNone(error)
            self.assertAlmostEqual(conn.execute(sql).fetchone()[0], 35 / 3)

    def test_unsupported_functions_and_multicolumn_are_not_silently_changed(self):
        for expr in ['RANDOM() + COUNT(*)', 'SUM(amount), COUNT(*)', 'SUM(amount) OVER ()']:
            with self.subTest(expr=expr):
                self.mt['expr'] = expr
                self.assertIsNone(compile_single(self.mt, self.ds)[0])
        self.mt['extra_where'] = 'SUM(amount)>0'
        self.mt['expr'] = 'COUNT(*)'
        self.assertIsNone(compile_single(self.mt, self.ds)[0])
        # Declaring fields named SQL keywords must not turn forbidden clauses into fields.
        self.ds['fields'] += [{'name': name} for name in ['SELECT', 'FROM', 'other']]
        self.mt['extra_where'] = ''
        self.mt['expr'] = 'COUNT((SELECT amount FROM other))'
        self.assertIsNone(compile_single(self.mt, self.ds)[0])


class MetricDetailBundle(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:'); self.addCleanup(self.conn.close)
        seed(self.conn); self.model = model()

    def bundle(self, **kw):
        return run_bundle(self.model, self.conn, 'companies', ['row_id', 'company_id'], **kw)

    def assert_error(self, result, code):
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error']['code'], code)
        for key in ['metric_value', 'matched_row_count', 'detail_rows', 'pagination']:
            self.assertNotIn(key, result)

    def test_three_counts_share_three_input_rows(self):
        for expr, count in [('COUNT(*)', 3), ('COUNT(company_id)', 2), ('COUNT(DISTINCT company_id)', 1)]:
            with self.subTest(expr=expr):
                self.model['metrics'][0]['expr'] = expr
                result = self.bundle()
                self.assertEqual(result['status'], 'computed_only')
                self.assertEqual(result['metric_value'], count)
                self.assertEqual(result['matched_row_count'], 3)
                self.assertEqual(result['detail_rows'], [[1, 'A'], [2, 'A'], [3, None]])
                self.assertFalse(result['pagination']['truncated'])

    def test_filter_precedes_projection_and_stable_pagination(self):
        first, second = self.bundle(limit=2), self.bundle(limit=2, offset=2)
        self.assertEqual(first['detail_columns'], ['row_id', 'company_id'])
        self.assertEqual(first['detail_rows'], [[1, 'A'], [2, 'A']])
        self.assertEqual(second['detail_rows'], [[3, None]])
        self.assertEqual(first['pagination']['next_offset'], 2)
        self.assertTrue(first['pagination']['has_more'])
        self.assertFalse(second['pagination']['has_more'])
        self.assertEqual(first['metric_value'], second['metric_value'])
        self.assertEqual(first['evidence']['data_snapshot_sha256'], second['evidence']['data_snapshot_sha256'])

    def test_empty_scope_and_offset_beyond_end_are_distinct(self):
        beyond = self.bundle(offset=100)
        self.assertEqual(beyond['detail_rows'], [])
        self.assertEqual(beyond['matched_row_count'], 3)
        self.model['metrics'][0]['filters'][0]['values'] = ['absent']
        empty = self.bundle()
        self.assertEqual(empty['metric_value'], 0)
        self.assertEqual(empty['matched_row_count'], 0)
        self.assertEqual(empty['detail_rows'], [])
        self.assertFalse(empty['pagination']['truncated'])
        self.assertFalse(self.bundle(offset=100)['pagination']['truncated'])

    def test_ratio_null_zero_and_error_preserve_same_scope(self):
        metric = self.model['metrics'][0]
        metric.pop('expr'); metric.update(type='ratio', numerator={'expr': 'SUM(amount)'}, denominator={'expr': 'SUM(amount)-35'})
        for policy, expected in [('null', None), ('zero', 0)]:
            metric['on_zero_denominator'] = policy
            result = self.bundle()
            self.assertEqual(result['metric_value'], expected)
            self.assertEqual(result['matched_row_count'], 3)
        metric['on_zero_denominator'] = 'error'
        self.assert_error(self.bundle(), 'zero_denominator')

    def test_bad_or_missing_primary_key_refuses_pagination(self):
        self.model['datasets'][0]['primary_key'] = []
        self.assert_error(self.bundle(), 'unstable_identity')
        self.model['datasets'][0]['primary_key'] = ['company_id']
        self.assert_error(self.bundle(), 'unstable_identity')
        self.conn.execute('UPDATE companies SET row_id=1 WHERE row_id=2'); self.conn.commit()
        self.model['datasets'][0]['primary_key'] = ['row_id']
        self.assert_error(self.bundle(), 'unstable_identity')

    def test_composite_key_is_verified_and_orders_all_components(self):
        self.model['datasets'][0]['primary_key'] = ['tenant', 'row_id']
        self.conn.execute('UPDATE companies SET row_id=1 WHERE row_id=4'); self.conn.commit()
        result = self.bundle()
        self.assertEqual(result['status'], 'computed_only')
        self.assertEqual(result['pagination']['order_by'], ['tenant', 'row_id'])
        self.assertEqual(result['detail_rows'], [[1, 'A'], [2, 'A'], [3, None]])

    def test_invalid_columns_and_pages_return_no_partial_result(self):
        for columns in [[], ['secret'], ['row_id', 'row_id'], ['row_id; DELETE FROM companies']]:
            self.assert_error(run_bundle(self.model, self.conn, 'companies', columns), 'invalid_columns')
        for kw in [{'limit': 0}, {'limit': 501}, {'offset': -1}, {'limit': True}]:
            self.assert_error(self.bundle(**kw), 'invalid_page')

    def test_physical_schema_missing_declared_detail_column_refuses(self):
        self.conn.execute('ALTER TABLE companies RENAME COLUMN company_id TO changed'); self.conn.commit()
        self.model['metrics'][0]['expr'] = 'COUNT(*)'
        self.assert_error(self.bundle(), 'source_schema_mismatch')

    def test_model_binding_precedes_connection_and_snapshot_changes(self):
        mismatch = run_bundle(self.model, None, 'companies', ['row_id'], expected_model_sha256='obsolete')
        self.assert_error(mismatch, 'model_mismatch')
        first = self.bundle(expected_model_sha256=object_digest(self.model))
        self.conn.execute('UPDATE companies SET amount=11 WHERE row_id=1'); self.conn.commit()
        second = self.bundle()
        self.assertEqual(first['evidence']['model_sha256'], second['evidence']['model_sha256'])
        self.assertNotEqual(first['evidence']['data_snapshot_sha256'], second['evidence']['data_snapshot_sha256'])

    def test_query_does_not_write_or_change_caller_transaction(self):
        self.conn.execute('UPDATE companies SET amount=11 WHERE row_id=1')
        self.assertTrue(self.conn.in_transaction)
        before = self.conn.total_changes
        self.bundle()
        self.assertEqual(self.conn.total_changes, before)
        self.assertTrue(self.conn.in_transaction)
        self.assertEqual(self.conn.execute('PRAGMA query_only').fetchone()[0], 0)
        self.conn.rollback()
        self.assertEqual(self.conn.execute('SELECT amount FROM companies WHERE row_id=1').fetchone()[0], 10)

    def test_failure_does_not_leave_query_only_enabled(self):
        self.model['datasets'][0]['primary_key'] = ['company_id']
        self.assert_error(self.bundle(), 'unstable_identity')
        self.assertEqual(self.conn.execute('PRAGMA query_only').fetchone()[0], 0)
        self.assertFalse(self.conn.in_transaction)


class SnapshotAndCLI(unittest.TestCase):
    def test_concurrent_wal_write_does_not_mix_metric_count_and_detail(self):
        with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
            path = Path(td) / 'wal.sqlite'
            writer = stack.enter_context(closing(sqlite3.connect(path)))
            writer.execute('PRAGMA journal_mode=WAL'); seed(writer)
            reader = stack.enter_context(closing(sqlite3.connect(path)))
            expected_conn, expected_hash = snapshot(path); expected_conn.close()
            changed = []
            def trace(sql):
                if sql.startswith('SELECT COUNT ( DISTINCT') and not changed:
                    writer.execute("INSERT INTO companies VALUES(9,'NEW','T1','active','freight',900)")
                    writer.commit(); changed.append(True)
            reader.set_trace_callback(trace)
            result = run_bundle(model(), reader, 'companies', ['row_id', 'company_id'])
            self.assertEqual(changed, [True])
            self.assertEqual(result['metric_value'], 1)
            self.assertEqual(result['matched_row_count'], 3)
            self.assertEqual(result['detail_rows'], [[1, 'A'], [2, 'A'], [3, None]])
            self.assertEqual(result['evidence']['data_snapshot_sha256'], expected_hash)
            self.assertEqual(writer.execute('SELECT COUNT(*) FROM companies').fetchone()[0], 7)

    def test_cli_files_are_bound_and_missing_snapshot_is_not_created(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td); mp = path / 'model.json'; dp = path / 'sample.sqlite'; op = path / 'result.json'
            mp.write_text(json.dumps(model()), encoding='utf-8')
            with closing(sqlite3.connect(dp)) as conn: seed(conn)
            digest = hashlib.sha256(mp.read_bytes()).hexdigest()
            command = [sys.executable, str(ROOT / 'scripts/query_bundle.py'), '--model', str(mp), '--db', str(dp),
                       '--metric', 'companies', '--columns', 'row_id,company_id', '--limit', '2', '--out', str(op)]
            result = subprocess.run(command + ['--expected-model', digest], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(op.read_text(encoding='utf-8'))
            self.assertEqual(report['metric_value'], 1)
            self.assertEqual(report['evidence']['model_sha256'], digest)
            self.assertEqual(report['evidence']['semantic_model_sha256'], object_digest(model()))
            mismatch = subprocess.run(command + ['--expected-model', 'old'], capture_output=True, text=True)
            self.assertEqual(mismatch.returncode, 2)
            self.assertEqual(json.loads(op.read_text(encoding='utf-8'))['error']['code'], 'model_mismatch')
            dp.unlink()
            missing = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(missing.returncode, 2)
            self.assertFalse(dp.exists())


if __name__ == '__main__':
    unittest.main()
