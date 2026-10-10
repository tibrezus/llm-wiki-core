#!/usr/bin/env bash
set -euo pipefail

# Lint pipeline — installs tools and runs all validators.
# Called by the reusable lint workflow and usable locally.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$SCRIPT_DIR/lib"
source "$LIB_DIR/config.sh"
source "$LIB_DIR/install-tools.sh"

require_config
cd "$INSTANCE_ROOT"

echo "=== LLM Wiki Lint Pipeline ==="
echo "Instance root: $INSTANCE_ROOT"

install_all_lint_tools
configure_path

# Ensure pip user bin is on PATH for this shell too
export PATH="$HOME/.local/bin:$PATH"

echo ""
echo "--- markdownlint ---"
markdownlint-cli2 "wiki/**/*.md" "index.md" "log.md"

echo ""
echo "--- mdlint-obsidian ---"
# Filter out std-internal-link — we intentionally use [text](path.md) links
# for platform rendering (Codeberg/GitHub/Forgejo). All other mdlint rules apply.
MDLINT_OUT=$(mdlint wiki/ --vault wiki/ --severity error --format json 2>/dev/null || true)
echo "$MDLINT_OUT" | python3 -c "
import json, sys
try:
    data = json.loads(sys.stdin.read().strip())
except:
    sys.exit(0)
filtered = [e for e in data if e.get('rule') != 'std-internal-link']
if filtered:
    print(json.dumps(filtered, indent=2))
    sys.exit(1)
"

echo ""
echo "--- remark frontmatter schema ---"
npx remark wiki/ --frail

echo ""
echo "--- unique filenames ---"
dups=$(find wiki/ -name "*.md" -exec basename {} \; | sort | uniq -d)
if [ -n "$dups" ]; then
    echo "::error::Duplicate filenames in wiki/: $dups"
    exit 1
fi
echo "OK"

echo ""
echo "--- mermaid diagram validation ---"
# Extract every ```mermaid block from wiki pages and render-check it with mmdc.
# Catches broken Mermaid syntax before it ships.
MERMAID_FAILED=0
MERMAID_COUNT=$(python3 "$SCRIPT_DIR/validate-mermaid.py" wiki/ "$INSTANCE_ROOT/.llm-wiki/scripts/lib/puppeteer-config.json" 2>&1) || MERMAID_FAILED=1
echo "$MERMAID_COUNT"
if [ "$MERMAID_FAILED" -eq 1 ]; then
    echo "::error::Mermaid diagram validation failed"
    exit 1
fi

echo ""
echo "--- likec4 model validation ---"
# Validate LikeC4 (.c4) model files. Each project lives in its own
# directory under raw/arch/<project>/, so we run likec4 per-project.
# We use 'likec4 validate' (not 'format --check') because validate exits
# non-zero on syntax/semantic errors, while format --check always exits 0.
C4_COUNT=0
LIKEC4_FAILED=0
while IFS= read -r c4file; do
    [ -z "$c4file" ] && continue
    C4_COUNT=$((C4_COUNT + 1))
    c4dir=$(dirname "$c4file")
    echo "  checking $c4file"
    if ! likec4 validate "$c4dir" 2>&1; then
        echo "::error::LikeC4 model validation failed for $c4file"
        LIKEC4_FAILED=1
    fi
done < <(find raw/arch -mindepth 2 -name 'model.c4' 2>/dev/null || true)
if [ "$LIKEC4_FAILED" -eq 1 ]; then
    exit 1
fi
if [ "$C4_COUNT" -gt 0 ]; then
    echo "OK ($C4_COUNT model file(s))"
else
    echo "OK (no .c4 model files)"
fi

echo ""
echo "--- raw/ immutability ---"
# raw/ holds curated source documents that must NEVER be modified once placed.
# The single exception is raw/arch/ — that subdirectory holds CI-fetched /
# agent-regenerated Repository Intelligence Graphs (RIG JSONs) used by the
# LC4 architecture workflow. RIGs are intentionally refreshed over time, so
# they are exempt from the immutability rule.
#
# This check only runs on pull/merge requests. PR/MR checkouts (actions/
# checkout, Forgejo Actions, GitLab CI) fetch only the PR ref by default and
# leave the base branch absent, which would make `git diff origin/main...HEAD`
# fail with 'bad revision'. We therefore resolve the base branch name from
# platform-specific env vars and fetch it explicitly before diffing.

base_ref=""
# GitHub Actions + Forgejo Actions (Gitea) — pull_request events
if [ -z "$base_ref" ] && [ -n "${GITHUB_BASE_REF:-}" ]; then
    base_ref="$GITHUB_BASE_REF"
fi
# GitLab CI — merge_request_event
if [ -z "$base_ref" ] && [ -n "${CI_MERGE_REQUEST_TARGET_BRANCH_NAME:-}" ]; then
    base_ref="$CI_MERGE_REQUEST_TARGET_BRANCH_NAME"
fi
# Bitbucket Pipelines / generic fallbacks
if [ -z "$base_ref" ] && [ -n "${BITBUCKET_PR_DESTINATION_BRANCH:-}" ]; then
    base_ref="$BITBUCKET_PR_DESTINATION_BRANCH"
fi

if [ -n "$base_ref" ]; then
    # Make the base branch locally resolvable (shallow-checkout safe). Best
    # effort: if the fetch fails (offline runner, restricted refspec, etc.) we
    # fall through to the rev-parse guard rather than failing the pipeline.
    git fetch --depth=1 origin "$base_ref" >/dev/null 2>&1 || true
    base="origin/$base_ref"
    if git rev-parse --verify --quiet "$base" >/dev/null; then
        # Changed raw/ files, EXCLUDING raw/arch/ (legitimate RIG additions).
        changed=$(git diff --name-only "${base}...HEAD" -- raw/ | grep -vE '^raw/arch/' || true)
        if [ -n "$changed" ]; then
            echo "::error::Files in raw/ (outside raw/arch/) must not be modified: $changed"
            exit 1
        fi
    else
        echo "::warning::raw/ immutability check skipped: base ref '$base' not resolvable"
    fi
fi
echo "OK"

echo ""
echo "--- repo size guard ---"
# Binaries must be git-lfs tracked: git keeps every committed byte forever, so
# a large binary committed N times is N × size of unremovable history.
# Delegated to its own script (also runnable locally + unit-tested).
BASE_REF="${base:-}" bash "$SCRIPT_DIR/check-repo-size.sh"

echo ""
echo "--- wiki health check ---"
python3 .llm-wiki/scripts/wiki-health.py wiki/

echo ""
echo "--- page size ---"
# Each wiki/ page should be absorbable in a single glance. Over-limit pages
# emit an annotation nudging shrink/split; fails CI only when
# pages.size_strict is true (default: warn).
python3 "$SCRIPT_DIR/validate-page-size.py" wiki/ "$CONFIG_FILE"

echo ""
echo "--- RIG compliance audit (paper: arXiv:2601.10112) ---"
# Audit every committed RIG against the paper's standard.
# ERROR-level checks (correctness) are gating — they indicate structural
# defects (duplicate IDs, dangling refs, circular deps).
# WARN-level checks (evidence, tests, aggregators) are informational —
# we are working towards full compliance but do not block on them.
# Guard with [ -d ]: `find raw/arch` exits non-zero (and under `set -euo
# pipefail` aborts the pipeline) when raw/arch/ is absent — i.e. on any
# instance without architecture projects. Only count if the dir exists.
RIG_COUNT=0
if [ -d raw/arch ]; then
    RIG_COUNT=$(find raw/arch -name 'rig.json' 2>/dev/null | wc -l)
fi
if [ "$RIG_COUNT" -gt 0 ]; then
    python3 .llm-wiki/scripts/arch/rig-compliance.py --all raw/arch/ 2>&1
    # Exit 1 only if the auditor found ERROR-level issues (exit code 1).
    # Exit code 0 = warnings only, 2 = --strict (not used here).
    RC=$?
    if [ "$RC" -eq 1 ]; then
        echo "::error::RIG compliance audit found structural errors"
        exit 1
    fi
    echo "OK ($RIG_COUNT RIG file(s) audited)"
else
    echo "OK (no RIG files)"
fi

echo ""
echo "=== Lint Pipeline Complete ==="
