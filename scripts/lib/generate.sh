#!/usr/bin/env bash
set -euo pipefail

# File generators for LLM Wiki instances.
# Source this file: source "$(dirname "$0")/generate.sh"
# Each function takes a destination directory as the first argument.

generate_agents_md() {
    local dest="$1"
    local submodule="$2"
    # The wiki schema lives at instance/AGENTS.md in the module and is copied
    # verbatim into the instance root as AGENTS.md.
    cp "$submodule/instance/AGENTS.md" "$dest/AGENTS.md"
}

generate_markdownlint() {
    local dest="$1"
    local submodule="$2"
    cp "$submodule/.markdownlint.yaml" "$dest/.markdownlint.yaml"
}

generate_pre_commit() {
    local dest="$1"
    local submodule="$2"
    cp "$submodule/.pre-commit-config.yaml" "$dest/.pre-commit-config.yaml"
}

generate_gitignore() {
    local dest="$1"
    cat > "$dest/.gitignore" <<'EOF'
node_modules/
.obsidian/
EOF
}

generate_gitattributes() {
    local dest="$1"
    # LFS routing for the binary classes a wiki realistically receives.
    # Git keeps every committed byte forever: a 3 MB binary committed 200x is
    # ~600 MB of unremovable history. Deliberately NOT routed: svg, json, csv,
    # ipynb, lock files and all source code — they are text and delta-compress.
    # Extend via the core module (llm-wiki-core), never per-instance:
    # ci-consistency.sh fails on drift.
    cat > "$dest/.gitattributes" <<'EOF'
# Binary files -> git-lfs (see AGENTS.md > Binary Files and Repository Size).
# CI enforces this: .llm-wiki/scripts/check-repo-size.sh fails on any tracked
# binary > 512 KB that is not routed here.

# Images (raster). SVG is text (XML) and stays in git.
*.png   filter=lfs diff=lfs merge=lfs -text
*.jpg   filter=lfs diff=lfs merge=lfs -text
*.jpeg  filter=lfs diff=lfs merge=lfs -text
*.gif   filter=lfs diff=lfs merge=lfs -text
*.webp  filter=lfs diff=lfs merge=lfs -text
*.bmp   filter=lfs diff=lfs merge=lfs -text
*.tif   filter=lfs diff=lfs merge=lfs -text
*.tiff  filter=lfs diff=lfs merge=lfs -text
*.ico   filter=lfs diff=lfs merge=lfs -text
*.avif  filter=lfs diff=lfs merge=lfs -text
*.heic  filter=lfs diff=lfs merge=lfs -text

# Documents (papers, specs, spreadsheets)
*.pdf   filter=lfs diff=lfs merge=lfs -text
*.docx  filter=lfs diff=lfs merge=lfs -text
*.xlsx  filter=lfs diff=lfs merge=lfs -text
*.pptx  filter=lfs diff=lfs merge=lfs -text
*.odt   filter=lfs diff=lfs merge=lfs -text
*.ods   filter=lfs diff=lfs merge=lfs -text
*.odp   filter=lfs diff=lfs merge=lfs -text
*.epub  filter=lfs diff=lfs merge=lfs -text

# Archives
*.zip   filter=lfs diff=lfs merge=lfs -text
*.tar   filter=lfs diff=lfs merge=lfs -text
*.gz    filter=lfs diff=lfs merge=lfs -text
*.tgz   filter=lfs diff=lfs merge=lfs -text
*.bz2   filter=lfs diff=lfs merge=lfs -text
*.xz    filter=lfs diff=lfs merge=lfs -text
*.zst   filter=lfs diff=lfs merge=lfs -text
*.7z    filter=lfs diff=lfs merge=lfs -text
*.rar   filter=lfs diff=lfs merge=lfs -text

# Databases & binary data
*.db        filter=lfs diff=lfs merge=lfs -text
*.sqlite    filter=lfs diff=lfs merge=lfs -text
*.sqlite3   filter=lfs diff=lfs merge=lfs -text
*.db-wal    filter=lfs diff=lfs merge=lfs -text
*.db-shm    filter=lfs diff=lfs merge=lfs -text
*.parquet   filter=lfs diff=lfs merge=lfs -text
*.arrow     filter=lfs diff=lfs merge=lfs -text
*.h5        filter=lfs diff=lfs merge=lfs -text
*.hdf5      filter=lfs diff=lfs merge=lfs -text
*.npy       filter=lfs diff=lfs merge=lfs -text
*.npz       filter=lfs diff=lfs merge=lfs -text
*.pkl       filter=lfs diff=lfs merge=lfs -text

# ML model weights
*.onnx         filter=lfs diff=lfs merge=lfs -text
*.pt           filter=lfs diff=lfs merge=lfs -text
*.pth          filter=lfs diff=lfs merge=lfs -text
*.safetensors  filter=lfs diff=lfs merge=lfs -text
*.gguf         filter=lfs diff=lfs merge=lfs -text
*.tflite       filter=lfs diff=lfs merge=lfs -text
*.pb           filter=lfs diff=lfs merge=lfs -text
*.keras        filter=lfs diff=lfs merge=lfs -text

# Media recordings
*.mp4   filter=lfs diff=lfs merge=lfs -text
*.mov   filter=lfs diff=lfs merge=lfs -text
*.mkv   filter=lfs diff=lfs merge=lfs -text
*.webm  filter=lfs diff=lfs merge=lfs -text
*.mp3   filter=lfs diff=lfs merge=lfs -text
*.wav   filter=lfs diff=lfs merge=lfs -text
*.ogg   filter=lfs diff=lfs merge=lfs -text
*.flac  filter=lfs diff=lfs merge=lfs -text

# Executables, libraries, packages
*.exe       filter=lfs diff=lfs merge=lfs -text
*.dll       filter=lfs diff=lfs merge=lfs -text
*.so        filter=lfs diff=lfs merge=lfs -text
*.dylib     filter=lfs diff=lfs merge=lfs -text
*.a         filter=lfs diff=lfs merge=lfs -text
*.o         filter=lfs diff=lfs merge=lfs -text
*.obj       filter=lfs diff=lfs merge=lfs -text
*.wasm      filter=lfs diff=lfs merge=lfs -text
*.deb       filter=lfs diff=lfs merge=lfs -text
*.rpm       filter=lfs diff=lfs merge=lfs -text
*.AppImage  filter=lfs diff=lfs merge=lfs -text
*.dmg       filter=lfs diff=lfs merge=lfs -text
*.iso       filter=lfs diff=lfs merge=lfs -text

# Fonts
*.ttf   filter=lfs diff=lfs merge=lfs -text
*.otf   filter=lfs diff=lfs merge=lfs -text
*.woff  filter=lfs diff=lfs merge=lfs -text
*.woff2 filter=lfs diff=lfs merge=lfs -text
*.eot   filter=lfs diff=lfs merge=lfs -text

# Profiler & design artifacts (CUDA/Nsight traces, design tools)
*.nsys-rep  filter=lfs diff=lfs merge=lfs -text
*.ncu-rep   filter=lfs diff=lfs merge=lfs -text
*.qdrep     filter=lfs diff=lfs merge=lfs -text
*.qdstrm    filter=lfs diff=lfs merge=lfs -text
*.vsdx      filter=lfs diff=lfs merge=lfs -text
*.psd       filter=lfs diff=lfs merge=lfs -text
*.sketch    filter=lfs diff=lfs merge=lfs -text
EOF
}

generate_remarkrc() {
    local dest="$1"
    cat > "$dest/.remarkrc.mjs" <<'EOF'
import remarkFrontmatter from "remark-frontmatter";
import remarkLintFrontmatterSchema from "remark-lint-frontmatter-schema";

const remarkConfig = {
  plugins: [
    remarkFrontmatter,
    [
      remarkLintFrontmatterSchema,
      {
        schemas: {
          "./.llm-wiki/schemas/wiki-page.schema.yaml": ["./wiki/**/*.md"],
        },
      },
    ],
  ],
};
export default remarkConfig;
EOF
}

generate_package_json() {
    local dest="$1"
    local title="$2"
    cat > "$dest/package.json" <<EOF
{
  "private": true,
  "type": "module",
  "description": "LLM Wiki for ${title} — dev dependencies for frontmatter validation",
  "devDependencies": {
    "remark-cli": "^12.0.0",
    "remark-frontmatter": "^5.0.0",
    "remark-lint-frontmatter-schema": "^3.0.0"
  },
  "scripts": {
    "lint": "markdownlint-cli2 'wiki/**/*.md' index.md log.md",
    "lint:fix": "markdownlint-cli2 --fix 'wiki/**/*.md' index.md log.md",
    "validate": "npx remark wiki/ --frail",
    "health": "python3 .llm-wiki/scripts/wiki-health.py wiki/",
    "check": "npm run lint && npm run validate && npm run health"
  }
}
EOF
}

generate_qmd_yml() {
    local dest="$1"
    local global="$2"
    local entity="$3"
    local concept="$4"
    local guide="$5"
    local reference="$6"
    cat > "$dest/qmd.yml" <<EOF
collections:
  wiki:
    path: ./wiki
    pattern: "**/*.md"

context:
  global: "${global}"
  paths:
    qmd://wiki/entities: "${entity}"
    qmd://wiki/concepts: "${concept}"
    qmd://wiki/guides: "${guide}"
    qmd://wiki/reference: "${reference}"
EOF
}

generate_ci_workflow() {
    local dest="$1"
    local runner="$2"
    local node_version="$3"
    local platform="${4:-github}"

    local wf_dir
    case "$platform" in
        forgejo) wf_dir="$dest/.forgejo/workflows" ;;
        gitea)   wf_dir="$dest/.gitea/workflows" ;;
        *)       wf_dir="$dest/.github/workflows" ;;
    esac
    mkdir -p "$wf_dir"

    # Action URLs differ per platform:
    #   github  -> actions/checkout@v4 (resolves from github.com)
    #   forgejo -> https://code.forgejo.org/actions/checkout@v4
    #   gitea   -> https://gitea.com/actions/checkout@v4
    #
    # setup-node: GitHub runners need actions/setup-node to put npm on PATH.
    # Forgejo/Gitea self-hosted runners have Node pre-installed but the
    # setup-node action fails in their environment, so we skip it there.
    local checkout_action setup_node_block
    case "$platform" in
        forgejo)
            checkout_action="https://code.forgejo.org/actions/checkout@v4"
            setup_node_block=''
            ;;
        gitea)
            checkout_action="https://gitea.com/actions/checkout@v4"
            setup_node_block=''
            ;;
        *)
            checkout_action="actions/checkout@v4"
            setup_node_block="      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: \"${node_version}\""
            ;;
    esac

    cat > "$wf_dir/wiki-ci.yml" <<EOF
name: Wiki CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    name: Lint, Validate, and Consistency
    runs-on: ${runner}
    steps:
      - name: Checkout
        uses: ${checkout_action}
        with:
          submodules: true
${setup_node_block}
      - name: Install python deps (pyyaml)
        run: bash .llm-wiki/scripts/install-python-deps.sh pyyaml

      - name: Install npm dependencies
        run: npm ci 2>/dev/null || npm install

      - name: Consistency check
        run: bash .llm-wiki/scripts/ci-consistency.sh

      - name: Lint pipeline
        run: bash .llm-wiki/scripts/ci-lint.sh

  index:
    name: QMD Index Health
    runs-on: ${runner}
    needs: lint
    steps:
      - name: Checkout
        uses: ${checkout_action}
        with:
          submodules: true
${setup_node_block}
      - name: Install python deps (pyyaml)
        run: bash .llm-wiki/scripts/install-python-deps.sh pyyaml

      - name: Run index pipeline
        run: bash .llm-wiki/scripts/ci-index.sh
EOF
}

generate_index() {
    local dest="$1"
    local title="$2"
    local date="$3"
    cat > "$dest/index.md" <<EOF
# Wiki Index

> Last updated: ${date}

## Entities

Specific technologies and products. Searched by name ("what is X?").

| Page | Summary | Sources | Updated |
|------|---------|---------|---------|

## Concepts

Architectural patterns and design principles. Searched by description ("how does X work?").

| Page | Summary | Sources | Updated |
|------|---------|---------|---------|

## Guides

Step-by-step procedures. Searched by intent ("how to X?").

| Page | Summary | Sources | Updated |
|------|---------|---------|---------|

## Reference

Catalogs, comparisons, and lookup tables. Searched by topic.

| Page | Summary | Sources | Updated |
|------|---------|---------|---------|
EOF
}

generate_log() {
    local dest="$1"
    local title="$2"
    local date="$3"
    cat > "$dest/log.md" <<EOF
# Wiki Log

Chronological append-only activity log for the ${title} LLM Wiki.

## [${date}] create | Initial Wiki Bootstrap

- **Operation**: create
- **Pages affected**: None
- **Summary**: Bootstrapped the LLM Wiki instance using the llm-wiki template submodule. Created wiki.config.yml, directory structure, and initial index.md/log.md.
EOF
}

generate_readme() {
    local dest="$1"
    local name="$2"
    local title="$3"
    local description="$4"
    local url="$5"
    local url_line=""
    if [ -n "$url" ]; then
        url_line="[$title]($url) — "
    fi
    cat > "$dest/README.md" <<EOF
# ${name}

A persistent, compounding knowledge base for the ${url_line}${description}.

This wiki is maintained by LLM agents following the schema defined in \`AGENTS.md\`. It is designed to be browsed in [Obsidian](https://obsidian.md) for graph view and wikilink navigation, and searched with [qmd](https://github.com/tobi/qmd) for hybrid BM25/vector search with LLM re-ranking.

## Structure

\`\`\`text
${name}/
├── .llm-wiki/          # Shared tooling (git submodule)
├── wiki.config.yml     # Project-specific configuration
├── qmd.yml             # QMD search engine config
├── index.md            # Content-oriented catalog of all wiki pages
├── log.md              # Chronological append-only activity log
├── raw/                # Immutable source documents (never modify)
└── wiki/               # Wiki pages organized by entity type
    ├── entities/       # Specific technologies and products
    ├── concepts/       # Architectural patterns and design principles
    ├── guides/         # Step-by-step procedures
    └── reference/      # Catalogs and lookups
\`\`\`

## Setup

\`\`\`bash
# Install global validation tools
npm install -g markdownlint-cli2 @tobilu/qmd
pip install mdlint-obsidian

# Install local remark dependencies
npm ci

# Set up pre-commit hooks
pre-commit install

# Set up qmd search index
bash .llm-wiki/scripts/qmd-setup.sh
\`\`\`

## Validation

\`\`\`bash
# Run all checks
npm run check

# Individual tools
npm run lint          # markdownlint formatting
npm run validate      # frontmatter schema validation
npm run health        # structural wiki health check
\`\`\`

See \`.llm-wiki/instance/AGENTS.md\` for the full schema and \`llm-wiki.md\` for the original pattern document.
EOF
}
