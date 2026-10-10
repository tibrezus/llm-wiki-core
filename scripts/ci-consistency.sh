#!/usr/bin/env bash
set -euo pipefail

# Consistency check: verify generated files match what the current module
# would produce from wiki.config.yml. Run in CI to catch drift.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$SCRIPT_DIR/lib"
source "$LIB_DIR/config.sh"
source "$LIB_DIR/generate.sh"

require_config

echo "=== Consistency Check ==="

# Read all config values
PROJECT_TITLE=$(read_config project.title)
CI_RUNNER=$(read_config_default ci.runner "ubuntu-latest")
CI_NODE=$(read_config_default ci.node_version "20")
CI_PLATFORM=$(read_config_default ci.platform "github")
QMD_GLOBAL=$(read_config qmd.global_context)
QMD_ENTITY=$(read_config_default qmd.entity_context "")
QMD_CONCEPT=$(read_config_default qmd.concept_context "")
QMD_GUIDE=$(read_config_default qmd.guide_context "")
QMD_REFERENCE=$(read_config_default qmd.reference_context "")
PROJECT_NAME=$(read_config project.name)
PROJECT_DESCRIPTION=$(read_config project.description)
PROJECT_URL=$(read_config_default project.url "")

# Create temp dir for expected files
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Generate expected files
generate_gitignore "$TMPDIR"
generate_gitattributes "$TMPDIR"
generate_remarkrc "$TMPDIR"
generate_package_json "$TMPDIR" "$PROJECT_TITLE"
generate_qmd_yml "$TMPDIR" "$QMD_GLOBAL" "$QMD_ENTITY" "$QMD_CONCEPT" "$QMD_GUIDE" "$QMD_REFERENCE"
generate_ci_workflow "$TMPDIR" "$CI_RUNNER" "$CI_NODE" "$CI_PLATFORM"

# Files to compare (generated from config)
CI_PLATFORM=$(read_config_default ci.platform "github")

# Determine the workflow directory from the platform config.
WF_PATH=
WARECASE_PATH=".github/workflows/wiki-ci.yml"
case "$CI_PLATFORM" in
    forgejo) WARECASE_PATH=".forgejo/workflows/wiki-ci.yml" ;;
    gitea)   WARECASE_PATH=".gitea/workflows/wiki-ci.yml" ;;
    *)       WARECASE_PATH=".github/workflows/wiki-ci.yml" ;;
esac

GENERATED_FILES=('.gitignore' '.gitattributes' '.remarkrc.mjs' 'package.json' 'qmd.yml' "${WARECASE_PATH}")

# Workflow directories for every platform. Only the configured platform's
# directory should exist; the others are stale leftovers from a platform
# switch and must be removed (a stray wiki-ci.yml in the wrong directory
# would either be ignored by the runner or, worse, run with the wrong action URLs).
ALL_WF_DIRS=('.github/workflows' '.forgejo/workflows' '.gitea/workflows')
ACTIVE_WF_DIR="$(dirname "$WARECASE_PATH")"

# Files to compare (copied from submodule)
COPIED_FILES=('AGENTS.md' '.markdownlint.yaml' '.pre-commit-config.yaml')
SUBMODULE_DIR="$INSTANCE_ROOT/.llm-wiki"

# Resolve the submodule source path for a copied file.
# AGENTS.md is sourced from instance/AGENTS.md (the wiki schema); all other
# copied files live at the module root.
copied_source() {
    case "$1" in
        AGENTS.md) echo "$SUBMODULE_DIR/instance/AGENTS.md" ;;
        *)         echo "$SUBMODULE_DIR/$1" ;;
    esac
}

FAILED=0

echo ""
echo "--- Generated Files ---"
for file in "${GENERATED_FILES[@]}"; do
    expected="$TMPDIR/$file"
    actual="$INSTANCE_ROOT/$file"
    if [ ! -f "$actual" ]; then
        echo "  MISSING: $file"
        FAILED=1
        continue
    fi
    if ! diff -q "$expected" "$actual" > /dev/null 2>&1; then
        echo "  DRIFT: $file differs from expected"
        diff --unified=3 "$expected" "$actual" | head -20
        FAILED=1
    else
        echo "  OK: $file"
    fi
done

echo ''
echo '--- Copied Files (must match submodule) ---'
for file in "${COPIED_FILES[@]}"; do
    expected="$(copied_source "$file")"
    actual="$INSTANCE_ROOT/$file"
    if [ ! -f "$expected" ]; then
        echo "  MISSING-IN-SUBMODULE: $file"
        FAILED=1
        continue
    fi
    if [ ! -f "$actual" ]; then
        echo "  MISSING: $file"
        FAILED=1
        continue
    fi
    if [ -L "$actual" ]; then
        echo "  IS-SYMLINK: $file (expected regular file copy)"
        FAILED=1
        continue
    fi
    if ! diff -q "$expected" "$actual" > /dev/null 2>&1; then
        echo "  DRIFT: $file differs from submodule version"
        FAILED=1
    else
        echo "  OK: $file"
    fi
done

echo ""
echo "--- Stale Workflow Directories ---"
for wf_dir in "${ALL_WF_DIRS[@]}"; do
    if [ "$wf_dir" = "$ACTIVE_WF_DIR" ]; then
        continue
    fi
    if [ -e "$INSTANCE_ROOT/$wf_dir" ]; then
        echo "  STALE: $wf_dir/ (platform is $CI_PLATFORM; remove with 'rm -rf $wf_dir')"
        FAILED=1
    fi
done

echo ""
echo "--- Directory Structure ---"
for dir in wiki/entities wiki/concepts wiki/guides wiki/reference raw; do
    if [ -d "$INSTANCE_ROOT/$dir" ]; then
        echo "  OK: $dir/"
    else
        echo "  MISSING: $dir/"
        FAILED=1
    fi
done

echo ""
echo "--- Config Validation ---"
if python3 "$SCRIPT_DIR/validate-config.py" "$CONFIG_FILE" > /dev/null 2>&1; then
    echo "  OK: wiki.config.yml"
else
    echo "  INVALID: wiki.config.yml"
    python3 "$SCRIPT_DIR/validate-config.py" "$CONFIG_FILE"
    FAILED=1
fi

echo ""
if [ "$FAILED" -eq 1 ]; then
    echo "=== Consistency Check FAILED ==="
    echo "Run 'bash .llm-wiki/scripts/bootstrap.sh' to regenerate drifted files."
    exit 1
else
    echo "=== Consistency Check PASSED ==="
    exit 0
fi
