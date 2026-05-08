# Troubleshooting

## `gh: command not found` or authentication errors

ci-guard shells out to `gh` for all GitHub API calls. Verify it is installed and
authenticated:

```bash
gh --version
gh auth status
```

If `gh auth status` shows no active login, run:

```bash
gh auth login
```

For CI environments (`deliver.yml`), `GH_TOKEN` must be set in the workflow step's
`env:` block. The default `GITHUB_TOKEN` secret is sufficient — no personal access
token is needed.

## "scripts are stale" warning on every run

```
[ci-guard] scripts are stale (local 0.3.0, skill 0.4.0). Re-run bootstrap…
```

Your per-project `.ci-guard/scripts/` snapshot is older than the installed skill.
Re-run bootstrap from the project root and commit:

```bash
python3 /path/to/ci-guard/scripts/bootstrap.py
git add .ci-guard/scripts && git commit -m "chore: update ci-guard scripts"
```

See [`docs/updating.md`](updating.md) for the full update workflow.

## `flaky-ledger.json` shows wrong counts

Never edit `.ci-guard/flaky-ledger.json` by hand — the derived fields
(`failure_count_30d`, `flake_rate`) are recomputed from the `events` array and will
desync if you edit them directly. Always use the CLI:

```bash
# Record a failure
python3 .ci-guard/scripts/flaky_ledger.py record-failure \
    --test "<test-id>" --sha <sha> --run-id <run-id>

# Mark a test quarantined
python3 .ci-guard/scripts/flaky_ledger.py set-status \
    --test "<test-id>" --status quarantined \
    --issue-url "https://github.com/org/repo/issues/<n>"

# Remove stale entries
python3 .ci-guard/scripts/flaky_ledger.py prune --older-than 60
```

If the file is already corrupt, restore it from git history
(`git checkout HEAD -- .ci-guard/flaky-ledger.json`) and re-record the missing events.

## `--watch` process left running after a session ends

`--watch` streams JSONL until a terminal state is reached. If the agent turn ends
before a terminal state, the subprocess may be left running in the background.

Find and stop it:

```bash
pkill -f "ci_watch.py.*--watch"
```

For programmatic callers, `action_runner.py` exits with a structured code when the
`stop` action is received:

| Exit code | Terminal state            | Meaning                            |
| --------- | ------------------------- | ---------------------------------- |
| 0         | `pr_merged` / `pr_closed` | Normal completion                  |
| 2         | `needs_help`              | Human or agent must intervene      |
| 3         | `budget_exhausted`        | Reliability problem to investigate |

See `references/wrapper-contract.md` for all terminal values and exit codes.

## `deliver.yml` not posting PR comments on fork PRs

GitHub restricts `pull-requests: write` permission for workflows triggered by forks
when using `pull_request` events. The `workflow_run` trigger used in `deliver.yml`
runs in the base repo's security context and should have full permissions for
same-repo PRs.

For fork PRs you have two options:

1. **Accept the limitation** — annotations in the job log will still appear; only PR
   comments are blocked.
2. **Use `pull_request_target`** — switch the trigger to `pull_request_target` in
   `deliver.yml`. Read GitHub's [security hardening guide](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions#understanding-the-risk-of-script-injections)
   carefully before exposing `GITHUB_TOKEN` to code from a fork.

## Quarantine recommended but no test ID matches in the ledger

The `--test` flag in `flaky_ledger.py` expects the exact test identifier your CI
runner uses. Common framework formats:

| Framework     | Test ID format                           |
| ------------- | ---------------------------------------- |
| pytest        | `tests/path/test_file.py::test_function` |
| Jest / Vitest | `describe block > test name`             |
| Go            | `TestFunctionName/SubtestName`           |
| RSpec         | `path/to/spec.rb[1:1:1]`                 |
| JUnit         | `com.example.ClassName#methodName`       |
| Cargo         | `module::test_name`                      |

If the quarantine candidate shows an ID that does not match your runner's output,
check the `record-failure` hook in your CI workflow — the `TEST_ID` variable may need
to be reformatted to match the framework's convention.

## `bootstrap.py` reports "nothing to do" but `.ci-guard/scripts/` is missing

`bootstrap.py` checks for the `.ci-guard/` directory, not just the scripts. If the
directory exists but the scripts subfolder does not, pass `--force` to re-copy:

```bash
python3 /path/to/ci-guard/scripts/bootstrap.py --force
```

## Classification always returns `unknown`

The classifier uses log-text heuristics from `references/heuristics.md`. `unknown`
is the safe fallback when no pattern matches. Common causes:

- The failing check produces no log output (e.g. a required status check from an
  external service). Use `gh run view <run-id> --log-failed` to inspect manually.
- The log is very large and the relevant error is beyond the heuristic's scan window.
  Pipe the log through `grep` to extract the error lines, then classify manually.
- The failure is genuinely novel. Add a pattern to `references/heuristics.md` and
  open a PR.
