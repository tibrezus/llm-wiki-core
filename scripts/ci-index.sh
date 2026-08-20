#!/usr/bin/env bash
set -euo pipefail

# QMD index pipeline — installs QMD, indexes wiki, verifies search.
# Called by the reusable index workflow and usable locally.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$SCRIPT_DIR/lib"
source "$LIB_DIR/config.sh"
source "$LIB_DIR/install-tools.sh"

require_config
cd "$INSTANCE_ROOT"

echo "=== LLM Wiki Index Pipeline ==="

install_qmd
configure_path

# Ensure locally-installed bins are on PATH for this shell
export PATH="$HOME/.local/bin:$HOME/.bun/bin:$PATH"

echo ""
bash .llm-wiki/scripts/qmd-setup.sh

echo ""
echo "--- re-index ---"
qmd update

echo ""
echo "--- embed ---"
qmd embed

echo ""
echo "--- verify ---"
qmd status

echo ""
echo "--- search test ---"
# The test term is derived from the corpus itself: a fixed query like
# "test query" cannot be answered by a small or freshly-bootstrapped wiki.
term=$(awk -F': *' '/^title:/ {print $2; exit}' wiki/*/*.md 2>/dev/null | head -1)
if [ -z "$term" ]; then
    echo "::error::No wiki pages found — add at least one page under wiki/ before the index can be verified"
    exit 1
fi
echo "Searching for: $term"
result=$(qmd search "$term" --json -n 1 2>/dev/null || echo "")
if [ "$result" = "[]" ] || [ -z "$result" ]; then
    echo "::error::QMD search returned no results for '$term'"
    exit 1
fi
echo "QMD search verification passed"

echo ""
echo "=== Index Pipeline Complete ==="
