"""Consume ci-guard watch JSONL and execute action directives.

Pipe ci-guard watch output into this module:
    ci-guard watch --pr auto | ci-guard run-actions

Exit codes:
    0 — pr_merged or pr_closed
    2 — needs_help
    3 — budget_exhausted
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

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
            "run `ci-guard ledger quarantine-candidates`"
        )

    emoji = _TERMINAL_EMOJI.get(terminal, "")
    lines.append(f"\nTerminal: {emoji} `{terminal}`")

    return "\n".join(lines)


def _invoke_ci_guard(pr_number: int, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "ci_guard.cli", "--pr", str(pr_number), *args],
        check=False,
    )


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
            print(f"[ci-guard run-actions] skipping non-JSON line: {raw}",
                  file=sys.stderr, flush=True)
            continue

        if pr_number is None:
            pr_number = snap.get("pr_number")

        last_snap = snap
        print(raw, flush=True)

        for act in snap.get("actions", []):
            action = act.get("action")

            if action == "idle":
                continue
            elif action == "retry_failed_now":
                if pr_number is not None:
                    _invoke_ci_guard(pr_number, "--retry-failed-now")
            elif action == "verify_flaky_green":
                if pr_number is not None:
                    _invoke_ci_guard(pr_number, "--verify-flaky-green")
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


def main() -> int:
    return run()
