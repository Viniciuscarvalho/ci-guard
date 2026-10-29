#!/usr/bin/env python3
"""GitHub Action entry point for ci-guard."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

# Support in-tree execution
_repo_dir = Path(__file__).resolve().parent.parent
_src_dir = _repo_dir / "src"
if _src_dir.exists() and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from ci_guard._providers.github import resolve_pr
from ci_guard.actions import _format_report, _post_pr_comment, _write_step_summary
from ci_guard.gate import _verdict, cmd_gate
from ci_guard.watch import assemble_snapshot, repo_root


def _set_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as fh:
        if "\n" in str(value):
            delim = f"EOF_{uuid.uuid4().hex[:8]}"
            fh.write(f"{name}<<{delim}\n{value}\n{delim}\n")
        else:
            fh.write(f"{name}={value}\n")


def _detect_pr(input_pr: str) -> int:
    if input_pr and input_pr != "auto":
        return resolve_pr(input_pr)

    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and os.path.exists(event_path):
        try:
            with open(event_path, "r", encoding="utf-8") as fh:
                evt = json.load(fh)
            if "pull_request" in evt and "number" in evt["pull_request"]:
                return int(evt["pull_request"]["number"])
            if "workflow_run" in evt:
                head_branch = evt["workflow_run"].get("head_branch")
                if head_branch:
                    out = subprocess.check_output(
                        ["gh", "pr", "list", "--head", head_branch, "--state", "open", "--json", "number", "-q", ".[0].number"],
                        text=True,
                    ).strip()
                    if out and out.isdigit():
                        return int(out)
        except Exception as e:
            sys.stderr.write(f"ci-guard action: error reading event path: {e}\n")

    return resolve_pr("auto")


def _snap_to_dict(snap) -> dict:
    if hasattr(snap, "__dataclass_fields__"):
        return asdict(snap)
    if isinstance(snap, dict):
        return snap
    return {
        "pr_number": getattr(snap, "pr_number", 0),
        "head_sha_short": getattr(snap, "head_sha_short", ""),
        "terminal": getattr(snap, "terminal", None),
        "checks": getattr(snap, "checks", []),
        "cost_summary": getattr(snap, "cost_summary", {}),
        "quarantine_candidates": getattr(snap, "quarantine_candidates", []),
    }


def main() -> int:
    mode = os.environ.get("INPUT_MODE", "gate").strip().lower()
    input_pr = os.environ.get("INPUT_PR", "auto").strip()
    comment_pr = os.environ.get("INPUT_COMMENT", "true").strip().lower() == "true"
    post_summary = os.environ.get("INPUT_SUMMARY", "true").strip().lower() == "true"
    fail_on_block = os.environ.get("INPUT_FAIL_ON_BLOCK", "true").strip().lower() == "true"

    root = repo_root()

    try:
        pr_number = _detect_pr(input_pr)
    except Exception as e:
        sys.stderr.write(f"::error::ci-guard could not resolve PR number: {e}\n")
        return 1

    if mode in {"gate", "report"}:
        snap = assemble_snapshot(pr_number, root)
        verdict, exit_code, blocked, unknown, retryable = _verdict(snap)
        snap_dict = _snap_to_dict(snap)
        report = _format_report(snap_dict)
        cost = snap_dict.get("cost_summary", {})

        minutes_saved = str(cost.get("minutes_saved", 0))
        retries_avoided = str(cost.get("retries_avoided_pr", len(blocked)))
        minutes_spent = str(cost.get("minutes_spent", 0))

        _set_output("verdict", verdict)
        _set_output("exit-code", str(exit_code))
        _set_output("minutes-saved", minutes_saved)
        _set_output("retries-avoided", retries_avoided)
        _set_output("minutes-spent", minutes_spent)
        _set_output("report", report)

        if mode == "gate":
            print(f"ci-guard gate: verdict={verdict} exit_code={exit_code}", flush=True)

        if comment_pr:
            _post_pr_comment(pr_number, report)

        if post_summary:
            _write_step_summary(report)

        if mode == "gate" and fail_on_block and exit_code != 0:
            return exit_code
        return 0

    elif mode == "guard":
        # Continuous watcher piping into action runner
        from ci_guard.actions import run as run_actions
        from ci_guard.watch import cmd_watch
        import io

        # Run watch in a subprocess or stream
        proc = subprocess.Popen(
            [sys.executable, "-m", "ci_guard.cli", "watch", "--pr", str(pr_number), "--stream"],
            stdout=subprocess.PIPE,
            text=True,
        )
        code = run_actions(proc.stdout)
        proc.wait()

        # Capture snapshot for outputs
        snap = assemble_snapshot(pr_number, root)
        snap_dict = asdict(snap)
        cost = snap_dict.get("cost_summary", {})
        _set_output("terminal", snap.terminal or "none")
        _set_output("exit-code", str(code))
        _set_output("minutes-saved", str(cost.get("minutes_saved", 0)))
        _set_output("retries-avoided", str(cost.get("retries_avoided_pr", 0)))
        _set_output("minutes-spent", str(cost.get("minutes_spent", 0)))

        return code

    else:
        sys.stderr.write(f"::error::Unknown mode '{mode}'. Choose 'gate', 'guard', or 'report'.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
