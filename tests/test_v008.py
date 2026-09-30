# -*- coding: utf-8 -*-
"""v0.0.8 测试：输入文件缺失/非法时的干净报错（exit 2 + 可操作提示，不抛堆栈）。"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


def run_cli(args):
    return subprocess.run([sys.executable] + args,
                          encoding="utf-8", capture_output=True,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                          cwd=ROOT / "scripts")


class TestCleanInputErrors(unittest.TestCase):
    def test_check_model_missing_file(self):
        result = run_cli([str(ROOT / "scripts" / "check_model.py"), "-f", "no_such.yaml"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("输入文件不存在", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_check_model_bad_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.yaml"
            bad.write_text("datasets: [unclosed\n  : : :", encoding="utf-8")
            result = run_cli([str(ROOT / "scripts" / "check_model.py"), "-f", str(bad)])
        self.assertEqual(result.returncode, 2)
        self.assertIn("不是合法 YAML", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_run_eval_missing_cases(self):
        result = run_cli([str(ROOT / "scripts" / "run_eval.py"),
                          "--model", str(ROOT / "mocks" / "finance" / "semantic.yaml"),
                          "--endpoint", "http://localhost:9/v1",
                          "--cases", "no_such_cases.json"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("输入文件不存在", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_detect_isomorphic_out_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli([str(ROOT / "scripts" / "detect_isomorphic.py"),
                              "--tables", "no_such.yaml", "--columns", "no_such.yaml",
                              "--out", tmp])
        self.assertEqual(result.returncode, 2)
        self.assertIn("不是目录", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_profile_db_missing_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli([str(ROOT / "scripts" / "profile_db.py"),
                              "--db", "no_such.db",
                              "--out", str(Path(tmp) / "p.yaml")])
        self.assertEqual(result.returncode, 2)
        self.assertIn("数据库文件不存在", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        # sqlite3.connect 对缺失路径会静默建空库：确认防御先触发、没有留下文件
        self.assertFalse((ROOT / "scripts" / "no_such.db").exists())


if __name__ == "__main__":
    unittest.main()
