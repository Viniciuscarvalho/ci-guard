# CI providers — adapting beyond GitHub Actions

The default scripts target GitHub Actions because that's where the `gh` CLI
gives us a reliable, auth-handled API for free. The skill's *logic* is
provider-agnostic, but the I/O layer needs adapting per provider. This
document describes what to swap.

## What's GitHub-specific

In `ci_watch.py`, every call that talks to the outside world goes through
the `gh()` wrapper. That's the only place provider knowledge lives. The four
functions that need provider equivalents are:

| Function | What it returns | GH implementation |
|---|---|---|
| `resolve_pr` | PR number from arg | `gh pr view --json number` |
| `fetch_pr_state` | PR metadata (state, head SHA, mergeable) | `gh pr view --json ...` |
| `fetch_checks` | List of checks for the PR | `gh pr checks --json ...` |
| `fetch_failed_log` | Stdout of failed jobs | `gh run view --log-failed` |
| (in retry path) | trigger a rerun | `gh run rerun <id> --failed` |

If you implement those for another provider, the rest of the skill works
unchanged.

## GitLab CI

The natural mapping is via `glab` (the GitLab CLI):

| Function | glab equivalent |
|---|---|
| `resolve_pr` (MR) | `glab mr view -F json` |
| `fetch_pr_state` | `glab mr view -F json` (state, sha, merge_status) |
| `fetch_checks` | `glab ci status -F json` for the MR's pipeline |
| `fetch_failed_log` | `glab ci trace --job <job-id>` |
| trigger rerun | `glab ci retry <pipeline-id>` (whole pipeline) or `glab ci run-job` |

Two semantic differences to watch for:

1. GitLab's pipeline rerun is *whole-pipeline* by default, which makes the
   per-job retry budget less meaningful. Use `run-job` for individual job
   reruns where supported.
2. Job logs in GitLab are not as cleanly "failed-only" as `--log-failed`;
   you may need to fetch the full trace and filter.

## CircleCI

CircleCI has a REST API but no first-party CLI for PR-scoped checks. The
practical wiring:

| Function | API call |
|---|---|
| `resolve_pr` | from the GitHub side via `gh`, then map PR head SHA to a CircleCI pipeline via `/api/v2/project/<slug>/pipeline?branch=...` |
| `fetch_checks` | `/api/v2/pipeline/<pipeline-id>/workflow` then `/workflow/<id>/job` |
| `fetch_failed_log` | `/api/v1.1/project/<slug>/<job-num>/output/0/0` (per-step output) |
| trigger rerun | `/api/v2/workflow/<id>/rerun` with `from_failed: true` |

A `CIRCLE_TOKEN` env var is required. Cache pipeline IDs locally to avoid
re-resolving on every snapshot.

## Buildkite

| Function | Buildkite API |
|---|---|
| `resolve_pr` | from GitHub; then list builds via `/v2/organizations/<org>/pipelines/<pipeline>/builds?commit=<sha>` |
| `fetch_checks` | each build's `jobs[]` |
| `fetch_failed_log` | `GET /v2/organizations/<org>/pipelines/<pipeline>/builds/<n>/jobs/<id>/log` |
| trigger rerun | `PUT .../jobs/<id>/retry` |

`BUILDKITE_API_TOKEN` env var required.

## Multi-provider repos

A single repo with multiple providers (e.g., GitHub Actions for unit tests,
Buildkite for integration) is the most common reality. The way to handle it
is to keep the skill's interface uniform — a `Check` is a `Check` regardless
of where it ran — and have the I/O layer dispatch on a `provider` field.

A reasonable pattern is to add a `provider` key to each check returned by
`fetch_checks`, and have a registry of fetchers:

```python
FETCHERS = {
    "github": GitHubFetcher(),
    "buildkite": BuildkiteFetcher(),
    "circleci": CircleCIFetcher(),
}

def fetch_failed_log(check):
    return FETCHERS[check["provider"]].fetch_failed_log(check["run_id"])
```

The classifier and ledger don't care about provider; they operate on logs
and test IDs.

## What the heuristics need (per provider)

The classifier looks for substrings; some are GitHub-specific:

- `"the runner has received a shutdown signal"` — GitHub Actions runner.
- `"GitHub Actions infrastructure"` — GitHub specific.

Add provider-specific equivalents to `classify_failure.py`. The general
pattern is: each provider has 3–5 idiosyncratic infra error strings that are
high-signal. Find them once (search past failures), add them, move on. Don't
over-engineer the classifier with a per-provider abstraction; a flat list of
patterns with comments noting their origin is enough.

## What does NOT need adapting

- The flaky ledger. Test IDs are language-/framework-specific, not
  provider-specific.
- The retry budgets. Minutes are minutes.
- The verification protocol. Re-running a flaky-tagged green is the same
  decision regardless of where it ran.
- The quarantine workflow. Skipping a test is in the test framework, not the
  CI provider.
