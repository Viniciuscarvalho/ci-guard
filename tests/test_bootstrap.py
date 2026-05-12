"""Tests for ci_guard.init (ci-guard init subcommand).

The old subprocess-based bootstrap tests have been replaced with direct
unit tests against run_init() since the v0.5 rewrite no longer copies
scripts into .ci-guard/scripts/ — that directory is gone; scripts are
provided by the pip package.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ci_guard.init import run_init


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(path), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path), check=True, capture_output=True,
    )


class TestInit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        _git_init(self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_expected_files(self):
        changed = run_init(self.repo)
        self.assertTrue(changed)
        self.assertTrue((self.repo / ".ci-guard" / "config.yml").exists())
        self.assertTrue((self.repo / ".ci-guard" / "flaky-ledger.json").exists())
        self.assertIn(
            ".ci-guard/.watch-state.json",
            (self.repo / ".gitignore").read_text(),
        )

    def test_does_not_create_scripts_directory(self):
        run_init(self.repo)
        self.assertFalse((self.repo / ".ci-guard" / "scripts").exists())

    def test_idempotent_on_second_run(self):
        run_init(self.repo)
        changed = run_init(self.repo)
        self.assertFalse(changed)

    def test_does_not_overwrite_existing_ledger(self):
        run_init(self.repo)
        ledger = self.repo / ".ci-guard" / "flaky-ledger.json"
        data = json.loads(ledger.read_text())
        data["tests"]["sentinel_test"] = {"status": "watched"}
        ledger.write_text(json.dumps(data))
        run_init(self.repo)
        result_data = json.loads(ledger.read_text())
        self.assertIn("sentinel_test", result_data["tests"])

    def test_dry_run_writes_nothing(self):
        changed = run_init(self.repo, dry_run=True)
        self.assertTrue(changed)
        self.assertFalse((self.repo / ".ci-guard").exists())

    def test_missing_gitignore_is_created(self):
        gi = self.repo / ".gitignore"
        if gi.exists():
            gi.unlink()
        run_init(self.repo)
        self.assertTrue(gi.exists())
        self.assertIn(".ci-guard/.watch-state.json", gi.read_text())

    def test_existing_gitignore_entry_not_duplicated(self):
        gi = self.repo / ".gitignore"
        gi.write_text(".ci-guard/.watch-state.json\n")
        run_init(self.repo)
        occurrences = gi.read_text().count(".ci-guard/.watch-state.json")
        self.assertEqual(occurrences, 1)

    def test_ledger_is_valid_json(self):
        run_init(self.repo)
        ledger = self.repo / ".ci-guard" / "flaky-ledger.json"
        data = json.loads(ledger.read_text())
        self.assertIn("version", data)
        self.assertIn("tests", data)
        self.assertIn("history", data)

    def test_migrate_removes_legacy_scripts_dir(self):
        scripts_dir = self.repo / ".ci-guard" / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "ci_watch.py").write_text("# old script")
        run_init(self.repo, migrate=True)
        self.assertFalse(scripts_dir.exists())

    def test_migrate_dry_run_does_not_remove(self):
        scripts_dir = self.repo / ".ci-guard" / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "ci_watch.py").write_text("# old script")
        run_init(self.repo, dry_run=True, migrate=True)
        self.assertTrue(scripts_dir.exists())


class TestBootstrapShim(unittest.TestCase):
    """Smoke test: the legacy scripts/bootstrap.py shim still runs and redirects."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        subprocess.run(["git", "init", str(self.repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=str(self.repo), check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(self.repo), check=True, capture_output=True,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_shim_exits_0_and_prints_deprecation(self):
        bootstrap = Path(__file__).parent.parent / "scripts" / "bootstrap.py"
        result = subprocess.run(
            [sys.executable, str(bootstrap)],
            cwd=str(self.repo),
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deprecated", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
