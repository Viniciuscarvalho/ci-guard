import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SKILL_ROOT = Path(__file__).parent.parent
_BOOTSTRAP_PY = _SKILL_ROOT / "scripts" / "bootstrap.py"


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


def _run_bootstrap(repo: Path, dry_run: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_BOOTSTRAP_PY), "--skill-dir", str(_SKILL_ROOT)]
    if dry_run:
        cmd.append("--dry-run")
    return subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True)


class TestBootstrap(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        _git_init(self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_expected_files(self):
        result = _run_bootstrap(self.repo)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue((self.repo / ".ci-guard" / "scripts").is_dir())
        self.assertTrue((self.repo / ".ci-guard" / "config.yml").exists())
        self.assertTrue((self.repo / ".ci-guard" / "flaky-ledger.json").exists())
        self.assertIn(
            ".ci-guard/.watch-state.json",
            (self.repo / ".gitignore").read_text(),
        )

    def test_copies_python_scripts(self):
        _run_bootstrap(self.repo)
        dest = self.repo / ".ci-guard" / "scripts"
        source = _SKILL_ROOT / "scripts"
        for src in source.glob("*.py"):
            self.assertTrue((dest / src.name).exists(), f"missing {src.name}")

    def test_idempotent_on_second_run(self):
        _run_bootstrap(self.repo)
        result = _run_bootstrap(self.repo)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Nothing to do", result.stdout)

    def test_does_not_overwrite_existing_ledger(self):
        _run_bootstrap(self.repo)
        ledger = self.repo / ".ci-guard" / "flaky-ledger.json"
        data = json.loads(ledger.read_text())
        data["tests"]["sentinel_test"] = {"status": "watched"}
        ledger.write_text(json.dumps(data))
        _run_bootstrap(self.repo)
        result_data = json.loads(ledger.read_text())
        self.assertIn("sentinel_test", result_data["tests"])

    def test_dry_run_writes_nothing(self):
        result = _run_bootstrap(self.repo, dry_run=True)
        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.repo / ".ci-guard").exists())
        self.assertIn("dry-run", result.stdout.lower())

    def test_missing_gitignore_is_created(self):
        gi = self.repo / ".gitignore"
        if gi.exists():
            gi.unlink()
        _run_bootstrap(self.repo)
        self.assertTrue(gi.exists())
        self.assertIn(".ci-guard/.watch-state.json", gi.read_text())

    def test_existing_gitignore_entry_not_duplicated(self):
        gi = self.repo / ".gitignore"
        gi.write_text(".ci-guard/.watch-state.json\n")
        _run_bootstrap(self.repo)
        occurrences = gi.read_text().count(".ci-guard/.watch-state.json")
        self.assertEqual(occurrences, 1)

    def test_ledger_is_valid_json(self):
        _run_bootstrap(self.repo)
        ledger = self.repo / ".ci-guard" / "flaky-ledger.json"
        data = json.loads(ledger.read_text())
        self.assertIn("version", data)
        self.assertIn("tests", data)
        self.assertIn("history", data)


if __name__ == "__main__":
    unittest.main()
