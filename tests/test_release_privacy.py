import codecs
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


CHECKER = Path(__file__).resolve().parents[1] / "maintainer" / "privacy_check.py"


class ReleasePrivacyTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.repo = self.root / "tree"
        self.repo.mkdir()
        self.git("init", "--quiet")
        self.term = "SYNTH-" + "雪🧭"
        self.terms = self.root / "excluded.txt"
        self.terms.write_text(" \n" + self.term + "\n", encoding="utf-8-sig")
        self.package = self.root / "install.zip"
        self.notes = self.root / "notes.md"
        self.notes.write_text("public notes", encoding="utf-8")
        self.write_package({"ok.txt": b"public"})
        (self.repo / "ok.txt").write_text("public", encoding="utf-8")
        self.commit()

    def git(self, *args):
        # Windows may drop empty environment entries after another test restores os.environ.
        # An explicit environment preserves Git configuration that contains empty values.
        return subprocess.check_output(["git", "-C", str(self.repo), *args],
                                       stderr=subprocess.PIPE, env=dict(os.environ))

    def commit(self):
        self.git("add", "-A")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")

    def write_package(self, entries):
        with zipfile.ZipFile(self.package, "w") as archive:
            for name, body in entries.items():
                archive.writestr(name, body)

    def check(self, rc, *extra):
        proc = subprocess.run(
            [sys.executable, str(CHECKER), "--terms-file", str(self.terms), "--repo", str(self.repo),
             "--zip", str(self.package), "--release-notes", str(self.notes), *extra],
            capture_output=True, encoding="utf-8", env=dict(os.environ),
        )
        self.assertEqual(rc, proc.returncode)
        self.assertEqual("", proc.stderr)
        self.assertNotIn(self.term, proc.stdout)
        self.assertNotIn(str(self.root), proc.stdout)
        return json.loads(proc.stdout)

    def test_commit_not_working_copy_and_separate_zip(self):
        (self.repo / "ok.txt").write_text(self.term, encoding="utf-8")
        self.assertEqual("no_match_in_scanned_scope", self.check(0)["result"])
        self.write_package({"folder/" + self.term + ".bin": b"\0opaque", "extra.txt": self.term})
        counts = self.check(1)["counts"]
        self.assertEqual((0, 0), (counts["tree"]["matched_names"], counts["tree"]["matched_bodies"]))
        self.assertEqual((1, 1), (counts["zip"]["matched_names"], counts["zip"]["matched_bodies"]))
        self.assertEqual(1, counts["zip"]["opaque_bodies"])

    def test_tree_name_unicode_escapes_and_notes(self):
        filename = self.term + ".md"
        escaped = json.dumps(self.term.lower(), ensure_ascii=True)
        (self.repo / filename).write_text(escaped, encoding="ascii")
        self.commit()
        (self.repo / filename).unlink()
        self.notes.write_bytes(codecs.BOM_UTF16_BE + self.term.encode("utf-16-be"))
        self.write_package({"escaped.txt": escaped, "braced.txt": r"synth-\u{96ea}\U0001f9ed"})
        counts = self.check(1)["counts"]
        self.assertEqual((1, 1), (counts["tree"]["matched_names"], counts["tree"]["matched_bodies"]))
        self.assertEqual(2, counts["zip"]["matched_bodies"])
        self.assertEqual(1, counts["notes"]["matched_bodies"])
        self.assertEqual(0, self.check(1, "--ref", "HEAD^")["counts"]["tree"]["matched_bodies"])

    def test_opaque_body_is_counted_and_not_certified(self):
        data = b"\x00\xff" + self.term.encode("utf-8")
        self.write_package({"image.bin": data})
        (self.repo / "artifact.bin").write_bytes(data)
        self.commit()
        result = self.check(0)
        self.assertEqual("no_match_in_scanned_scope", result["result"])
        self.assertEqual(1, result["counts"]["tree"]["opaque_bodies"])
        self.assertEqual(1, result["counts"]["zip"]["opaque_bodies"])
        self.assertEqual(0, result["counts"]["zip"]["text_bodies"])

    def test_invalid_inputs_fail_without_echo(self):
        self.assertEqual("tree", self.check(2, "--ref", self.term)["stage"])
        self.package.write_bytes(self.term.encode("utf-8"))
        self.assertEqual("zip", self.check(2)["stage"])
        self.terms.write_text("", encoding="utf-8")
        self.assertEqual("terms", self.check(2)["stage"])


if __name__ == "__main__":
    unittest.main()
