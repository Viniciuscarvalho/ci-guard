# GitHub Actions integration

ci-guard offers three GitHub Actions hooks. The first two sharpen the flaky ledger
automatically; the third surfaces classifications directly on the PR page.

## Hook 1 — Record failures from the test runner

Add to your test workflow's after-tests step so every failure is logged to the ledger:

```yaml
- name: Update flaky ledger
  if: always()
  run: |
    ci-guard ledger record-failure \
      --test "${TEST_ID}" \
      --sha "${{ github.sha }}" \
      --run-id "${{ github.run_id }}" || true
```

Adapt `TEST_ID` to your test framework. Most runners produce JUnit XML; a short loop
over failed test cases is enough.

## Hook 2 — Warn on quarantine candidates

Add as a required status check or a standalone step after tests run:

```yaml
- name: Quarantine guard
  run: |
    candidates=$(ci-guard ledger quarantine-candidates)
    if [ -n "$(echo "$candidates" | jq -r '.[]' 2>/dev/null)" ]; then
      echo "::warning::Quarantine candidates exist. Review before merging."
      echo "$candidates"
    fi
```

## Hook 3 — Surface classifications on the PR page

`deliver.yml` wires `ci_watch --watch` into a `workflow_run` trigger so
classifications appear on the PR page automatically after every CI run — no manual
invocation required.

### How it works

1. Your `ci` workflow completes (pass or fail) on a PR branch.
2. `deliver.yml` fires via `workflow_run` on that completion event.
3. It resolves the PR number from the triggering branch.
4. It pipes `ci_watch.py --watch` into `action_runner.py`.
5. `action_runner.py` reads the JSONL stream and posts to the PR.

### What gets posted

| Output                                | When                       | Where visible             |
| ------------------------------------- | -------------------------- | ------------------------- |
| `::error:: branch_failure` annotation | Any `branch_failure` check | Job log + Files tab       |
| `::warning:: unknown` annotation      | Any `unknown` check        | Job log + Files tab       |
| PR comment — branch failure           | `branch_failure` detected  | PR conversation tab       |
| PR comment — unknown failure          | `unknown` detected         | PR conversation tab       |
| PR comment — final report             | Terminal state reached     | PR conversation tab       |
| Markdown step summary                 | Terminal state reached     | Workflow run summary page |

The final PR comment includes a table of every failing check with its classification
and confidence, the current retry budget, and a quarantine-candidate count.

### Full workflow file

Copy `deliver.yml` from this repo into your project's `.github/workflows/`:

```yaml
name: deliver

on:
  workflow_run:
    workflows: [ci] # replace with the name(s) of your CI workflow(s)
    types: [completed]

jobs:
  guard:
    # Only runs for pull_request events — not direct pushes to main.
    if: github.event.workflow_run.event == 'pull_request'
    runs-on: ubuntu-latest
    timeout-minutes: 120
    permissions:
      actions: write # trigger reruns via gh run rerun
      checks: read
      contents: read
      pull-requests: write # post annotations and PR comments

    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.workflow_run.head_sha }}

      - name: Resolve PR number
        id: pr
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          PR=$(gh pr list \
            --head "${{ github.event.workflow_run.head_branch }}" \
            --state open \
            --json number \
            -q '.[0].number // empty')
          if [ -z "$PR" ]; then
            echo "No open PR for branch ${{ github.event.workflow_run.head_branch }}, skipping."
            echo "skip=true" >> "$GITHUB_OUTPUT"
          else
            echo "number=$PR" >> "$GITHUB_OUTPUT"
          fi

      - name: Watch and guard
        if: steps.pr.outputs.skip != 'true'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          ci-guard watch \
            --pr ${{ steps.pr.outputs.number }} --stream | \
          ci-guard run-actions
```

### Required permissions

| Permission             | Scope | Why                               |
| ---------------------- | ----- | --------------------------------- |
| `actions: write`       | Job   | Trigger reruns via `gh run rerun` |
| `checks: read`         | Job   | Read check-run conclusions        |
| `contents: read`       | Job   | Checkout the PR head SHA          |
| `pull-requests: write` | Job   | Post PR comments                  |

`GITHUB_TOKEN` is available automatically — no additional secrets needed.

### Opt-in per repo

1. Copy `.github/workflows/deliver.yml` from this repo into your project.
2. Update the `workflows:` list to match your CI workflow name(s).
3. Commit and push. The workflow activates on the next completed CI run for a PR.

No changes to `ci.yml` or any other workflow are required.

### Opt-out / disable

To stop posting PR comments for a specific repo, either:

- Delete or disable `deliver.yml` in that repo, or
- Remove the `pull-requests: write` permission (annotations will still appear but PR
  comments will be skipped silently — `action_runner.py` guards all `gh pr comment`
  calls behind a `GH_TOKEN` check).

## Troubleshooting

**No PR comment is posted**

- Confirm `permissions: pull-requests: write` is present in the job.
- Check that `GH_TOKEN` is set in the `Watch and guard` step's `env:` block.
- For **fork PRs**: GitHub restricts `pull-requests: write` on workflows triggered by
  forks. The `workflow_run` trigger runs in the base repo's context and has full
  permissions — if comments still don't appear, check that the PR was opened from a
  branch on the same repo (not a fork). For fork support, switch the trigger to
  `pull_request_target` and follow GitHub's [security hardening guidance](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions#understanding-the-risk-of-script-injections) before exposing secrets.

**Duplicate PR comments on re-runs**

Each `deliver.yml` run posts its own final report. If the `deliver` workflow is
retried (e.g. via the Actions UI), a second comment will appear. This is intentional
— the second run may have a different classification result. Delete stale comments
manually or add a step to find-and-edit the previous comment using
`gh pr comment --edit-last`.

**`deliver` job is skipped every time**

Verify the `if:` condition matches your workflow's trigger. The default
`if: github.event.workflow_run.event == 'pull_request'` requires your CI workflow to
be triggered by a `pull_request` or `pull_request_target` event. Workflows triggered
only by `push` will not satisfy this condition.

**Rate limited on large monorepos**

If many PRs are open simultaneously, `ci_watch.py --watch` may exhaust the GitHub API
rate limit. Lower `watch_interval_seconds` in `.ci-guard/config.yml` to reduce
polling frequency (default 60 s), or add a `concurrency:` block to `deliver.yml` to
serialise runs per branch:

```yaml
concurrency:
  group: deliver-${{ github.event.workflow_run.head_branch }}
  cancel-in-progress: true
```
