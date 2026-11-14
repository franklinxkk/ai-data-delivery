"""Public host review/edit entry points retain transaction and operator boundaries."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class KnowledgeCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="核对 CLI ")
        self.root = Path(self.temp.name)
        self.project = self.root / "项目"

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, code=0):
        p = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/knowledge.py"),
                            "--project", str(self.project), *args], cwd=self.root,
                           capture_output=True, encoding="utf-8")
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8-sig")
        return str(path)

    def proposal(self):
        path = self.root / "表结构.sql"
        path.write_text("CREATE TABLE plant (id INTEGER PRIMARY KEY, moisture REAL);", encoding="utf-8")
        self.run_cli("import", "--file", str(path), "--domain", "植物", "--scope", "H1")
        state = self.run_cli("state")["result"]
        self.assertEqual(state["assets"], [])
        return state["groups"][0]["id"]

    def test_review_requires_explicit_decision_and_preserves_receipt_and_conflict(self):
        group = self.proposal()
        self.run_cli("review", "--group", group, "--action", "accept", "--reason", " ", code=2)
        self.assertEqual(self.run_cli("state")["result"]["assets"], [])
        stale_revision = self.run_cli("state")["result"]["revision"]
        args = ("--operation-id", "test-review", "review", "--group", group, "--action", "accept", "--reason", "Authorized synthetic operator")
        first = self.run_cli(*args)
        replay = self.run_cli(*args)
        self.assertEqual(first["result"], replay["result"])
        self.assertTrue(all(a["status"] == "confirmed" for a in self.run_cli("state")["result"]["assets"]))
        asset = self.run_cli("state")["result"]["assets"][0]
        asset["definition"] = "Changed without fresh revision"
        fail = self.run_cli("--revision", str(stale_revision), "edit", "--file", self.write("变更.json", asset), "--confirm", code=2)
        self.assertEqual(fail["status"], "conflict")
        self.assertNotEqual(self.run_cli("state")["result"]["assets"][0]["definition"], asset["definition"])

    def test_rejection_cannot_be_silently_reaccepted(self):
        group = self.proposal()
        self.run_cli("review", "--group", group, "--action", "reject", "--reason", "Incorrect scope")
        self.run_cli("review", "--group", group, "--action", "accept", "--reason", "Retry", code=2)
        self.assertEqual(self.run_cli("state")["result"]["assets"], [])

    def test_edit_is_draft_by_default_and_confirmation_is_validated(self):
        asset = {"id": "r", "kind": "rule", "name": "人工确认", "definition": "温室 H1 须人工核对",
                 "domain": "植物", "scope": "H1", "properties": {"conditions": "H1", "requirements": "核对"},
                 "evidence": [{"type": "manual", "quote": "温室 H1 须人工核对", "actor": "synthetic operator"}]}
        file = self.write("规则.json", asset)
        self.run_cli("edit", "--file", file)
        self.assertEqual(self.run_cli("state")["result"]["assets"][0]["status"], "draft")
        self.run_cli("edit", "--file", file, "--confirm", code=2)
        self.assertEqual(self.run_cli("state")["result"]["assets"][0]["status"], "draft")
        asset["properties"] = {"condition": "H1", "requirement": "人工核对"}
        self.run_cli("edit", "--file", self.write("规则.json", asset), "--confirm")
        self.assertEqual(self.run_cli("state")["result"]["assets"][0]["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
