"""Metadata reuse and consumption regressions, independent expected results."""
import base64
import copy
import json
import io
import zipfile
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from derive_ontology import derive
from check_join_graph import analyze
from _sql import compile_single
from guide_model import new_session
from workbench.service import Service
from workbench.store import Conflict
from workbench.service import lint, gaps
from gen_dictionary import fmt_metric
from _contract import binding_errors


def metadata():
    return {'version': 'synthetic', 'custom': {'keep': [3, 5]},
            'datasets': [
                {'name': 'vehicles', 'source': 'vehicles', 'grain': '一辆车',
                 'primary_key': ['id'], 'temporal': {'kind': 'current'},
                 'fields': [{'name': 'id', 'role': 'pk'}, {'name': 'company_id', 'role': 'dim', 'cn': '企业标识'}]},
                {'name': 'companies', 'source': 'companies', 'grain': '一家企业',
                 'primary_key': ['id'], 'temporal': {'kind': 'current'},
                 'fields': [{'name': 'id', 'role': 'pk'}]}],
            'relationships': [{'id': 'vehicle_company', 'from': 'vehicles', 'to': 'companies',
                               'from_columns': ['company_id'], 'to_columns': ['id'],
                               'cardinality': 'N:1', 'traversable': True}],
            'metrics': [{'id': 'total', 'dataset': 'companies', 'type': 'count', 'expr': 'COUNT(*)',
                         'caliber': {'note': '当前企业记录数'}, 'unit': '条'}]}


class MetadataReuse(unittest.TestCase):
    def test_candidates_and_repeat_preserve_input(self):
        src = metadata(); original = copy.deepcopy(src)
        out, summary = derive(src)
        self.assertEqual(src, original)
        self.assertEqual(len(summary['entities_added']), 2)
        self.assertEqual(len(summary['relations_added']), 1)
        self.assertEqual(out['ontology']['relations'][0]['predicate'], '关联（待确认）')
        self.assertEqual(out['ontology']['entities'][0]['evidence']['source'], 'model_inferred')
        again, summary = derive(out)
        self.assertEqual(out, again)
        self.assertEqual(summary['entities_added'], [])
        self.assertEqual(again['custom'], original['custom'])

    def test_manual_semantics_and_renamed_entity_are_preserved(self):
        src, _ = derive(metadata())
        entity = src['ontology']['entities'][0]
        old = entity['name']; entity['name'] = '已审车辆'; entity['note'] = '人工作出的限定'
        for r in src['ontology']['relations']:
            if r['from'] == old: r['from'] = entity['name']
        src['ontology']['relations'][0]['predicate'] = '登记在'
        out, _ = derive(src)
        self.assertEqual(src, out)

    def test_bad_reference_and_missing_column_refuse_without_mutation(self):
        for change in ('reference', 'column', 'mapping'):
            src, _ = derive(metadata())
            if change == 'reference': src['datasets'][0]['ontology_ref'] = 'lost'
            if change == 'column': src['relationships'][0]['from_columns'] = ['lost']
            if change == 'mapping': src['ontology']['relations'][0]['to'] = 'vehicles'
            original = copy.deepcopy(src)
            with self.subTest(change=change), self.assertRaises(ValueError): derive(src)
            self.assertEqual(src, original)

    def test_parallel_relationships_keep_identity(self):
        src = metadata()
        other = copy.deepcopy(src['relationships'][0]); other['id'] = 'vehicle_operator'
        src['relationships'].append(other)
        result, _ = derive(src)
        self.assertEqual(len({r['id'] for r in result['ontology']['relations']}), 2)
        self.assertEqual(len(result['ontology']['relations']), 2)  # no inverse copies

    def test_same_name_entity_requires_binding_not_guess(self):
        src = metadata(); src['ontology'] = {'entities': [{'uid': 'manual', 'name': 'vehicles'}]}
        with self.assertRaisesRegex(ValueError, 'ontology_ref'): derive(src)

    def test_malformed_metadata_reports_input_problem(self):
        for ds in (['bad'], [{'name': 'same'}, {'name': 'same'}]):
            with self.subTest(ds=ds), self.assertRaises(ValueError): derive({'datasets': ds})

    def test_guide_uid_and_explicit_current_scope(self):
        src, _ = derive(metadata()); src['ontology']['entities'][0]['attributes'] = []
        scope = {'id': 'now', 'question': '当前企业记录数', 'datasets': ['vehicles', 'companies'],
                 'metrics': ['total'], 'time_requirement': 'current'}
        result = new_session(src, scope, 'synthetic')
        self.assertIn('attributes', [g['property'] for g in result['gaps']])
        self.assertNotIn('time_field', [g['property'] for g in result['gaps']])
        scope['time_requirement'] = 'historical_as_of'
        result = new_session(src, scope, 'synthetic')
        self.assertIn('time_field', [g['property'] for g in result['gaps']])


class ResultSemantics(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:'); self.addCleanup(self.db.close)

    def test_three_counts_filter_before_aggregate(self):
        self.db.execute('CREATE TABLE companies(id TEXT, tenant TEXT, state TEXT, industry TEXT)')
        self.db.executemany('INSERT INTO companies VALUES (?,?,?,?)', [
            ('A', 'T1', '开业', '危货'), ('A', 'T1', '开业', '危货'), (None, 'T1', '开业', '危货'),
            ('B', 'T2', '开业', '危货'), ('C', 'T1', '停业', '危货'), ('D', 'T1', '开业', '普货')])
        ds = {'name': 'companies', 'source': 'companies', 'fields': [{'name': x} for x in ['id', 'tenant', 'state', 'industry']]}
        for expr, expected in [('COUNT(*)', 3), ('COUNT(id)', 2), ('COUNT(DISTINCT id)', 1)]:
            mt = {'type': 'count', 'expr': expr, 'filters': [
                {'field': 'tenant', 'values': ['T1']}, {'field': 'state', 'values': ['开业']}],
                'extra_where': "(industry = '危货' OR industry = '客运')"}
            with self.subTest(expr=expr):
                sql, error = compile_single(mt, ds, {'companies'})
                self.assertIsNone(error)
                self.assertEqual(self.db.execute(sql).fetchone()[0], expected)
                mt['filters'][0]['values'] = ['absent']
                self.assertEqual(self.db.execute(compile_single(mt, ds, {'companies'})[0]).fetchone()[0], 0)
        # Explicit WHERE is a test condition, not implementation of authentication.

    def test_empty_graph_cannot_pass_with_database(self):
        self.assertEqual(analyze({'datasets': []}, self.db)['status'], 'not_ready')
        self.assertEqual(analyze({'datasets': []})['status'], 'not_ready')

    def test_current_metric_is_not_forced_to_invent_time_field(self):
        src = metadata(); mt = src['metrics'][0]
        mt.update(structured=True, time_requirement='current')
        self.assertFalse(any('W04' in w for w in lint(src)['warnings']))
        self.assertFalse(any(g['property'] == 'time_field' for g in gaps({'model': src})))
        mt['time_requirement'] = 'field'
        self.assertTrue(any('W04' in w for w in lint(src)['warnings']))
        self.assertTrue(any(g['property'] == 'time_field' for g in gaps({'model': src})))

    def test_raw_report_and_malformed_evidence_return_explanation(self):
        for report in ([], {'evidence': []}, {'evidence': None}):
            self.assertIn('evidence', binding_errors(report, 'unused')[0])

    def test_dictionary_preserves_scope_and_boolean_parentheses(self):
        result = fmt_metric({'expr': 'COUNT(*)', 'filters': [{'field': 'tenant', 'values': ['T1']}],
                             'extra_where': "state='开业' AND (industry='危货' OR industry='客运')"})
        self.assertIn('tenant IN ["T1"]', result)
        self.assertIn("AND (state='开业' AND (industry='危货' OR industry='客运'))", result)

    def test_reverse_path_uses_one_edge_and_detects_fanout(self):
        self.db.executescript('CREATE TABLE companies(id TEXT); INSERT INTO companies VALUES ("A");'
                              'CREATE TABLE vehicles(id TEXT, company_id TEXT);'
                              'INSERT INTO vehicles VALUES ("V1","A"),("V2","A");')
        src = metadata()
        src['query_plans'] = [{'id': 'reverse', 'metric': 'total', 'relationships': ['vehicle_company']}]
        result = analyze(src, self.db)
        self.assertEqual(len(result['relationships']), 1)
        self.assertEqual(result['queries'][0]['status'], 'fail')
        self.assertEqual(result['queries'][0]['steps'][0]['status'], 'fanout')


class WorkbenchConsumer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.service = Service(Path(self.temp.name) / 'project')
        payload = base64.b64encode(json.dumps(metadata()).encode()).decode()
        self.service.import_file({'revision': 0, 'kind': 'model', 'filename': 'model.json', 'content': payload})

    def test_generate_persist_reopen_no_duplicate_stale_rejected(self):
        before = self.service.store.read()['revision']
        first = self.service.derive({'revision': before})
        saved = self.service.store.read()
        with self.assertRaises(Conflict): self.service.derive({'revision': before})
        again = Service(self.service.store.directory)
        second = again.derive({'revision': saved['revision']})
        self.assertEqual(second['revision'], first['revision'])
        self.assertEqual(again.store.read(), saved)

    def test_mismatch_never_sends_ask(self):
        foreign = metadata(); foreign['metrics'][0]['expr'] = 'COUNT(DISTINCT id)'
        with patch('workbench.service.local_json', return_value=foreign) as call:
            result = self.service.consumer({'endpoint': 'http://127.0.0.1:9999', 'question': '企业数', 'expected': [[3]]})
        self.assertEqual(result['status'], 'model_mismatch')
        self.assertFalse(result['query_sent'])
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[1], '/api/model')

    def test_matching_projection_does_call_and_compare(self):
        with patch('workbench.service.local_json', side_effect=[metadata(), {'value': 3}]) as call:
            result = self.service.consumer({'endpoint': 'http://127.0.0.1:9999', 'question': '企业数', 'expected': [[3]]})
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(call.call_count, 2)
        self.assertEqual(call.call_args.args[1], '/api/ask')

    def test_workbench_export_contains_metric_scope(self):
        state = self.service.store.read()
        self.service.edit({'revision': state['revision'], 'kind': 'metrics', 'key': 'total',
                           'patch': {'filters': [{'field': 'id', 'values': ['A']}], 'extra_where': "id <> 'B'"}})
        with zipfile.ZipFile(io.BytesIO(self.service.export())) as z:
            text = z.read('dictionary.md').decode()
        self.assertIn('COUNT(*)', text)
        self.assertIn('id IN ["A"]', text)
        self.assertIn("id <> 'B'", text)


if __name__ == '__main__':
    unittest.main()
