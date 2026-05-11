"""ci-guard — unified CLI entry point."""

from __future__ import annotations

import sys


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(
        prog="ci-guard",
        description="Guard CI from wasted minutes — classify failures and maintain a flaky-test ledger.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {_version()}")

    sub = p.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # init
    sub.add_parser("init", help="Bootstrap ci-guard into the current git repo.",
                   add_help=True)

    # watch
    w = sub.add_parser("watch", help="Snapshot CI state for a PR.")
    w.add_argument("--pr", default="auto",
                   help="PR number, URL, or 'auto' (default).")
    wm = w.add_mutually_exclusive_group()
    wm.add_argument("--once", action="store_true", default=True,
                    help="Single snapshot (default).")
    wm.add_argument("--stream", action="store_true",
                    help="Continuous JSONL stream until PR closes.")
    wm.add_argument("--retry-failed-now", action="store_true",
                    help="Trigger budget-aware reruns of failed checks.")
    wm.add_argument("--verify-flaky-green", action="store_true",
                    help="Re-run checks that flipped green but match the ledger.")

    # classify
    c = sub.add_parser("classify", help="Classify a CI failure log.")
    csrc = c.add_mutually_exclusive_group(required=True)
    csrc.add_argument("--run-id", help="Fetch failed log via gh CLI.")
    csrc.add_argument("--log-file", help="Path to a log file on disk.")
    csrc.add_argument("--stdin", action="store_true", help="Read log from stdin.")
    c.add_argument("--check-name", default=None)

    # ledger
    from ci_guard import ledger as _ledger
    _ledger.build_parser(sub)

    # run-actions
    sub.add_parser("run-actions",
                   help="Consume ci-guard watch JSONL and post PR comments/annotations.")

    # install-skill  (no-op in v0.5, implemented in v0.7)
    _is = sub.add_parser("install-skill",
                         help="Install ci-guard skill for AI agent(s). [available in v0.7]")
    _is.add_argument("--agent",
                     choices=["claude", "codex", "opencode", "skills-sh", "all"],
                     default="all")
    _is.add_argument("--copy", action="store_true",
                     help="Copy files instead of symlinking (useful on Windows).")

    args = p.parse_args()
    sys.exit(_dispatch(args))


def _version() -> str:
    from ci_guard import __version__
    return __version__


def _dispatch(args) -> int:
    cmd = args.command

    if cmd == "init":
        from ci_guard.init import main as _main
        return _main([])

    if cmd == "watch":
        import argparse as _ap
        # Rebuild the args that watch.main() expects
        watch_args = ["--pr", args.pr]
        if getattr(args, "stream", False):
            watch_args.append("--watch")
        elif getattr(args, "retry_failed_now", False):
            watch_args.append("--retry-failed-now")
        elif getattr(args, "verify_flaky_green", False):
            watch_args.append("--verify-flaky-green")
        else:
            watch_args.append("--once")
        from ci_guard.watch import main as _main
        return _main(watch_args)

    if cmd == "classify":
        import json
        from ci_guard.classify import classify, fetch_log
        if args.run_id:
            log = fetch_log(args.run_id)
        elif args.log_file:
            log = open(args.log_file, encoding="utf-8", errors="replace").read()
        else:
            log = sys.stdin.read()
        result = classify(log)
        if args.check_name:
            result["check_name"] = args.check_name
        print(json.dumps(result, indent=2))
        return 0

    if cmd == "ledger":
        from ci_guard import ledger as _ledger
        return _ledger.dispatch(args)

    if cmd == "run-actions":
        from ci_guard.actions import run
        return run()

    if cmd == "install-skill":
        print("ci-guard: install-skill is available in v0.7. "
              "Until then, symlink SKILL.md manually:\n"
              "  ln -s /path/to/ci-guard/SKILL.md ~/.claude/skills/ci-guard/SKILL.md",
              file=sys.stderr)
        return 1

    return 0
