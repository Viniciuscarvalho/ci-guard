"""Tests for GitHub Action manifest and entrypoint."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import action_entrypoint


class TestActionManifest(unittest.TestCase):
    def test_action_yml_exists_and_is_valid(self):
        root = Path(__file__).parent.parent
        action_path = root / "action.yml"
        self.assertTrue(action_path.exists(), "action.yml should exist in repo root")

        content = action_path.read_text(encoding="utf-8")
        self.assertIn("name:", content)
        self.assertIn("runs:", content)
        self.assertIn("using: \"composite\"", content)
        self.assertIn("inputs:", content)
        self.assertIn("outputs:", content)
        self.assertIn("mode:", content)
        self.assertIn("github-token:", content)
        self.assertIn("minutes-saved", content)
        self.assertIn("retries-avoided", content)


class TestActionEntrypoint(unittest.TestCase):
    def test_set_output_single_line(self):
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            temp_path = f.name

        try:
            with patch.dict(os.environ, {"GITHUB_OUTPUT": temp_path}):
                action_entrypoint._set_output("verdict", "green")
            content = Path(temp_path).read_text()
            self.assertEqual(content.strip(), "verdict=green")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_set_output_multiline(self):
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            temp_path = f.name

        try:
            with patch.dict(os.environ, {"GITHUB_OUTPUT": temp_path}):
                action_entrypoint._set_output("report", "line1\nline2\nline3")
            content = Path(temp_path).read_text()
            self.assertIn("report<<EOF_", content)
            self.assertIn("line1\nline2\nline3", content)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_detect_pr_from_input(self):
        self.assertEqual(action_entrypoint._detect_pr("123"), 123)

    def test_detect_pr_from_event_json(self):
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            json.dump({"pull_request": {"number": 99}}, f)
            temp_path = f.name

        try:
            with patch.dict(os.environ, {"GITHUB_EVENT_PATH": temp_path}):
                pr = action_entrypoint._detect_pr("auto")
                self.assertEqual(pr, 99)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("scripts.action_entrypoint.assemble_snapshot")
    @patch("scripts.action_entrypoint._verdict")
    @patch("scripts.action_entrypoint._post_pr_comment")
    @patch("scripts.action_entrypoint._write_step_summary")
    def test_main_gate_mode_success(self, mock_summary, mock_comment, mock_verdict, mock_snap):
        fake_snap = MagicMock()
        fake_snap.pr_number = 42
        fake_snap.head_sha_short = "abc1234"
        fake_snap.checks = []
        fake_snap.quarantine_candidates = []
        fake_snap.cost_summary = {
            "retries_used_pr": 0,
            "retries_max_pr": 5,
            "minutes_spent": 10,
            "minutes_max": 90,
            "retries_avoided_pr": 2,
            "minutes_saved": 15,
        }
        mock_snap.return_value = fake_snap
        mock_verdict.return_value = ("green", 0, [], [], [])

        env = {
            "INPUT_MODE": "gate",
            "INPUT_PR": "42",
            "INPUT_COMMENT": "true",
            "INPUT_SUMMARY": "true",
            "INPUT_FAIL_ON_BLOCK": "true",
        }
        with patch.dict(os.environ, env):
            code = action_entrypoint.main()
            self.assertEqual(code, 0)
            mock_comment.assert_called_once()
            mock_summary.assert_called_once()

    @patch("ci_guard.cli._dispatch")
    def test_cli_report_parser(self, mock_dispatch):
        from ci_guard import cli
        import sys

        test_args = ["ci-guard", "report", "--pr", "42", "--json"]
        with patch.object(sys, "argv", test_args):
            try:
                cli.main()
            except SystemExit:
                pass
            mock_dispatch.assert_called_once()
            args = mock_dispatch.call_args[0][0]
            self.assertEqual(args.command, "report")
            self.assertEqual(args.pr, "42")
            self.assertTrue(args.json_output)


if __name__ == "__main__":
    unittest.main()
