#!/usr/bin/env bash
# Portability lint: catch path leaks and per-user config dependencies in
# committed docs/configs before they ship in a PR.
#
# Usage: portability-lint.sh [--all]
#   default: lint files modified vs HEAD (staged + unstaged)
#   --all:   lint all tracked files
#
# Exits 0 if clean, 1 if any leak is found.

set -euo pipefail

mode="${1:-diff}"
case "$mode" in
    --all) mapfile -d '' -t files < <(git ls-files -z -- ':(exclude)*.lock') ;;
    diff|--diff) mapfile -d '' -t files < <(git diff --diff-filter=AMR --name-only -z HEAD -- ':(exclude)*.lock') ;;
    *) echo "Usage: $(basename "$0") [--all]" >&2; exit 2 ;;
esac

[ "${#files[@]}" -eq 0 ] && { echo "(no files to check)"; exit 0; }

# ----- Check 1: hard-coded /home/<user>/... paths -----
hits1=$(grep -nE '/home/[a-z][a-z0-9_-]+/' "${files[@]}" 2>/dev/null || true)

# ----- Check 2: per-user dotfile *config* refs in committed docs/configs -----
# Carve-outs (allowed, NOT flagged):
#   - ~/.agents/skills/<x>/scripts/   installed skill tool calls
#   - ~/.codex/skills/<x>/scripts/    environment-specific installed bundles
#   - ~/.culture/                     Culture mesh data this skill is supposed to read
md_yaml=()
for file in "${files[@]}"; do
    case "$file" in
        *.md|*.yml|*.yaml|*.toml|*.json|*.jsonc) md_yaml+=("$file") ;;
    esac
done
if [ "${#md_yaml[@]}" -gt 0 ]; then
    hits2=$(grep -nE '~/\.[A-Za-z]' "${md_yaml[@]}" 2>/dev/null \
        | grep -vE '~/\.agents/skills/[^[:space:]"]+/scripts/' \
        | grep -vE '~/\.codex/skills/[^[:space:]"]+/scripts/' \
        | grep -vE '~/\.culture/' \
        || true)
else
    hits2=""
fi

fail=0
if [ -n "$hits1" ]; then
    echo "❌ Hard-coded /home/<user>/ paths:"
    echo "$hits1" | sed 's/^/    /'
    echo "   Fix: use ../sibling, repo URL, or \$WORKSPACE/sibling instead."
    fail=1
fi
if [ -n "$hits2" ]; then
    [ "$fail" -eq 1 ] && echo
    echo "❌ Per-user ~/.<dotfile> config refs in committed doc/config:"
    echo "$hits2" | sed 's/^/    /'
    echo "   Allowed carve-outs: ~/.agents/skills/.../scripts/, ~/.codex/skills/.../scripts/, ~/.culture/."
    echo "   Otherwise: commit a repo-local config or document a portable lookup."
    fail=1
fi

[ "$fail" -eq 0 ] && echo "✓ portability lint clean (${#files[@]} files checked)"
exit $fail
