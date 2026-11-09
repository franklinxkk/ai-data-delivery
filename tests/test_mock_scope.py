"""Harmless containment fixtures: rejected domains cannot run or lose a DB."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mocks import run_mock
from maintainer.build_skill import runtime_paths


class MockScope(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mock-scope-')
        self.base = Path(self.temp.name)
        self.managed = self.base / 'mocks'
        self.managed.mkdir()
        self.domain = self.make_domain(self.managed / 'valid')
        self.external = self.make_domain(self.base / 'external')
        self.original_db = b'outside database must survive unchanged'
        (self.external / 'domain.db').write_bytes(self.original_db)
        self.here = patch.object(run_mock, 'HERE', str(self.managed))
        self.here.start()
        self.addCleanup(self.here.stop)
        self.addCleanup(self.temp.cleanup)

    def make_domain(self, directory):
        directory.mkdir()
        (directory / 'build_db.py').write_text(
            "from pathlib import Path\nPath(__file__).with_name('executed.marker').write_text('executed')\n",
            encoding='utf-8')
        (directory / 'semantic.yaml').write_text('{}\n', encoding='utf-8')
        (directory / 'cases.json').write_text('[]\n', encoding='utf-8')
        return directory

    def assert_external_untouched(self):
        self.assertFalse((self.external / 'executed.marker').exists())
        self.assertEqual((self.external / 'domain.db').read_bytes(), self.original_db)

    def symlink(self, target, link, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'OS does not permit symbolic links: {exc}')

    def test_cli_rejects_absolute_traversal_and_nested_paths(self):
        for name in (str(self.external), '../external', '..\\external', 'valid/child', 'valid\\child', 'valid.'):
            with self.subTest(name=name), patch.object(sys, 'argv', ['run_mock.py', '--domain', name]), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run_mock.main(), 2)
                self.assert_external_untouched()

    def test_direct_domain_and_step_entrypoints_reject_external_paths(self):
        for domain in (self.external, self.managed / '..' / 'external'):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                run_mock.run_domain(domain)
        with self.assertRaises(ValueError):
            run_mock.run_step('external cwd', [str(self.external / 'build_db.py')], self.external)
        with self.assertRaises(ValueError):
            run_mock.run_step('external script', [str(self.external / 'build_db.py')], self.domain)
        self.assert_external_untouched()

    def test_symlink_domain_is_rejected(self):
        link = self.managed / 'linked'
        self.symlink(self.external, link, directory=True)
        with self.assertRaises(ValueError):
            run_mock.run_domain(link)
        self.assert_external_untouched()

    @unittest.skipUnless(os.name == 'nt', 'Windows junction fixture')
    def test_windows_junction_domain_is_rejected(self):
        import _winapi
        link = self.managed / 'junction'
        _winapi.CreateJunction(str(self.external), str(link))
        try:
            with self.assertRaises(ValueError):
                run_mock.run_domain(link)
            self.assert_external_untouched()
        finally:
            os.rmdir(link)

    def test_symlinked_builder_is_rejected_before_database_delete(self):
        builder = self.domain / 'build_db.py'
        builder.unlink()
        self.symlink(self.external / 'build_db.py', builder)
        local_db = self.domain / 'domain.db'
        local_db.write_bytes(b'local database also survives')
        with self.assertRaises(ValueError):
            run_mock.run_domain(self.domain)
        self.assertEqual(local_db.read_bytes(), b'local database also survives')
        self.assert_external_untouched()

    def test_symlinked_output_is_rejected_before_execution(self):
        for filename in ('domain.db', 'actual.jsonl', 'report.json'):
            with self.subTest(filename=filename):
                link = self.domain / filename
                self.symlink(self.external / 'domain.db', link)
                try:
                    with self.assertRaises(ValueError):
                        run_mock.run_domain(self.domain)
                    self.assertFalse((self.domain / 'executed.marker').exists())
                    self.assert_external_untouched()
                finally:
                    link.unlink()

    def test_hardlinked_output_is_rejected(self):
        os.link(self.external / 'domain.db', self.domain / 'domain.db')
        with self.assertRaises(ValueError):
            run_mock.run_domain(self.domain)
        self.assert_external_untouched()

    def test_all_preflights_domains_before_starting_any(self):
        link = self.managed / 'z_external'
        if os.name == 'nt':
            import _winapi
            _winapi.CreateJunction(str(self.external), str(link))
        else:
            self.symlink(self.external, link, directory=True)
        try:
            with patch.object(sys, 'argv', ['run_mock.py', '--all']), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run_mock.main(), 2)
            self.assertFalse((self.domain / 'executed.marker').exists())
            self.assert_external_untouched()
        finally:
            os.rmdir(link) if os.name == 'nt' else link.unlink()

    def test_real_managed_retail_scenario_still_completes(self):
        for filename in ('build_db.py', 'semantic.yaml', 'cases.json'):
            shutil.copyfile(ROOT / 'mocks' / 'retail' / filename, self.domain / filename)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertTrue(run_mock.run_domain(self.domain), output.getvalue())
        self.assertTrue((self.domain / 'domain.db').is_file())
        self.assertTrue((self.domain / 'actual.jsonl').is_file())
        self.assertTrue((self.domain / 'report.json').is_file())
        self.assert_external_untouched()


class RuntimePackageScope(unittest.TestCase):
    def test_maintainer_and_mock_executables_cannot_enter_runtime(self):
        paths = ['SKILL.md', 'scripts/start.py', 'scripts/_contract.py',
                 'scripts/rebuild.py', 'scripts/_process.py', 'maintainer/rebuild.py',
                 'maintainer/_process.py', 'mocks/run_mock.py', 'mocks/retail/build_db.py',
                 'mocks/retail/semantic.yaml', 'tests/test_mock_scope.py',
                 'examples/onboarding/run_demo.py', 'workbench/web/index.html']
        self.assertEqual(runtime_paths(paths), sorted([
            'SKILL.md', 'scripts/start.py', 'scripts/_contract.py',
            'examples/onboarding/run_demo.py', 'workbench/web/index.html']))
        self.assertFalse((ROOT / 'scripts' / 'rebuild.py').exists())
        self.assertFalse((ROOT / 'scripts' / '_process.py').exists())
        self.assertTrue((ROOT / 'maintainer' / 'rebuild.py').is_file())
        self.assertTrue((ROOT / 'maintainer' / '_process.py').is_file())


if __name__ == '__main__':
    unittest.main()
