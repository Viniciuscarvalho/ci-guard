#!/usr/bin/env python3
"""bootstrap.py — one-command per-project setup for ci-guard.

Run from the project root (not from inside .ci-guard/):
    python3 /path/to/ci-guard/scripts/bootstrap.py

Idempotent: re-running on an already-bootstrapped repo prints what is
current without writing anything.  Pass --dry-run to preview changes.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_SKILL_SEARCH = [
    Path.home() / ".claude" / "skills" / "ci-guard",
    Path.home() / ".codex" / "skills" / "ci-guard",
    Path.home() / ".opencode" / "skills" / "ci-guard",
]

_CONFIG_TEMPLATE = """\
# ci-guard per-project configuration.
# Uncomment and adjust any value to override the default.
# retries_per_job: 2
# retries_per_pr: 5
# minutes_per_pr: 90
# watch_interval_seconds: 60
"""

_LEDGER_EMPTY = '{"version": 1, "tests": {}, "history": []}\n'


def _find_skill_root(explicit: "Path | None") -> Path:
    if explicit is not None:
        return explicit.resolve()
    # When running directly from the skill's scripts/ dir, the grandparent is
    # the skill root (ci-guard/).
    candidate = Path(__file__).resolve().parent.parent
    if (candidate / "SKILL.md").exists():
        return candidate
    for p in _SKILL_SEARCH:
        if (p / "SKILL.md").exists():
            return p.resolve()
    sys.stderr.write(
        "bootstrap: cannot locate ci-guard skill root.\n"
        "Pass --skill-dir explicitly, e.g.:\n"
        "  python3 bootstrap.py --skill-dir /path/to/ci-guard\n"
    )
    sys.exit(2)


def _repo_root() -> Path:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(r.stdout.strip()).resolve()
    except subprocess.CalledProcessError:
        sys.stderr.write("bootstrap: not inside a git repository.\n")
        sys.exit(2)
    except FileNotFoundError:
        sys.stderr.write("bootstrap: 'git' not found in PATH.\n")
        sys.exit(2)


class _Reporter:
    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.changes: list[str] = []

    def write(self, action: str) -> None:
        self.changes.append(action)
        tag = "[dry-run]" if self.dry_run else "[create] "
        print(f"  {tag} {action}")

    def skip(self, label: str) -> None:
        print(f"  [ok]     {label}")


def _ensure_dir(path: Path, label: str, rep: _Reporter) -> None:
    if path.is_dir():
        rep.skip(label)
    else:
        rep.write(f"create {label}")
        if not rep.dry_run:
            path.mkdir(parents=True, exist_ok=True)


def _copy_scripts(skill_scripts: Path, dest: Path, rep: _Reporter) -> None:
    py_files = sorted(skill_scripts.glob("*.py"))
    if not py_files:
        sys.stderr.write(f"bootstrap: no .py files found in {skill_scripts}\n")
        sys.exit(2)
    for src in py_files:
        dst = dest / src.name
        if dst.exists() and dst.read_bytes() == src.read_bytes():
            rep.skip(f"scripts/{src.name}")
        else:
            rep.write(f"copy scripts/{src.name}")
            if not rep.dry_run:
                shutil.copy2(src, dst)
                dst.chmod(0o755)


def _write_if_absent(path: Path, content: str, label: str, rep: _Reporter) -> None:
    if path.exists():
        rep.skip(label)
    else:
        rep.write(f"create {label}")
        if not rep.dry_run:
            path.write_text(content)


def _append_gitignore(repo_root: Path, entry: str, rep: _Reporter) -> None:
    gi = repo_root / ".gitignore"
    current = gi.read_text() if gi.exists() else ""
    if entry in current.splitlines():
        rep.skip(f".gitignore: {entry}")
        return
    rep.write(f"append '{entry}' to .gitignore")
    if not rep.dry_run:
        tail = "\n" if current and not current.endswith("\n") else ""
        gi.write_text(current + tail + entry + "\n")


def run_bootstrap(repo_root: Path, skill_root: Path, dry_run: bool = False) -> bool:
    """Bootstrap ci-guard into a repo. Returns True if any changes were made."""
    ci_guard_dir = repo_root / ".ci-guard"
    dest_scripts = ci_guard_dir / "scripts"

    print("ci-guard bootstrap")
    print(f"  repo:  {repo_root}")
    print(f"  skill: {skill_root}")
    print()

    rep = _Reporter(dry_run=dry_run)

    _ensure_dir(ci_guard_dir, ".ci-guard/", rep)
    _ensure_dir(dest_scripts, ".ci-guard/scripts/", rep)
    _copy_scripts(skill_root / "scripts", dest_scripts, rep)
    _write_if_absent(
        ci_guard_dir / "config.yml",
        _CONFIG_TEMPLATE,
        ".ci-guard/config.yml",
        rep,
    )
    _write_if_absent(
        ci_guard_dir / "flaky-ledger.json",
        _LEDGER_EMPTY,
        ".ci-guard/flaky-ledger.json",
        rep,
    )
    _append_gitignore(repo_root, ".ci-guard/.watch-state.json", rep)

    print()
    if rep.changes and not dry_run:
        print("Done. Suggested commit:")
        print("  git add .ci-guard .gitignore")
        print('  git commit -m "ci: bootstrap ci-guard"')
    elif rep.changes and dry_run:
        print("Dry run complete — no files written.")
    else:
        print("Nothing to do — repo is already bootstrapped.")

    return bool(rep.changes)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument(
        "--skill-dir", type=Path, metavar="PATH",
        help="Override path to ci-guard skill root.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be done without writing anything.",
    )
    args = p.parse_args()

    skill_root = _find_skill_root(args.skill_dir)
    repo_root = _repo_root()
    run_bootstrap(repo_root, skill_root, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
