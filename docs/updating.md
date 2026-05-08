# Updating ci-guard

ci-guard has two separate update surfaces:

- **The skill** (`SKILL.md` + `scripts/*.py` in the ci-guard repo) — lives on your
  machine, shared across all projects that use ci-guard.
- **Per-project scripts** (`.ci-guard/scripts/*.py`) — a snapshot copied into each
  repo at bootstrap time. These need refreshing after a skill update.

Keeping them in sync is important: `ci_watch.py` checks on every run and prints a
warning to stderr when the per-project snapshot is older than the installed skill
(see [How to tell if your scripts are stale](#how-to-tell-if-your-scripts-are-stale)).

## Step 1 — Update the skill (once per machine)

| Install method            | Update command                                 |
| ------------------------- | ---------------------------------------------- |
| `ln -s` to a git clone    | `cd /path/to/ci-guard && git pull`             |
| `npx skills add ...`      | `npx skills update ci-guard`                   |
| Manual copy of `SKILL.md` | Replace the file with the latest from the repo |

The symlink method (`ln -s`) is recommended: the agent picks up the new `SKILL.md`
immediately without any extra step, because the symlink always points to the current
HEAD of your local clone.

## Step 2 — Refresh per-project scripts (once per repo, after a skill update)

`.ci-guard/scripts/` is a snapshot taken at bootstrap time. Re-run `bootstrap.py`
from the project root to update it:

```bash
python3 /path/to/ci-guard/scripts/bootstrap.py
git add .ci-guard/scripts
git commit -m "chore: update ci-guard scripts to v$(python3 .ci-guard/scripts/config.py 2>/dev/null || echo latest)"
```

`bootstrap.py` is idempotent — running it on an already-current repo prints the
current state without writing anything. Pass `--dry-run` to preview changes before
applying them.

## How to tell if your scripts are stale

`ci_watch.py` reads the `version:` field from your installed `SKILL.md` on every run
and compares it to `SCRIPT_VERSION` in `config.py`. When the skill is newer, it
prints to stderr:

```
[ci-guard] scripts are stale (local 0.3.0, skill 0.4.0). Re-run bootstrap from the repo root:
  python3 /path/to/ci-guard/scripts/bootstrap.py
```

No output means your scripts are current. The warning only fires when
`skill version > local script version` — it is silent when both are equal or when
the skill is not installed at a known path.

To check the local script version directly:

```bash
python3 .ci-guard/scripts/config.py
```

## Version compatibility

`SKILL.md` and `config.py` share a single version string (`0.4.0` as of this
writing). They must match:

- `SKILL.md` frontmatter: `version: 0.4.0`
- `config.py`: `SCRIPT_VERSION = "0.4.0"`

A skill version newer than the local scripts is safe to run — the staleness warning
appears but everything still works. A local scripts version _newer_ than the skill
means the skill was downgraded (unusual); re-install the skill to re-align.

## Updating in CI (deliver.yml)

If you use `deliver.yml` for automatic PR-page surfacing, the workflow checks out
`.ci-guard/scripts/` from the PR's head SHA — so per-project script updates are
picked up automatically on the next commit. No changes to `deliver.yml` are needed
when updating scripts.
