#!/usr/bin/env python3
# Deprecated shim — logic moved to ci_guard.ledger. Use: ci-guard ledger <subcommand>
import sys
from ci_guard.ledger import main as _orig_main

# Preserve original argparse interface for backward compat
import argparse
import json
from pathlib import Path
from ci_guard.config import LEDGER_PATH
from ci_guard.ledger import (
    cmd_record, cmd_query, cmd_list, cmd_quarantine_candidates,
    cmd_set_status, cmd_prune, cmd_repair,
    QUARANTINE_FAIL_THRESHOLD, QUARANTINE_RATE_THRESHOLD,
)

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ledger", default=LEDGER_PATH)
    sub = p.add_subparsers(dest="cmd", required=True)
    rf = sub.add_parser("record-failure")
    rf.add_argument("--test", required=True)
    rf.add_argument("--sha")
    rf.add_argument("--run-id")
    rp = sub.add_parser("record-pass")
    rp.add_argument("--test", required=True)
    rp.add_argument("--sha")
    rp.add_argument("--run-id")
    q = sub.add_parser("query")
    q.add_argument("--test", required=True)
    q.add_argument("--verbose", action="store_true")
    ls = sub.add_parser("list")
    ls.add_argument("--status", choices=["watched", "quarantined", "fixed"])
    sub.add_parser("quarantine-candidates")
    ss = sub.add_parser("set-status")
    ss.add_argument("--test", required=True)
    ss.add_argument("--status", required=True)
    ss.add_argument("--issue-url")
    pr = sub.add_parser("prune")
    pr.add_argument("--older-than", type=int, default=60)
    sub.add_parser("repair")
    args = p.parse_args()
    dispatch = {
        "record-failure": lambda: cmd_record(args, "fail"),
        "record-pass": lambda: cmd_record(args, "pass"),
        "query": lambda: cmd_query(args),
        "list": lambda: cmd_list(args),
        "quarantine-candidates": lambda: cmd_quarantine_candidates(args),
        "set-status": lambda: cmd_set_status(args),
        "prune": lambda: cmd_prune(args),
        "repair": lambda: cmd_repair(args),
    }
    return dispatch[args.cmd]()

if __name__ == "__main__":
    sys.exit(main())
