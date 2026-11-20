import copy
import unittest

from workbench.authoring_inspect import inspect_model
from workbench.semantic_package import PackageError


def asset(aid, kind, refs=(), **extra):
    return {'id': aid, 'kind': kind, 'name': aid, 'status': 'confirmed',
            'refs': list(refs), 'properties': {}, 'evidence': [], **extra}


class AuthoringInspectTests(unittest.TestCase):
    def test_count_can_repeat_declared_business_grain(self):
        grain = ['hazard_id']
        plan = {'column_ids': grain, 'grain_ids': grain, 'aggregation': {'function': 'count', 'field_id': 'hazard_id'}}
        assets = [asset('hazard_id', 'field'), asset('closed_cases', 'metric', properties={'query_plan':plan})]
        def reviews():
            return [i for i in inspect_model(assets, [], asset_ids=['closed_cases'])['issues']
                    if i['code'] == 'COUNT_GRAIN_REVIEW']
        self.assertEqual(reviews()[0]['grain_ids'], grain)
        plan['aggregation']['function'] = 'count_distinct'
        self.assertEqual(reviews(), [])
        grain.append('tenant_id')
        self.assertEqual(len(reviews()), 1)

    def graph(self):
        return [asset('contracts', 'dataset'), asset('balances', 'dataset'),
                asset('contract_id', 'field', ['contracts'], properties={'column': 'id'}),
                asset('balance_contract_id', 'field', ['balances'], properties={'column': 'contract_id'}),
                asset('amount', 'field', ['balances'], properties={'column': 'amount'}),
                asset('business', 'entity'), asset('value', 'attribute', ['business', 'amount']),
                asset('mapping', 'mapping', **{'from': 'value', 'to': 'amount'}),
                asset('fk', 'relation', relation_type='physical_fk', **{'from': 'balances', 'to': 'contracts',
                      'properties': {'from_fields': ['contract_id'], 'to_fields': ['id']}}),
                asset('metric', 'metric', ['value', 'contract_id'])]

    def test_detects_omitted_mappings_and_cross_table_links_without_mutating(self):
        model = self.graph()
        original = copy.deepcopy(model)
        report = inspect_model(model, [], asset_ids=['metric'])
        codes = {x['code'] for x in report['issues']}
        self.assertTrue({'MAPPINGS_OUTSIDE_CONTEXT', 'RELATIONS_OUTSIDE_CONTEXT',
                         'MULTI_DATASET_RELATION_REVIEW'} <= codes)
        self.assertNotIn('mapping', report['required_asset_ids'])
        self.assertEqual(model, original)
        self.assertEqual(report['business_coverage'], 'not_verified')

    def test_scoped_model_includes_keys_and_relations_only_when_declared(self):
        model = self.graph()
        model[-1]['refs'] += ['mapping', 'fk']
        report = inspect_model(model, [], asset_ids=['metric'])
        keys = next(x for x in report['issues'] if x['code'] == 'JOIN_KEYS_OUTSIDE_CONTEXT')
        self.assertEqual(keys['asset_ids'], ['balance_contract_id'])
        model[-1]['refs'].append('balance_contract_id')
        fixed = inspect_model(model, [], asset_ids=['metric'])
        self.assertEqual(fixed['issues'], [])
        self.assertEqual(fixed['status'], 'ready_for_review')

    def test_draft_missing_and_untracked_sql_are_disclosed(self):
        model = [asset('m', 'metric', ['absent'], status='draft', properties={'host_readonly_sql': 'SELECT private FROM secret'})]
        result = inspect_model(model, [], asset_ids=['m'])
        self.assertEqual({x['code'] for x in result['issues']},
                         {'MISSING_DEPENDENCY', 'UNCONFIRMED_ASSETS', 'UNTRACKED_SQL_TEXT'})
        self.assertEqual(result['blockers'], 2)

    def test_retired_unrelated_relation_not_suggested_and_unknown_id_rejected(self):
        model = self.graph()
        model[-2]['status'] = 'retired'
        self.assertNotIn('RELATIONS_OUTSIDE_CONTEXT', {x['code'] for x in inspect_model(model, [], asset_ids=['metric'])['issues']})
        with self.assertRaises(PackageError):
            inspect_model(model, [], asset_ids=['guessed'])

    def test_retained_quote_does_not_clear_new_scope_or_confirm(self):
        model = [asset('m', 'metric', status='needs_review', evidence=[{'source_id': 's', 'revision': 1, 'quote': 'Count trips.'}])]
        sources = [{'id': 's', 'name': 'policy', 'current_revision': 2,
                    'revisions': [{'revision': 2, 'parsed': {'fragments': [{'text': 'Count trips. Exclude cancelled.', 'location': {'line': 3}}]}}]}]
        result = inspect_model(model, sources, asset_ids=['m'])
        row = result['changed_evidence'][0]
        self.assertTrue(row['quote_still_present'])
        self.assertEqual(row['meaning_unchanged'], 'not_established')
        self.assertEqual(model[0]['status'], 'needs_review')

    def test_declared_join_key_without_field_asset_is_not_silent(self):
        model = self.graph()
        model[-1]['refs'] += ['mapping', 'fk']
        model = [a for a in model if a['id'] != 'balance_contract_id']
        report = inspect_model(model, [], asset_ids=['metric'])
        gap = next(i for i in report['issues'] if i['code'] == 'UNRESOLVED_JOIN_KEY')
        self.assertEqual((gap['dataset_id'], gap['column']), ('balances', 'contract_id'))

    def test_duplicate_identity_rejected_and_empty_not_ready(self):
        with self.assertRaises(PackageError):
            inspect_model([asset('a', 'entity', status='draft'), asset('a', 'entity')], [])
        self.assertEqual(inspect_model([], [])['status'], 'empty')

    def test_copied_policy_does_not_masquerade_as_distinct_metric_properties(self):
        model = [asset('m', 'metric', properties=dict.fromkeys(('inclusions', 'exclusions', 'time_scope'), 'Whole policy.'))]
        result = inspect_model(model, [], asset_ids=['m'])
        self.assertIn('UNDISTINGUISHED_METRIC_PROPERTIES', {i['code'] for i in result['issues']})
        model[0]['properties'].update(inclusions='completed', exclusions='cancelled', time_scope='July')
        self.assertEqual(inspect_model(model, [], asset_ids=['m'])['issues'], [])

    def test_imported_policy_copied_to_manual_keeps_provenance_question_visible(self):
        text = 'Completed journeys count only once within the given reporting period.'
        sources = [{'id': 's', 'current_revision': 1,
                    'revisions': [{'revision': 1, 'parsed': {'fragments': [{'text': text}]}}]}]
        model = [asset('m', 'metric', evidence=[{'type': 'manual', 'quote': text, 'actor': 'local'}])]
        report = inspect_model(model, sources, asset_ids=['m'])
        issue = next(x for x in report['issues'] if x['code'] == 'IMPORTED_TEXT_AS_MANUAL')
        self.assertEqual(issue['candidate_source_ids'], ['s'])
        self.assertFalse(issue['equivalence_verified'])
        self.assertEqual(model[0]['evidence'][0]['type'], 'manual')
        model[0]['evidence'][0]['quote'] = 'An independent operator assertion.'
        self.assertEqual(inspect_model(model, sources, asset_ids=['m'])['issues'], [])


if __name__ == '__main__':
    unittest.main()
