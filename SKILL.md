---
name: ci-guard
version: 0.3.0
description: Guard CI from wasted minutes by classifying failures before retrying, and maintain a persistent flaky-test ledger per repo so chronic flakys get quarantined instead of burning money on every PR. Use this skill whenever the user mentions a failing CI check, a red build, retrying jobs, "rerun failed", flaky tests, intermittent failures, or asks why a build keeps breaking — even if they don't say "guard". Also use proactively before suggesting any `gh run rerun` / "retry" / "rebuild" command, before approving a merge with a recently-rerun green check, and when reviewing CI minute usage or cost reports. If the user asks you to monitor or babysit a PR end-to-end through merge, prefer the babysit-pr skill; ci-guard is the diagnostic + cost layer that babysit-pr can call into.
---

# CI Guard

## Objective

Prevent two specific failure modes that cost teams real money:

1. **Blind retries.** A check fails, someone (or an agent) hits "rerun failed jobs", it passes, the PR merges. The underlying flaky test never gets fixed and burns minutes on every future PR.
2. **Trusting a single green.** A known-flaky test passes once after several failures. The PR merges. Production breaks because the test was actually masking a real regression.

This skill makes Claude refuse to retry a failed check until it has been _classified_, and refuse to trust a green result on a known-flaky test until it has been _verified_.

A secondary goal is keeping a persistent ledger of flaky tests per repo so chronic offenders get quarantined (skipped with an issue filed) instead of being silently retried forever.

## When to use

Trigger this skill when any of these are true:

- A CI check has failed and someone is about to retry it.
- A user asks "why does this keep failing" / "is this flaky" / "should I rerun".
- A previously-failing check has just turned green and a merge is imminent.
- The user is auditing CI minute usage, retry counts, or flaky-test impact.
- An automated agent (including Claude itself in another skill) is about to call `gh run rerun` or equivalent.

Do NOT use this skill for first-time CI setup, writing new tests, or fixing tests — those are different jobs. This skill is purely about _triage and decisions_ on existing failures.

## Inputs

Accept any of:

- No argument: infer the PR from the current branch (`--pr auto`).
- A PR number or URL.
- A specific run-id (when triaging a single failed run outside a PR context).

## Core workflow

The workflow is a strict gate, not a loop. Each gate has to clear before the next one is even considered.

### Gate 1 — Snapshot

Run the watcher to get a structured view of the current state:

```
python3 .ci-guard/scripts/ci_watch.py --pr auto --once
```

Output is JSON containing every failed check with its classification, flaky history, retry budget remaining, and recommended action. Read it before doing anything else. Do not skim the human-readable CI page in lieu of this — the skill's classifications are what gate later actions.

### Gate 2 — Classify each failure

For every failed check, the watcher attaches a classification with one of these categories:

- `branch_failure` — the failure is almost certainly caused by changes on this branch (compile error, test in a touched file, lint/typecheck on a touched file, snapshot mismatch in touched UI). **Never retry.** Patch the code.
- `infra_flake` — runner provisioning failure, network timeout to GitHub itself, registry outage, container pull failure. **Retry is justified, but only within budget.**
- `test_flake` — a test that has a history of intermittent failures in this repo's flaky ledger. **Retry is justified, but the green that follows must be verified (Gate 4).**
- `dependency_failure` — npm/pip/cargo registry returned an error, lockfile drift, transient 5xx from a third party. **Retry once; if it recurs, treat as branch_failure (lockfile likely needs a bump).**
- `unknown` — heuristics couldn't classify. **Do one manual diagnosis pass before any retry.** Read the failed log with `gh run view <id> --log-failed` and decide which of the above buckets it actually belongs in. If still unsure, surface to the user — never default to retry.

The full heuristic decision tree is in `references/heuristics.md`. Read it whenever a classification feels off or the watcher returns `unknown`.

### Gate 3 — Cost guard

Before any retry, check the budget surfaced in the snapshot:

- `retries_used_pr` — total reruns triggered on this PR so far.
- `retries_used_job` — reruns of _this specific job_ so far.
- `pr_minutes_spent` — cumulative CI minutes consumed by this PR.

Default budget (configurable in `.ci-guard/config.yml`):

- 2 retries per job, 5 per PR, 90 cumulative minutes per PR.

If a retry would exceed any budget, **stop and surface the situation to the user**. Do not retry "just one more time". Exceeding the budget almost always means a real bug is being masked or a flaky has crossed the quarantine threshold.

Full cost-control rules and the rationale behind these numbers live in `references/cost-controls.md`.

### Gate 4 — Verify, don't trust

When a check transitions from failing to green:

- If the check's classification was `branch_failure` and the green came after a new commit: trust it. CI is doing its job.
- If the check's classification was `infra_flake` and there was no code change: trust it. The infra issue cleared.
- If the check's classification was `test_flake` (i.e., it appears in the ledger): **do not trust the single green.** Trigger one verification rerun:

  ```
  python3 .ci-guard/scripts/ci_watch.py --pr auto --verify-flaky-green
  ```

  Two consecutive greens on the same SHA are required before the check is considered actually passing. If the verification fails, the test is flakier than the ledger thought — bump its `failure_count_30d` and re-evaluate quarantine status (Gate 5).

This is the rule that protects against single-pass-by-luck merges. It costs one extra rerun on greens, which is a tiny price compared to a bad merge.

### Gate 5 — Quarantine candidates

After updating the ledger from this run's results, check whether any test has crossed the quarantine threshold:

- `failure_count_30d >= 3` AND `flake_rate >= 0.05`.

If so, surface a quarantine recommendation in the final report. Do not auto-quarantine — that's a human-judgment call (the test might be flaky because the _system under test_ is genuinely broken, in which case skipping it would mask a real bug). The recommendation should include:

- The test identifier.
- The flake rate over the last 30 days.
- A suggested skip-pragma snippet for the test framework in use.
- A draft GitHub issue body using `assets/flaky-quarantine-template.md`.

The detailed flaky-detection protocol, including how the ledger is updated and how flake rates are computed, is in `references/flaky-detection.md`.

## Commands

### One-shot snapshot (most common)

```
python3 .ci-guard/scripts/ci_watch.py --pr auto --once
```

### Watch mode (continuous, JSONL output)

```
python3 .ci-guard/scripts/ci_watch.py --pr auto --watch
```

Use only when explicitly asked to monitor. For most diagnostic conversations, `--once` is correct — running `--watch` and ending the turn leaves a stale process behind.

### Trigger a budget-aware retry

```
python3 .ci-guard/scripts/ci_watch.py --pr auto --retry-failed-now
```

Refuses to run if any failure classifies as `branch_failure` or if budgets are exceeded. This is the only sanctioned way to retry — calling `gh run rerun` directly bypasses the cost guard and the ledger update.

### Verify a flaky green

```
python3 .ci-guard/scripts/ci_watch.py --pr auto --verify-flaky-green
```

### Inspect / update the ledger

```
python3 .ci-guard/scripts/flaky_ledger.py query --test "<test-id>"
python3 .ci-guard/scripts/flaky_ledger.py quarantine-candidates
python3 .ci-guard/scripts/flaky_ledger.py prune --older-than 60
```

### Classify an arbitrary log

```
python3 .ci-guard/scripts/classify_failure.py --run-id <id>
python3 .ci-guard/scripts/classify_failure.py --log-file <path>
```

Useful when triaging a failure outside a PR (e.g., a `main`-branch nightly).

## Decision rules at a glance

When a check is failing:

1. classification == `branch_failure` → never retry, patch code instead.
2. classification == `infra_flake` AND budget remaining → retry once.
3. classification == `test_flake` AND budget remaining → retry once, verify green afterward.
4. classification == `dependency_failure` AND first occurrence → retry once. Second occurrence on same SHA → treat as `branch_failure`.
5. classification == `unknown` → read logs, reclassify. If still unknown, surface to user.

When a check just turned green:

1. previously `branch_failure` after a new commit → trust.
2. previously `infra_flake` with no code change → trust.
3. previously `test_flake` (in ledger) → require one verification rerun.
4. greens that came from `--retry-failed-now` while in the test_flake bucket → always verify, even if the watcher didn't flag it.

When budgets are exceeded:

1. Stop. Do not retry. Surface the situation.
2. Check whether any of the recurring failures cross the quarantine threshold.
3. If yes, recommend quarantine.
4. If no, the user has a genuine reliability problem that needs investigation — say so plainly.

## Output expectations

Every invocation should produce a concise, scannable report. Default template:

```
PR #<n>  SHA <short-sha>
─────────────────────────
Failing checks:
  • <name>  [<classification>]  <recommendation>
  ...
Greens-needing-verification:
  • <name>  (in flaky ledger; <fail_rate>% over 30d)
  ...
Budget: <retries_used>/<retries_max> retries, <minutes>/<minutes_max> min spent
Quarantine candidates: <count>  (see ledger query for details)

Recommended next action: <single concrete action>
```

Be explicit about what _not_ to do when a budget is exhausted or a `branch_failure` is present — the value of the skill is partly in saying "do not retry" out loud.

## Git and CI safety rules

- Never run `gh run rerun` directly. Always go through `ci_watch.py --retry-failed-now` so the budget and ledger update.
- Never modify `.ci-guard/flaky-ledger.json` by hand — use `flaky_ledger.py`. Manual edits desync the failure counters.
- Never quarantine a test without explicit user confirmation. The skill _recommends_; the human _decides_.
- When in doubt about a classification, surface the ambiguity. Default-to-retry is exactly the failure mode this skill exists to prevent.

## Per-project setup

A project adopts this skill by adding a `.ci-guard/` directory at its root with two files:

- `.ci-guard/config.yml` — per-project budget overrides and CI-provider hints.
- `.ci-guard/flaky-ledger.json` — persistent flaky-test ledger (committed to the repo so history survives across contributors).

Schema, defaults, and one-shot setup steps are in `references/setup.md`.

## References

- `references/heuristics.md` — failure classification decision tree and log-pattern checklist.
- `references/cost-controls.md` — retry budgets, why the defaults are what they are, and how to tune them.
- `references/flaky-detection.md` — flaky ledger schema, flake rate computation, verification protocol.
- `references/setup.md` — per-project `.ci-guard/` setup, config schema, gitignore guidance.
- `references/ci-providers.md` — adapting the skill for GitLab CI, CircleCI, and Buildkite (the default scripts target GitHub Actions).
- `assets/flaky-quarantine-template.md` — issue body template for quarantine recommendations.
