# Agent compatibility

ci-guard's Python scripts call no LLM and require no API key. Your coding agent reads
`SKILL.md` and drives the scripts via your shell. The same five Python files work
identically regardless of which agent invokes them.

## Supported agents

| Agent                                    | Type               | Skill path                     | Update command               |
| ---------------------------------------- | ------------------ | ------------------------------ | ---------------------------- |
| [Claude Code](https://claude.ai/code)    | Native             | `~/.claude/skills/ci-guard/`   | `git pull` in the clone      |
| [OpenAI Codex](https://openai.com/codex) | Native + manifest  | `~/.codex/skills/ci-guard/`    | `git pull` in the clone      |
| [opencode](https://opencode.ai)          | Native             | `~/.opencode/skills/ci-guard/` | `git pull` in the clone      |
| [skills.sh](https://skills.sh) runtimes  | Native (auto-path) | resolved from `$SKILLS_HOME`   | `npx skills update ci-guard` |
| Gemini CLI                               | Paste-in           | n/a                            | replace `SKILL.md` content   |
| Cursor                                   | Paste-in           | n/a                            | replace `SKILL.md` content   |
| GitHub Copilot                           | Paste-in           | n/a                            | replace `SKILL.md` content   |
| Any `AGENTS.md`-aware tool               | Paste-in           | n/a                            | replace `SKILL.md` content   |

## Native installs (Claude Code, Codex, opencode)

A symlink is recommended — edits to the source clone reflect instantly without
re-copying.

```bash
# Claude Code
ln -s /path/to/ci-guard ~/.claude/skills/ci-guard

# Codex
ln -s /path/to/ci-guard ~/.codex/skills/ci-guard

# opencode
ln -s /path/to/ci-guard ~/.opencode/skills/ci-guard
```

### Codex / skills.sh manifest

`agents/openai.yaml` is a thin interface manifest for Codex and skills.sh runtimes.
It provides a `default_prompt` that bootstraps the gate sequence without requiring
the user to type anything beyond the trigger phrase. No additional setup is needed —
the manifest is picked up automatically when the skill directory is registered.

### skills.sh auto-install

The `npx skills add` command resolves the correct skill path from `$SKILLS_HOME`
automatically:

```bash
npx skills add https://github.com/Viniciuscarvalho/ci-guard --skill ci-guard
```

## Paste-in fallback (Gemini CLI, Cursor, Copilot, others)

Agents without a native skill path can still use ci-guard. Copy the contents of
`SKILL.md` into your agent's context file:

| Agent           | Context file              |
| --------------- | ------------------------- |
| Gemini CLI      | `.gemini/GEMINI.md`       |
| Cursor          | `.cursorrules`            |
| Copilot / other | `AGENTS.md` or equivalent |

The scripts live in `.ci-guard/scripts/` after bootstrapping and work identically —
only the playbook delivery mechanism differs. When the skill is updated, replace the
pasted content with the new `SKILL.md`.

## What the agent does vs. what ci-guard does

The agent reads `SKILL.md` and decides _when_ to invoke ci-guard (on CI failure,
before a retry, when a check turns green on a known-flaky test). ci-guard's scripts
decide _what action to take_ based on log heuristics and the flaky ledger — and they
never execute mutations themselves. All state-changing operations (reruns, PR comments,
ledger updates) are performed by `action_runner.py` or the agent acting on the emitted
`actions[]` list.

This separation means the same scripts work under any agent: the decision logic is in
Python, not in the agent's prompt.

> See `SKILL.md` lines 29–31 for the authoritative statement of what ci-guard
> delegates to callers.
