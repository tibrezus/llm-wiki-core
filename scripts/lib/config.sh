#!/usr/bin/env bash
set -euo pipefail

# Shared configuration reader for wiki.config.yml.
# Source this file: source "$(dirname "$0")/config.sh"
# Provides: CONFIG_FILE, read_config, require_config

_resolve_dirs() {
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
    local submodule_dir
    submodule_dir="$(cd "$script_dir/.." 2>/dev/null && pwd)"
    if [ -d "$submodule_dir/scripts/lib" ]; then
        INSTANCE_ROOT="$(cd "$submodule_dir/.." && pwd)"
    else
        INSTANCE_ROOT="$(pwd)"
    fi
    CONFIG_FILE="$INSTANCE_ROOT/wiki.config.yml"
}
_resolve_dirs

read_config() {
    local key="$1"
    python3 -c "
import yaml, sys
with open(sys.argv[1]) as f:
    config = yaml.safe_load(f)
keys = sys.argv[2].split('.')
val = config
for k in keys:
    if val is None or k not in val:
        sys.exit(1)
    val = val[k]
print(val)
" "$CONFIG_FILE" "$key"
}

read_config_default() {
    local key="$1"
    local default="${2:-}"
    local val
    val=$(read_config "$key" 2>/dev/null) && echo "$val" || echo "$default"
}

# Exit 0 if a dotted config key exists (and is non-empty), 1 otherwise.
config_has() {
    local key="$1"
    python3 -c "
import sys, yaml
with open('$CONFIG_FILE') as f:
    c = yaml.safe_load(f) or {}
v = c
for k in '$key'.split('.'):
    if not isinstance(v, dict) or k not in v:
        sys.exit(1)
    v = v[k]
sys.exit(0 if v else 1)
" 2>/dev/null
}

require_config() {
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "ERROR: wiki.config.yml not found at $CONFIG_FILE"
        echo "Run .llm-wiki/scripts/bootstrap.sh first."
        exit 1
    fi
}

require_submodule() {
    if [ ! -d "$INSTANCE_ROOT/.llm-wiki" ]; then
        echo "ERROR: Submodule not found at .llm-wiki/"
        echo "Run: git submodule add https://github.com/tibrezus/llm-wiki-core.git .llm-wiki"
        exit 1
    fi
}
