# Architecture

ci-guard is a skill (agent playbook + Python CLI). No server, no daemon, no cloud
dependency. Everything runs locally via `gh` and Python stdlib.

## Component map

```
┌─────────────────────────────────────────────────────────────────┐
│  Your coding agent  (Claude Code / Codex / opencode / …)        │
│  reads SKILL.md → decides when to invoke ci-guard               │
└──────────────────────────┬──────────────────────────────────────┘
                           │  shell invocation
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  ci_watch.py  (decision engine — pure function, no I/O side     │
│  effects in decide_actions())                                    │
│                                                                  │
│  Snapshot ──► Classify ──► Cost gate ──► Verify gate ──►        │
│  Quarantine gate ──► Loop / terminal                             │
│                                                                  │
│  Emits:  --once   → single JSON object to stdout                 │
│          --watch  → JSONL stream until terminal state            │
└──────┬──────────────────────────────┬────────────────────────────┘
       │ reads / writes               │ JSONL stream (--watch)
       ▼                              ▼
┌─────────────────┐       ┌──────────────────────────────────────┐
│ flaky-ledger    │       │  Caller  (pick one)                  │
│ .json           │       │                                      │
│                 │       │  a) action_runner.py  — GitHub CI    │
│ committed to    │       │     posts PR comments, annotations,  │
│ repo; shared    │       │     step summary; triggers reruns    │
│ across all      │       │                                      │
│ contributors    │       │  b) babysit-pr skill  — end-to-end  │
└─────────────────┘       │     PR monitor that shells out here  │
                          │                                      │
┌─────────────────┐       │  c) custom wrapper  — your script   │
│ .watch-state    │       │     consuming the actions[] list     │
│ .json           │       │                                      │
│                 │       │  d) agent directly  — reads JSONL,  │
│ gitignored;     │       │     acts on actions[] inline         │
│ persists loop   │       └──────────────────────────────────────┘
│ state across    │
│ interruptions   │
└─────────────────┘
```

## Components

| File                            | Role                                                                                                                                                                                |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SKILL.md`                      | Agent-readable playbook. Tells the agent when to invoke ci-guard and what rules to follow. No LLM dependency — agents read it as a text document.                                   |
| `scripts/bootstrap.py`          | One-time per-project setup. Copies scripts into `.ci-guard/scripts/`, writes `config.yml` and an empty ledger. Idempotent.                                                          |
| `scripts/ci_watch.py`           | Core engine. Snapshots CI state via `gh`, classifies each failure, runs all five gates, emits JSON or JSONL. `decide_actions()` (line 373) is a pure function with no side effects. |
| `scripts/classify_failure.py`   | Heuristic log analyser. Cross-references log text against the flaky ledger to bucket each failure into one of five categories.                                                      |
| `scripts/flaky_ledger.py`       | Persistent ledger CLI and Python API. Manages `.ci-guard/flaky-ledger.json` — never edit that file by hand.                                                                         |
| `scripts/action_runner.py`      | GitHub CI consumer. Reads `ci_watch --watch` JSONL and executes the `actions[]` list: posts PR comments, emits workflow annotations, writes `$GITHUB_STEP_SUMMARY`.                 |
| `scripts/config.py`             | Shared constants: `SCRIPT_VERSION`, budget defaults, quarantine thresholds, config loader, staleness check.                                                                         |
| `agents/openai.yaml`            | Interface manifest for Codex and skills.sh runtimes. Provides a `default_prompt` that bootstraps the gate sequence.                                                                 |
| `.ci-guard/config.yml`          | Per-project budget overrides (`retries_per_job`, `retries_per_pr`, `minutes_per_pr`, `watch_interval_seconds`).                                                                     |
| `.ci-guard/flaky-ledger.json`   | Committed to the repo. Tracks every test failure and pass event with rolling 30-day counts, flake rates, and quarantine status.                                                     |
| `.ci-guard/.watch-state.json`   | Gitignored. Persists `last_terminal` per PR so an interrupted `--watch` loop exits immediately if the PR already reached a terminal state.                                          |
| `.github/workflows/deliver.yml` | Optional. Wires `ci_watch --watch \| action_runner.py` into a `workflow_run` trigger for automatic PR-page surfacing.                                                               |

## Data flow through the gates

```
ci_watch.py --once / --watch
│
├── Gate 1  Snapshot
│   gh pr view + gh pr checks → Snapshot dataclass
│   (pr_state, checks[], head_sha)
│
├── Gate 2  Classify  [classify_failure.py]
│   For each failing check:
│     log text + ledger entries → category (branch_failure / infra_flake /
│                                            test_flake / dependency_failure / unknown)
│   Source: classify_failure.py, ledger cross-ref in ci_watch.py:243
│
├── Gate 3  Cost guard  [config.py:37–42]
│   retries_per_job=2, retries_per_pr=5, minutes_per_pr=90
│   any_budget_exhausted → stop; no grace period
│
├── Gate 4  Verify green
│   test_flake check turned green? → require one verification rerun
│   two consecutive greens on same SHA → trusted
│
├── Gate 5  Quarantine  [config.py:48–49]
│   failure_count_30d ≥ 3 AND flake_rate ≥ 5%
│   → quarantine_candidates[] in snapshot; human confirms
│
└── Gate 6  Loop / terminal  [ci_watch.py:373–430  decide_actions()]
    pure function → (actions[], terminal)
    terminal: null | pr_merged | pr_closed | needs_help | budget_exhausted
```

The `actions[]` list is what callers act on. ci-guard never executes mutations itself.

For the full JSON contract (every field, action shape, terminal value, exit code) see
`references/wrapper-contract.md`.

For the heuristic decision tree used in Gate 2 see `references/heuristics.md`.
