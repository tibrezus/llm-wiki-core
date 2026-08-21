#!/usr/bin/env bash
set -euo pipefail

# Architecture graph pipeline — fetch + validate rig.db.
#
# For every project declared under `arch.projects` in wiki.config.yml:
#   1. fetch the project-published rig.db from its rig_url
#   2. validate it (roundtrip + schema + evidence rules)
#   3. write it verbatim to raw/arch/<name>/rig.db
#
# rig.db is the single source of truth (machine interface — query it with
# rig-query.py, never load it into context). It is committed to raw/
# (immutable). No transformation, no rollup, no extraction — the project
# owns graph generation entirely.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"          # .../scripts/arch
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"           # .../scripts
LIB_DIR="$SCRIPTS_DIR/lib"

source "$LIB_DIR/config.sh"
require_config
cd "$INSTANCE_ROOT"

RAW_ARCH="$INSTANCE_ROOT/raw/arch"
mkdir -p "$RAW_ARCH"

# Check if any projects are declared.
PROJECT_COUNT=$(python3 -c "
import yaml
with open('$CONFIG_FILE') as f:
    c = yaml.safe_load(f) or {}
print(len((c.get('arch') or {}).get('projects') or []))
")

if [ "$PROJECT_COUNT" -eq 0 ]; then
    echo "No arch.projects configured — nothing to do."
    exit 0
fi

FAILED=0

# Iterate projects (unit-separator delimited so empty fields survive).
while IFS=$'\x1f' read -r NAME RIG_URL TOKEN_ENV; do
    [ -n "$NAME" ] || continue
    echo ""
    echo "=== Project: $NAME ==="
    PROJECT_DIR="$RAW_ARCH/$NAME"
    mkdir -p "$PROJECT_DIR"
    OUT="$PROJECT_DIR/rig.db"

    [ -n "$RIG_URL" ] || { echo "::error::$NAME: rig_url is required"; FAILED=1; continue; }

    # For private project repos, rig_token_env names a CI secret whose value
    # is injected into the environment under the same name by the runner.
    # Works for GitHub PATs and Forgejo tokens alike (same auth header).
    CURL_AUTH=()
    if [ -n "$TOKEN_ENV" ]; then
        TOKEN_VALUE="${!TOKEN_ENV:-}"
        if [ -z "$TOKEN_VALUE" ]; then
            echo "::error::$NAME: rig_token_env '$TOKEN_ENV' is not set in CI"
            FAILED=1
            continue
        fi
        CURL_AUTH=(-H "Authorization: token $TOKEN_VALUE")
    fi

    echo "fetching RIG from $RIG_URL"
    if ! curl -fsSL "${CURL_AUTH[@]}" "$RIG_URL" -o "$OUT"; then
        echo "::error::$NAME: failed to fetch RIG from $RIG_URL"
        FAILED=1
        continue
    fi

    [ -s "$OUT" ] || { echo "::error::$NAME: RIG is empty"; FAILED=1; continue; }

    echo "validating RIG..."
    if ! python3 "$SCRIPT_DIR/validate-rig.py" "$OUT"; then
        echo "::error::$NAME: RIG validation failed"
        FAILED=1
        continue
    fi

    echo "RIG compliance audit (paper: arXiv:2601.10112)..."
    python3 "$SCRIPT_DIR/rig-compliance.py" "$OUT" || true

    echo "OK: $OUT ($(wc -c < "$OUT") bytes)"
done < <(python3 -c "
import yaml
with open('$CONFIG_FILE') as f:
    c = yaml.safe_load(f) or {}
for p in (c.get('arch') or {}).get('projects') or []:
    print('\x1f'.join([p.get('name',''), p.get('rig_url',''), p.get('rig_token_env','')]))
")

echo ""
if [ "$FAILED" -eq 1 ]; then
    echo "=== Architecture pipeline FAILED ==="
    exit 1
fi
echo "=== Architecture pipeline complete ==="
echo "Artifacts in $RAW_ARCH/ — committed to raw/ (immutable)."
