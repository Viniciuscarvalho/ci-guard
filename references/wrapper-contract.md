# ci-guard `--watch` wrapper contract

This document is the single source of truth for the JSON contract emitted by
`ci_watch.py --watch`. Use it when writing a wrapper, orchestrator, or any
consumer of ci-guard's JSONL stream.

**Version:** 0.4.0 (introduced structured `actions` and `terminal` fields)

---

## Overview

`--watch` streams one JSON object per poll to stdout (JSONL). The loop runs
until `terminal` is non-null, then exits with the code described below.
Consumers must iterate lines and parse each as JSON.

```
ci-guard watch --pr <n|auto|url> --stream
```

---

## Snapshot object

Every line is a complete snapshot of the PR at that moment.

```jsonc
{
  // --- identity ---
  "pr_number": 42,
  "head_sha": "a1b2c3d4e5f6...",       // full SHA of the PR head
  "head_sha_short": "a1b2c3d",          // first 7 chars, for display
  "timestamp": "2026-05-08T10:30:00Z",  // UTC ISO-8601

  // --- PR state ---
  "pr_state": "OPEN",        // "OPEN" | "MERGED" | "CLOSED"
  "mergeable": "MERGEABLE",  // "MERGEABLE" | "CONFLICTING" | "UNKNOWN"

  // --- loop control (new in 0.4.0) ---
  "terminal": null,          // null | "pr_merged" | "pr_closed" | "needs_help" | "budget_exhausted"
  "actions": [...],          // ordered list of action directives; see below

  // --- gate data ---
  "checks": [...],            // one entry per CI check; see below
  "cost_summary": {...},      // retry budget counters; see below
  "quarantine_candidates": [] // tests above the quarantine threshold; see below
}
```

---

## `terminal` values and exit codes

| Value                | Meaning                                             | Exit code   |
| -------------------- | --------------------------------------------------- | ----------- |
| `null`               | Loop is still running                               | — (no exit) |
| `"pr_merged"`        | PR merged successfully                              | 0           |
| `"pr_closed"`        | PR closed without merging                           | 0           |
| `"needs_help"`       | Budget exhausted with quarantine candidates present | 2           |
| `"budget_exhausted"` | Budget exhausted; no quarantine candidates          | 3           |

Exit code 2 signals that an agent or human must intervene (quarantine candidates
block progress). Exit code 3 signals a reliability problem to investigate.

When `terminal` is non-null, the last snapshot in the stream will also contain
a `{"action": "stop", "reason": "<terminal>"}` entry in `actions`.

---

## `actions` directives

Actions are ordered — execute them in order. ci-guard never executes them; the
caller does.

### `{"action": "idle"}`

Nothing actionable. The loop is waiting for CI state to change. No mutation
needed; the next snapshot will arrive after `watch_interval_seconds`.

### `{"action": "retry_failed_now"}`

Budget allows retrying the current failures. Invoke:

```
ci-guard watch --pr <n> --retry-failed-now
```

This is the only sanctioned retry path — calling `gh run rerun` directly
bypasses the budget guard and ledger update.

### `{"action": "diagnose_branch_failure", "checks": ["<name>", ...]}`

The named checks are classified `branch_failure`. Do NOT retry. The PR branch
has a genuine defect. Surface the check names to the developer.

### `{"action": "diagnose_unknown", "checks": ["<name>", ...]}`

The named checks could not be classified. Read the failed log with
`gh run view <run-id> --log-failed` and classify manually before any retry.

### `{"action": "verify_flaky_green", "checks": ["<name>", ...]}`

The named checks flipped from failing to green but appear in the flaky ledger.
A single green is not trustworthy. Trigger a verification rerun:

```
ci-guard watch --pr <n> --verify-flaky-green
```

Two consecutive greens on the same SHA are required before the check is
considered genuinely passing.

### `{"action": "stop", "reason": "<terminal>"}`

The loop is terminating. `reason` matches the `terminal` field. No further
polling will occur after this snapshot. Perform any cleanup and exit.

---

## `checks` entries

Each entry in the `checks` array represents one CI check at the time of the
snapshot.

```jsonc
{
  "name": "test / ubuntu-latest / 3.11",
  "workflow": "CI",
  "status": "completed",      // "queued" | "in_progress" | "completed"
  "conclusion": "failure",    // "success" | "failure" | "cancelled" | "skipped" | null
  "run_id": "12345678",       // GitHub Actions run ID; null if unavailable
  "duration_seconds": 142,
  "started_at": "2026-05-08T10:28:00Z",
  "retries_used_job": 1,      // how many times this job has been retried on this PR

  // only present when conclusion is failure/cancelled/timed_out:
  "classification": {
    "category": "test_flake",  // branch_failure | infra_flake | test_flake | dependency_failure | unknown
    "confidence": "high",      // high | medium | low
    "reason": "...",
    "matched_pattern": "...",       // optional
    "matched_snippet": "...",       // optional
    "matched_ledger_tests": [...]   // optional; test IDs from the flaky ledger
  },
  "flaky_history": {
    "tests/auth.py::test_login": {
      "failure_count_30d": 4,
      "flake_rate": 0.8,
      "last_failure": "2026-05-07T14:22:00Z",
      "status": "watched"
    }
  }
}
```

---

## `cost_summary`

```jsonc
{
  "retries_used_pr": 2, // total retries triggered on this PR so far
  "retries_max_pr": 5, // budget ceiling (from config.yml or default)
  "retries_used_per_job": {
    // per-job retry counts
    "test / ubuntu / 3.11": 1,
  },
  "retries_max_per_job": 2,
  "minutes_spent": 18,
  "minutes_max": 90,
  "any_budget_exhausted": false,
}
```

---

## `quarantine_candidates`

Tests that have crossed the quarantine threshold (≥ 3 failures AND ≥ 5% flake
rate in the last 30 days) but have not yet been quarantined.

```jsonc
[
  {
    "test": "tests/auth/test_login.py::test_session_expiry",
    "failure_count_30d": 5,
    "flake_rate": 0.83,
    "last_failure": "2026-05-07T14:22:00Z",
  },
]
```

---

## Polling cadence

The loop sleeps `watch_interval_seconds` (default 60 s, configurable in
`.ci-guard/config.yml`) between polls. When the PR head SHA or any check
conclusion changes, the sleep is skipped and the next snapshot is fetched
immediately.

---

## State persistence

`.ci-guard/.watch-state.json` (gitignored, schema version 1) stores per-PR:

- `last_seen_sha` — SHA at the last poll (for cadence reset)
- `last_seen_check_states` — `{name: conclusion}` map at the last poll
- `last_terminal` — set when the loop exits; causes immediate re-exit on restart

If the process is killed and restarted on an already-terminal PR, `cmd_watch`
exits immediately without polling and prints a message to stderr.

---

## Backward compatibility

Fields introduced in 0.4.0: `terminal`, and `actions` changed from
`list[str]` to `list[dict]`. Consumers written against 0.3.x that read
`actions` as strings will break — update to iterate `action["action"]` instead.

All other snapshot fields are unchanged from 0.3.x.
