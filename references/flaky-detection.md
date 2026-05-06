# Flaky detection — ledger, verification, and quarantine

The flaky ledger is the durable memory of this skill. Without it, every PR
re-discovers the same flaky tests independently and wastes compute on each
discovery. With it, a flaky that appears in one PR teaches every subsequent
PR to be skeptical.

## Ledger schema

Path: `.ci-guard/flaky-ledger.json` (committed to the repo).

```jsonc
{
  "version": 1,
  "tests": {
    "tests/auth/test_login.py::test_oauth_redirect": {
      "first_seen": "2026-04-12",
      "last_failure": "2026-05-05",
      "last_pass": "2026-05-06",
      "failure_count_30d": 4,
      "pass_count_30d": 42,
      "flake_rate": 0.087,
      "status": "watched",
      "quarantined_at": null,
      "quarantine_issue_url": null,
      "events": [
        {"kind": "fail", "at": "2026-04-12T03:11:02Z", "sha": "abc1234", "run_id": "1234567"},
        {"kind": "pass", "at": "2026-04-12T03:18:40Z", "sha": "abc1234", "run_id": "1234589"}
        // ...
      ]
    }
  },
  "history": []
}
```

### Field meanings

- **`first_seen`** — date the test first appeared in the ledger. Useful for
  "is this a new flaky?" judgments.
- **`last_failure` / `last_pass`** — most recent observation dates.
- **`failure_count_30d` / `pass_count_30d`** — rolling window counts derived
  from `events`. Recomputed every time `record-failure` or `record-pass` runs.
- **`flake_rate`** — `failure_count_30d / (failure_count_30d + pass_count_30d)`.
  Zero if no observations.
- **`status`** — `watched` (default), `quarantined` (skipped in CI with a
  tracking issue), or `fixed` (recently passing; will age out via `prune`).
- **`quarantined_at` / `quarantine_issue_url`** — set only when status flips
  to `quarantined`. Provide traceability for un-quarantining later.
- **`events`** — append-only event log, trimmed to the last 30 days on every
  recompute. The single source of truth from which the rolling counts are
  derived.

### Why we keep events

The rolling counts could be implemented as just two integers per test, but
storing the underlying events lets us:

1. Recompute over different windows (90-day audit, 7-day "is this getting
   worse" check) without losing data.
2. Catch double-counting bugs by spot-checking events against actual run-ids.
3. Migrate the schema later — events are the source, the rest is derived.

## Verification protocol

When a check that is in the ledger transitions from failing to green:

1. The single green is **not yet trusted**.
2. Trigger one verification rerun via `ci_watch.py --verify-flaky-green`.
3. If the verification passes, the test is genuinely passing on this SHA;
   record both passes in the ledger and let the PR proceed.
4. If the verification fails, the test is more flaky than the ledger thought.
   Record both events; this will likely push the test over the quarantine
   threshold on the next snapshot.

The verification rerun is a small cost — typically under a minute on a
single check — to catch the "passed once by luck" case that produces
production incidents from green CI.

### When verification is *not* needed

- A check that was failing transitions to green after a *new commit*. The new
  commit might have fixed a real bug; trust the green and let the dev push
  more if the fix was incomplete.
- A check that's flagged `infra_flake` and not in the ledger.
- The first time a test appears in the ledger and the verification cycle
  would itself be the second observation — record both events; verification
  is implicit.

## Quarantine threshold

A test becomes a *quarantine candidate* when both:

- `failure_count_30d >= 3`
- `flake_rate >= 0.05` (5%)

These are intentionally lenient. A test that fails 3 times out of 100 (3%
flake rate) does *not* qualify — it might just be unlucky. A test that fails
3 out of 30 (10% flake rate) does — it's costing real time on real PRs.

### What "quarantine" means

Quarantining a test = adding a skip-pragma so it does not run in CI, plus
opening a tracking issue so it doesn't get forgotten. Examples per framework:

| Framework | Skip pragma |
|---|---|
| pytest | `@pytest.mark.skip(reason="ci-guard quarantine: <issue-url>")` |
| Jest / Vitest | `it.skip("oauth redirect", ...)` with a comment linking the issue |
| Go test | `t.Skip("ci-guard quarantine: <issue-url>")` |
| RSpec | `it "...", skip: "ci-guard quarantine: <issue-url>"` |
| JUnit 5 | `@Disabled("ci-guard quarantine: <issue-url>")` |
| Cargo test | `#[ignore = "ci-guard quarantine: <issue-url>"]` |

The issue body should use `assets/flaky-quarantine-template.md`. After the
issue is filed, mark the ledger entry quarantined:

```bash
python3 .ci-guard/scripts/flaky_ledger.py set-status \
    --test "tests/auth/test_login.py::test_oauth_redirect" \
    --status quarantined \
    --issue-url "https://github.com/org/repo/issues/1234"
```

### What quarantine does NOT do

- It does not delete or modify the test file. Skipping is a *signal*, not a
  fix — the test stays in the codebase.
- It does not block the PR. The point is to stop the test from costing minutes
  on every PR while the underlying issue is investigated.
- It does not auto-un-quarantine. When the test is fixed, the maintainer must
  manually remove the skip pragma and run `set-status --status fixed`.

## Aging out fixed tests

`flaky_ledger.py prune --older-than 60` removes entries with no failures in
the last 60 days *and* status != `quarantined`. The 60-day default is
deliberate — short enough that the ledger doesn't grow without bound, long
enough that a flaky that disappears for a sprint isn't immediately forgotten.

Quarantined entries are never pruned; they need explicit `set-status` action
first, which forces the team to acknowledge the test before its history is
forgotten.

## Anti-patterns to watch for

- **Recording test passes too aggressively.** If you record a pass for every
  test that ran, the flake_rate becomes meaningless because passing tests
  vastly outnumber flaky ones. Only record pass/fail events for tests that
  have at least one prior failure event in the ledger. (The `record-pass`
  command happily creates new entries, but the calling code in
  `ci_watch.py` only records passes for tests that are already tracked.)
- **Counting reruns as new events.** A retry is part of the *same* CI cycle;
  recording fail-then-pass from a single rerun would inflate the flake rate.
  Only record one event per (test, SHA) pair.
- **Manually editing the ledger.** It's JSON, so you can — but the rolling
  counts will desync from the event log. Use `flaky_ledger.py repair` if
  you've made manual edits.

## Ledger size

A ledger with 100 tracked tests, each with ~50 events over 30 days, is
roughly 200KB. That's fine to commit. Repos with thousands of flaky tests
have bigger problems than ledger size, but if it ever does become a concern,
`prune` is the lever — and crossing 1MB is itself a strong signal that
quarantine thresholds need tightening.
