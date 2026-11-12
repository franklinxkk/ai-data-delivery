import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.ontology_export import main
from workbench.ogs_export import NAMESPACE, audit_roundtrip, export_ogs
from workbench.semantic_package import PackageError, build_package


def asset(aid, kind="entity", **changes):
    value = {"id": aid, "kind": kind, "name": "示例 " + aid, "definition": "Synthetic fixture definition " + aid,
             "domain": "synthetic", "scope": {"tenant": "test", "active": False, "partition": 0},
             "status": "confirmed", "properties": {}, "refs": [], "aliases": [],
             "evidence": [{"type": "manual", "actor": "synthetic-test-author", "created": "2026-11-12T00:00:00Z",
                           "quote": "Explicit synthetic test fixture, not real business policy."}]}
    value.update(changes)
    return value


def relation(aid, left, right, relation_type="business"):
    return asset(aid, "relation", **{"from": left, "to": right, "predicate": aid, "relation_type": relation_type})


class OGSExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ogs-export-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def package(self, assets, **kwargs):
        raw, _ = build_package(assets, [], project_id="test-ogs", revision=2, **kwargs)
        path = self.directory / "semantic.zip"
        path.write_bytes(raw)
        return path

    def test_entities_explicit_relationships_and_owned_attributes_project(self):
        assets = [asset("enterprise"), asset("vehicle"),
                  asset("vin", "attribute", properties={"value_type": "string"}),
                  relation("operates", "enterprise", "vehicle"),
                  relation("has_vin", "vehicle", "vin", "has_attribute")]
        model, report = export_ogs(self.package(assets))
        self.assertEqual(set(model["nodes"]), {"enterprise", "vehicle"})
        self.assertEqual(set(model["relationships"]), {"operates"})
        self.assertEqual(model["relationships"]["operates"]["from"], {"node": "enterprise"})
        self.assertEqual(model["relationships"]["operates"]["to"], {"node": "vehicle"})
        props = list(model["nodes"]["vehicle"]["properties"].values())
        self.assertEqual(props[0]["type"], "STRING")
        property_id = next(iter(model["nodes"]["vehicle"]["properties"]))
        self.assertEqual(props[0]["name"], property_id)
        self.assertEqual(report["native_property_placements"], 1)
        self.assertEqual(report["identifier_policy"], "new_design_identifier")
        self.assertFalse(report["execution"]["database_import_ready"])
        self.assertIn("示例 vehicle", model["nodes"]["vehicle"]["aliases"])

    def test_no_fake_metric_rule_fk_or_classification_database_semantics(self):
        values = [asset("person"), asset("employee"), asset("table_a", "dataset"), asset("table_b", "dataset"),
                  relation("subtype", "employee", "person", "is_a"),
                  relation("fk", "table_a", "table_b", "physical_fk"),
                  asset("rule", "rule", properties={"condition": "Test only", "requirement": "No automatic approval"}),
                  asset("metric", "metric", properties={"unit": "人", "grain": "person", "inclusions": "test",
                      "exclusions": "others", "time_scope": "declared date", "expression": "COUNT DISTINCT", "currency": "unknown"})]
        # Draft is explicit: physical FK fixture has no column mapping yet.
        model, report = export_ogs(self.package(values, draft=True, include_execution=True))
        self.assertEqual(set(model["nodes"]), {"person", "employee"})
        self.assertEqual(model["relationships"], {})
        recovered = json.loads(model["extensions"]["custom"][NAMESPACE]["model_json"])
        recovered_ids = {item["id"] for item in recovered["assets"]}
        self.assertEqual(recovered_ids, {item["id"] for item in values})
        for node in model["nodes"].values():
            self.assertNotIn("constraints", node)
        fk = next(item for item in report["assets"] if item["asset_id"] == "fk")
        self.assertEqual(fk["reason"], "physical_fk_not_business")

    def test_opaque_json_preserves_large_numbers_boolean_zero_and_null(self):
        value = asset("loan", scope={"account": 900719925474099312345, "zero": 0, "false": False, "none": None},
                      properties={"amount": 1.0, "identity": ["tenant", "source", "original_id"]})
        model, report = export_ogs(self.package([value]))
        raw = model["extensions"]["custom"][NAMESPACE]["model_json"]
        self.assertIsInstance(raw, str)
        restored = json.loads(raw)["assets"][0]
        self.assertEqual(restored["scope"], value["scope"])
        self.assertIs(type(restored["properties"]["amount"]), float)
        self.assertTrue(audit_roundtrip(model, json.loads(json.dumps(model)))["same_export_preserved"])

    def test_unconfirmed_nodes_and_relations_are_not_native_confirmed_design(self):
        assets = [asset("approved"), asset("pending", status="draft"), relation("possible", "approved", "pending")]
        model, report = export_ogs(self.package(assets, draft=True))
        self.assertEqual(set(model["nodes"]), {"approved"})
        self.assertEqual(model["relationships"], {})
        self.assertTrue(report["package_draft"])

    def test_decimal_type_not_silently_float_and_long_text_kept_in_companion(self):
        long_definition = "长" * 1500
        assets = [asset("contract", definition=long_definition),
                  asset("amount", "attribute", properties={"value_type": "decimal(20,2)"}),
                  relation("amount_on_contract", "contract", "amount", "has_attribute")]
        model, report = export_ogs(self.package(assets))
        prop = next(iter(model["nodes"]["contract"]["properties"].values()))
        self.assertNotIn("type", prop)
        self.assertEqual(len(model["nodes"]["contract"]["description"]), 1024)
        self.assertIn(long_definition, model["extensions"]["custom"][NAMESPACE]["model_json"])
        self.assertEqual({item["code"] for item in report["warnings"]},
                         {"PROPERTY_TYPE_UNMAPPED", "NATIVE_DESCRIPTION_TRUNCATED"})

    def test_roundtrip_label_normalisation_tolerated_but_reverse_relationship_detected(self):
        model, _ = export_ogs(self.package([asset("a"), asset("b"), relation("r", "a", "b")]))
        actual = copy.deepcopy(model)
        for node in actual["nodes"].values():
            node["labels"] = {"identifier": node.pop("label"), "implied": [], "optional": []}
        self.assertEqual(audit_roundtrip(model, actual)["status"], "preserved")
        actual["relationships"]["r"]["from"]["node"] = "b"
        self.assertEqual(audit_roundtrip(model, actual)["status"], "changed_or_lost")
        self.assertTrue(audit_roundtrip(model, actual)["semantic_model_preserved"])

    def test_lost_extension_detected_even_when_all_native_nodes_survive(self):
        model, _ = export_ogs(self.package([asset("a")]))
        actual = copy.deepcopy(model)
        actual.pop("extensions")
        result = audit_roundtrip(model, actual)
        self.assertTrue(result["native_projection_preserved"])
        self.assertFalse(result["semantic_model_preserved"])
        self.assertFalse(result["source_evidence_preserved"])
        self.assertFalse(result["same_export_preserved"])

    def test_modified_payload_invalid_even_if_native_shape_unchanged(self):
        model, _ = export_ogs(self.package([asset("a")]))
        actual = copy.deepcopy(model)
        actual["extensions"]["custom"][NAMESPACE]["model_json"] += " "
        result = audit_roundtrip(model, actual)
        self.assertFalse(result["companion_integrity"]["model"])
        self.assertFalse(result["semantic_model_preserved"])
        actual["extensions"]["custom"][NAMESPACE]["format"] = "other"
        self.assertFalse(audit_roundtrip(model, actual)["companion_present"])

    def test_native_additions_detected_and_corrupt_original_rejected(self):
        model, _ = export_ogs(self.package([asset("a")]))
        actual = copy.deepcopy(model)
        actual["nodes"]["a"]["properties"] = {"injected": {"type": "STRING"}}
        self.assertFalse(audit_roundtrip(model, actual)["native_projection_preserved"])
        model["extensions"]["custom"][NAMESPACE]["sources_sha256"] = "bad"
        with self.assertRaises(PackageError):
            audit_roundtrip(model, actual)

    def test_new_labels_endpoint_counts_and_attribute_types_change_meaning(self):
        values = [asset("a"), asset("b"), relation("r", "a", "b"),
                  asset("attr", "attribute", properties={"value_type": "unspecified"}),
                  relation("owns_attr", "a", "attr", "has_attribute")]
        model, _ = export_ogs(self.package(values))
        for case in ("implied", "optional", "min_count", "property_type", "empty_node"):
            with self.subTest(case=case):
                actual = copy.deepcopy(model)
                if case in {"implied", "optional"}:
                    actual["nodes"]["a"]["labels"] = {case: ["Unexpected"]}
                elif case == "min_count":
                    actual["relationships"]["r"]["from"]["min_count"] = 1
                elif case == "property_type":
                    next(iter(actual["nodes"]["a"]["properties"].values()))["type"] = "STRING"
                else:
                    actual["nodes"]["properties"] = {}
                self.assertFalse(audit_roundtrip(model, actual)["same_export_preserved"])
        actual = copy.deepcopy(model)
        next(iter(actual["nodes"]["a"]["properties"].values()))["type"] = "ANY"
        actual["relationships"]["r"]["from"]["min_count"] = None
        self.assertTrue(audit_roundtrip(model, actual)["same_export_preserved"])

    def test_explicit_false_and_zero_constraints_are_not_dropped(self):
        model, _ = export_ogs(self.package([asset("a")]))
        model["nodes"]["a"]["properties"] = {"flag": {"type": "BOOLEAN", "must_exist": False}}
        actual = copy.deepcopy(model)
        actual["nodes"]["a"]["properties"]["flag"].pop("must_exist")
        self.assertFalse(audit_roundtrip(model, actual)["same_export_preserved"])

    def test_header_changes_and_conflicting_label_shorthand_are_visible(self):
        model, _ = export_ogs(self.package([asset("a")]))
        for field in ("schema", "id", "version", "conflicting_label"):
            actual = copy.deepcopy(model)
            if field == "conflicting_label":
                actual["nodes"]["a"]["labels"] = {"identifier": "SomethingElse"}
            else:
                actual[field] = "changed"
            self.assertFalse(audit_roundtrip(model, actual)["same_export_preserved"])

    def test_export_is_deterministic_and_original_package_unchanged(self):
        path = self.package([asset("a.b"), asset("a_b")])
        before = path.read_bytes()
        first, second = export_ogs(path), export_ogs(path)
        self.assertEqual(first, second)
        self.assertNotEqual(first[0]["nodes"]["a.b"]["label"], first[0]["nodes"]["a_b"]["label"])
        self.assertEqual(path.read_bytes(), before)

    def test_cli_exports_both_and_refuses_existing_report_without_partial_model(self):
        path = self.package([asset("a")])
        out, report = self.directory / "model.json", self.directory / "report.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--package", str(path), "export", "--out", str(out), "--report", str(report)]), 0)
        before = report.read_bytes()
        second = self.directory / "second.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--package", str(path), "export", "--out", str(second), "--report", str(report)]), 2)
        self.assertFalse(second.exists())
        self.assertEqual(report.read_bytes(), before)
        actual = json.loads(out.read_text(encoding="utf-8"))
        actual.pop("extensions")
        returned = self.directory / "returned.json"
        returned.write_text(json.dumps(actual), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["audit", "--original", str(out), "--returned", str(returned)]), 1)

    def test_cli_rejects_duplicate_json_keys_and_colliding_outputs(self):
        path = self.package([asset("a")])
        target = self.directory / "target.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--package", str(path), "export", "--out", str(target), "--report", str(target)]), 2)
        self.assertFalse(target.exists())
        target.write_text('{"nodes":{},"nodes":{}}', encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["audit", "--original", str(target), "--returned", str(target)]), 2)

    def test_audit_invalid_original_headers_return_structured_cli_error(self):
        model, _ = export_ogs(self.package([asset("a")]))
        original, returned = self.directory / "original.json", self.directory / "returned.json"
        returned.write_text(json.dumps(model), encoding="utf-8")
        for field in ("schema", "version", "id", "snapshot_id"):
            for invalid in (None, "", 7):
                with self.subTest(field=field, invalid=invalid):
                    bad = copy.deepcopy(model)
                    container = bad["extensions"]["custom"][NAMESPACE] if field == "snapshot_id" else bad
                    if invalid is None:
                        container.pop(field)
                    else:
                        container[field] = invalid
                    original.write_text(json.dumps(bad), encoding="utf-8")
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        code = main(["audit", "--original", str(original), "--returned", str(returned)])
                    self.assertEqual(code, 2)
                    result = json.loads(output.getvalue())
                    self.assertEqual(result["error"]["code"], "INVALID_OGS_EXPORT")
                    self.assertEqual(result["error"]["field"], field)


if __name__ == "__main__":
    unittest.main()
