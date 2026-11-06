#!/usr/bin/env bash
set -euo pipefail

# raw/ is immutable — with one carve-out: DELETIONS of regenerated artifacts
# (raw/arch/**/rig.db) are policy-sanctioned (AGENTS.md > Binary Files, rule 3;
# the guard hard-fails on these paths, so keeping them committed breaks CI).
# Additions/modifications of anything in raw/ remain forbidden.
changed=$(git diff --cached --name-only raw/)
violations=""
while IFS= read -r f; do
    [ -n "$f" ] || continue
    case "$f" in
        raw/arch/*/rig.db|raw/arch/*/*/rig.db)
            # sanctioned deletion only if actually deleted from the index
            if git diff --cached --name-status -- "$f" | grep -q '^D'; then
                continue
            fi
            ;;
    esac
    violations="${violations}${f}"$'\n'
done <<< "$changed"
if [ -n "$violations" ]; then
    echo "ERROR: never modify files in raw/: $violations"
    exit 1
fi
