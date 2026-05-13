from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from ci_guard.gate import (
    EXIT_BLOCKED,
    EXIT_EXHAUSTED,
    EXIT_GREEN,
    EXIT_RETRYABLE,
    _verdict,
)
from ci_guard.watch import CheckSnapshot, Snapshot


def _check(name="job", conclusion="failure", category="branch_failure", flaky_history=None):
    c = CheckSnapshot(
        name=name,
        workflow="CI",
        status="completed",
        conclusion=conclusion,
        run_id="r1",
        duration_seconds=10,
        started_at=None,
    )
    c.classification = {"category": category, "confidence": "high", "reason": "x"} if category else {}
    c.flaky_history = flaky_history or {}
    return c


def _snap(pr_state="OPEN", checks=None, terminal=None, quarantine_candidates=None):
    s = Snapshot(
        pr_number=42,
        head_sha="abcdef0",
        head_sha_short="abcdef0",
        pr_state=pr_state,
        mergeable="MERGEABLE",
        checks=checks or [],
        quarantine_candidates=quarantine_candidates or [],
        terminal=terminal,
    )
    s.actions = []
    s.cost_summary = {"retries_used_pr": 0, "retries_max_pr": 5, "any_budget_exhausted": False}
    return s


class TestVerdictGreen(unittest.TestCase):

    def test_no_failing_checks_is_green(self):
        snap = _snap(checks=[_check(conclusion="success", category=None)])
        verdict, code, blocked, unknown, retryable = _verdict(snap)
        self.assertEqual(verdict, "green")
        self.assertEqual(code, EXIT_GREEN)

    def test_pr_merged_is_green(self):
        snap = _snap(pr_state="MERGED", terminal="pr_merged")
        verdict, code, *_ = _verdict(snap)
        self.assertEqual(verdict, "green")
        self.assertEqual(code, EXIT_GREEN)

    def test_pr_closed_is_green(self):
        snap = _snap(pr_state="CLOSED", terminal="pr_closed")
        verdict, code, *_ = _verdict(snap)
        self.assertEqual(verdict, "green")
        self.assertEqual(code, EXIT_GREEN)


class TestVerdictBlocked(unittest.TestCase):

    def test_branch_failure_blocks(self):
        snap = _snap(checks=[_check(category="branch_failure")])
        verdict, code, blocked, unknown, _ = _verdict(snap)
        self.assertEqual(verdict, "blocked")
        self.assertEqual(code, EXIT_BLOCKED)
        self.assertIn("job", blocked)

    def test_unknown_check_blocks(self):
        snap = _snap(checks=[_check(category="unknown")])
        verdict, code, blocked, unknown, _ = _verdict(snap)
        self.assertEqual(verdict, "blocked")
        self.assertEqual(code, EXIT_BLOCKED)
        self.assertIn("job", unknown)

    def test_branch_failure_beats_retryable(self):
        """A branch_failure + an infra_flake → still blocked, not retryable."""
        snap = _snap(checks=[
            _check(name="lint", category="branch_failure"),
            _check(name="e2e", category="infra_flake"),
        ])
        verdict, code, blocked, _, retryable = _verdict(snap)
        self.assertEqual(verdict, "blocked")
        self.assertEqual(code, EXIT_BLOCKED)
        self.assertIn("lint", blocked)
        self.assertIn("e2e", retryable)


class TestVerdictRetryable(unittest.TestCase):

    def test_infra_flake_is_retryable(self):
        snap = _snap(checks=[_check(category="infra_flake")])
        verdict, code, blocked, unknown, retryable = _verdict(snap)
        self.assertEqual(verdict, "retryable")
        self.assertEqual(code, EXIT_RETRYABLE)
        self.assertIn("job", retryable)
        self.assertFalse(blocked)

    def test_test_flake_is_retryable(self):
        snap = _snap(checks=[_check(category="test_flake")])
        verdict, code, *_ = _verdict(snap)
        self.assertEqual(verdict, "retryable")
        self.assertEqual(code, EXIT_RETRYABLE)

    def test_dependency_failure_is_retryable(self):
        snap = _snap(checks=[_check(category="dependency_failure")])
        verdict, code, *_ = _verdict(snap)
        self.assertEqual(verdict, "retryable")
        self.assertEqual(code, EXIT_RETRYABLE)


class TestVerdictExhausted(unittest.TestCase):

    def test_budget_exhausted_terminal_is_exhausted(self):
        snap = _snap(terminal="budget_exhausted")
        snap.cost_summary["any_budget_exhausted"] = True
        verdict, code, *_ = _verdict(snap)
        self.assertEqual(verdict, "exhausted")
        self.assertEqual(code, EXIT_EXHAUSTED)

    def test_needs_help_terminal_is_exhausted(self):
        snap = _snap(terminal="needs_help")
        verdict, code, *_ = _verdict(snap)
        self.assertEqual(verdict, "exhausted")
        self.assertEqual(code, EXIT_EXHAUSTED)


class TestCmdGateJsonOutput(unittest.TestCase):

    def _run_gate(self, snap):
        from ci_guard.gate import cmd_gate
        with patch("ci_guard.gate.assemble_snapshot", return_value=snap):
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                code = cmd_gate(42, Path("/fake"), json_output=True)
        output = json.loads(buf.getvalue())
        return code, output

    def test_green_json(self):
        snap = _snap(checks=[_check(conclusion="success", category=None)])
        code, out = self._run_gate(snap)
        self.assertEqual(code, EXIT_GREEN)
        self.assertEqual(out["verdict"], "green")
        self.assertEqual(out["exit_code"], EXIT_GREEN)

    def test_blocked_json_lists_checks(self):
        snap = _snap(checks=[_check(name="lint", category="branch_failure")])
        code, out = self._run_gate(snap)
        self.assertEqual(code, EXIT_BLOCKED)
        self.assertIn("lint", out["blocked_checks"])

    def test_retryable_json(self):
        snap = _snap(checks=[_check(name="e2e", category="infra_flake")])
        code, out = self._run_gate(snap)
        self.assertEqual(code, EXIT_RETRYABLE)
        self.assertIn("e2e", out["retryable_checks"])


if __name__ == "__main__":
    unittest.main()
