import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from classify_failure import classify  # noqa: E402

_FIXTURES = Path(__file__).parent / "fixtures" / "logs"


class TestClassifyFailure(unittest.TestCase):
    def _load(self, name: str) -> str:
        return (_FIXTURES / name).read_text()

    def test_branch_failure_pytest(self):
        result = classify(self._load("branch_failure_pytest.txt"))
        self.assertEqual(result["category"], "branch_failure")
        self.assertEqual(result["confidence"], "high")

    def test_infra_flake_runner(self):
        result = classify(self._load("infra_flake_runner.txt"))
        self.assertEqual(result["category"], "infra_flake")
        self.assertEqual(result["confidence"], "high")

    def test_test_flake_timeout(self):
        result = classify(self._load("test_flake_timeout.txt"))
        self.assertEqual(result["category"], "test_flake")
        self.assertEqual(result["confidence"], "medium")

    def test_dependency_failure_npm(self):
        result = classify(self._load("dependency_failure_npm.txt"))
        self.assertEqual(result["category"], "dependency_failure")
        self.assertEqual(result["confidence"], "high")

    def test_unknown(self):
        result = classify(self._load("unknown_generic.txt"))
        self.assertEqual(result["category"], "unknown")

    def test_empty_log_returns_unknown(self):
        result = classify("")
        self.assertEqual(result["category"], "unknown")

    def test_result_has_required_fields(self):
        result = classify("FAILED tests/auth.py::test_login")
        self.assertIn("category", result)
        self.assertIn("confidence", result)
        self.assertIn("reason", result)

    def test_branch_failure_includes_snippet(self):
        result = classify("FAILED tests/auth.py::test_login - AssertionError")
        self.assertEqual(result["category"], "branch_failure")
        self.assertIn("matched_snippet", result)
        self.assertIn("matched_pattern", result)

    def test_unknown_result_has_no_snippet(self):
        result = classify("everything is fine, carrying on normally")
        self.assertEqual(result["category"], "unknown")
        self.assertNotIn("matched_snippet", result)

    def test_branch_failure_beats_infra_in_same_log(self):
        # If a log has both a FAILED test line and an infra signal, branch_failure
        # must win because RULES is ordered branch_failure first.
        log = "FAILED tests/foo.py::test_bar\n\nDNS could not resolve host example.com"
        result = classify(log)
        self.assertEqual(result["category"], "branch_failure")


if __name__ == "__main__":
    unittest.main()
