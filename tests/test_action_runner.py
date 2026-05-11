"""Tests for action_runner.py — JSONL consumer and action executor."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from unittest.mock import call, patch

from ci_guard import actions as action_runner


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _line(**kwargs) -> str:
    defaults = {"pr_number": 42, "actions": []}
    defaults.update(kwargs)
    return json.dumps(defaults)


def _snap_with_checks(terminal: str, checks: list[dict] | None = None, cost: dict | None = None) -> str:
    return json.dumps({
        "pr_number": 42,
        "head_sha_short": "abc1234",
        "terminal": terminal,
        "checks": checks or [],
        "cost_summary": cost or {"retries_used_pr": 1, "retries_max_pr": 5,
                                  "minutes_spent": 10, "minutes_max": 90},
        "quarantine_candidates": [],
        "actions": [{"action": "stop", "reason": terminal}],
    })


# --------------------------------------------------------------------------- #
# Idle / pass-through
# --------------------------------------------------------------------------- #

class TestRunIdle(unittest.TestCase):
    def test_idle_action_returns_0(self):
        self.assertEqual(action_runner.run(io.StringIO(_line(actions=[{"action": "idle"}]))), 0)

    def test_empty_stream_returns_0(self):
        self.assertEqual(action_runner.run(io.StringIO("")), 0)

    def test_blank_lines_skipped(self):
        self.assertEqual(action_runner.run(io.StringIO("\n\n" + _line() + "\n\n")), 0)

    def test_non_json_line_skipped(self):
        self.assertEqual(action_runner.run(io.StringIO("not json\n" + _line())), 0)


# --------------------------------------------------------------------------- #
# Retry actions
# --------------------------------------------------------------------------- #

class TestRetryActions(unittest.TestCase):
    @patch("ci_guard.actions._invoke_ci_guard")
    def test_retry_failed_now_calls_ci_watch(self, mock_run):
        action_runner.run(io.StringIO(_line(actions=[{"action": "retry_failed_now"}])))
        mock_run.assert_called_once_with(42, "--retry-failed-now")

    @patch("ci_guard.actions._invoke_ci_guard")
    def test_verify_flaky_green_calls_ci_watch(self, mock_run):
        action_runner.run(io.StringIO(_line(actions=[{"action": "verify_flaky_green", "checks": ["lint"]}])))
        mock_run.assert_called_once_with(42, "--verify-flaky-green")

    @patch("ci_guard.actions._invoke_ci_guard")
    def test_no_call_without_pr_number(self, mock_run):
        action_runner.run(io.StringIO(json.dumps({"actions": [{"action": "retry_failed_now"}]})))
        mock_run.assert_not_called()

    @patch("ci_guard.actions._invoke_ci_guard")
    def test_pr_number_taken_from_first_snapshot(self, mock_run):
        lines = "\n".join([
            _line(pr_number=7, actions=[]),
            _line(pr_number=99, actions=[{"action": "retry_failed_now"}]),
        ])
        action_runner.run(io.StringIO(lines))
        mock_run.assert_called_once_with(7, "--retry-failed-now")


# --------------------------------------------------------------------------- #
# Diagnose annotations
# --------------------------------------------------------------------------- #

class TestDiagnoseAnnotations(unittest.TestCase):
    @patch("ci_guard.actions._post_pr_comment")
    @patch("builtins.print")
    def test_branch_failure_emits_error_annotation(self, mock_print, _):
        action_runner.run(io.StringIO(_line(actions=[{"action": "diagnose_branch_failure", "checks": ["test/unit"]}])))
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("::error::", printed)
        self.assertIn("branch_failure", printed)
        self.assertIn("test/unit", printed)

    @patch("ci_guard.actions._post_pr_comment")
    @patch("builtins.print")
    def test_unknown_emits_warning_annotation(self, mock_print, _):
        action_runner.run(io.StringIO(_line(actions=[{"action": "diagnose_unknown", "checks": ["build"]}])))
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("::warning::", printed)
        self.assertIn("build", printed)

    @patch("ci_guard.actions._post_pr_comment")
    @patch("builtins.print")
    def test_multiple_checks_joined_in_annotation(self, mock_print, _):
        action_runner.run(io.StringIO(_line(actions=[{"action": "diagnose_branch_failure", "checks": ["a", "b", "c"]}])))
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("a, b, c", printed)


# --------------------------------------------------------------------------- #
# PR comments on diagnose
# --------------------------------------------------------------------------- #

class TestDiagnosePrComments(unittest.TestCase):
    @patch("ci_guard.actions._post_pr_comment")
    def test_branch_failure_posts_pr_comment(self, mock_comment):
        action_runner.run(io.StringIO(_line(actions=[
            {"action": "diagnose_branch_failure", "checks": ["test/unit"]}
        ])))
        mock_comment.assert_called_once()
        body = mock_comment.call_args[0][1]
        self.assertIn("branch_failure", body)
        self.assertIn("test/unit", body)

    @patch("ci_guard.actions._post_pr_comment")
    def test_unknown_posts_pr_comment(self, mock_comment):
        action_runner.run(io.StringIO(_line(actions=[
            {"action": "diagnose_unknown", "checks": ["build"]}
        ])))
        mock_comment.assert_called_once()
        body = mock_comment.call_args[0][1]
        self.assertIn("unknown", body)
        self.assertIn("build", body)

    @patch("ci_guard.actions._post_pr_comment")
    def test_no_comment_without_pr_number(self, mock_comment):
        snap = json.dumps({"actions": [{"action": "diagnose_branch_failure", "checks": ["x"]}]})
        action_runner.run(io.StringIO(snap))
        mock_comment.assert_not_called()


# --------------------------------------------------------------------------- #
# Stop action — exit codes
# --------------------------------------------------------------------------- #

class TestStopExitCodes(unittest.TestCase):
    def _stop(self, reason: str) -> int:
        return action_runner.run(io.StringIO(_snap_with_checks(reason)))

    @patch("ci_guard.actions._post_pr_comment")
    @patch("ci_guard.actions._write_step_summary")
    def test_pr_merged_exits_0(self, *_):
        self.assertEqual(self._stop("pr_merged"), 0)

    @patch("ci_guard.actions._post_pr_comment")
    @patch("ci_guard.actions._write_step_summary")
    def test_pr_closed_exits_0(self, *_):
        self.assertEqual(self._stop("pr_closed"), 0)

    @patch("ci_guard.actions._post_pr_comment")
    @patch("ci_guard.actions._write_step_summary")
    def test_needs_help_exits_2(self, *_):
        self.assertEqual(self._stop("needs_help"), 2)

    @patch("ci_guard.actions._post_pr_comment")
    @patch("ci_guard.actions._write_step_summary")
    def test_budget_exhausted_exits_3(self, *_):
        self.assertEqual(self._stop("budget_exhausted"), 3)


# --------------------------------------------------------------------------- #
# Stop action — PR comment + step summary
# --------------------------------------------------------------------------- #

class TestStopOutputs(unittest.TestCase):
    @patch("ci_guard.actions._write_step_summary")
    @patch("ci_guard.actions._post_pr_comment")
    def test_stop_posts_pr_comment(self, mock_comment, _):
        action_runner.run(io.StringIO(_snap_with_checks("pr_merged")))
        mock_comment.assert_called_once()
        self.assertEqual(mock_comment.call_args[0][0], 42)

    @patch("ci_guard.actions._write_step_summary")
    @patch("ci_guard.actions._post_pr_comment")
    def test_stop_writes_step_summary(self, _, mock_summary):
        action_runner.run(io.StringIO(_snap_with_checks("pr_merged")))
        mock_summary.assert_called_once()

    @patch("ci_guard.actions._write_step_summary")
    @patch("ci_guard.actions._post_pr_comment")
    def test_stop_halts_subsequent_actions(self, mock_comment, _):
        snap = _line(actions=[
            {"action": "stop", "reason": "pr_merged"},
            {"action": "retry_failed_now"},
        ])
        with patch("ci_guard.actions._invoke_ci_guard") as mock_run:
            action_runner.run(io.StringIO(snap))
            mock_run.assert_not_called()

    @patch("builtins.print")
    @patch("ci_guard.actions._post_pr_comment")
    @patch("ci_guard.actions._write_step_summary")
    def test_stop_emits_notice_on_success(self, _, __, mock_print):
        action_runner.run(io.StringIO(_snap_with_checks("pr_merged")))
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("::notice::", printed)

    @patch("builtins.print")
    @patch("ci_guard.actions._post_pr_comment")
    @patch("ci_guard.actions._write_step_summary")
    def test_stop_emits_warning_on_intervention(self, _, __, mock_print):
        action_runner.run(io.StringIO(_snap_with_checks("needs_help")))
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("::warning::", printed)


# --------------------------------------------------------------------------- #
# _post_pr_comment no-op without GH_TOKEN
# --------------------------------------------------------------------------- #

class TestPostPrCommentNoOp(unittest.TestCase):
    @patch("subprocess.run")
    def test_no_gh_call_without_token(self, mock_run):
        env = {k: v for k, v in os.environ.items() if k != "GH_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            action_runner._post_pr_comment(42, "hello")
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_calls_gh_when_token_present(self, mock_run):
        with patch.dict(os.environ, {"GH_TOKEN": "tok"}):
            action_runner._post_pr_comment(42, "hello")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("gh", cmd)
        self.assertIn("pr", cmd)
        self.assertIn("comment", cmd)


# --------------------------------------------------------------------------- #
# _write_step_summary
# --------------------------------------------------------------------------- #

class TestWriteStepSummary(unittest.TestCase):
    def test_writes_to_summary_file(self):
        with tempfile.NamedTemporaryFile(mode="r", suffix=".md", delete=False) as f:
            path = f.name
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": path}):
            action_runner._write_step_summary("## hello")
        with open(path) as f:
            self.assertIn("hello", f.read())

    def test_no_op_without_env_var(self):
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_STEP_SUMMARY"}
        with patch.dict(os.environ, env, clear=True):
            action_runner._write_step_summary("should not crash")


# --------------------------------------------------------------------------- #
# _format_report
# --------------------------------------------------------------------------- #

class TestFormatReport(unittest.TestCase):
    def _snap(self, terminal="pr_merged", checks=None, qc=None):
        return {
            "pr_number": 42,
            "head_sha_short": "abc1234",
            "terminal": terminal,
            "checks": checks or [],
            "cost_summary": {"retries_used_pr": 2, "retries_max_pr": 5,
                              "minutes_spent": 15, "minutes_max": 90},
            "quarantine_candidates": qc or [],
        }

    def test_contains_pr_and_sha(self):
        report = action_runner._format_report(self._snap())
        self.assertIn("PR #42", report)
        self.assertIn("abc1234", report)

    def test_contains_budget(self):
        report = action_runner._format_report(self._snap())
        self.assertIn("2/5", report)
        self.assertIn("15/90", report)

    def test_contains_terminal(self):
        report = action_runner._format_report(self._snap("needs_help"))
        self.assertIn("needs_help", report)
        self.assertIn("🚨", report)

    def test_failed_checks_table(self):
        checks = [{
            "name": "test/unit",
            "conclusion": "failure",
            "classification": {"category": "test_flake", "confidence": "high"},
        }]
        report = action_runner._format_report(self._snap(checks=checks))
        self.assertIn("test/unit", report)
        self.assertIn("test_flake", report)
        self.assertIn("high", report)

    def test_quarantine_candidates_shown(self):
        qc = [{"test": "tests/auth.py::test_login", "flake_rate": 0.8}]
        report = action_runner._format_report(self._snap(qc=qc))
        self.assertIn("quarantine", report)

    def test_no_table_when_no_failures(self):
        checks = [{"name": "test/unit", "conclusion": "success", "classification": {}}]
        report = action_runner._format_report(self._snap(checks=checks))
        self.assertNotIn("| Check |", report)


# --------------------------------------------------------------------------- #
# Pass-through
# --------------------------------------------------------------------------- #

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
