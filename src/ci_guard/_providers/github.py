"""GitHub provider — thin wrapper over the gh CLI.

All GitHub-specific I/O is isolated here to ease future provider swaps (v2.0).
Callers should import from ci_guard.watch, not directly from this module.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from typing import Optional


def gh(*args: str, check: bool = True) -> str:
    """Run a gh command and return stdout, or exit on failure."""
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=check,
        )
        return result.stdout
    except FileNotFoundError:
        sys.stderr.write(
            "ci-guard: 'gh' CLI not found. Install from https://cli.github.com.\n"
        )
        sys.exit(2)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"ci-guard: gh failed: {e.stderr}\n")
        if check:
            sys.exit(2)
        return ""


def gh_returncode(*args: str) -> int:
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True).returncode
    except FileNotFoundError:
        sys.stderr.write("ci-guard: 'gh' CLI not found. Install from https://cli.github.com.\n")
        sys.exit(2)


def resolve_pr(arg: str) -> int:
    if arg == "auto":
        out = gh("pr", "view", "--json", "number")
        return int(json.loads(out)["number"])
    if arg.isdigit():
        return int(arg)
    parts = [p for p in arg.split("/") if p]
    if "pull" in parts:
        idx = parts.index("pull")
        if idx + 1 < len(parts):
            return int(parts[idx + 1])
    raise ValueError(f"Could not resolve PR from: {arg}")


def fetch_pr_state(pr: int) -> dict:
    fields = ",".join([
        "number", "state", "headRefOid", "mergeable", "mergeStateStatus",
        "headRefName", "baseRefName",
    ])
    return json.loads(gh("pr", "view", str(pr), "--json", fields))


def fetch_checks(pr: int) -> list[dict]:
    out = gh("pr", "checks", str(pr), "--json",
             "name,workflow,state,bucket,startedAt,completedAt,link")
    return json.loads(out) if out.strip() else []


def fetch_run_jobs(run_id: str) -> dict:
    return json.loads(gh(
        "run", "view", run_id,
        "--json", "jobs,conclusion,status,name,workflowName,headSha,createdAt,updatedAt",
    ))


def fetch_failed_log(run_id: str, max_chars: int = 20000) -> str:
    raw = gh("run", "view", run_id, "--log-failed", check=False)
    if len(raw) > max_chars:
        return raw[:max_chars // 2] + "\n...[truncated]...\n" + raw[-max_chars // 2:]
    return raw


def normalize_check(c: dict) -> tuple[str, Optional[str], Optional[int]]:
    """Map gh pr checks fields to (status, conclusion, duration_seconds)."""
    bucket = (c.get("bucket") or "").lower()
    status = (
        "completed" if bucket in {"pass", "fail", "cancel", "skipping"}
        else (c.get("state") or "").lower() or "in_progress"
    )
    conclusion = {"pass": "success", "fail": "failure",
                  "cancel": "cancelled", "skipping": "skipped"}.get(bucket)
    duration_seconds = None
    if c.get("startedAt") and c.get("completedAt"):
        try:
            s = datetime.fromisoformat(c["startedAt"].replace("Z", "+00:00"))
            e = datetime.fromisoformat(c["completedAt"].replace("Z", "+00:00"))
            duration_seconds = int((e - s).total_seconds())
        except Exception:
            pass
    return status, conclusion, duration_seconds
