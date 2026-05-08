"""Tests for action_runner.py — JSONL consumer and action executor."""

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import action_runner


def _line(**kwargs) -> str:
    defaults = {"pr_number": 42, "actions": []}
    defaults.update(kwargs)
    return json.dumps(defaults)


class TestRunIdle(unittest.TestCase):
    def test_idle_action_returns_0(self):
        stream = io.StringIO(_line(actions=[{"action": "idle"}]))
        self.assertEqual(action_runner.run(stream), 0)

    def test_empty_stream_returns_0(self):
        self.assertEqual(action_runner.run(io.StringIO("")), 0)

    def test_blank_lines_skipped(self):
        stream = io.StringIO("\n\n" + _line() + "\n\n")
        self.assertEqual(action_runner.run(stream), 0)

    def test_non_json_line_skipped(self):
        stream = io.StringIO("not json\n" + _line())
        self.assertEqual(action_runner.run(stream), 0)


class TestRetryActions(unittest.TestCase):
    @patch("action_runner._run_ci_watch")
    def test_retry_failed_now_calls_ci_watch(self, mock_run):
        stream = io.StringIO(_line(actions=[{"action": "retry_failed_now"}]))
        action_runner.run(stream)
        mock_run.assert_called_once_with(42, "--retry-failed-now")

    @patch("action_runner._run_ci_watch")
    def test_verify_flaky_green_calls_ci_watch(self, mock_run):
        stream = io.StringIO(_line(actions=[{"action": "verify_flaky_green", "checks": ["lint"]}]))
        action_runner.run(stream)
        mock_run.assert_called_once_with(42, "--verify-flaky-green")

    @patch("action_runner._run_ci_watch")
    def test_no_call_without_pr_number(self, mock_run):
        snap = json.dumps({"actions": [{"action": "retry_failed_now"}]})
        action_runner.run(io.StringIO(snap))
        mock_run.assert_not_called()

    @patch("action_runner._run_ci_watch")
    def test_pr_number_taken_from_first_snapshot(self, mock_run):
        lines = "\n".join([
            _line(pr_number=7, actions=[]),
            _line(pr_number=99, actions=[{"action": "retry_failed_now"}]),
        ])
        action_runner.run(io.StringIO(lines))
        mock_run.assert_called_once_with(7, "--retry-failed-now")


class TestDiagnoseAnnotations(unittest.TestCase):
    @patch("builtins.print")
    def test_branch_failure_emits_error_annotation(self, mock_print):
        snap = _line(actions=[{"action": "diagnose_branch_failure", "checks": ["test/unit"]}])
        action_runner.run(io.StringIO(snap))
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("::error::", printed)
        self.assertIn("branch_failure", printed)
        self.assertIn("test/unit", printed)

    @patch("builtins.print")
    def test_unknown_emits_warning_annotation(self, mock_print):
        snap = _line(actions=[{"action": "diagnose_unknown", "checks": ["build"]}])
        action_runner.run(io.StringIO(snap))
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("::warning::", printed)
        self.assertIn("build", printed)

    @patch("builtins.print")
    def test_multiple_checks_joined(self, mock_print):
        snap = _line(actions=[{"action": "diagnose_branch_failure", "checks": ["a", "b", "c"]}])
        action_runner.run(io.StringIO(snap))
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("a, b, c", printed)


class TestStopAction(unittest.TestCase):
    def _stop_stream(self, reason: str) -> io.StringIO:
        return io.StringIO(_line(actions=[{"action": "stop", "reason": reason}]))

    def test_pr_merged_exits_0(self):
        self.assertEqual(action_runner.run(self._stop_stream("pr_merged")), 0)

    def test_pr_closed_exits_0(self):
        self.assertEqual(action_runner.run(self._stop_stream("pr_closed")), 0)

    def test_needs_help_exits_2(self):
        self.assertEqual(action_runner.run(self._stop_stream("needs_help")), 2)

    def test_budget_exhausted_exits_3(self):
        self.assertEqual(action_runner.run(self._stop_stream("budget_exhausted")), 3)

    @patch("builtins.print")
    def test_stop_emits_notice_on_success(self, mock_print):
        action_runner.run(self._stop_stream("pr_merged"))
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("::notice::", printed)

    @patch("builtins.print")
    def test_stop_emits_warning_on_intervention(self, mock_print):
        action_runner.run(self._stop_stream("needs_help"))
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("::warning::", printed)

    @patch("action_runner._run_ci_watch")
    def test_stop_halts_processing_subsequent_actions(self, mock_run):
        snap = _line(actions=[
            {"action": "stop", "reason": "pr_merged"},
            {"action": "retry_failed_now"},
        ])
        action_runner.run(io.StringIO(snap))
        mock_run.assert_not_called()


class TestPassthrough(unittest.TestCase):
    @patch("builtins.print")
    def test_each_snapshot_printed_to_stdout(self, mock_print):
        line = _line(actions=[{"action": "idle"}])
        action_runner.run(io.StringIO(line))
        raw_calls = [str(c.args[0]) for c in mock_print.call_args_list
                     if c.args and '"pr_number"' in str(c.args[0])]
        self.assertEqual(len(raw_calls), 1)


if __name__ == "__main__":
    unittest.main()
