#!/usr/bin/env bash
set -euo pipefail

# Shared tool installation for CI and local development.
# Source this file: source "$(dirname "$0")/install-tools.sh"

install_node_tools() {
    if command -v markdownlint-cli2 >/dev/null 2>&1; then
        echo "::group::Install Node.js tools (markdownlint-cli2 present — skipped)"
        echo "::endgroup::"; return
    fi
    echo "::group::Install Node.js tools"
    npm install -g markdownlint-cli2
    echo "::endgroup::"
}

install_python_tools() {
    if command -v mdlint >/dev/null 2>&1 && python3 -c "import yaml" >/dev/null 2>&1; then
        echo "::group::Install Python tools (mdlint + pyyaml present — skipped)"
        echo "::endgroup::"; return
    fi
    echo "::group::Install Python tools"
    _TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    _SCRIPTS_DIR="$(dirname "$_TOOLS_DIR")"

    # 1) pyyaml via the portable installer (pip / apt / dnf / apk / get-pip).
    bash "$_SCRIPTS_DIR/install-python-deps.sh" pyyaml

    # 2) mdlint-obsidian needs pip. Some runners ship system Python without
    #    pip ('No module named pip'), so bootstrap it from get-pip.py first.
    if ! python3 -m pip --version >/dev/null 2>&1; then
        echo "[install-tools] pip missing; bootstrapping via get-pip.py"
        if command -v curl >/dev/null 2>&1 \
           && curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py 2>/dev/null; then
            python3 /tmp/get-pip.py --user --break-system-packages 2>/dev/null \
              || python3 /tmp/get-pip.py --user 2>/dev/null \
              || python3 /tmp/get-pip.py 2>/dev/null \
              || true
        fi
    fi

    # 3) Install mdlint-obsidian (the lint pipeline needs the 'mdlint' binary).
    #    Try several pip invocation styles; only fail if none work.
    if python3 -m pip --version >/dev/null 2>&1; then
        python3 -m pip install --user --break-system-packages mdlint-obsidian 2>/dev/null \
          || python3 -m pip install --user mdlint-obsidian 2>/dev/null \
          || python3 -m pip install --break-system-packages mdlint-obsidian 2>/dev/null \
          || python3 -m pip install mdlint-obsidian 2>/dev/null \
          || pip3 install --user mdlint-obsidian 2>/dev/null \
          || { echo "::error::Failed to install mdlint-obsidian via pip"; exit 1; }
    else
        echo "::error::pip unavailable after bootstrap; cannot install mdlint-obsidian"
        exit 1
    fi
    echo "::endgroup::"
}

install_remark_deps() {
    echo "::group::Install remark dependencies"
    npm ci 2>/dev/null || npm install
    echo "::endgroup::"
}

# tree-sitter grammars (QMD deps) fall back to source builds when no prebuild
# matches the runner (musl containers, new node ABIs); that needs make + a
# C++ compiler. GitHub-hosted images have them; slim self-hosted runner
# containers may not.
ensure_native_build_tools() {
    if command -v make >/dev/null 2>&1 && command -v c++ >/dev/null 2>&1; then
        return
    fi
    echo "::group::Install native build tools (make, g++)"
    if command -v apk >/dev/null 2>&1; then
        apk add --no-cache make g++
    elif command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq && apt-get install -y -qq make g++ || sudo apt-get install -y -qq make g++
    else
        echo "::warning::make/c++ missing and no known package manager — tree-sitter source builds will fail"
    fi
    echo "::endgroup::"
}

install_qmd() {
    ensure_native_build_tools
    echo "::group::Install QMD"
    npm install -g @tobilu/qmd
    if ! command -v bun &>/dev/null; then
        curl -fsSL https://bun.sh/install | bash
        echo "$HOME/.bun/bin" >> "${GITHUB_PATH:-/dev/null}"
    fi
    echo "::endgroup::"
}

install_likec4() {
    if command -v likec4 >/dev/null 2>&1; then return; fi
    echo "::group::Install LikeC4"
    npm install -g likec4 2>/dev/null || npm install -g likec4
    echo "::endgroup::"
}

install_mermaid_cli() {
    if command -v mmdc >/dev/null 2>&1; then return; fi
    echo "::group::Install Mermaid CLI"
    npm install -g @mermaid-js/mermaid-cli 2>/dev/null || npm install -g @mermaid-js/mermaid-cli
    # Ensure Chromium is installed for Puppeteer (mmdc uses it to render)
    npx puppeteer browsers install chrome 2>/dev/null || true
    # Install Chrome system dependencies (needed on minimal CI runners)
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y -qq \
            libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 \
            libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
            libpango-1.0-0 libcairo2 libasound2 2>/dev/null || true
    fi
    echo "::endgroup::"
}

install_all_lint_tools() {
    install_node_tools
    install_python_tools
    install_remark_deps
    install_likec4
    install_mermaid_cli
}

configure_path() {
    local npm_bin
    npm_bin="$(npm prefix -g 2>/dev/null)/bin"
    if [ -d "$npm_bin" ]; then
        echo "$npm_bin" >> "${GITHUB_PATH:-/dev/null}"
        export PATH="$npm_bin:$PATH"
    fi
    local pip_bin="$HOME/.local/bin"
    if [ -d "$pip_bin" ]; then
        echo "$pip_bin" >> "${GITHUB_PATH:-/dev/null}"
        export PATH="$pip_bin:$PATH"
    fi
}
