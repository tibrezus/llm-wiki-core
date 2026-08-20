#!/usr/bin/env bash
set -euo pipefail

# Bootstrap a new LLM Wiki instance.
# Run from the instance repo root after adding the llm-wiki submodule:
#   git submodule add https://github.com/tibrezus/llm-wiki-core.git .llm-wiki
#   bash .llm-wiki/scripts/bootstrap.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$SCRIPT_DIR/lib"
source "$LIB_DIR/config.sh"
source "$LIB_DIR/generate.sh"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[bootstrap]${NC} $*"; }
warn()  { echo -e "${YELLOW}[bootstrap]${NC} $*"; }
error() { echo -e "${RED}[bootstrap]${NC} $*" >&2; exit 1; }

cd "$INSTANCE_ROOT"
require_submodule

info "Bootstrapping LLM Wiki instance at $INSTANCE_ROOT"

# --- Collect project config ---
if [ -f "$CONFIG_FILE" ]; then
    warn "wiki.config.yml already exists. Skipping config prompts."
    warn "Delete wiki.config.yml and re-run to reconfigure."
else
    info "Configuring wiki instance..."

    read -rp "Project name (lowercase, hyphen-separated): " PROJECT_NAME
    [[ "$PROJECT_NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]] || error "Invalid project name."

    read -rp "Project title (human-readable) [$PROJECT_NAME]: " PROJECT_TITLE
    PROJECT_TITLE="${PROJECT_TITLE:-$PROJECT_NAME}"

    read -rp "Project description (one sentence): " PROJECT_DESCRIPTION
    [ -n "$PROJECT_DESCRIPTION" ] || error "Project description is required."

    read -rp "Project URL (optional): " PROJECT_URL

    read -rp "QMD global context (rich description for search embeddings): " QMD_GLOBAL
    [ -n "$QMD_GLOBAL" ] || QMD_GLOBAL="Knowledge base for $PROJECT_TITLE"

    read -rp "QMD entity context [Specific technologies and products]: " QMD_ENTITY
    QMD_ENTITY="${QMD_ENTITY:-Specific technologies and products — each page describes one technology or product}"

    read -rp "QMD concept context [Architectural patterns and design principles]: " QMD_CONCEPT
    QMD_CONCEPT="${QMD_CONCEPT:-Architectural patterns and design principles connecting entities}"

    read -rp "QMD guide context [Step-by-step procedures]: " QMD_GUIDE
    QMD_GUIDE="${QMD_GUIDE:-Step-by-step procedures the reader follows}"

    read -rp "QMD reference context [Catalogs and lookup tables]: " QMD_REFERENCE
    QMD_REFERENCE="${QMD_REFERENCE:-Catalogs, comparisons, and lookup tables}"

    read -rp "CI runner [self-hosted]: " CI_RUNNER
    CI_RUNNER="${CI_RUNNER:-self-hosted}"

    read -rp "Node.js version [20]: " CI_NODE
    CI_NODE="${CI_NODE:-20}"

    cat > "$CONFIG_FILE" <<EOF
project:
  name: "$PROJECT_NAME"
  title: "$PROJECT_TITLE"
  description: "$PROJECT_DESCRIPTION"
  url: "${PROJECT_URL:-}"
qmd:
  global_context: "$QMD_GLOBAL"
  entity_context: "$QMD_ENTITY"
  concept_context: "$QMD_CONCEPT"
  guide_context: "$QMD_GUIDE"
  reference_context: "$QMD_REFERENCE"
ci:
  runner: "$CI_RUNNER"
  node_version: "$CI_NODE"
EOF
    info "Created wiki.config.yml"
fi

# --- Read config values (allows re-running) ---
PROJECT_NAME=$(read_config project.name)
PROJECT_TITLE=$(read_config project.title)
PROJECT_DESCRIPTION=$(read_config project.description)
PROJECT_URL=$(read_config_default project.url "")
CI_RUNNER=$(read_config_default ci.runner "ubuntu-latest")
CI_NODE=$(read_config_default ci.node_version "20")
CI_PLATFORM=$(read_config_default ci.platform "github")
QMD_GLOBAL=$(read_config qmd.global_context)
QMD_ENTITY=$(read_config_default qmd.entity_context "")
QMD_CONCEPT=$(read_config_default qmd.concept_context "")
QMD_GUIDE=$(read_config_default qmd.guide_context "")
QMD_REFERENCE=$(read_config_default qmd.reference_context "")
TODAY=$(date +%Y-%m-%d)

# --- Validate config ---
info "Validating config..."
python3 "$SCRIPT_DIR/validate-config.py" "$CONFIG_FILE" || error "Config validation failed."

# --- Copy shared config files from submodule ---
info "Copying shared config files..."
generate_agents_md "$INSTANCE_ROOT" "$INSTANCE_ROOT/.llm-wiki"
generate_markdownlint "$INSTANCE_ROOT" "$INSTANCE_ROOT/.llm-wiki"
generate_pre_commit "$INSTANCE_ROOT" "$INSTANCE_ROOT/.llm-wiki"

# --- Generate files (always regenerated from config) ---
info "Generating files..."

# Remove stale workflow directories from a previous platform before
# regenerating. Only the configured platform's directory should survive.
case "$CI_PLATFORM" in
    forgejo) rm -rf "$INSTANCE_ROOT/.github/workflows" "$INSTANCE_ROOT/.gitea/workflows" ;;
    gitea)   rm -rf "$INSTANCE_ROOT/.github/workflows" "$INSTANCE_ROOT/.forgejo/workflows" ;;
    *)       rm -rf "$INSTANCE_ROOT/.forgejo/workflows" "$INSTANCE_ROOT/.gitea/workflows" ;;
esac
# Also remove now-empty platform dirs if left behind
rmdir "$INSTANCE_ROOT/.github" "$INSTANCE_ROOT/.forgejo" "$INSTANCE_ROOT/.gitea" 2>/dev/null || true

generate_gitignore "$INSTANCE_ROOT"
generate_remarkrc "$INSTANCE_ROOT"
generate_package_json "$INSTANCE_ROOT" "$PROJECT_TITLE"
generate_qmd_yml "$INSTANCE_ROOT" "$QMD_GLOBAL" "$QMD_ENTITY" "$QMD_CONCEPT" "$QMD_GUIDE" "$QMD_REFERENCE"
generate_ci_workflow "$INSTANCE_ROOT" "$CI_RUNNER" "$CI_NODE" "$CI_PLATFORM"

# --- Create wiki directory structure ---
info "Creating wiki directories..."
mkdir -p "$INSTANCE_ROOT/wiki/entities"
mkdir -p "$INSTANCE_ROOT/wiki/concepts"
mkdir -p "$INSTANCE_ROOT/wiki/guides"
mkdir -p "$INSTANCE_ROOT/wiki/reference"
mkdir -p "$INSTANCE_ROOT/raw"
touch "$INSTANCE_ROOT/raw/.gitkeep"

# --- Create content files (only if they don't exist) ---
if [ ! -f "$INSTANCE_ROOT/index.md" ]; then
    info "Creating index.md..."
    generate_index "$INSTANCE_ROOT" "$PROJECT_TITLE" "$TODAY"
else
    info "index.md already exists. Skipping."
fi

if [ ! -f "$INSTANCE_ROOT/log.md" ]; then
    info "Creating log.md..."
    generate_log "$INSTANCE_ROOT" "$PROJECT_TITLE" "$TODAY"
else
    info "log.md already exists. Skipping."
fi

if [ ! -f "$INSTANCE_ROOT/README.md" ]; then
    info "Creating README.md..."
    generate_readme "$INSTANCE_ROOT" "$PROJECT_NAME" "$PROJECT_TITLE" "$PROJECT_DESCRIPTION" "$PROJECT_URL"
else
    info "README.md already exists. Skipping."
fi

# --- Install dependencies ---
info "Installing npm dependencies..."
if command -v npm &>/dev/null; then
    npm ci 2>/dev/null || npm install
else
    warn "npm not found. Run 'npm ci' manually."
fi

# --- Install pre-commit hooks ---
if ! command -v pre-commit &>/dev/null; then
    info "Installing pre-commit..."
    pip3 install pre-commit 2>/dev/null || python3 -m pip install --break-system-packages pre-commit 2>/dev/null || warn "Could not install pre-commit. Run: pip install pre-commit"
fi
if command -v pre-commit &>/dev/null; then
    info "Installing pre-commit hooks..."
    pre-commit install 2>/dev/null || warn "pre-commit install failed."
else
    warn "pre-commit not available. Install manually: pip install pre-commit && pre-commit install"
fi

# --- Summary ---
echo ""
info "========================================="
info "  LLM Wiki instance bootstrapped!"
info "========================================="
info ""
info "  Project:      $PROJECT_TITLE"
info "  Config:       wiki.config.yml"
info "  Submodule:    .llm-wiki/"
info ""
info "  Next steps:"
info "    1. Add content to wiki/ (see AGENTS.md for schema)"
info "    2. Drop source documents into raw/"
info "    3. Start your LLM agent and begin ingesting"
info "    4. Run 'npm run check' to validate"
info ""
info "  To update shared tooling:"
info "    cd .llm-wiki && git pull origin main && cd .."
info ""
