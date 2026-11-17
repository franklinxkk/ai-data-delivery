"""Entry simplification must retain evidence, paging, old packages and review guards."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from test_query_control import package, fixture
import test_query_control as helper_module
from workbench.semantic_package import SemanticPackage, build_package
from workbench.query_control import semantic_fingerprint


class BriefTests(unittest.TestCase):
    def test_brief_keeps_question_control_and_explicit_unread_evidence(self):
        p, _, _ = package()
        r = p.brief()
        self.assertEqual(r['task'], p.task()['task'])
        self.assertEqual(r['control'], p.control())
        self.assertEqual(r['context'], p.task()['context'])
        self.assertFalse(r['evidence_details_included'])
        self.assertFalse(r['authorization_granted'])
        self.assertFalse(r['answer_verified'])
        self.assertEqual(r['evidence_read_by_consumer'], 'not_established')
        self.assertEqual({x['asset_id'] for x in r['evidence_index']}, set(r['context']['required_asset_ids']))
        self.assertNotIn('quote', json.dumps(r['context']['evidence']))

    def test_pagination_retains_every_required_identity_without_claiming_complete(self):
        p, _, _ = package()
        seen, offset = set(), 0
        while True:
            r = p.brief(limit=2, offset=offset)
            self.assertFalse(r['context']['request_complete'])
            self.assertTrue(r['continuation']['all_pages_required'])
            seen.update(a['id'] for a in r['context']['assets'])
            offset = r['continuation']['next_offset']
            if offset is None:
                break
        self.assertEqual(seen, set(r['continuation']['required_asset_ids']))
        self.assertNotIn('unrelated', seen)

    def test_expected_snapshot_mismatch_is_visible_at_entry(self):
        p, _, _ = package()
        r = p.brief(expected_snapshot='another-snapshot')
        self.assertEqual(r['decision'], 'needs_review')
        self.assertIn('STALE_SNAPSHOT', [b['code'] for b in r['control']['blockers']])
        self.assertFalse(r['authorization_granted'])

    def test_knowledge_only_package_does_not_invent_question(self):
        rows, _ = fixture()
        raw, _ = build_package(rows, [], project_id='legacy', revision=1, asset_ids=['metric'])
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            p = SemanticPackage({n: z.read(n) for n in z.namelist()})
        r = p.brief()
        self.assertEqual(r['decision'], 'needs_question')
        self.assertNotIn('task', r)
        self.assertEqual(r['control']['blockers'][0]['code'], 'NO_CONTROL')

    def test_cli_consumes_actual_zip_and_rejects_invalid_paging(self):
        _, _, raw = package()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'question.zip'
            path.write_bytes(raw)
            cmd = [sys.executable, '-X', 'utf8', str(Path(__file__).resolve().parents[1] / 'scripts/semantic_read.py'), '--package', str(path), 'brief']
            r = subprocess.run(cmd, text=True, capture_output=True, encoding='utf-8')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(json.loads(r.stdout)['authorization_granted'])
            invalid = subprocess.run(cmd + ['--limit', '0'], text=True, capture_output=True, encoding='utf-8')
            self.assertNotEqual(invalid.returncode, 0)
            self.assertNotIn('Traceback', invalid.stderr)

    def test_search_uses_same_width_case_and_space_normalization_as_discovery(self):
        rows, task = fixture()
        rows[-2]['aliases'] = ['ＦＬＥＥＴ　ＲＥＡＤＹ']
        p, _, _ = package(rows=rows, task=task)
        r = p.search('fleet ready')
        self.assertEqual(r['matches'][0]['asset']['id'], 'metric')
        self.assertEqual(r['matches'][0]['match_reason'], 'name_or_alias_exact')
        self.assertEqual(p.resolve('fleet ready')['status'], 'needs_selection')

    def test_alignment_review_is_explicit_preserves_values_and_invalidates_observations(self):
        helper = helper_module.QueryControlTests(methodName='runTest')
        self.addCleanup(helper.doCleanups)
        service, call, scenario = helper.service_fixture()
        checked = service.scenario_check({'scenario_id': scenario['id']})
        call('scenario_assess', scenario_id=scenario['id'], case_id='count',
             basis_fingerprint=checked['acceptance']['basis_fingerprint'], outcome='passed',
             actor='synthetic tester', observed='2', evidence='synthetic independent fixture')
        metric = copy.deepcopy(next(a for a in service.state()['assets'] if a['id'] == 'metric'))
        metric['properties']['time_scope'] = 'reviewed synthetic window'
        plan = metric['properties']['query_plan']
        plan['time_scope'] = metric['properties']['time_scope']
        plan['filters'] = [{'field_id': 'status', 'op': 'eq', 'value': False}, {'field_id': 'status', 'op': 'is_null', 'value': None}]
        with self.assertRaises(ValueError):
            call('edit', asset=metric, confirm=True, review_query_plan=True)
        call('edit', asset=metric, confirm=True)
        stale = service.scenario_check({'scenario_id': scenario['id']})
        self.assertIn('PLAN_REVIEW_STALE', [b['code'] for b in stale['query_control']['blockers']])
        call('edit', asset=metric, confirm=True, review_query_plan=True, plan_review_reason='Synthetic review: checked this declared window against the provided meaning')
        current = next(a for a in service.state()['assets'] if a['id'] == 'metric')
        self.assertEqual(current['properties']['query_plan']['semantic_fingerprint'], semantic_fingerprint(current))
        self.assertIs(current['properties']['query_plan']['filters'][0]['value'], False)
        self.assertIsNone(current['properties']['query_plan']['filters'][1]['value'])
        self.assertEqual(current['evidence'][-1]['type'], 'manual')
        self.assertEqual(service.scenario_check({'scenario_id': scenario['id']})['acceptance']['status'], 'stale')


if __name__ == '__main__':
    unittest.main()
