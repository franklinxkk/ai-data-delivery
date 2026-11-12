"""Real domain counterexamples through import, review, publish and offline read."""
import copy
from pathlib import Path
import tempfile
import unittest

from maintainer.check_cross_domain import DOMAINS, load_fixture, observations, run_domain


class CrossDomainTests(unittest.TestCase):
    def test_four_domains_follow_public_review_and_independent_reader(self):
        with tempfile.TemporaryDirectory(prefix="cross-domain-") as directory:
            for domain in DOMAINS:
                with self.subTest(domain=domain):
                    result = run_domain(domain, Path(directory) / domain)
                    self.assertEqual(result["cases_passed"], 8)
                    self.assertTrue(result["independent_cli"])

    def test_finance_oracle_refuses_conflicting_contract_values(self):
        fixture = copy.deepcopy(load_fixture("finance"))
        fixture["observations"]["joined_contract_rows"][1]["amount"] = "101"
        with self.assertRaisesRegex(AssertionError, "Conflicting balance"):
            observations(fixture)

    def test_employment_oracle_does_not_silently_choose_overlapping_employer(self):
        fixture = copy.deepcopy(load_fixture("traffic"))
        fixture["observations"]["employment"][0]["to"] = None
        with self.assertRaisesRegex(AssertionError, "one employer"):
            observations(fixture)


if __name__ == "__main__":
    unittest.main()
