"""Shared paths, defaults, and config loader for ci-guard."""

from __future__ import annotations

from pathlib import Path

from ci_guard import __version__

SCRIPT_VERSION = __version__

_SKILL_SEARCH_PATHS = [
    Path.home() / ".claude" / "skills" / "ci-guard" / "SKILL.md",
    Path.home() / ".codex" / "skills" / "ci-guard" / "SKILL.md",
    Path.home() / ".opencode" / "skills" / "ci-guard" / "SKILL.md",
]

LEDGER_PATH = ".ci-guard/flaky-ledger.json"
CONFIG_PATH = ".ci-guard/config.yml"
STATE_PATH = ".ci-guard/.watch-state.json"

DEFAULT_BUDGET: dict = {
    "retries_per_job": 2,
    "retries_per_pr": 5,
    "minutes_per_pr": 90,
    "watch_interval_seconds": 60,
}

QUARANTINE_FAIL_THRESHOLD: int = 3
QUARANTINE_RATE_THRESHOLD: float = 0.05


def _parse_skill_version(skill_md: Path) -> str | None:
    try:
        in_front = False
        for line in skill_md.read_text().splitlines():
            if line.strip() == "---":
                if not in_front:
                    in_front = True
                    continue
                break
            if in_front and line.startswith("version:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def check_script_freshness() -> str | None:
    skill_version: str | None = None
    for candidate in _SKILL_SEARCH_PATHS:
        v = _parse_skill_version(candidate)
        if v is not None:
            skill_version = v
            break

    if skill_version is None:
        return None

    if _version_tuple(skill_version) > _version_tuple(SCRIPT_VERSION):
        return (
            f"[ci-guard] scripts are stale (local {SCRIPT_VERSION}, "
            f"skill {skill_version}). Run: pip install --upgrade ci-guard"
        )
    return None


def load_config(repo_root: Path) -> dict:
    cfg_path = repo_root / CONFIG_PATH
    cfg = dict(DEFAULT_BUDGET)
    if not cfg_path.exists():
        return cfg
    for line in cfg_path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if v.isdigit():
            cfg[k] = int(v)
        elif v.lower() in {"true", "false"}:
            cfg[k] = v.lower() == "true"
        else:
            cfg[k] = v
    return cfg
