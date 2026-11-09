"""The authored quickstart uses the real intake/review/publish boundaries."""
import copy
import tempfile
import unittest
import uuid
from pathlib import Path

from scripts.start import prepare
from workbench.semantic_package import PackageError, read_package


class BilingualQuickstartTests(unittest.TestCase):
    def test_both_languages_require_review_and_deliver_same_business_scope(self):
        for language in ('en', 'zh'):
            with self.subTest(language=language), tempfile.TemporaryDirectory(prefix='双语 example ') as directory:
                project = Path(directory) / 'project'
                service, _ = prepare(project, example='equipment', language=language)
                knowledge = service.knowledge
                def call(method, **payload):
                    return getattr(knowledge, method)({'revision': service.store.read()['revision'],
                        'operation_id': uuid.uuid4().hex, **payload})['result']
                state = knowledge.state()
                self.assertEqual(state['assets'], [])
                self.assertEqual(len(state['sources']), 2)
                with self.assertRaisesRegex(ValueError, 'DDL'):
                    call('example')
                self.assertEqual(knowledge.state()['assets'], [])
                call('review', group_id=state['groups'][0]['id'], action='accept', reason='Synthetic test only')
                proposal = call('example')
                self.assertEqual(len(knowledge.state()['assets']), 5)
                call('review', group_id=proposal['group_ids'][0], action='accept', reason='Synthetic test only')
                state = knowledge.state()
                self.assertEqual(len(state['assets']), 12)
                self.assertFalse([p for p in state['problems'] if p['kind'] == 'identity_review'],
                    'A business object and its physical table are not merge-compatible identities')
                published = call('publish', asset_ids=['demo.available'], draft=False)
                package = Path(directory) / 'equipment.zip'
                package.write_bytes(knowledge.download(published['snapshot_id']))
                reader = read_package(package)
                context = reader.context(['demo.available'], intent='query')
                self.assertTrue(context['request_complete'])
                self.assertTrue({'demo.scope', 'demo.eligible', 'demo.mapping', 'demo.equipment', 'demo.lab'} <= set(context['required_asset_ids']))
                self.assertTrue({'DECLARED_KNOWLEDGE_GAP', 'NO_DATA_CONNECTOR'} <= {g['code'] for g in context['gaps']})
                before = copy.deepcopy(state['assets'])
                reopened, _ = prepare(project, language='zh' if language == 'en' else 'en')
                self.assertEqual(reopened.knowledge.state()['assets'], before)
                with self.assertRaises(ValueError):
                    prepare(project, example='equipment', language=language)
                # Same-kind collisions remain actionable; search ambiguity is not removed.
                duplicate = copy.deepcopy(next(a for a in before if a['id'] == 'demo.equipment'))
                duplicate['id'] = 'demo.other_equipment'
                call('edit', asset=duplicate, confirm=True)
                self.assertTrue(any(p['kind'] == 'identity_review' for p in knowledge.state()['problems']))
                with self.assertRaises(PackageError):
                    call('publish', draft=False)

    def test_modified_fixture_does_not_receive_canned_business_proposals(self):
        with tempfile.TemporaryDirectory() as directory:
            service, _ = prepare(Path(directory) / 'project', example='equipment')
            state = service.knowledge.state()
            source = next(s for s in state['sources'] if s['name'].endswith('.txt'))
            service.knowledge.import_material({'revision': state['revision'], 'operation_id': uuid.uuid4().hex,
                'filename': source['name'], 'source_id': source['id'], 'text': 'Different policy: allow other labs.'})
            with self.assertRaisesRegex(ValueError, 'material changed'):
                service.knowledge.example({'revision': service.store.read()['revision'], 'operation_id': uuid.uuid4().hex})
            self.assertEqual(service.knowledge.state()['assets'], [])


if __name__ == '__main__':
    unittest.main()
