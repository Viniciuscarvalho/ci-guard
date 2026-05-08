import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from config import QUARANTINE_FAIL_THRESHOLD, QUARANTINE_RATE_THRESHOLD  # noqa: E402
from flaky_ledger import get_quarantine_candidates, load, record_failure, record_pass, save  # noqa: E402


class TestFlakyLedger(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self._tmp.name) / "flaky-ledger.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_failure_creates_entry(self):
        entry = record_failure("tests/auth.py::test_oauth", sha="abc", ledger_path=self.ledger)
        self.assertEqual(entry["failure_count_30d"], 1)
        self.assertEqual(entry["pass_count_30d"], 0)
        self.assertEqual(entry["flake_rate"], 1.0)
        self.assertEqual(entry["status"], "watched")

    def test_record_pass_creates_entry(self):
        entry = record_pass("tests/auth.py::test_oauth", sha="abc", ledger_path=self.ledger)
        self.assertEqual(entry["pass_count_30d"], 1)
        self.assertEqual(entry["failure_count_30d"], 0)
        self.assertEqual(entry["flake_rate"], 0.0)

    def test_record_failure_then_pass(self):
        record_failure("tests/auth.py::test_oauth", sha="a", ledger_path=self.ledger)
        entry = record_pass("tests/auth.py::test_oauth", sha="b", ledger_path=self.ledger)
        self.assertEqual(entry["failure_count_30d"], 1)
        self.assertEqual(entry["pass_count_30d"], 1)
        self.assertAlmostEqual(entry["flake_rate"], 0.5)

    def test_quarantine_candidates_empty_below_threshold(self):
        # One failure only — below the fail count threshold.
        record_failure("tests/auth.py::test_oauth", sha="a", ledger_path=self.ledger)
        self.assertEqual(get_quarantine_candidates(self.ledger), [])

    def test_quarantine_candidates_triggered_at_threshold(self):
        test_id = "tests/auth.py::test_oauth"
        for i in range(QUARANTINE_FAIL_THRESHOLD):
            record_failure(test_id, sha=f"sha{i}", ledger_path=self.ledger)
        candidates = get_quarantine_candidates(self.ledger)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["test"], test_id)
        self.assertGreaterEqual(candidates[0]["flake_rate"], QUARANTINE_RATE_THRESHOLD)

    def test_quarantined_test_not_in_candidates(self):
        test_id = "tests/auth.py::test_oauth"
        for i in range(QUARANTINE_FAIL_THRESHOLD):
            record_failure(test_id, sha=f"sha{i}", ledger_path=self.ledger)
        data = load(self.ledger)
        data["tests"][test_id]["status"] = "quarantined"
        save(self.ledger, data)
        self.assertEqual(get_quarantine_candidates(self.ledger), [])

    def test_ledger_persists_across_loads(self):
        record_failure("tests/foo.py::test_bar", sha="a", ledger_path=self.ledger)
        data = load(self.ledger)
        self.assertIn("tests/foo.py::test_bar", data["tests"])

    def test_multiple_tests_tracked_independently(self):
        record_failure("tests/a.py::test_one", sha="x", ledger_path=self.ledger)
        record_failure("tests/b.py::test_two", sha="x", ledger_path=self.ledger)
        data = load(self.ledger)
        self.assertIn("tests/a.py::test_one", data["tests"])
        self.assertIn("tests/b.py::test_two", data["tests"])

    def test_absent_ledger_returns_empty_structure(self):
        absent = Path(self._tmp.name) / "nonexistent.json"
        data = load(absent)
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["tests"], {})
        self.assertEqual(data["history"], [])

    def test_candidates_sorted_by_severity(self):
        for test_id, fail_count in [("tests/a.py::t1", 5), ("tests/b.py::t2", 10)]:
            for i in range(fail_count):
                record_failure(test_id, sha=f"sha{i}", ledger_path=self.ledger)
        candidates = get_quarantine_candidates(self.ledger)
        self.assertEqual(len(candidates), 2)
        # Higher failure count should sort first.
        self.assertGreater(
            candidates[0]["failure_count_30d"],
            candidates[1]["failure_count_30d"],
        )


if __name__ == "__main__":
    unittest.main()
