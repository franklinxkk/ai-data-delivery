"""Independent reviewer field baselines; never imported by the authoring generator."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from maintainer.check_industry_handoff import FIXTURES, run_case

# Supplied separately by the root reviewer from original industry questions.
INDEPENDENT_FIELDS = {
    'finance': 'contract.id contract.tenant contract.currency balance.contract_id balance.as_of balance.version balance.amount'.split(),
    'energy': 'meter.id meter.tenant meter.multiplier meter.rollover reading.meter_id reading.day reading.value meter_event.meter_id meter_event.kind meter_event.count'.split(),
    'hospitality': 'room.id room.tenant room_day.room_id room_day.day room_day.sellable stay.room_id stay.check_in stay.check_out stay.state stay.complimentary'.split(),
}
REMOVALS = {'finance': 'balance.amount', 'energy': 'reading.value', 'hospitality': 'stay.check_out'}


def independent_review(result):
    delivered = set(result['context']['required_asset_ids'])
    expected = {'field.' + f for f in INDEPENDENT_FIELDS[result['industry']]}
    missing = sorted(expected - delivered)
    if missing:
        raise AssertionError('Independent business review missing required fields: ' + ', '.join(missing))
    return {'validation_scope': 'independent_minimum_field_review', 'passed': True,
            'required_field_count': len(expected), 'business_correctness': 'not_proven'}


class IndustryHandoffTests(unittest.TestCase):
    def test_three_independent_field_baselines_and_omission_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in INDEPENDENT_FIELDS:
                with self.subTest(industry=name):
                    result = run_case(name, root / 'normal')
                    self.assertTrue(result['passed'])
                    self.assertEqual(result['validation_scope'], 'configuration_delivery_only')
                    self.assertTrue(independent_review(result)['passed'])
                    self.assertEqual(result['source_revision'], 2)
                    self.assertEqual(result['unknown_status'], 'unknown')
                    self.assertEqual(result['context']['status'], 'ok')
                    self.assertTrue(result['context']['request_complete'])
                    fixture = root / 'mutated' / name
                    shutil.copytree(FIXTURES / name, fixture)
                    brief_path = fixture / 'brief.json'
                    brief = json.loads(brief_path.read_text(encoding='utf-8'))
                    brief['handoff']['required_fields'].remove(REMOVALS[name])
                    brief_path.write_text(json.dumps(brief, ensure_ascii=False), encoding='utf-8')
                    shrunk = run_case(name, root / 'negative', fixture_root=root / 'mutated')
                    self.assertTrue(shrunk['passed'])  # Configuration closure alone is insufficient.
                    with self.assertRaisesRegex(AssertionError, REMOVALS[name]):
                        independent_review(shrunk)


if __name__ == '__main__': unittest.main()
