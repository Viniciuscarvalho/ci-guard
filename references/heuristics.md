# Heuristics — failure classification decision tree

This document is the source of truth for *how* the skill decides which bucket
a failed CI check belongs in. The categories are deliberately few because
every category corresponds to a different action; if you find yourself wanting
a fifth "kind of" branch failure, the right answer is usually a sub-flag in an
existing category, not a new top-level bucket.

## Categories and their actions

| Category | Action |
|---|---|
| `branch_failure` | Never retry. Patch code. |
| `infra_flake` | Retry once if budget allows. |
| `test_flake` | Retry once + verify the green afterward. |
| `dependency_failure` | Retry once. Second time on same SHA → reclassify as `branch_failure`. |
| `unknown` | Diagnose manually. Never default to retry. |

## Decision order

Run rules in this order; first match wins. The order matters: a real bug can
emit network-looking errors (e.g., a misconfigured base URL produces DNS
failures), so branch-failure signals must be checked first.

```
1. branch_failure signals  →  branch_failure
2. dependency_failure signals  →  dependency_failure
3. infra_flake signals  →  infra_flake
4. test_flake signals (race/retry language OR ledger match)  →  test_flake
5. nothing matched  →  unknown
```

## Signals per category

### branch_failure (high confidence)

These almost never appear from infra problems; if the log contains them, the
branch broke something:

- `SyntaxError`, `IndentationError`, `ImportError` from compile-time imports.
- TypeScript `error TS\d+:`, Flow type errors.
- Go `# package`-prefixed compile errors with `.go:line:col`.
- Rust `error[E\d+]:`.
- Java/Kotlin `compilation failed`.
- Snapshot/golden file mismatches in tests touching changed UI/components.
- Lint failures (`N errors, M warnings`) when lint passed on `main`.
- `Cannot find module` / `ModuleNotFoundError` / `cannot find symbol`.

### branch_failure (medium confidence)

- A test in a file that this PR touched fails. Check via `git diff --name-only origin/main...HEAD`.
- A test that exists on `main` and passes there fails on this PR. (Compare to recent runs of the same job on `main`.)

### dependency_failure

Anything pointing at a third-party registry or supply-chain endpoint:

- `npm ERR! 5xx`, `npm ERR! 429`.
- Yarn lockfile mismatch / out of date.
- `pypi.org` / `pythonhosted.org` 5xx or connection errors.
- Cargo `failed to fetch` or `failed to download`.
- Docker registry pull errors (`registry-1.docker.io`, `error pulling image`).
- Go module proxy 5xx (`proxy.golang.org`).
- Maven Central / Gradle resolution errors.

If the *same* registry-related error appears on a *retry on the same SHA*, it
is no longer a transient issue — it's a lockfile/version-pin problem and
should be reclassified as `branch_failure`.

### infra_flake

The runner or GitHub itself is unwell:

- `the runner has received a shutdown signal`.
- `lost communication with the server`.
- `GitHub Actions infrastructure` mentions in cancel reasons.
- DNS failures (`could not resolve host`, `getaddrinfo`).
- Connection resets / `i/o timeout` at the OS level.
- Generic `502 Bad Gateway` / `503 Service Unavailable` / `504 Gateway Timeout`.
- `no space left on device` (runner disk pressure).

### test_flake

Two different signal sources, either of which is sufficient:

1. **Ledger match.** A test name in `.ci-guard/flaky-ledger.json` appears in
   the failed log. This is the strongest signal because we have prior history.
2. **Race-condition language** in the log: "timed out waiting for X", "expected
   N got M (retried)", explicit `flaky`/`@retry` markers from the test framework.

Note that "the test passed on retry" inside the same job's output (e.g.,
pytest-rerunfailures) is itself evidence: log it to the ledger and let the job
move on.

### unknown

Falling here is a feature, not a bug. The right action is to read the log
yourself and either reclassify or surface to the user. Do not retry on
`unknown` — that is the failure mode this skill exists to prevent.

## When to override the heuristic classification

The heuristic is fast and cheap; it is not always right. Override it when:

- You read the log and see a clear category the regexes missed. Add a rule for
  that pattern in `classify_failure.py` so the next person doesn't have to
  re-do the work.
- The log contains both a branch-failure signal *and* an infra signal. Trust
  the branch-failure signal — the infra noise is incidental.
- A test has been ledger-flagged but the current failure mode is structurally
  different (different error class, different stack frame). It might no
  longer be the same flake; investigate.

## Ambiguity protocol

When two strong signals from different categories appear:

1. Prefer the category higher in the decision order.
2. If still tied, surface to the user with both signals quoted.
3. Never auto-retry on ambiguity.

## Adding new rules

`classify_failure.py` keeps rules in a single ordered list at the top of the
file. To add one:

1. Pick the right category and a confidence level (`high`, `medium`, `low`).
2. Write a regex that's specific enough to not match unrelated logs. Test it
   against three real logs from your repo before committing.
3. Put it in the right *section* (the file is partitioned by category).
4. Bump the `WINDOW_DAYS` constant only if you have a good reason; existing
   ledger entries assume 30.

When a new rule lands, prune any redundant ones that the new rule subsumes —
having two rules match the same log just hides whichever runs second.
