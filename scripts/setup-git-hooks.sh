#!/usr/bin/env bash
# setup-git-hooks.sh — Install git hooks from scripts/git-hooks/
#
# Usage:
#   bash scripts/setup-git-hooks.sh        # install all hooks
#   bash scripts/setup-git-hooks.sh -f     # force overwrite existing hooks
set -euo pipefail

FORCE=false
if [ "${1:-}" = "-f" ]; then
    FORCE=true
fi

HOOKS_DIR="$(cd "$(dirname "$0")/git-hooks" && pwd)"
GIT_HOOKS_DIR="$(cd "$(dirname "$0")/.." && pwd)/.git/hooks"

echo "Installing git hooks from $HOOKS_DIR → $GIT_HOOKS_DIR"

for hook in "$HOOKS_DIR"/*; do
    hook_name=$(basename "$hook")
    target="$GIT_HOOKS_DIR/$hook_name"

    if [ -f "$target" ] && ! $FORCE; then
        echo "  skip $hook_name (already exists, use -f to overwrite)"
        continue
    fi

    cp "$hook" "$target"
    chmod +x "$target"
    echo "  install $hook_name ✅"
done

echo "Done. Hooks will run automatically on git commit."
echo ""
echo "For full pre-commit (actionlint, formatting):"
echo "  pip install pre-commit && pre-commit install"
