import unittest
from tests import test_knowledge_cli as _cli

class AtomicAuthoringTests(unittest.TestCase):
    setUp = _cli.KnowledgeCliTests.setUp
    tearDown = _cli.KnowledgeCliTests.tearDown
    run_cli = _cli.KnowledgeCliTests.run_cli
    write = _cli.KnowledgeCliTests.write

    def test_atomic_dependencies_rollback_retry_and_summary(self):
        assets = [{"id": "child", "kind": "term", "name": "Child", "refs": ["parent"]},
                  {"id": "parent", "kind": "entity", "name": "Parent"}]
        path = self.write("group.json", assets)
        first = self.run_cli("--operation-id", "atomic", "edit", "--file", path)
        self.assertEqual(first["result"], self.run_cli("--operation-id", "atomic", "edit", "--file", path)["result"])
        state = self.run_cli("state")["result"]
        summary = self.run_cli("state", "--summary")["result"]
        self.assertNotIn("document", summary)
        self.assertNotIn("history", summary)
        self.assertEqual(len(summary["assets"]), 2)
        assets[0]["name"] = "Changed"
        assets[1]["refs"] = ["missing"]
        self.run_cli("edit", "--file", self.write("bad.json", assets), code=2)
        self.assertEqual(self.run_cli("state")["result"]["assets"], state["assets"])
        self.run_cli("--revision", "0", "edit", "--file", path, code=2)
        self.run_cli("edit", "--file", self.write("duplicate.json", [assets[0], assets[0]]), code=2)
        self.run_cli("edit", "--file", path, "--confirm", code=2)
        self.assertEqual(self.run_cli("state")["result"]["revision"], state["revision"])

    def test_json_argument_error(self):
        error = self.run_cli("edit", code=2)
        self.assertEqual(error["status"], "argument_error")
