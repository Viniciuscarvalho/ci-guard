"""Per-project setup for ci-guard (ci-guard init).

Idempotent: re-running on an already-bootstrapped repo prints current state
without writing. Pass --dry-run to preview changes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_CONFIG_TEMPLATE = """\
# ci-guard per-project configuration.
# Uncomment and adjust any value to override the default.
# retries_per_job: 2
# retries_per_pr: 5
# minutes_per_pr: 90
# watch_interval_seconds: 60
"""

_LEDGER_EMPTY = '{"version": 1, "tests": {}, "history": []}\n'


def _repo_root() -> Path:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(r.stdout.strip()).resolve()
    except subprocess.CalledProcessError:
        sys.stderr.write("ci-guard: not inside a git repository.\n")
        sys.exit(2)
    except FileNotFoundError:
        sys.stderr.write("ci-guard: 'git' not found in PATH.\n")
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


def _remove_legacy_scripts(ci_guard_dir: Path, rep: _Reporter) -> None:
    scripts_dir = ci_guard_dir / "scripts"
    if not scripts_dir.is_dir():
        return
    py_files = list(scripts_dir.glob("*.py"))
    if not py_files:
        return
    rep.write(f"remove legacy {scripts_dir} ({len(py_files)} files) — now provided by pip package")
    if not rep.dry_run:
        import shutil
        shutil.rmtree(scripts_dir)


def run_init(
    repo_root: Path,
    dry_run: bool = False,
    migrate: bool = False,
    force: bool = False,
) -> bool:
    """Bootstrap ci-guard into a repo. Returns True if any changes were made."""
    ci_guard_dir = repo_root / ".ci-guard"

    print("ci-guard init")
    print(f"  repo: {repo_root}")
    print()

    rep = _Reporter(dry_run=dry_run)

    if migrate:
        _remove_legacy_scripts(ci_guard_dir, rep)

    _ensure_dir(ci_guard_dir, ".ci-guard/", rep)
    _write_if_absent(ci_guard_dir / "config.yml", _CONFIG_TEMPLATE, ".ci-guard/config.yml", rep)
    _write_if_absent(ci_guard_dir / "flaky-ledger.json", _LEDGER_EMPTY,
                     ".ci-guard/flaky-ledger.json", rep)
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


def main(args=None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Bootstrap ci-guard into the current git repo.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be done without writing anything.")
    p.add_argument("--migrate", action="store_true",
                   help="Remove legacy .ci-guard/scripts/ copies (from pre-v0.5 bootstrap).")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing config files.")
    parsed = p.parse_args(args)
    run_init(_repo_root(), dry_run=parsed.dry_run, migrate=parsed.migrate, force=parsed.force)
    return 0
