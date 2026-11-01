"""Declared fields and aggregate meaning must survive lint and schema drift."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_model import Reporter, check_metrics, drift_report


def model():
    return {
        "datasets": [{"name": "orders", "source": "orders", "grain": "one order",
                      "primary_key": "id",
                      "fields": [{"name": "id", "role": "pk"},
                                 {"name": "amount", "role": "measure"},
                                 {"name": "status", "role": "dim"},
                                 {"name": "units", "role": "measure"}]}],
        "metrics": [{"id": "paid_amount", "dataset": "orders", "structured": True,
                     "type": "sum", "expr": "SUM(amount)", "time_requirement": "current",
                     "synonyms": ["paid amount", "paid sales", "paid revenue"],
                     "filters": [{"field": "status", "values": ["paid"]}]}],
    }


def lint(value):
    report = Reporter()
    check_metrics(value, report, {d["name"]: d for d in value["datasets"]})
    return report


def drop_field(value, name):
    value["datasets"][0]["fields"] = [f for f in value["datasets"][0]["fields"]
                                      if f["name"] != name]


class MetricDependencyLint(unittest.TestCase):
    def test_valid_single_table_metric(self):
        report = lint(model())
        self.assertEqual(report.errors, [])
        self.assertFalse(any("W19" in item for item in report.warnings))

    def test_deleted_aggregate_and_filter_fields_are_errors(self):
        for field in ("amount", "status"):
            with self.subTest(field=field):
                current = model()
                drop_field(current, field)
                self.assertTrue(any("E19" in item and field in item
                                    for item in lint(current).errors))

    def test_extra_where_and_ratio_dependencies_are_checked(self):
        for changes, missing in (({"extra_where": "missing_flag = 1"}, "missing_flag"),
                                 ({"type": "ratio", "expr": None,
                                   "numerator": {"expr": "SUM(amount)"},
                                   "denominator": {"expr": "SUM(missing_units)"}}, "missing_units")):
            with self.subTest(missing=missing):
                current = model()
                current["metrics"][0].update(changes)
                self.assertTrue(any("E19" in item and missing in item
                                    for item in lint(current).errors))

    def test_scalar_max_and_unaggregated_field_cannot_pass_lint(self):
        for expression in ("MAX(amount, 0)", "SUM(amount) + id"):
            with self.subTest(expression=expression):
                current = model()
                current["metrics"][0]["expr"] = expression
                self.assertTrue(any("E19" in item for item in lint(current).errors))

    def test_string_literal_is_not_a_field_reference(self):
        current = model()
        current["metrics"][0]["expr"] = "SUM(CASE WHEN status = 'missing_field' THEN amount ELSE 0 END)"
        self.assertEqual(lint(current).errors, [])

    def test_external_engine_and_join_are_unverified_not_invalid(self):
        for changes in ({"expr": "MEDIAN(amount)"},
                        {"join_path": ["orders", "customers"], "expr": "SUM(customers.amount)"}):
            with self.subTest(changes=changes):
                current = model()
                current["metrics"][0].update(changes)
                report = lint(current)
                self.assertEqual(report.errors, [])
                self.assertTrue(any("W19" in item for item in report.warnings))

    def test_legacy_metric_is_not_forced_into_local_compiler(self):
        current = model()
        current["metrics"][0].update(structured=False, expr="历史口径待落地")
        report = lint(current)
        self.assertEqual(report.errors, [])
        self.assertFalse(any("W19" in item for item in report.warnings))


class MetricDependencyDrift(unittest.TestCase):
    def test_removed_expression_and_filter_fields_are_breaking(self):
        baseline = model()
        for field in ("amount", "status"):
            with self.subTest(field=field):
                current = copy.deepcopy(baseline)
                drop_field(current, field)
                report = drift_report(current, baseline)
                self.assertTrue(any(field in item["reason"] and "paid_amount" in item["reason"]
                                    for item in report["breaking"]))

    def test_removed_extra_where_and_denominator_fields_are_breaking(self):
        for changes in ({"extra_where": "units > 0"},
                        {"type": "ratio", "expr": None,
                         "numerator": {"expr": "SUM(amount)"},
                         "denominator": {"expr": "SUM(units)"}}):
            with self.subTest(changes=changes):
                baseline = model()
                baseline["metrics"][0].update(changes)
                current = copy.deepcopy(baseline)
                drop_field(current, "units")
                self.assertTrue(any("units" in item["reason"]
                                    for item in drift_report(current, baseline)["breaking"]))

    def test_removed_unused_field_is_not_breaking(self):
        baseline = model()
        current = copy.deepcopy(baseline)
        drop_field(current, "units")
        self.assertEqual(drift_report(current, baseline)["breaking"], [])

    def test_revised_metric_removes_dependency_and_literal_is_ignored(self):
        baseline = model()
        current = copy.deepcopy(baseline)
        drop_field(current, "amount")
        current["metrics"][0]["expr"] = "SUM(CASE WHEN status = 'amount' THEN units ELSE 0 END)"
        self.assertEqual(lint(current).errors, [])
        self.assertEqual(drift_report(current, baseline)["breaking"], [])

    def test_new_field_in_current_expression_does_not_hide_removed_field(self):
        baseline = model()
        current = copy.deepcopy(baseline)
        drop_field(current, "amount")
        current["datasets"][0]["fields"].append({"name": "discount", "role": "measure"})
        current["metrics"][0]["expr"] = "SUM(amount - discount)"
        self.assertTrue(any("amount" in item["reason"]
                            for item in drift_report(current, baseline)["breaking"]))


if __name__ == "__main__":
    unittest.main()
