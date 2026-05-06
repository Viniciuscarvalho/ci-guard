# Cost controls — retry budgets and the rationale behind them

The whole skill exists to make retries *expensive to perform sloppily*. This
document explains the levers, the defaults, and the math that justifies them.

## The two levers

### 1. Retry budgets

Three numbers, all configurable per-project in `.ci-guard/config.yml`:

```yaml
retries_per_job: 2          # rerun any single job at most N times per PR
retries_per_pr: 5           # rerun ANY job at most N times per PR
minutes_per_pr: 90          # cumulative CI minutes consumed by reruns
```

If a retry would push any of these over its limit, the watcher refuses. This
is the only enforcement — there are no warnings or grace periods — because
warnings get ignored in practice and the whole point is friction.

### 2. Classification gating

Even if budgets allow, retries are refused for `branch_failure` and `unknown`
classifications. A budget-exhausted retry that *would* have been a
`branch_failure` is the worst case — it wastes minutes *and* hides a real bug.
Classification gating prevents that case from ever reaching the budget check.

## Why these numbers

The defaults are conservative on purpose. Tighter is safer; loose budgets
defeat the point. The reasoning:

- **2 retries per job.** If a job has failed three times in a row on the same
  SHA, it is not flaky — it is broken. Three is also enough to verify a flaky
  green if the flaky failed once first (fail → retry → pass → verify-pass).
- **5 retries per PR.** Most PRs have 5–15 jobs; if more than five distinct
  reruns are needed to land a single PR, something is structurally wrong.
- **90 minutes per PR.** Median PR CI consumes 15–30 minutes of compute; 90
  is roughly 3–6× that, which catches runaway PRs without flagging normal
  multi-job pipelines.

These are starting points. Tune in `.ci-guard/config.yml` after a couple of
weeks of data. The ledger and your billing dashboard will tell you whether
they're too tight or too loose.

## Tuning signals

Watch for these signals in the first month:

| Signal | Adjustment |
|---|---|
| Lots of "budget exhausted" surfaces but the failures classified as `branch_failure` would have been refused anyway | budgets are fine; investigate why so many `branch_failure`s are reaching CI |
| Tests legitimately need 2 reruns to settle on one job | `retries_per_job: 3`, but also: file an issue to fix the test |
| Multiple flaky tests in one PR exhausting the PR-level budget | tighten quarantine threshold instead of loosening budgets |
| Average PR consumes >70% of `minutes_per_pr` even without retries | budgets too tight; bump the floor |

## Concurrency cancellation (free money)

Most "wasted CI" actually comes from running stale workflows on superseded
SHAs, not from retries. The skill itself can't enable workflow concurrency
cancellation, but it can recommend it. When auditing a project's CI, check
that every workflow has:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

A repo without this typically wastes 10–30% of its CI minutes on superseded
runs, which dwarfs anything retries can save.

## Stale-run reaping

If `--watch` is left running and the PR is closed, the watcher exits. If a
PR sits idle for >24h with running jobs (a real failure mode in practice),
those jobs are usually wedged. The skill does not auto-cancel them; it
surfaces the situation in the report so the user can decide.

## What the skill does NOT try to do

- It does not gate *initial* runs of any check. CI runs as configured by the
  repo. The skill only intervenes on *retries* and the *trust decision* on
  greens.
- It does not estimate dollar costs. Provider pricing changes; the watcher
  sticks to minutes, which translate consistently regardless of plan.
- It does not balance budgets across PRs or weeks. One PR, one budget. If a
  team has a global monthly budget, that's a billing-side concern.

## Surfacing budget state

Every snapshot includes a `cost_summary` block:

```json
{
  "retries_used_pr": 1,
  "retries_max_pr": 5,
  "retries_used_per_job": {"test-unit": 1},
  "retries_max_per_job": 2,
  "minutes_spent": 47,
  "minutes_max": 90,
  "any_budget_exhausted": false
}
```

In the Claude-facing report, render this as one line:

```
Budget: 1/5 retries, 47/90 min spent  (1 retry on test-unit)
```

When `any_budget_exhausted` is true, render in red and put the budget message
above the per-check breakdown. The user needs to see "stop retrying" before
they see anything else.
