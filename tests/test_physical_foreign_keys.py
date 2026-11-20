"""Verification of physical join keys across authoring and scoped handoff."""
import base64
import copy
import io
import json
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile

from scripts.ingest_ddl import qualified_identifier
from tests.test_semantic_package import asset
from workbench.knowledge import KnowledgeService
from workbench.store import Store
from workbench.authoring_inspect import inspect_model
from workbench.semantic_package import (
    PackageError, SemanticPackage, _json, _sha, build_package, legacy_ddl_name, validate_semantic_assets,
)


class PhysicalForeignKeyTests(unittest.TestCase):
    def setUp(self):
        self.left = asset("child", "dataset")
        self.right = asset("parent", "dataset")
        self.fk = asset("child_parent", "relation", **{"from": "child", "to": "parent"},
                        relation_type="physical_fk", predicate="references",
                        properties={"from_fields": ["tenant", "parent_id"], "to_fields": ["tenant", "id"]})
        self.tables = [self.left, self.right]
        self.fields = [asset(f"{table}_{column}", "field", refs=[table], properties={"column": column})
                       for table, column in [("child", "tenant"), ("child", "parent_id"),
                                             ("parent", "tenant"), ("parent", "id"), ("parent", "unrelated")]]
        self.assets = self.tables + [self.fk] + self.fields

    def package(self, *, assets=None, sources=(), draft=False):
        content, manifest = build_package(self.assets if assets is None else assets, list(sources),
                                          project_id="fk", revision=1, draft=draft,
                                          asset_ids=[self.fk["id"]])
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            return {name: z.read(name) for name in z.namelist()}, manifest

    def test_scoped_composite_keeps_only_matching_field_assets(self):
        entries, manifest = self.package()
        self.assertEqual(set(manifest["scope"]["dependency_ids"]),
                         {"child", "parent", "child_tenant", "child_parent_id", "parent_tenant", "parent_id"})
        self.assertEqual(SemanticPackage(entries).verify()["issues"], [])

    def test_incomplete_manual_column_inventory_discloses_unknown(self):
        assets = self.tables + [self.fk, self.fields[0]]
        validate_semantic_assets(assets)
        entries, manifest = self.package(assets=assets)
        self.assertTrue(manifest["complete"])
        issues = SemanticPackage(entries).verify()["issues"]
        self.assertEqual(issues, manifest["issues"])
        self.assertEqual({(i["code"], i["dataset_id"], i["column"]) for i in issues},
                         {("UNRESOLVED_JOIN_KEY", "child", "parent_id"),
                          ("UNRESOLVED_JOIN_KEY", "parent", "tenant"),
                          ("UNRESOLVED_JOIN_KEY", "parent", "id")})

    def test_malformed_duplicate_or_retired_keys_allow_draft_only(self):
        cases = {
            "unequal": lambda a: a[2]["properties"]["from_fields"].pop(),
            "repeated_pair": lambda a: a[2]["properties"]["from_fields"].__setitem__(1, "tenant"),
            "ambiguous_field": lambda a: a.append(dict(a[3], id="child_tenant_duplicate")),
            "retired_field": lambda a: a[3].update(status="retired"),
            "retired_endpoint": lambda a: a[0].update(status="retired"),
        }
        for label, edit in cases.items():
            with self.subTest(case=label):
                draft = copy.deepcopy(self.assets)
                edit(draft)
                with self.assertRaisesRegex(PackageError, "物理外键"):
                    validate_semantic_assets(draft)
                with self.assertRaises(PackageError) as caught:
                    self.package(assets=draft)
                self.assertEqual(caught.exception.code, "NOT_PUBLISHABLE")
                draft[2]["status"] = "draft"
                validate_semantic_assets(draft)
                report = inspect_model(draft, [], asset_ids=[self.fk["id"]])
                self.assertIn("INVALID_FOREIGN_KEY", [i["code"] for i in report["issues"]])
                entries, manifest = self.package(assets=draft, draft=True)
                self.assertFalse(manifest["complete"])
                self.assertIn("INVALID_FOREIGN_KEY", [i["code"] for i in SemanticPackage(entries).verify()["issues"]])

    def test_legacy_conflict_does_not_block_unrelated_work(self):
        self.fields[0]["status"] = "retired"
        before = copy.deepcopy(self.assets)
        unrelated = asset("unrelated", "entity")
        validate_semantic_assets(self.assets + [unrelated], previous=(before, []), reasserted=["unrelated"])
        with self.assertRaises(PackageError):
            validate_semantic_assets(self.assets, previous=(before, []), reasserted=[self.fk["id"]])
        self.fields[2]["status"] = "retired"
        with self.assertRaises(PackageError):
            validate_semantic_assets(self.assets, previous=(before, []))
        build_package(self.assets + [unrelated], [], project_id="fk", revision=1, asset_ids=["unrelated"])
        with self.assertRaises(PackageError):
            self.package()

    def test_catalog_completeness_depends_on_column_inventory(self):
        self.fk["properties"]["from_fields"][1] = "typo"
        cases = [
            ("KEY idx (tenant)", "INVALID_FOREIGN_KEY"),
            ("usage DOUBLE PRECISION", "INVALID_FOREIGN_KEY"),
            ("derived INTEGER GENERATED ALWAYS AS (tenant + 1) STORED", "INVALID_FOREIGN_KEY"),
            ("unknown", "UNRESOLVED_JOIN_KEY"),
        ]
        for tail, expected in cases:
            with self.subTest(tail=tail):
                statement = f"CREATE TABLE child (tenant INTEGER, parent_id INTEGER, {tail});"
                self.left["evidence"] = [{"source_id": "ddl", "revision": 1, "fragment_id": "table", "quote": statement}]
                sources = [{"id": "ddl", "name": "tables.sql", "format": "ddl", "revisions": [{
                    "revision": 1, "sha256": "a" * 64, "parsed": {"fragments": [
                        {"id": "table", "text": statement, "location": {"type": "ddl"}}]}}]}]
                if expected == "INVALID_FOREIGN_KEY":
                    with self.assertRaises(PackageError) as caught:
                        self.package(sources=sources)
                    self.assertEqual(caught.exception.code, "NOT_PUBLISHABLE")
                entries, manifest = self.package(sources=sources, draft=expected == "INVALID_FOREIGN_KEY")
                actual = SemanticPackage(entries).verify()["issues"]
                self.assertEqual([i["code"] for i in actual if i.get("column") == "typo"], [expected])
                self.assertEqual(manifest["complete"], expected == "UNRESOLVED_JOIN_KEY")

    def test_legacy_dotted_literal_roundtrip_keeps_identity(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        service = KnowledgeService(Store(directory.name))

        def mutate(method, **payload):
            return getattr(service, method)({"revision": service.store.read()["revision"],
                                              "operation_id": uuid.uuid4().hex, **payload})["result"]

        def ingest(sql, name, **extras):
            return mutate("import_material", filename=name,
                          content_base64=base64.b64encode(sql.encode()).decode(), **extras)

        sql = ('CREATE TABLE "main.ledger" (id INTEGER PRIMARY KEY); '
               'CREATE TABLE "main.posting" (ref INTEGER REFERENCES "main.ledger"(id));')
        with patch("scripts.ingest_ddl.qualified_identifier",
                   side_effect=lambda name: legacy_ddl_name(qualified_identifier(name))):
            source = ingest(sql, "original.sql", seed_draft=True)["source_id"]
            mutate("edit", asset=service.state()["assets"], confirm=True)
        before = service.state()
        before_ids = {a["id"] for a in before["assets"]}
        published = mutate("publish")
        with zipfile.ZipFile(io.BytesIO(service.download(published["snapshot_id"]))) as z:
            self.assertEqual(SemanticPackage({name: z.read(name) for name in z.namelist()}).verify()["issues"], [])

        other = "CREATE TABLE main.ledger (other TEXT);"
        with self.assertRaises(PackageError) as collision:
            ingest(other, "separate.sql", source_id=source)
        self.assertEqual(collision.exception.code, "DDL_IDENTITY_COLLISION")
        state = service.state()
        self.assertEqual((before["assets"], before["sources"], before["groups"]),
                         (state["assets"], state["sources"], state["groups"]))

        ingest(sql.replace("id INTEGER PRIMARY KEY", "id INTEGER PRIMARY KEY, note TEXT"), "rev.sql", source_id=source)
        candidates = service.state()["groups"][-1]["candidates"]
        targets = {c["target_id"] for c in candidates}
        self.assertTrue(before_ids < targets)
        self.assertEqual(len(targets - before_ids), 1)
        ingest(other, "separate.sql", distinct_source=True)
        self.assertTrue(all(c["target_id"] not in targets for c in service.state()["groups"][-1]["candidates"]))

    def test_ddl_absence_is_rechecked_offline(self):
        statement = "CREATE TABLE child (tenant INT, parent_id INT, FOREIGN KEY (tenant, parent_id) REFERENCES parent (tenant, id));"
        self.left["evidence"] = [{"source_id": "ddl", "revision": 1, "fragment_id": "child_stmt", "quote": statement}]
        sources = [{"id": "ddl", "name": "tables.sql", "format": "ddl", "revisions": [{"revision": 1, "sha256": "a" * 64,
            "parsed": {"fragments": [{"id": "child_stmt", "text": statement, "location": {"type": "ddl"}}]}}]}]
        entries, manifest = self.package(sources=sources)
        model = json.loads(entries["model.json"])
        fk = next(a for a in model["assets"] if a["id"] == self.fk["id"])
        fk["properties"]["from_fields"][1] = "typo"
        entries["model.json"] = _json(model)
        manifest["files"]["model.json"] = manifest["model_sha256"] = _sha(entries["model.json"])
        entries["manifest.json"] = _json(manifest)
        with self.assertRaises(PackageError) as caught:
            SemanticPackage(entries)
        self.assertEqual(caught.exception.code, "PACKAGE_CORRUPT")
        self.assertTrue(any(i.get("column") == "typo" and i["code"] == "INVALID_FOREIGN_KEY"
                            for i in caught.exception.details["issues"]))
