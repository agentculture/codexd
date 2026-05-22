---
name: cicd
description: Codexd PR and CI lane layered on agex pr. Use when creating PRs, polling CI, checking SonarCloud status, reading review feedback, replying to comments, or resolving review threads.
---

# CI/CD

Use this skill for the PR lifecycle around `codexd`: lint, open, read, reply,
delta, status, and await. The core PR verbs delegate to `agex pr`; the vendored
scripts keep AgentCulture's SonarCloud and unresolved-thread gates available in
this repo.

## Prerequisites

- `agex` from `uv tool install agex-cli`
- `gh` authenticated with access to `agentculture/codexd`
- `jq`, `bash`, `python3`, and `curl`

## Commands

```bash
bash .agents/skills/cicd/scripts/workflow.sh lint
bash .agents/skills/cicd/scripts/workflow.sh open --title "..." --body-file /tmp/pr.md
bash .agents/skills/cicd/scripts/workflow.sh read <PR>
bash .agents/skills/cicd/scripts/workflow.sh reply <PR>
bash .agents/skills/cicd/scripts/workflow.sh status <PR>
bash .agents/skills/cicd/scripts/workflow.sh await <PR>
bash .agents/skills/cicd/scripts/workflow.sh delta
```

`workflow.sh reply` expects JSONL on stdin, matching `agex pr reply`.

## Codexd Conventions

- Branch names should be `codex/<description>` for Codex-authored work.
- PR and comment signatures should be `- <nick> (Codex)`, with `<nick>` resolved
  from `culture.yaml` when the tool supports it.
- If a PR touches `AGENTS.md`, `culture.yaml`, or `.agents/skills`, run
  `workflow.sh delta` before declaring review feedback handled.
- Prefer fixing concrete portability, test, doc, lint, and security feedback.
  Push back only when the rule conflicts with the implemented repo contract.
