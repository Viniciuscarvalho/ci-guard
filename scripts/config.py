#!/usr/bin/env python3
"""config.py — shared paths, defaults, and config loader for ci-guard scripts.

Import from a sibling script:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from config import LEDGER_PATH, CONFIG_PATH, STATE_PATH, load_config
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths (relative to repo root)
# --------------------------------------------------------------------------- #

LEDGER_PATH = ".ci-guard/flaky-ledger.json"
CONFIG_PATH = ".ci-guard/config.yml"
STATE_PATH = ".ci-guard/.watch-state.json"  # gitignored

# --------------------------------------------------------------------------- #
# Budget defaults
# --------------------------------------------------------------------------- #

DEFAULT_BUDGET: dict = {
    "retries_per_job": 2,
    "retries_per_pr": 5,
    "minutes_per_pr": 90,
    "watch_interval_seconds": 60,
}

# --------------------------------------------------------------------------- #
# Quarantine thresholds — single source of truth for ci_watch and flaky_ledger
# --------------------------------------------------------------------------- #

QUARANTINE_FAIL_THRESHOLD: int = 3
QUARANTINE_RATE_THRESHOLD: float = 0.05


# --------------------------------------------------------------------------- #
# Config loading
# --------------------------------------------------------------------------- #

def load_config(repo_root: Path) -> dict:
    """Load .ci-guard/config.yml, falling back to DEFAULT_BUDGET for missing keys."""
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
