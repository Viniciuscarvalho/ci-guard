# Updating ci-guard

## Update the package (once per machine)

```bash
pip install --upgrade ci-guard
```

Because all logic lives in the installed package — not in per-project copies —
upgrading is a single command. No per-project re-bootstrap is needed after an upgrade.

## Update the skill symlink (if applicable)

If you registered the skill by symlinking the repo directory rather than via pip, pull
the latest source:

```bash
cd /path/to/ci-guard && git pull
```

The symlink resolves to the current HEAD automatically — no extra step needed for the
agent to pick up changes.

For skills.sh:

```bash
npx skills update ci-guard
```

## Check the installed version

```bash
ci-guard --version
```

## Updating in CI (deliver.yml)

`deliver.yml` runs `pip install ci-guard` at workflow start, so CI always uses the
latest published version. To pin a specific version:

```yaml
- name: Install ci-guard
  run: pip install "ci-guard==0.5.0"
```

## Migrating from the pre-v0.5 bootstrap layout

If your repo was bootstrapped before v0.5 (it has a `.ci-guard/scripts/` directory),
run:

```bash
ci-guard init --migrate
git add .ci-guard && git commit -m "chore: migrate ci-guard to v0.5 package layout"
```

`--migrate` removes the now-redundant `.ci-guard/scripts/` directory and updates
`.ci-guard/config.yml` to the current schema. It is idempotent and safe to re-run.
Pass `--dry-run` to preview changes before applying them.
