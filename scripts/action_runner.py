#!/usr/bin/env python3
"""action_runner.py — consume ci_watch --watch JSONL and execute action directives.

Pipe ci_watch --watch output into this script:
    python3 .ci-guard/scripts/ci_watch.py --pr auto --watch | \
    python3 .ci-guard/scripts/action_runner.py

Exit codes mirror ci_watch terminal values:
    0 — pr_merged or pr_closed
    2 — needs_help (human or agent must intervene)
    3 — budget_exhausted (reliability problem to investigate)

GitHub integrations (no-ops outside CI):
  - ::error:: / ::warning:: annotations appear in the job log and Files tab
  - PR comment posted on diagnose_* and on stop (final report)
  - $GITHUB_STEP_SUMMARY written on stop so the deliver check shows a report
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_CI_WATCH = _SCRIPTS_DIR / "ci_watch.py"

_EXIT_CODES: dict[str, int] = {
    "pr_merged": 0,
    "pr_closed": 0,
    "needs_help": 2,
    "budget_exhausted": 3,
}

_TERMINAL_EMOJI: dict[str, str] = {
    "pr_merged": "✅",
    "pr_closed": "🔒",
    "needs_help": "🚨",
    "budget_exhausted": "⚠️",
}


# --------------------------------------------------------------------------- #
# GitHub output helpers — all no-ops when the relevant env var is absent
# --------------------------------------------------------------------------- #

def _annotation(level: str, message: str) -> None:
    print(f"::{level}::{message}", flush=True)


def _post_pr_comment(pr_number: int, body: str) -> None:
    if not os.environ.get("GH_TOKEN"):
        return
    subprocess.run(
        ["gh", "pr", "comment", str(pr_number), "--body", body],
        check=False,
    )


def _write_step_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


# --------------------------------------------------------------------------- #
# Report formatting
# --------------------------------------------------------------------------- #

def _format_report(snap: dict) -> str:
    pr = snap.get("pr_number", "?")
    sha = snap.get("head_sha_short", "?")
    terminal = snap.get("terminal") or "—"
    cost = snap.get("cost_summary", {})
    checks = snap.get("checks", [])
    qc = snap.get("quarantine_candidates", [])

    lines: list[str] = [f"**ci-guard** — PR #{pr} | `{sha}`\n"]

    failed = [
        c for c in checks
        if c.get("conclusion") in {"failure", "cancelled", "timed_out"}
    ]
    if failed:
        lines += [
            "| Check | Classification | Confidence |",
            "|---|---|---|",
        ]
        for c in failed:
            clf = c.get("classification") or {}
            lines.append(
                f"| `{c.get('name', '?')}` "
                f"| `{clf.get('category', '—')}` "
                f"| {clf.get('confidence', '—')} |"
            )
        lines.append("")

    retries_used = cost.get("retries_used_pr", 0)
    retries_max = cost.get("retries_max_pr", "?")
    minutes = cost.get("minutes_spent", 0)
    minutes_max = cost.get("minutes_max", "?")
    lines.append(f"Budget: {retries_used}/{retries_max} retries · {minutes}/{minutes_max} min")

    if qc:
        lines.append(
            f"\n⚠️ {len(qc)} quarantine candidate(s) — "
            "run `flaky_ledger.py quarantine-candidates`"
        )

    emoji = _TERMINAL_EMOJI.get(terminal, "")
    lines.append(f"\nTerminal: {emoji} `{terminal}`")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# ci_watch subprocess helper
# --------------------------------------------------------------------------- #

def _run_ci_watch(pr_number: int, *args: str) -> None:
    subprocess.run(
        [sys.executable, str(_CI_WATCH), "--pr", str(pr_number), *args],
        check=False,
    )


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #

def run(stream=None) -> int:
    if stream is None:
        stream = sys.stdin

    pr_number: int | None = None
    last_snap: dict = {}

    for raw in stream:
        raw = raw.strip()
        if not raw:
            continue

        try:
            snap = json.loads(raw)
        except json.JSONDecodeError:
            print(f"[action_runner] skipping non-JSON line: {raw}", file=sys.stderr, flush=True)
            continue

        if pr_number is None:
            pr_number = snap.get("pr_number")

        last_snap = snap
        print(raw, flush=True)  # pass-through so the caller still sees the stream

        for act in snap.get("actions", []):
            action = act.get("action")

            if action == "idle":
                continue

            elif action == "retry_failed_now":
                if pr_number is not None:
                    _run_ci_watch(pr_number, "--retry-failed-now")

            elif action == "verify_flaky_green":
                if pr_number is not None:
                    _run_ci_watch(pr_number, "--verify-flaky-green")

            elif action == "diagnose_branch_failure":
                checks = ", ".join(act.get("checks", []))
                _annotation("error", f"ci-guard: branch_failure — patch code before retrying: {checks}")
                if pr_number is not None:
                    _post_pr_comment(
                        pr_number,
                        f"**ci-guard** ⛔ `branch_failure` detected\n\n"
                        f"The following checks failed due to changes on this branch "
                        f"— **do not retry**, patch the code first:\n\n"
                        + "\n".join(f"- `{c}`" for c in act.get("checks", [])),
                    )

            elif action == "diagnose_unknown":
                checks = ", ".join(act.get("checks", []))
                _annotation("warning", f"ci-guard: unknown failure — read logs before retrying: {checks}")
                if pr_number is not None:
                    _post_pr_comment(
                        pr_number,
                        f"**ci-guard** ❓ `unknown` failure — manual triage needed\n\n"
                        f"Could not classify the following checks automatically. "
                        f"Read the logs with `gh run view <run-id> --log-failed` "
                        f"before any retry:\n\n"
                        + "\n".join(f"- `{c}`" for c in act.get("checks", [])),
                    )

            elif action == "stop":
                reason = act.get("reason", "")
                code = _EXIT_CODES.get(reason, 0)
                _annotation(
                    "notice" if code == 0 else "warning",
                    f"ci-guard: terminal={reason} exit={code}",
                )
                report = _format_report(last_snap)
                if pr_number is not None:
                    _post_pr_comment(pr_number, report)
                _write_step_summary(report)
                return code

    return 0


if __name__ == "__main__":
    sys.exit(run())
