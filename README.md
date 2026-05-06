# ci-guard

A skills.sh / Anthropic Agent Skills compatible skill that protects your CI
from two specific failure modes:

1. **Blind retries** — failed checks getting `gh run rerun`'d without anyone
   classifying *why* they failed.
2. **Trusting a single green** — a known-flaky test passing once and the PR
   merging, masking either real bugs or chronic flakys.

## Structure

```
ci-guard/
├── SKILL.md                              # The playbook Claude reads
├── scripts/
│   ├── ci_watch.py                       # Snapshot CI state, classify, gate retries
│   ├── classify_failure.py               # Heuristic log analysis
│   └── flaky_ledger.py                   # Persistent flaky-test ledger CLI
├── references/
│   ├── heuristics.md                     # Failure classification decision tree
│   ├── cost-controls.md                  # Retry budgets and rationale
│   ├── flaky-detection.md                # Ledger schema and verification protocol
│   ├── setup.md                          # Per-project setup steps
│   └── ci-providers.md                   # Adapting to GitLab/CircleCI/Buildkite
└── assets/
    └── flaky-quarantine-template.md      # Issue body template
```

## Install

skills.sh-compatible runtimes (Codex, Claude Code, opencode, etc.):

```bash
npx skills add <your-repo-url> --skill ci-guard
```

Or copy the directory directly into your skills path
(`~/.claude/skills/ci-guard/`).

## Per-repo setup

See `references/setup.md`. The short version:

```bash
mkdir -p .ci-guard/scripts
cp ~/.claude/skills/ci-guard/scripts/*.py .ci-guard/scripts/
chmod +x .ci-guard/scripts/*.py
echo '{"version": 1, "tests": {}, "history": []}' > .ci-guard/flaky-ledger.json
echo ".ci-guard/.watch-state.json" >> .gitignore
git add .ci-guard .gitignore
git commit -m "ci-guard: bootstrap"
```

## Dependencies

- Python 3.9+ (stdlib only)
- `gh` CLI, authenticated against the repo's GitHub host

No `pip install` needed. The skill is portable across any environment that
runs Python and has `gh`.

## Relationship to babysit-pr

`babysit-pr` (from openai/codex) sits on a PR end-to-end through merge.
`ci-guard` is the diagnostic and cost layer underneath that decision-making.
You can use them together: babysit-pr can shell out to `ci_watch.py` to
classify failures before deciding to retry, and ci-guard's verification
protocol catches single-pass-by-luck greens before babysit-pr declares the
PR ready.
