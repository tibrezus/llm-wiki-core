#!/usr/bin/env bash
set -euo pipefail

# Repo-size guard — catch binary bloat before it enters git history.
#
# Git stores every committed byte forever: a 3 MB binary committed 200 times is
# ~600 MB of history that no later commit can undo. This guard fails when a
# large binary is committed *without* being routed to git-lfs, and when any
# tracked file would bloat the repo past a hard ceiling.
#
# Rules (all configurable via env):
#   LARGE_KB   — a tracked non-LFS binary above this size is an error
#                (default 512 KB; LFS-routed paths are always allowed)
#   HARD_MB    — absolute ceiling for any single tracked file
#                (default 50 MB, LFS or not — even LFS should be justified)
#
# LFS routing is read from .gitattributes (filter=lfs patterns), so it works
# identically in CI and locally, with or without git-lfs installed.
#
# Usage:
#   bash .llm-wiki/scripts/check-repo-size.sh            # whole tree
#   BASE_REF=origin/main bash .../check-repo-size.sh     # only what the diff adds

LARGE_KB="${LARGE_KB:-512}"
HARD_MB="${HARD_MB:-50}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTANCE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$INSTANCE_ROOT"

echo "--- repo size guard (LFS routing + large binaries) ---"

[ -f .gitattributes ] && echo "LFS patterns:" && grep -E 'filter=lfs' .gitattributes || echo "LFS patterns: (none)"

# ---------------------------------------------------------------------------
# 1. Build the list of LFS-tracked path patterns from .gitattributes.
#    We keep the raw git attribute patterns and ask git itself which paths they
#    match — no reimplementation of fnmatch semantics.
# ---------------------------------------------------------------------------
lfs_match() {
    # $1 = path; true if git considers it filtered through lfs
    local attr
    attr=$(git check-attr --all -- "$1" 2>/dev/null | sed -n 's/.*: filter: //p')
    [ "$attr" = "lfs" ]
}

# ---------------------------------------------------------------------------
# 2. Which files to inspect? The diff (if BASE_REF resolvable) or the tree.
# ---------------------------------------------------------------------------
files=""
if [ -n "${BASE_REF:-}" ]; then
    base="$BASE_REF"
    if git rev-parse --verify --quiet "$base" >/dev/null 2>&1; then
        echo "Mode: diff against $base"
        files=$(git diff --name-only --diff-filter=AM "$base"...HEAD 2>/dev/null || true)
        if [ -z "$files" ]; then
            echo "  no files added or modified by the diff"
            echo "OK"
            exit 0
        fi
    else
        echo "::warning::BASE_REF '$base' not resolvable; falling back to whole tree"
    fi
fi
if [ -z "$files" ]; then
    echo "Mode: whole tracked tree"
    files=$(git ls-files)
fi

# ---------------------------------------------------------------------------
# 3. Classify each file: size + binary-ness (NUL byte in first 8 KB).
# ---------------------------------------------------------------------------
errors=0
violations=""
largest_kb=0
largest_path=""

is_binary() {
    # rc 0 = binary. Portable NUL-byte probe: hexdump the first 8 KB and look
    # for an exact 00 token (argv cannot carry a literal NUL, so grep-pattern
    # based probes are unreliable). NOTE: must not use `grep -q` here — under
    # `set -o pipefail` its early exit SIGPIPEs od/head and the pipeline would
    # report failure even on a match. `grep -c` reads to EOF, so it is safe.
    local count
    count=$(head -c 8192 "$1" 2>/dev/null | od -An -v -tx1 2>/dev/null \
        | tr -s ' ' '\n' | grep -cx '00' || true)
    [ "${count:-0}" -gt 0 ]
}

while IFS= read -r f; do
    [ -n "$f" ] || continue
    [ -f "$f" ] || continue
    kb=$(( ( $(wc -c < "$f") + 1023 ) / 1024 ))
    [ "$kb" -gt "$largest_kb" ] && { largest_kb=$kb; largest_path=$f; }

    if [ "$kb" -gt $(( HARD_MB * 1024 )) ]; then
        violations="${violations}${f}  (${kb} KB) exceeds HARD_MB=${HARD_MB} MB ceiling"$'\n'
        errors=$((errors + 1))
        continue
    fi

    if [ "$kb" -gt "$LARGE_KB" ] && is_binary "$f"; then
        if lfs_match "$f"; then
            echo "  OK (LFS): $f (${kb} KB)"
            case "$f" in
                *.db|*.sqlite|*.sqlite3|*.db-wal|*.db-shm)
                    echo "    ::warning::'$f' looks regenerable — prefer rebuilding it from raw/ instead of committing it (see AGENTS.md > Binary Files, rule 3)"
                    ;;
            esac
        else
            violations="${violations}${f}  (${kb} KB) is binary, not LFS-tracked"$'\n'
            errors=$((errors + 1))
        fi
    fi
done <<< "$files"

# ---------------------------------------------------------------------------
# 4. Report.
# ---------------------------------------------------------------------------
if [ "$errors" -gt 0 ]; then
    echo ""
    echo "::error::Large binaries must be git-lfs tracked (see AGENTS.md > Binary Files)."
    echo "Violations:"
    printf '%s' "$violations"
    echo ""
    echo "Fix a file already committed as a plain blob:"
    echo "  git lfs migrate import --include=\"<pattern>\"        # rewrites history"
    echo "Fix going forward: add the pattern to .gitattributes as:"
    echo "  <pattern> filter=lfs diff=lfs merge=lfs -text"
    exit 1
fi

echo "  largest tracked file: ${largest_path} (${largest_kb} KB)"
if git rev-parse --git-dir >/dev/null 2>&1; then
    echo "  current pack (informational): $(git count-objects -vH | sed -n 's/^size-pack: //p')"
fi
echo "OK"