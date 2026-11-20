from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).resolve().parents[1] / "scripts" / "knowledge.py"


class RelationHintsTest(unittest.TestCase):
    def test_prefixed_tables_and_documented_self_reference(self):
        base = """
        CREATE TABLE t_order (id INT PRIMARY KEY);
        CREATE TABLE t_contract (order_id INT);
        CREATE TABLE t_refund (order_id INT);
        CREATE TABLE t_org (id INT PRIMARY KEY, parent_id INT COMMENT '上级机构');
        CREATE TABLE departments (id INT PRIMARY KEY, parent_id INT COMMENT 'Parent department ID');
        CREATE TABLE teams (id INT PRIMARY KEY, parent_id INT) COMMENT='parent_id: Parent team ID';
        CREATE TABLE groups (id INT PRIMARY KEY, parent_id INT COMMENT 'Parent ID');
        CREATE TABLE categories (id INT PRIMARY KEY, parent_id INT);
        CREATE TABLE t_company (id INT PRIMARY KEY, parent_id INT COMMENT 'Parent organization');
        CREATE TABLE t_tree (id INT PRIMARY KEY, parent_id INT REFERENCES t_tree(id));
        """
        with tempfile.TemporaryDirectory() as directory:
            def hints(folder, ddl):
                project = Path(directory) / folder
                project.mkdir()
                path = project / "schema.sql"
                path.write_text(ddl, encoding="utf-8")
                argv = [sys.executable, str(CLI), "--project", str(project)]
                subprocess.run([*argv, "import", "--file", str(path), "--seed-draft"], capture_output=True, check=True)
                result = subprocess.run([*argv, "relation-hints"], capture_output=True, encoding="utf-8", check=True)
                receipt = json.loads(result.stdout)["result"]
                self.assertEqual(receipt["business_rows_read"], 0)
                return {(h["from_name"], h["to_name"]): h for h in receipt["hints"]}

            result = hints("unambiguous", base)
            order_pairs = {("t_contract", "t_order"), ("t_refund", "t_order")}
            hierarchy_pairs = {("t_org", "t_org"), ("departments", "departments"), ("teams", "teams")}
            self.assertEqual(set(result), order_pairs | hierarchy_pairs)
            self.assertEqual(result[("t_org", "t_org")]["hierarchy_comment"], "上级机构")
            for pair in hierarchy_pairs:
                self.assertEqual(result[pair]["basis"], "documented_parent_column_and_compatible_primary_key")
                self.assertEqual(result[pair]["columns"][0]["from"]["name"], "parent_id")
                self.assertEqual(result[pair]["columns"][0]["to"]["name"], "id")
                self.assertTrue(result[pair]["hierarchy_evidence"]["fragment_id"])
            self.assertEqual(result[("teams", "teams")]["hierarchy_evidence"], result[("teams", "teams")]["target_key_evidence"])
            ambiguous = hints("ambiguous", base + 'CREATE TABLE "order" (id BIGINT PRIMARY KEY);')
            self.assertEqual(set(ambiguous), hierarchy_pairs)

    def test_cli_reads_structural_leads_without_saving(self):
        schema = """
        CREATE TABLE routes (tenant_id INT, id INT, PRIMARY KEY (tenant_id, id));
        CREATE TABLE journeys (tenant_id INT, route_id INTEGER);
        CREATE TABLE bad_journeys (tenant_id TEXT, route_id INT);
        CREATE TABLE partial_journeys (route_id INT);
        CREATE TABLE shorter_routes (id INT PRIMARY KEY);
        CREATE TABLE planned (shorter_route_id INT REFERENCES shorter_routes(id));
        CREATE TABLE flawed_plan (shorter_route_id INT REFERENCES shorter_routes(missing));
        CREATE TABLE courses (id INT PRIMARY KEY, parent_course_id INT, course_id INT);
        CREATE TABLE lessons (course_id INT, created_by INT);
        CREATE TABLE accounts (code VARCHAR(10) PRIMARY KEY);
        CREATE TABLE postings (account_code VARCHAR(10), external_account_code VARCHAR(10));
        CREATE TABLE a_bad_posting (account_code VARCHAR(11));
        CREATE TABLE clients (id INT PRIMARY KEY);
        CREATE TABLE client (id INTEGER PRIMARY KEY);
        CREATE TABLE visits (client_id INT);
        CREATE TABLE no_key (id INT);
        CREATE TABLE dirty (broken_column INT, no_key_id INT, stray_id INT);
        CREATE TABLE "core.v1".members (id INT PRIMARY KEY);
        CREATE TABLE core.v1.crossings (member_id INT);
        CREATE TABLE "finance.account" (id INT PRIMARY KEY);
        CREATE TABLE zz_literal_refs (finance_account_id INT, account_id INT);
        CREATE TABLE finance.qualified_refs (account_id INT, finance_account_id INT);
        """
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "项目 with space and ' quote"
            project.mkdir()
            source = project / "schema.sql"
            source.write_text(schema, encoding="utf-8")

            def call(*args):
                result = subprocess.run([sys.executable, str(CLI), "--project", str(project), *args],
                                        capture_output=True, encoding="utf-8", check=True)
                self.assertEqual(result.stderr, "")
                return json.loads(result.stdout)["result"]

            imported = call("import", "--file", str(source), "--seed-draft")
            argv = imported["result"]["optional_relation_hints_argv"]
            self.assertEqual(argv[-1], "relation-hints")
            self.assertEqual(Path(argv[3]), project.resolve())
            subprocess.run(argv, capture_output=True, encoding="utf-8", check=True)
            first = call("relation-hints", "--limit", "1")
            self.assertEqual(first["revision"], imported["revision"])
            self.assertEqual(first["business_rows_read"], 0)
            self.assertEqual(first["total"], 5)
            self.assertEqual(first["next_offset"], 1)
            remaining = call("relation-hints", "--offset", "1")
            hints = first["hints"] + remaining["hints"]
            self.assertEqual([(h["from_name"], h["to_name"]) for h in hints],
                             [("courses", "courses"), ("journeys", "routes"),
                              ("lessons", "courses"), ("postings", "accounts"),
                              ("zz_literal_refs", '"finance.account"')])
            self.assertEqual(hints[-1]["columns"][0]["from"]["name"], "finance_account_id")
            self.assertEqual([(p["from"]["name"], p["to"]["name"]) for p in hints[1]["columns"]],
                             [("tenant_id", "tenant_id"), ("route_id", "id")])
            self.assertTrue(all(p["from"]["evidence"]["fragment_id"] for p in hints[1]["columns"]))
            focus = call("relation-hints", "--id", hints[1]["to"])
            self.assertEqual(focus["total"], 1)
            self.assertEqual(focus["editor_focus_argument"], "--focus")
            state = call("state", "--summary")
            self.assertEqual(state["revision"], first["revision"])
            self.assertEqual(sum(asset["kind"] == "relation" for asset in state["assets"]), 1)

    def test_catalog_hints_use_saved_column_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            database = directory / "catalog.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.executescript("CREATE TABLE stops (id INTEGER PRIMARY KEY);"
                                         "CREATE TABLE events (stop_id INTEGER);")
            profile = directory / "connection.json"
            profile.write_text(json.dumps({"engine": "sqlite", "name": "Test", "path": str(database),
                                           "tables": ["stops", "events"]}), encoding="utf-8")

            def call(*args):
                result = subprocess.run([sys.executable, str(CLI), "--project", str(directory / "project"), *args],
                                        capture_output=True, encoding="utf-8", check=True)
                return json.loads(result.stdout)["result"]

            registered = call("connect", "--file", str(profile))
            scanned = call("scan", "--connection", registered["result"]["connection"]["id"], "--seed-draft")
            call_result = call("relation-hints")
            self.assertEqual(call_result["revision"], scanned["revision"])
            self.assertEqual(call_result["total"], 1)
            self.assertEqual(call_result["hints"][0]["columns"][0]["from"]["name"], "stop_id")


if __name__ == "__main__":
    unittest.main()
