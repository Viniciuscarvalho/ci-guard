"""ci-guard gate — quality-gate check for a PR.

Exit codes
----------
0  GREEN      All checks pass (or PR already merged/closed). Merge allowed.
1  BLOCKED    branch_failure or unknown check present. Code must be fixed.
2  RETRYABLE  infra_flake / test_flake / dependency_failure within budget.
3  EXHAUSTED  Retry budget exhausted, or quarantine candidates present.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ci_guard.watch import CheckSnapshot, Snapshot, assemble_snapshot

EXIT_GREEN = 0
EXIT_BLOCKED = 1
EXIT_RETRYABLE = 2
EXIT_EXHAUSTED = 3

_FAILING = {"failure", "cancelled", "timed_out"}
_HARD_BLOCK_CATEGORIES = {"branch_failure", "unknown"}
_RETRYABLE_CATEGORIES = {"infra_flake", "test_flake", "dependency_failure"}


def _verdict(snap: Snapshot) -> tuple[str, int, list[str], list[str], list[str]]:
    """Return (verdict, exit_code, blocked_checks, unknown_checks, retryable_checks)."""
    if snap.terminal in {"pr_merged", "pr_closed"}:
        return "green", EXIT_GREEN, [], [], []

    blocked = [c.name for c in snap.checks
               if c.classification.get("category") in _HARD_BLOCK_CATEGORIES
               and c.conclusion in _FAILING]
    unknown = [c.name for c in snap.checks
               if c.classification.get("category") == "unknown"
               and c.conclusion in _FAILING]
    retryable = [c.name for c in snap.checks
                 if c.classification.get("category") in _RETRYABLE_CATEGORIES
                 and c.conclusion in _FAILING]

    if blocked:
        return "blocked", EXIT_BLOCKED, blocked, unknown, retryable

    if snap.terminal in {"budget_exhausted", "needs_help"}:
        return "exhausted", EXIT_EXHAUSTED, blocked, unknown, retryable

    if retryable:
        return "retryable", EXIT_RETRYABLE, blocked, unknown, retryable

    any_failing = any(c.conclusion in _FAILING for c in snap.checks)
    if any_failing:
        # Unclassified failure — treat as blocked
        return "blocked", EXIT_BLOCKED, blocked, unknown, retryable

    return "green", EXIT_GREEN, [], [], []


def _print_report(snap: Snapshot, verdict: str, blocked: list[str],
                  unknown: list[str], retryable: list[str]) -> None:
    lines = [
        f"PR #{snap.pr_number}  SHA {snap.head_sha_short}",
        "─" * 40,
    ]

    if blocked:
        lines.append("Blocked checks (must fix code):")
        for name in blocked:
            lines.append(f"  • {name}  [branch_failure]")
    if unknown:
        lines.append("Unknown checks (manual diagnosis required):")
        for name in unknown:
            lines.append(f"  • {name}  [unknown]")
    if retryable:
        budget = snap.cost_summary
        used = budget.get("retries_used_pr", 0)
        max_r = budget.get("retries_max_pr", "?")
        lines.append(f"Retryable checks ({used}/{max_r} PR retries used):")
        for name in retryable:
            lines.append(f"  • {name}")

    if snap.quarantine_candidates:
        lines.append(f"Quarantine candidates: {len(snap.quarantine_candidates)}")

    _LABEL = {
        "green": "GATE PASSED — merge allowed",
        "blocked": "GATE BLOCKED — fix code before merging",
        "retryable": "GATE SOFT-BLOCKED — retry recommended (ci-guard watch --retry-failed-now)",
        "exhausted": "GATE BLOCKED — budget exhausted, investigation required",
    }
    lines.append("")
    lines.append(_LABEL.get(verdict, verdict.upper()))
    print("\n".join(lines))


def cmd_gate(pr: int, repo_root_path: Path, *, json_output: bool = False) -> int:
    snap = assemble_snapshot(pr, repo_root_path)
    verdict, exit_code, blocked, unknown, retryable = _verdict(snap)

    if json_output:
        print(json.dumps({
            "verdict": verdict,
            "exit_code": exit_code,
            "pr": snap.pr_number,
            "sha": snap.head_sha_short,
            "blocked_checks": blocked,
            "unknown_checks": unknown,
            "retryable_checks": retryable,
            "quarantine_candidates": snap.quarantine_candidates,
            "budget": snap.cost_summary,
            "actions": snap.actions,
        }, indent=2, default=str))
    else:
        _print_report(snap, verdict, blocked, unknown, retryable)

    return exit_code
