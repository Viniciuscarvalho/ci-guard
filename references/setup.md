# Per-project setup

Adopting `ci-guard` in a new repo takes about three minutes. The skill itself
is installed once per machine; each repo just needs a `.ci-guard/` directory
with two files.

## One-time machine setup

ci-guard works with any agent. The Python scripts have no LLM dependency —
the agent only reads the `SKILL.md` playbook and drives the scripts. Only the
install path differs per agent.

### Skills.sh-compatible runtimes (Claude Code, Codex, opencode)

```bash
# Auto-detects your runtime and installs to the right path
npx skills add https://github.com/Viniciuscarvalho/ci-guard --skill ci-guard
```

Or symlink your local copy directly:

```bash
# Claude Code
ln -s /path/to/ci-guard ~/.claude/skills/ci-guard

# Codex
ln -s /path/to/ci-guard ~/.codex/skills/ci-guard

# opencode
ln -s /path/to/ci-guard ~/.opencode/skills/ci-guard
```

The per-repo bootstrap below uses `$SKILLS_HOME` to find the scripts. If your
agent sets a different env var, override `SKILL_DIR` manually.

### Agents without a native skill path (Gemini CLI, Cursor, Copilot, etc.)

These agents have no `~/.agent/skills/` convention. Instead, deliver the
playbook by pasting `SKILL.md` content into your agent context file:

| Agent                        | Context file                                    |
| ---------------------------- | ----------------------------------------------- |
| Gemini CLI                   | `.gemini/GEMINI.md` or `GEMINI.md` at repo root |
| Cursor                       | `.cursorrules`                                  |
| GitHub Copilot               | `.github/copilot-instructions.md`               |
| Any (`AGENTS.md` convention) | `AGENTS.md` at repo root                        |

The `.ci-guard/scripts/` directory and all commands work identically regardless
of which agent is reading the instructions.

### Required: `gh` CLI

All scripts call `gh` for GitHub API access. Run `gh auth status` before using
any script — it must show the repo's host as authenticated.

## Per-repo setup (copy-paste)

From the repo root:

```bash
mkdir -p .ci-guard/scripts
# Copy the three scripts from the skill into the repo so CI runners can find
# them at the path the SKILL.md uses. Adjust SKILL_DIR for your install.
SKILL_DIR="${SKILLS_HOME:-$HOME/.claude/skills}/ci-guard"
cp "$SKILL_DIR/scripts/"*.py .ci-guard/scripts/
chmod +x .ci-guard/scripts/*.py

# Initial config (defaults are fine; tune later)
cat > .ci-guard/config.yml <<'YAML'
# Per-project ci-guard config. Defaults shown; uncomment to override.
# retries_per_job: 2
# retries_per_pr: 5
# minutes_per_pr: 90
# watch_interval_seconds: 60
YAML

# Empty ledger
echo '{"version": 1, "tests": {}, "history": []}' > .ci-guard/flaky-ledger.json

# State is per-machine; never commit it.
echo ".ci-guard/.watch-state.json" >> .gitignore

git add .ci-guard .gitignore
git commit -m "ci-guard: bootstrap"
```

After that, the skill works against the repo from any machine that has the
skill installed and `gh` authenticated.

## Why scripts live in the repo (`.ci-guard/scripts/`)

Two reasons:

1. **CI runners don't have the skill installed.** When CI itself wants to
   call `flaky_ledger.py record-failure` after a test fails, the script needs
   to be on disk in the repo.
2. **Pinning.** Every PR's behavior is reproducible from its own SHA; a skill
   update on one developer's machine doesn't silently change another
   developer's results.

The cost is that the scripts are duplicated across repos. If that becomes a
maintenance burden, an alternative is to commit a thin `.ci-guard/version`
file pointing at a specific skill release and have a CI step `npm install`
that release. For most teams the duplication is fine.

## Wiring the skill into CI itself

You don't need to. The skill is designed to be invoked by Claude on demand,
not as part of every CI run. But two optional hooks pay back quickly:

### Hook 1: record passes/failures from the test runner

In your test workflow's "after tests" step:

```yaml
- name: Update flaky ledger
  if: always()
  run: |
    ci-guard ledger record-failure \
      --test "${TEST_ID}" --sha "${{ github.sha }}" --run-id "${{ github.run_id }}" || true
```

The exact wiring depends on the test framework. Most produce a JUnit XML
file; a small shell loop over the failed cases is enough. Use `|| true` so
ledger update failures never break the build itself.

### Hook 2: refuse merges with quarantine candidates

A required status check that runs:

```yaml
- name: Quarantine guard
  run: |
    if [ -n "$(ci-guard ledger quarantine-candidates | jq -r '.[]')" ]; then
      echo "::warning::Quarantine candidates exist; review before merging."
      ci-guard ledger quarantine-candidates
    fi
```

This is a warning, not a hard block — quarantine is a human-judgment call.
Some teams escalate it to a hard block once they're comfortable with the
threshold; that's a project-by-project decision.

## Config schema

`.ci-guard/config.yml` is a flat key/value file (the parser is intentionally
minimal so the skill has no YAML dependency). Supported keys:

| Key                            | Type  | Default | Notes                                                                              |
| ------------------------------ | ----- | ------- | ---------------------------------------------------------------------------------- |
| `retries_per_job`              | int   | 2       | Hard cap on reruns of a single job within one PR.                                  |
| `retries_per_pr`               | int   | 5       | Hard cap on total reruns across all jobs in one PR.                                |
| `minutes_per_pr`               | int   | 90      | Cumulative CI minutes consumed by reruns.                                          |
| `watch_interval_seconds`       | int   | 60      | Polling cadence for `--watch`.                                                     |
| `quarantine_failure_threshold` | int   | 3       | Failures in 30d before a test becomes a quarantine candidate.                      |
| `quarantine_rate_threshold`    | float | 0.05    | Flake rate threshold (5%).                                                         |
| `record_passes_for_untracked`  | bool  | false   | If true, record passes for tests not yet in the ledger. Almost always leave false. |

## Migrating an existing flaky-test list

If you already track flaky tests in a Markdown file or a spreadsheet, you can
seed the ledger directly:

```bash
for test_id in tests/foo.py::test_bar tests/baz.py::test_qux; do
  ci-guard ledger record-failure --test "$test_id"
done
```

Each `record-failure` adds an event dated _now_, so all the migrated tests
will have a `failure_count_30d` of 1 to start. They'll need real failures
before they cross the quarantine threshold, which is correct — the skill
shouldn't quarantine on hearsay.
