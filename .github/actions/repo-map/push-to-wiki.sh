#!/usr/bin/env bash
set -euo pipefail

# push-to-wiki.sh — Push generated wiki pages to the project's wiki repo.
#
# Works on GitHub, Codeberg, and Forgejo. Uses GITHUB_SERVER_URL and
# GITHUB_REPOSITORY (available in all CI runners) to construct the wiki URL.
#
# The wiki repo is <server>/<owner>/<repo>.wiki.git — a separate git repo that
# all three platforms provision automatically once the wiki feature is enabled.
#
# Usage:
#   push-to-wiki.sh <pages-dir> [--token <token>] [--commit-message <msg>]
#
# Env:
#   WIKI_TOKEN          Token with wiki write access (or --token)
#   GITHUB_SERVER_URL   CI runner base URL (auto)
#   GITHUB_REPOSITORY   CI runner owner/repo (auto)

PAGES_DIR=""
# The CI's built-in token (GITHUB_TOKEN on all platforms) has access to the
# wiki repo — it's the same project, just <repo>.wiki.git. No PAT needed.
TOKEN="${GITHUB_TOKEN:-${WIKI_TOKEN:-}}"
COMMIT_MSG="Update architecture diagrams [skip ci]"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --token)          TOKEN="$2"; shift 2;;
        --commit-message) COMMIT_MSG="$2"; shift 2;;
        --*) echo "[push-to-wiki] Unknown option: $1"; exit 1;;
        *)
            if [ -z "$PAGES_DIR" ]; then
                PAGES_DIR="$1"
            else
                echo "[push-to-wiki] Unexpected argument: $1"; exit 1
            fi
            shift;;
    esac
done

if [ -z "$PAGES_DIR" ]; then
    echo "Usage: push-to-wiki.sh <pages-dir> [--token <token>] [--commit-message <msg>]"
    exit 1
fi

if [ ! -d "$PAGES_DIR" ]; then
    echo "[push-to-wiki] Pages directory not found: $PAGES_DIR"
    exit 1
fi

if [ -z "$TOKEN" ]; then
    echo "[push-to-wiki] No GITHUB_TOKEN in environment."
    echo "  The CI auto-provides GITHUB_TOKEN with 'contents: write' permission."
    echo "  Ensure your workflow has:"
    echo "    permissions:"
    echo "      contents: write"
    exit 1
fi

if [ -z "${GITHUB_REPOSITORY:-}" ]; then
    echo "[push-to-wiki] GITHUB_REPOSITORY not set — this script must run in CI"
    exit 1
fi

SERVER="${GITHUB_SERVER_URL:-https://github.com}"
SERVER_HOST="${SERVER#https://}"

# Construct the wiki clone URL with token auth.
# GitHub uses x-access-token:<token>; Forgejo/Codeberg use oauth2:<token>.
if [[ "$SERVER_HOST" == "github.com" ]]; then
    AUTH="x-access-token:${TOKEN}"
else
    AUTH="oauth2:${TOKEN}"
fi
WIKI_URL="https://${AUTH}@${SERVER_HOST}/${GITHUB_REPOSITORY}.wiki.git"

log() { echo "[push-to-wiki] $*"; }

WIKI_DIR="$(mktemp -d)/wiki"
log "cloning wiki…"
if ! git clone --depth 1 "$WIKI_URL" "$WIKI_DIR" 2>&1 | tail -1; then
    log "ERROR: wiki clone failed."
    log "  The wiki may not be initialized. On GitHub/Codeberg/Forgejo:"
    log "    1. Go to the repo → Wiki tab"
    log "    2. Create the first page (any content)"
    log "    3. Re-run this workflow"
    exit 1
fi

# Sync generated pages into the wiki repo.
# First, clean up previous generated files (so stale pages from older
# formats don't accumulate). We only remove patterns we generate.
log "cleaning up previous generated files…"
rm -rf "$WIKI_DIR/Components"  # old format (subdirectory — caused 500)
rm -f "$WIKI_DIR"/Component---*.md  # old format (flat per-component pages)
rm -f "$WIKI_DIR/Architecture.md"   # the merged page (only generated page now)
rm -f "$WIKI_DIR/C4-Model.md"       # old format (merged into Architecture.md)
rm -f "$WIKI_DIR/CI.md"             # old format (merged into Architecture.md)
rm -rf "$WIKI_DIR/raw"  # artifacts now live in the main repo

log "syncing pages from $PAGES_DIR…"
cp -r "$PAGES_DIR"/* "$WIKI_DIR/"

cd "$WIKI_DIR"
git config user.name "arch-graph-bot"
git config user.email "arch-graph-bot@users.noreply.${SERVER_HOST}"

git add -A
if git diff --cached --quiet; then
    log "no changes — wiki is up to date"
    exit 0
fi

# Show what changed
CHANGED=$(git diff --cached --name-only | wc -l)
log "committing $CHANGED changed file(s)…"
git commit -m "$COMMIT_MSG" --no-verify 2>&1 | tail -1

log "pushing…"
if git push 2>&1 | tail -1; then
    log "wiki updated successfully"
else
    log "ERROR: push failed (the wiki may have concurrent updates — re-run)"
    exit 1
fi
