#!/usr/bin/env bash
set -euo pipefail

# Create a brand-new LLM Wiki instance in a single command.
#
# Usage:
#   bash new-wiki.sh <target-dir> [module-url]
#
#   <target-dir>  Directory to create (becomes the instance repo root).
#   [module-url]  Optional git URL of the llm-wiki module. Defaults to the
#                 canonical https URL.
#
# What it does:
#   1. mkdir <target-dir> && cd into it && git init
#   2. git submodule add <module-url> .llm-wiki
#   3. bash .llm-wiki/scripts/bootstrap.sh   (interactive: project info + config)
#
# The result is a fully wired, ready-to-use wiki instance.
#
# Run from anywhere (e.g. from a local clone of the module, or piped from curl):
#   bash /path/to/llm-wiki/scripts/new-wiki.sh my-wiki
#   curl -fsSL https://raw.githubusercontent.com/tibrezus/llm-wiki-core/main/scripts/new-wiki.sh \
#     | bash -s my-wiki

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[new-wiki]${NC} $*"; }
warn()  { echo -e "${YELLOW}[new-wiki]${NC} $*"; }
error() { echo -e "${RED}[new-wiki]${NC} $*" >&2; exit 1; }

DEFAULT_MODULE_URL="https://github.com/tibrezus/llm-wiki-core.git"

TARGET_DIR="${1:-}"
MODULE_URL="${2:-$DEFAULT_MODULE_URL}"

[ -n "$TARGET_DIR" ] || error "Usage: bash new-wiki.sh <target-dir> [module-url]"

command -v git >/dev/null 2>&1 || error "git is required."

# Resolve to an absolute path before we change directories.
TARGET_DIR="$(cd "$(dirname "$TARGET_DIR")" && pwd)/$(basename "$TARGET_DIR")"

if [ -e "$TARGET_DIR" ]; then
    error "Target already exists: $TARGET_DIR"
fi

info "Creating instance at: $TARGET_DIR"
mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR"

info "Initializing git repository..."
git init -q

info "Adding llm-wiki module as submodule at .llm-wiki/ ..."
git submodule add -q "$MODULE_URL" .llm-wiki
git -C .llm-wiki submodule update --init --recursive -q || true

info "Running bootstrap (interactive)..."
bash .llm-wiki/scripts/bootstrap.sh

echo ""
info "========================================="
info "  New LLM Wiki instance created!"
info "========================================="
info "  Location:   $TARGET_DIR"
info "  Submodule:  .llm-wiki/ ($MODULE_URL)"
info ""
info "  Next: cd \"$TARGET_DIR\" && start ingesting into wiki/"
