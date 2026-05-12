#!/usr/bin/env python3
# Deprecated shim — re-exports from ci_guard.config for backward compat
from ci_guard.config import (  # noqa: F401
    SCRIPT_VERSION,
    LEDGER_PATH,
    CONFIG_PATH,
    STATE_PATH,
    DEFAULT_BUDGET,
    QUARANTINE_FAIL_THRESHOLD,
    QUARANTINE_RATE_THRESHOLD,
    load_config,
    check_script_freshness,
)
