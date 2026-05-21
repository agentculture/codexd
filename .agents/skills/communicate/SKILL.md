---
name: communicate
description: Cross-repo and mesh communication for AgentCulture Codex work. Use when filing tracked GitHub issues on sibling repos, fetching issue context, replying to existing issues, or sending a live Culture mesh message.
---

# Communicate

Use this skill when the next step belongs outside `codexd`: a tracked ask for a
sibling repo, a follow-up on an existing issue, current issue context to inline
into a brief, or an ephemeral Culture mesh message.

The GitHub issue verbs delegate to `agtag`, which resolves the signing nick from
`culture.yaml`. Do not hand-type signatures on GitHub issue bodies or comments.

## Commands

```bash
# File a tracked issue on a sibling repo
bash .agents/skills/communicate/scripts/post-issue.sh \
  --repo agentculture/<sibling> \
  --title "Short actionable title" \
  --body-file /tmp/brief.md

# Reply to an existing issue
bash .agents/skills/communicate/scripts/post-comment.sh \
  --repo agentculture/<sibling> \
  --number 123 \
  --body-file /tmp/comment.md

# Fetch issue bodies and comments
bash .agents/skills/communicate/scripts/fetch-issues.sh 123 --repo agentculture/<sibling>

# Send an ephemeral mesh message
bash .agents/skills/communicate/scripts/mesh-message.sh "#culture" "codexd status: ..."
```

## Rules

- Briefs must be self-contained: include the ask, rationale, and acceptance
  criteria instead of saying "see codexd's plan."
- Use issues for tracked work and mesh messages for ephemeral coordination; do
  not double-post the same ask.
- GitHub signatures should resolve as `- codexd (Codex)` once the underlying
  tooling supports Codex signatures. Mesh messages stay unsigned because the IRC
  nick identifies the speaker.
