---
name: sonarcloud
description: Query SonarCloud API for quality gate status, code issues, security hotspots, and metrics. Use when checking "sonar", "quality gate", or "code quality" status.
---

# SonarCloud

Query SonarCloud projects for quality gate status, issues, metrics, and
security hotspots.

## Prerequisites

- `bash`
- `curl`
- `jq`
- `SONAR_TOKEN` in the environment

Set `SONAR_PROJECT=agentculture_codexd` or pass `--project KEY`.

## Usage

```bash
bash .agents/skills/sonarcloud/scripts/sonar.sh status
bash .agents/skills/sonarcloud/scripts/sonar.sh issues
bash .agents/skills/sonarcloud/scripts/sonar.sh metrics
bash .agents/skills/sonarcloud/scripts/sonar.sh hotspots
bash .agents/skills/sonarcloud/scripts/sonar.sh issues --severity CRITICAL --type BUG
```

Use `accept` only after a clear review decision that a Sonar issue is a false
positive or intentionally accepted risk:

```bash
bash .agents/skills/sonarcloud/scripts/sonar.sh accept \
  --issue ISSUE_KEY \
  --comment "Pushback: explain the repo-specific rationale."
```
