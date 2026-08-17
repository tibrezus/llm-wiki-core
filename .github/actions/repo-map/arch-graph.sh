#!/usr/bin/env bash
set -euo pipefail

# arch-graph.sh — Full deterministic architecture pipeline for project CI.
#
# Pipeline: source → RIG → model.c4 → Mermaid → wiki pages
#
# Runs in the current source directory (already checked out by CI). Produces:
#   <output-dir>/rig.json
#   <output-dir>/model.c4
#   <output-dir>/*.mmd            (raw Mermaid exports)
#   <output-dir>/Architecture.md  (wiki-ready, renders natively on GitHub/Codeberg)
#   <output-dir>/Components/*.md  (one page per component view, if any)
#
# This is the SAME deterministic pipeline harmostes runs, extracted into a
# single script that any project's CI can call. No LLM, no k8s, no external
# infrastructure — just Python + Node.js + git.
#
# Usage:
#   arch-graph.sh [options]
#
# Options:
#   --language <lang>     Language hint for the RIG emitter (go, zig, python, ...)
#   --source-dir <dir>    Source directory (default: current directory)
#   --output-dir <dir>    Output directory (default: ./arch-out)
#   --project-name <name> Project name for wiki page titles (default: repo name)
#   --tools-dir <dir>     Directory containing emit-rig.sh etc. (default: this script's dir)
#   --skip-mermaid        Skip likec4 Mermaid generation (RIG + model.c4 only)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LANGUAGE=""
SOURCE_DIR="."
OUTPUT_DIR="./arch-out"
PROJECT_NAME=""
TOOLS_DIR="$SCRIPT_DIR"
SKIP_MERRAID=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --language)     LANGUAGE="$2"; shift 2;;
        --source-dir)   SOURCE_DIR="$2"; shift 2;;
        --output-dir)   OUTPUT_DIR="$2"; shift 2;;
        --project-name) PROJECT_NAME="$2"; shift 2;;
        --tools-dir)    TOOLS_DIR="$2"; shift 2;;
        --skip-mermaid) SKIP_MERRAID=true; shift;;
        *) echo "[arch-graph] Unknown option: $1"; exit 1;;
    esac
done

SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
OUTPUT_DIR="$(mkdir -p "$OUTPUT_DIR" && cd "$OUTPUT_DIR" && pwd)"

# Auto-detect project name from git remote or directory name
if [ -z "$PROJECT_NAME" ]; then
    PROJECT_NAME="$(basename "$(git -C "$SOURCE_DIR" remote get-url origin 2>/dev/null | sed 's/\.git$//' || echo "$SOURCE_DIR")")"
    PROJECT_NAME="${PROJECT_NAME:-project}"
fi

log() { echo "[arch-graph] $*"; }

# ── Step 1: Generate RIG ─────────────────────────────────────────────
log "Step 1/4: Generating RIG (language=${LANGUAGE:-auto})…"
RIG_FILE="$OUTPUT_DIR/rig.json"
if [ -n "$LANGUAGE" ]; then
    ( cd "$SOURCE_DIR" && bash "$TOOLS_DIR/emit-rig.sh" "$RIG_FILE" "$LANGUAGE" )
else
    ( cd "$SOURCE_DIR" && bash "$TOOLS_DIR/emit-rig.sh" "$RIG_FILE" )
fi

COMPONENTS=$(python3 -c "import json;print(len(json.load(open('$RIG_FILE'))['components']))" 2>/dev/null || echo "?")
log "  RIG: $COMPONENTS components ($RIG_FILE)"

# ── Step 2: Generate model.c4 ────────────────────────────────────────
log "Step 2/4: Generating model.c4 (deterministic, from rig.db + code comments)…"
MODEL_FILE="$OUTPUT_DIR/model.c4"
RIG_DB="${RIG_FILE%.json}.db"
if [ ! -f "$RIG_DB" ]; then
    log "  FATAL: $RIG_DB missing — emit-rig.py must produce it alongside the JSON"
    exit 1
fi
python3 "$TOOLS_DIR/rig-to-c4.py" "$RIG_DB" --source-dir "$SOURCE_DIR" -o "$MODEL_FILE"
log "  model.c4: $(wc -l < "$MODEL_FILE") lines"

# ── Step 3: Generate Mermaid diagrams ─────────────────────────────────
if [ "$SKIP_MERRAID" = true ]; then
    log "Step 3/4: Skipping Mermaid generation (--skip-mermaid)"
    log "Done. Output: $OUTPUT_DIR"
    echo "{\"status\":\"ok\",\"output_dir\":\"$OUTPUT_DIR\",\"components\":$COMPONENTS,\"mermaid\":false}"
    exit 0
fi

log "Step 3/4: Generating Mermaid diagrams (likec4 gen mermaid)…"
# likec4 scans a DIRECTORY for .c4 files, not a single file. The model.c4
# is already in OUTPUT_DIR, so we pass OUTPUT_DIR as the workspace.
MMD_DIR="$OUTPUT_DIR"
if ! command -v likec4 &>/dev/null; then
    log "  likec4 not found — installing…"
    npm install -g likec4 2>&1 | tail -1
fi
likec4 gen mermaid --use-dot -o "$MMD_DIR" "$OUTPUT_DIR" 2>&1 | tail -5
MMD_COUNT=$(find "$MMD_DIR" -maxdepth 1 -name '*.mmd' | wc -l)
if [ "$MMD_COUNT" -eq 0 ]; then
    log "WARN: --use-dot produced 0 diagrams — retrying with WASM layout engine…"
    likec4 gen mermaid -o "$MMD_DIR" "$OUTPUT_DIR" 2>&1 | tail -5
    MMD_COUNT=$(find "$MMD_DIR" -maxdepth 1 -name '*.mmd' | wc -l)
fi
log "  Mermaid: $MMD_COUNT diagram(s)"

# ── Step 4: Build wiki pages ──────────────────────────────────────────
log "Step 4/4: Building wiki pages…"
python3 "$TOOLS_DIR/build-wiki-pages.py" "$MMD_DIR" \
    --output-dir "$OUTPUT_DIR/wiki" \
    --project-name "$PROJECT_NAME" \
    --rig-file "$RIG_FILE" \
    --model-file "$MODEL_FILE"

log "Done. Output: $OUTPUT_DIR"
log "  Wiki pages: $OUTPUT_DIR/wiki/"
echo "{\"status\":\"ok\",\"output_dir\":\"$OUTPUT_DIR\",\"components\":$COMPONENTS,\"mermaid\":true,\"mmd_count\":$MMD_COUNT}"
