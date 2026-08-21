# llm-wiki-core

A shared tooling module for **LLM Wiki** instances — persistent, compounding
knowledge bases maintained by LLM agents. This repository provides three layers:

1. **Wiki tooling** — schema, lint, CI pipelines, bootstrap, health checks
2. **RIG generation** — the universal code-graph extractor, consumed by
   project CI (package-registry architecture pipeline)
3. **Agent skill** — the `llm-wiki` skill for the pi.dev harness

## Architecture

```text
┌─ Module (this repo) ──────────────────────────────────────────┐
│                                                               │
│  Wiki Tooling          RIG Generation            Agent Skill    │
│  ─────────────         ────────────              ───────────    │
│  instance/AGENTS.md    .github/actions/repo-map/  .agents/skills/wiki/SKILL.md │
│  schemas/              (used by project CI:       Dockerfile    │
│  scripts/               rig.db package pipeline)                │
│  tests/                                                       │
│                                                               │
│  Used by wiki           Used by project CI       Used by pi     │
│  instances (submodule)  (workflows)              (--skill)      │
└───────────────────────────────────────────────────────────────┘
```

> **The GitOps controller is retired.** The in-cluster operator (WikiMap
> CRD, CronJob reconcile loop, Dapr, Valkey, PVC cache, GLM agent-sync) was
> removed from this module and from k8s-config — superseded by the
> package-registry pipeline below. The auto-update loop it provided will be
> reimplemented cleanly later. The `Dockerfile` stays: the published image is
> reused by platform components (e.g. the fork-maintenance conflict-resolver).

## Package-Registry Architecture Pipeline

Project CI owns its graph end-to-end (reference implementation: rhesadox's
`.forgejo/workflows/arch.yml`):

```text
project CI:
  1. emit-rig (this module's repo-map action) → rig.db
  2. publish as an immutable Forgejo package (version = commit SHA)
     — exactly two artifacts: rig.db (machine) + Architecture.md (human)
  3. wiki stage: package → Architecture.md → project wiki
  4. kb stage:   package → raw/arch/<project>/ (rig.db + derived model.c4) → LLM wiki instance

rig.db is the machine interface — query it (rig-query.py / the pi `rig`
tool), never load it into context. Architecture.md is the single human-facing
page: rendered C4 views, source map, LikeC4 model, CI registry — all merged.

Any consumer can fetch the exact graph for a SHA; the wiki never touches the
source tree.
```

## Two Documentation Workflows

Every wiki instance supports two workflows:

| Workflow | Diagrams | RIG | LLM command | When to use |
|----------|----------|-----|-------------|-------------|
| **LC4** (Architecture) | LikeC4 → Mermaid | Yes | `arch-sync` | Documenting a project's architecture from code |
| **Generic** | Mermaid only | No | `update` | Documenting concepts, guides, reference from raw sources |

## File Layout

```text
├── AGENTS.md                       # Module maintenance guide (this context)
├── README.md                       # This file
├── instance/AGENTS.md              # Wiki schema (copied into instances)
├── skill/SKILL.md                  # Agent skill (synced to ~/.agents/skills/wiki/)
├── llm-wiki.md                     # Founding pattern document
│
├── schemas/
│   ├── wiki-page.schema.yaml       # Frontmatter JSON Schema
│   ├── wiki-config.schema.yaml     # wiki.config.yml JSON Schema
│   └── repo-map.schema.yaml        # RIG JSON Schema
│
├── scripts/                        # Wiki instance tooling
│   ├── bootstrap.sh                # Generate/regenerate an instance from config
│   ├── new-wiki.sh                 # One-command instance creation
│   ├── ci-lint.sh                  # Lint pipeline (markdown + mermaid + likec4)
│   ├── ci-index.sh                 # QMD index build + verify
│   ├── ci-consistency.sh           # Drift check (generated vs config)
│   ├── validate-config.py          # Validate wiki.config.yml
│   ├── validate-mermaid.py         # Render-check mermaid blocks with mmdc
│   ├── wiki-health.py              # Orphans, bidirectional links, type/dir
│   ├── arch/
│   │   ├── rig-to-c4.py             # Deterministic RIG → LikeC4 model generator
│   │   └── validate-rig.py         # Validate RIG against schema
│   └── lib/
│       ├── config.sh               # read_config(), require_config()
│       ├── generate.sh             # File generators (CI, package.json, etc.)
│       ├── install-tools.sh        # Tool installer (likec4, mmdc, etc.)
│       └── puppeteer-config.json   # Headless Chromium config for mmdc
│
├── Dockerfile                      # Controller image (pi + git + go + jq + kubectl) — the published
│                                   # image is reused by platform components (conflict-resolver)
│
├── .github/actions/repo-map/       # Universal RIG generator (also used as standalone GitHub Action)
│   ├── action.yml                  # Composite Action dispatch
│   ├── emit-rig.sh                 # Shell wrapper
│   ├── emit-rig.py                 # Slim entry point: detect → extract → validate → output
│   └── rig/                        # Modular RIG package (Spade-aligned)
│       ├── model.py                # Data types: Component, Runner, TestDefinition, Evidence
│       ├── builder.py              # RIGBuilder: IDs, evidence cache, name→ID resolution
│       ├── validator.py            # Generation-time validation
│       └── extractors/             # One module per build system
│           ├── go.py               # Go (go list -json)
│           ├── zig.py              # Zig (build.zig + native C/CUDA)
│           ├── cargo.py            # Rust (Cargo.toml)
│           ├── npm.py              # npm/TypeScript (package.json)
│           ├── python.py           # Python (pyproject.toml)
│           ├── cmake.py            # CMake + standalone C/C++/CUDA
│           └── generic.py          # Fallback (language-grouped scan)
│
├── tests/
│   └── test_wiki_health.py         # Unit tests for wiki-health.py
│
├── .markdownlint.yaml              # Shared markdown rules
├── .pre-commit-config.yaml         # Pre-commit hooks
├── .remarkrc.mjs                   # remark config (module self-lint)
└── package.json                    # npm: lint, test, check
```text

## Quick Start

### Create a new wiki instance

```bash
bash /path/to/llm-wiki/scripts/new-wiki.sh my-wiki
```text

Or manually:

```bash
mkdir my-wiki && cd my-wiki
git init && git switch -c main
git submodule add https://github.com/tibrezus/llm-wiki-core.git .llm-wiki
# Edit wiki.config.yml, then:
bash .llm-wiki/scripts/bootstrap.sh
```text

### Add a project to the architecture pipeline

The GitOps operator (add-wikimap.sh / WikiMap CRs) was retired. The current
pattern is per-project CI publishing the graph as a package — see rhesadox's
`.forgejo/workflows/arch.yml` (publish rig.db → package registry; wiki/kb
stages render from the package).text

### Develop the module

```bash
npm run check    # lint + test
npm run lint     # markdownlint only
npm run test     # pytest only
```text

## CI Validation (Wiki Instances)

The wiki CI validates every push:

1. **Consistency** — generated files match config
2. **Config** — `wiki.config.yml` valid against schema
3. **markdownlint** — markdown formatting
4. **mdlint-obsidian** — wikilinks, frontmatter, embeds
5. **remark** — frontmatter schema validation
6. **Mermaid** — every `mermaid` block render-checked with mmdc
7. **LikeC4** — every `.c4` model validated with `likec4 format --check`
8. **Unique filenames** — no duplicates across `wiki/`
9. **Raw/ immutability** — `raw/` not modified in PRs
10. **Wiki health** — orphans, bidirectional links, type/dir match

## Propagation

When the module changes, propagate to all instances:

```bash
cd <instance>
git -C .llm-wiki pull origin main
bash .llm-wiki/scripts/bootstrap.sh
git add -A && git commit -m "chore: bump submodule" && git push
# Watch CI: gh run watch (GitHub) or fj actions tasks (Forgejo/Codeberg)
```text

For the controller image: rebuild and push:

```bash
docker build -t ghcr.io/tibrezus/llm-wiki-controller:0.1.0 .
docker push ghcr.io/tibrezus/llm-wiki-controller:0.1.0
```text

## License

Open source — see repository for details.
