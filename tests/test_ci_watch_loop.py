import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ci_guard.watch import CheckSnapshot, Snapshot, _terminal_exit_code, decide_actions


def _budget(exhausted=False, retries_used=0):
    return {
        "retries_used_pr": retries_used,
        "retries_max_pr": 5,
        "retries_used_per_job": {},
        "retries_max_per_job": 2,
        "minutes_spent": 0,
        "minutes_max": 90,
        "any_budget_exhausted": exhausted,
    }


def _check(name="job", conclusion="failure", category="branch_failure", flaky_history=None):
    c = CheckSnapshot(
        name=name,
        workflow="CI",
        status="completed",
        conclusion=conclusion,
        run_id="1",
        duration_seconds=10,
        started_at=None,
    )
    c.classification = (
        {"category": category, "confidence": "high", "reason": "test"} if category else {}
    )
    c.flaky_history = flaky_history or {}
    return c


def _snap(pr_state="OPEN", mergeable="MERGEABLE", checks=None, quarantine_candidates=None):
    return Snapshot(
        pr_number=1,
        head_sha="abc",
        head_sha_short="abc",
        pr_state=pr_state,
        mergeable=mergeable,
        checks=checks or [],
        quarantine_candidates=quarantine_candidates or [],
    )


class TestDecideActions(unittest.TestCase):

    # --- terminal conditions ---

    def test_pr_merged_terminal(self):
        actions, terminal = decide_actions(_snap(pr_state="MERGED"), _budget())
        self.assertEqual(terminal, "pr_merged")
        self.assertEqual(actions[0], {"action": "stop", "reason": "pr_merged"})

    def test_pr_closed_terminal(self):
        _, terminal = decide_actions(_snap(pr_state="CLOSED"), _budget())
        self.assertEqual(terminal, "pr_closed")

    def test_budget_exhausted_with_quarantine_needs_help(self):
        candidates = [{"test": "tests/a.py::t1", "failure_count_30d": 5, "flake_rate": 0.8}]
        snap = _snap(checks=[_check(category="infra_flake")], quarantine_candidates=candidates)
        _, terminal = decide_actions(snap, _budget(exhausted=True))
        self.assertEqual(terminal, "needs_help")

    def test_budget_exhausted_no_quarantine_budget_exhausted(self):
        snap = _snap(checks=[_check(category="infra_flake")])
        _, terminal = decide_actions(snap, _budget(exhausted=True))
        self.assertEqual(terminal, "budget_exhausted")

    # --- action directives ---

    def test_branch_failure_includes_diagnose_action(self):
        snap = _snap(checks=[_check(category="branch_failure")])
        actions, _ = decide_actions(snap, _budget())
        action_types = [a["action"] for a in actions]
        self.assertIn("diagnose_branch_failure", action_types)

    def test_branch_failure_check_name_in_action(self):
        snap = _snap(checks=[_check(name="lint", category="branch_failure")])
        actions, _ = decide_actions(snap, _budget())
        diag = next(a for a in actions if a["action"] == "diagnose_branch_failure")
        self.assertIn("lint", diag["checks"])

    def test_branch_failure_no_retry_failed_now(self):
        snap = _snap(checks=[_check(category="branch_failure")])
        actions, _ = decide_actions(snap, _budget())
        action_types = [a["action"] for a in actions]
        self.assertNotIn("retry_failed_now", action_types)

    def test_flaky_failure_within_budget_retries(self):
        snap = _snap(checks=[_check(category="test_flake")])
        actions, _ = decide_actions(snap, _budget(exhausted=False))
        action_types = [a["action"] for a in actions]
        self.assertIn("retry_failed_now", action_types)

    def test_infra_flake_within_budget_retries(self):
        snap = _snap(checks=[_check(category="infra_flake")])
        actions, _ = decide_actions(snap, _budget(exhausted=False))
        action_types = [a["action"] for a in actions]
        self.assertIn("retry_failed_now", action_types)

    def test_budget_exhausted_no_retry_failed_now(self):
        snap = _snap(checks=[_check(category="test_flake")])
        actions, _ = decide_actions(snap, _budget(exhausted=True))
        action_types = [a["action"] for a in actions]
        self.assertNotIn("retry_failed_now", action_types)

    def test_verify_flaky_green(self):
        c = _check(conclusion="success", category=None,
                   flaky_history={"tests/a.py::t": {"failure_count_30d": 3}})
        snap = _snap(checks=[c])
        actions, _ = decide_actions(snap, _budget())
        action_types = [a["action"] for a in actions]
        self.assertIn("verify_flaky_green", action_types)

    def test_unknown_failure_diagnose_unknown(self):
        snap = _snap(checks=[_check(category="unknown")])
        actions, _ = decide_actions(snap, _budget())
        action_types = [a["action"] for a in actions]
        self.assertIn("diagnose_unknown", action_types)

    # --- non-terminal cases ---

    def test_conflicting_not_terminal(self):
        snap = _snap(mergeable="CONFLICTING")
        _, terminal = decide_actions(snap, _budget())
        self.assertIsNone(terminal)

    def test_all_green_idle(self):
        c = _check(conclusion="success", category=None)
        snap = _snap(checks=[c])
        actions, terminal = decide_actions(snap, _budget())
        self.assertIsNone(terminal)
        self.assertEqual(actions, [{"action": "idle"}])

    def test_no_checks_idle(self):
        actions, terminal = decide_actions(_snap(), _budget())
        self.assertIsNone(terminal)
        self.assertEqual(actions, [{"action": "idle"}])

    # --- terminal always includes a stop action ---

    def test_terminal_includes_stop_action(self):
        _, terminal = decide_actions(_snap(pr_state="MERGED"), _budget())
        self.assertEqual(terminal, "pr_merged")

    def test_needs_help_includes_stop_action(self):
        candidates = [{"test": "t", "failure_count_30d": 5, "flake_rate": 0.8}]
        snap = _snap(checks=[_check(category="test_flake")], quarantine_candidates=candidates)
        actions, terminal = decide_actions(snap, _budget(exhausted=True))
        self.assertEqual(terminal, "needs_help")
        action_types = [a["action"] for a in actions]
        self.assertIn("stop", action_types)
        stop = next(a for a in actions if a["action"] == "stop")
        self.assertEqual(stop["reason"], "needs_help")


class TestTerminalExitCode(unittest.TestCase):

    def test_pr_merged_exits_0(self):
        self.assertEqual(_terminal_exit_code("pr_merged"), 0)

    def test_pr_closed_exits_0(self):
        self.assertEqual(_terminal_exit_code("pr_closed"), 0)

    def test_needs_help_exits_2(self):
        self.assertEqual(_terminal_exit_code("needs_help"), 2)

    def test_budget_exhausted_exits_3(self):
        self.assertEqual(_terminal_exit_code("budget_exhausted"), 3)


class TestCmdWatch(unittest.TestCase):
    """Smoke tests for cmd_watch loop behavior using mocked I/O."""

    def _make_snap(self, pr_state="OPEN", terminal=None, actions=None):
        s = _snap(pr_state=pr_state)
        s.terminal = terminal
        s.actions = actions or [{"action": "idle"}]
        return s

    @patch("ci_guard.watch._sleep")
    @patch("ci_guard.watch.save_state")
    @patch("ci_guard.watch.load_state")
    @patch("ci_guard.watch._auto_record_events")
    @patch("ci_guard.watch.assemble_snapshot")
    def test_watch_exits_0_on_pr_merged(self, mock_snap, mock_record, mock_load,
                                        mock_save, mock_sleep):
        from ci_guard.watch import cmd_watch
        mock_load.return_value = {"state_version": 1, "prs": {}}
        mock_snap.return_value = self._make_snap(
            pr_state="MERGED", terminal="pr_merged",
            actions=[{"action": "stop", "reason": "pr_merged"}],
        )
        result = cmd_watch(1, Path("/tmp"))
        self.assertEqual(result, 0)
        mock_sleep.assert_not_called()

    @patch("ci_guard.watch._sleep")
    @patch("ci_guard.watch.save_state")
    @patch("ci_guard.watch.load_state")
    @patch("ci_guard.watch._auto_record_events")
    @patch("ci_guard.watch.assemble_snapshot")
    def test_watch_exits_2_on_needs_help(self, mock_snap, mock_record, mock_load,
                                         mock_save, mock_sleep):
        from ci_guard.watch import cmd_watch
        mock_load.return_value = {"state_version": 1, "prs": {}}
        mock_snap.return_value = self._make_snap(
            terminal="needs_help",
            actions=[{"action": "diagnose_branch_failure", "checks": ["job"]},
                     {"action": "stop", "reason": "needs_help"}],
        )
        result = cmd_watch(1, Path("/tmp"))
        self.assertEqual(result, 2)

    @patch("ci_guard.watch._sleep")
    @patch("ci_guard.watch.save_state")
    @patch("ci_guard.watch.load_state")
    @patch("ci_guard.watch._auto_record_events")
    @patch("ci_guard.watch.assemble_snapshot")
    def test_watch_exits_3_on_budget_exhausted(self, mock_snap, mock_record, mock_load,
                                               mock_save, mock_sleep):
        from ci_guard.watch import cmd_watch
        mock_load.return_value = {"state_version": 1, "prs": {}}
        mock_snap.return_value = self._make_snap(
            terminal="budget_exhausted",
            actions=[{"action": "stop", "reason": "budget_exhausted"}],
        )
        result = cmd_watch(1, Path("/tmp"))
        self.assertEqual(result, 3)

    @patch("ci_guard.watch._sleep")
    @patch("ci_guard.watch.save_state")
    @patch("ci_guard.watch.load_state")
    @patch("ci_guard.watch._auto_record_events")
    @patch("ci_guard.watch.assemble_snapshot")
    def test_watch_sleeps_when_no_state_change(self, mock_snap, mock_record, mock_load,
                                               mock_save, mock_sleep):
        """When SHA and check states don't change, _sleep is called."""
        from ci_guard.watch import cmd_watch
        mock_load.return_value = {"state_version": 1, "prs": {"1": {"last_seen_sha": "abc"}}}
        idle_snap = self._make_snap()
        idle_snap.head_sha = "abc"
        terminal_snap = self._make_snap(terminal="pr_closed",
                                        actions=[{"action": "stop", "reason": "pr_closed"}])
        terminal_snap.head_sha = "abc"
        mock_snap.side_effect = [idle_snap, terminal_snap]
        cmd_watch(1, Path("/tmp"))
        mock_sleep.assert_called_once()

    @patch("ci_guard.watch._sleep")
    @patch("ci_guard.watch.save_state")
    @patch("ci_guard.watch.load_state")
    @patch("ci_guard.watch._auto_record_events")
    @patch("ci_guard.watch.assemble_snapshot")
    def test_watch_skips_sleep_on_state_change(self, mock_snap, mock_record, mock_load,
                                               mock_save, mock_sleep):
        """When SHA changes between iterations, _sleep is NOT called."""
        from ci_guard.watch import cmd_watch
        mock_load.return_value = {"state_version": 1, "prs": {}}
        first_snap = self._make_snap()
        first_snap.head_sha = "sha1"
        terminal_snap = self._make_snap(terminal="pr_merged",
                                        actions=[{"action": "stop", "reason": "pr_merged"}])
        terminal_snap.head_sha = "sha2"  # different SHA → state changed
        mock_snap.side_effect = [first_snap, terminal_snap]
        cmd_watch(1, Path("/tmp"))
        mock_sleep.assert_not_called()

    @patch("ci_guard.watch._sleep")
    @patch("ci_guard.watch.save_state")
    @patch("ci_guard.watch.load_state")
    @patch("ci_guard.watch._auto_record_events")
    @patch("ci_guard.watch.assemble_snapshot")
    def test_watch_fast_exit_on_last_terminal(self, mock_snap, mock_record, mock_load,
                                              mock_save, mock_sleep):
        """If last_terminal is already recorded, cmd_watch exits without polling."""
        from ci_guard.watch import cmd_watch
        mock_load.return_value = {
            "state_version": 1,
            "prs": {"1": {"last_terminal": "pr_merged"}},
        }
        result = cmd_watch(1, Path("/tmp"))
        self.assertEqual(result, 0)
        mock_snap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
