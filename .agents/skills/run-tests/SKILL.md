---
name: run-tests
description: Run pytest with parallel execution and coverage. Use when running tests, verifying changes, or the user says "run tests", "test", or "pytest".
---

# Run Tests

Run the project's pytest suite with optional parallelism and coverage. Coverage
targets are read from `pyproject.toml`'s `[tool.coverage.run]` section, so the
same script works across AgentCulture Python siblings.

## Usage

```bash
# Default: parallel + verbose
bash .agents/skills/run-tests/scripts/test.sh -p

# Quick check: parallel + quiet
bash .agents/skills/run-tests/scripts/test.sh -p -q

# Full CI mode: parallel + coverage + XML report
bash .agents/skills/run-tests/scripts/test.sh --ci

# Specific test file
bash .agents/skills/run-tests/scripts/test.sh -p tests/test_cli.py

# Without parallelism
bash .agents/skills/run-tests/scripts/test.sh tests/test_cli.py

# With coverage
bash .agents/skills/run-tests/scripts/test.sh -p -c
```

Extra arguments are passed through to pytest.
