---
title: LLM Wiki — Shared Tooling Module
---

# AGENTS.md — llm-wiki (Shared Tooling Module)

> **You are in the `tibrezus/llm-wiki-core` module repository — NOT a wiki instance.**
> This repo will never contain `wiki/`, `raw/`, `wiki.config.yml`, `index.md`, or
> `log.md`. Do not look for them and do not follow instance workflows here.

This repository is the **shared tooling module** for the LLM Wiki system. It has
three layers:

1. **Wiki tooling** — schema, lint, CI pipelines, bootstrap, health checks.
   Consumed by wiki instances as a git submodule at `.llm-wiki/`.
2. **RIG generation** — the universal code-graph extractor
   (`.github/actions/repo-map/`), consumed by project CI to publish graph
   packages (the package-registry architecture pipeline).
3. **Agent skill** — `.agents/skills/wiki/SKILL.md` (git submodule of `tibrezus/agents`), synced to `~/.agents/skills/wiki/`.
   Guides the LLM when operating on wiki content.

## Three Documents — Do Not Confuse Them

| File | Role |
|------|------|
| **This file** (`AGENTS.md`) | How to maintain the **module** (scripts, schemas, CI, chart, emitters) |
| `instance/AGENTS.md` | The **wiki schema** — page format, frontmatter, entity types, two documentation workflows. Copied verbatim into each instance's root `AGENTS.md` by `bootstrap.sh`. |
| `.agents/skills/wiki/SKILL.md` | The **agent skill** — commands for the pi.dev harness (`read`, `update`, `create`, `prune`, `list`, `arch-sync`, `consult`). Source of truth: `tibrezus/agents` repo (git submodule at `.agents/`). Synced to `~/.agents/skills/wiki/SKILL.md`. |

## Module ↔ Instance Relationship

Each wiki instance adds this repo as a git submodule at `.llm-wiki/` and runs
`bootstrap.sh`, which produces:

- **Copied** from module (must match submodule exactly): `AGENTS.md`
  (← `instance/AGENTS.md`), `.markdownlint.yaml`, `.pre-commit-config.yaml`.
- **Generated** from `wiki.config.yml`: `.gitignore`, `.remarkrc.mjs`,
  `package.json`, `qmd.yml`, CI workflow (`.github/workflows/`,
  `.forgejo/workflows/`, or `.gitea/workflows/` depending on `ci.platform`).
- **Instance-owned** (never regenerated): `wiki.config.yml`, `wiki/`, `raw/`,
  `index.md`, `log.md`, `README.md`.

The instance CI is **self-contained** — no cross-repo `uses:` references. Each
job inlines checkout + install + script calls. The `ci.platform` field in
`wiki.config.yml` controls the workflow directory and action URL prefix:

| Platform | Directory | Action URLs |
|----------|-----------|-------------|
| `github` | `.github/workflows/` | `actions/checkout@v4` |
| `forgejo` | `.forgejo/workflows/` | `https://code.forgejo.org/actions/checkout@v4` |
| `gitea` | `.gitea/workflows/` | `https://gitea.com/actions/checkout@v4` |

## Module Layout

```text
AGENTS.md                           # THIS FILE
instance/AGENTS.md                  # Wiki schema (copied into instances)
.agents/skills/wiki/SKILL.md         # Agent skill (submodule of tibrezus/agents; synced to ~/.agents/skills/wiki/)
schemas/
  wiki-page.schema.yaml             # Page frontmatter schema
  wiki-config.schema.yaml           # wiki.config.yml schema
  repo-map.schema.yaml              # RIG JSON schema
scripts/                            # Wiki instance tooling
  bootstrap.sh                      # Generate/regenerate from config
  new-wiki.sh                       # One-command instance creation
  ci-lint.sh                        # Lint: markdown + mermaid + likec4 + health
  ci-index.sh                       # QMD index build + verify
  ci-consistency.sh                 # Drift check (stale dirs, generated vs config)
  validate-config.py               # Validate wiki.config.yml
  validate-mermaid.py              # Render-check mermaid blocks (mmdc)
  wiki-health.py                   # Orphans, bidirectional links, type/dir
  arch/
    rig-to-c4.py                 # Deterministic RIG → LikeC4 model generator
    validate-rig.py             # Validate RIG against schema
  lib/
    config.sh                       # read_config(), require_config()
    generate.sh                     # File generators (CI, package.json, etc.)
    install-tools.sh                # Tool installer (likec4, mmdc, etc.)
    puppeteer-config.json           # Headless Chromium config
Dockerfile                          # Controller image (pi + git + go + jq + kubectl) — kept: the
                                    # published image is reused by other platform components
.github/actions/repo-map/           # Universal RIG generator (also usable as GitHub Action)
  action.yml                        # Composite Action dispatch
  emit-rig.sh                       # Shell wrapper
  emit-rig.py                       # Slim entry point: detect → extract → validate → output
  rig/                              # Modular RIG package (Spade-aligned)
    model.py                        # Data types: Component, Runner, TestDefinition, Evidence, ...
    builder.py                      # RIGBuilder: ID assignment, evidence cache, name→ID resolution
    validator.py                    # Generation-time validation (refs/cycles/evidence=ERROR, completeness=WARN)
    extractors/                     # One module per build system
      base.py                       # Extractor ABC: detects() + extract(builder)
      go.py                         # Go: go list -json
      zig.py                        # Zig: build.zig static analysis + native C/CUDA tracing
      cargo.py                      # Rust: Cargo.toml manifest parsing
      npm.py                        # npm/TypeScript: package.json + workspaces
      python.py                     # Python: pyproject.toml + package discovery
      cmake.py                      # CMake: add_executable/add_library + standalone C fallback
      generic.py                    # Fallback: groups source files by language
tests/
  test_wiki_health.py
```

Module self-checks: `npm run check` (lint + test).

## Two Documentation Workflows

| Workflow | Input | Diagrams | CI validates | LLM command |
|----------|-------|----------|-------------|-------------|
| **Generic** | Raw sources (articles, READMEs) | Mermaid only | mermaid render | `wiki update` |
| **LC4** | RIG JSON (from code) | LikeC4 model → Mermaid | likec4 format + mermaid render | `wiki arch-sync` |

Both share the same page format, entity types, naming, and cross-referencing
rules defined in `instance/AGENTS.md`.

## Architecture Pipeline (package registry)

The GitOps controller (WikiMap CRD + CronJob reconcile + Dapr/Valkey + PVC
cache + GLM agent-sync) is **retired** — removed from this module and from
k8s-config. Its job is now owned by project CI:

```text
project CI (reference: rhesadox .forgejo/workflows/arch.yml):
  1. emit-rig (this module's repo-map tools) → rig.db
  2. publish as an immutable Forgejo package (version = commit SHA)
     — exactly two artifacts: rig.db (machine) + Architecture.md (human,
       merged: rendered views + source map + LikeC4 model + CI registry)
  3. wiki stage: package → Architecture.md → project wiki
  4. kb stage:   package → raw/arch/<project>/ (rig.db + derived model.c4) → LLM wiki instance

model.c4 is DERIVED from rig.db wherever needed (rig-to-c4.py) and never
transported. rig.json was removed — the db is the only serialization.
```

The auto-update loop (agent reacting to graph changes and updating wiki prose)
will be reimplemented cleanly later (harmostes). The Dockerfile stays — the
published controller image is reused by platform components (fork-maintenance
conflict-resolver).

## RIG Pipeline (arXiv:2601.10112 / Spade)

The RIG (Repository Intelligence Graph) is the deterministic contract between
a project and the wiki. It is a graph of **evidence-backed** build artifacts:
components are BUILD TARGETS (not source files), evidence proves each node is
defined by the build system, and test definitions link tests to production code.

### Architecture

```text
harmostes (k8s) — the documentation engine
┌───────────────────────────────────────────────────────────────────┐
│ rig-emit plugin (deterministic)                                   │
│  ├─ clone project source repo                                     │
│  ├─ emit-rig.py    → rig.db (SQLite + FTS5)                       │
│  ├─ rig-to-c4.py   → model.c4                                     │
│  └─ likec4 gen mermaid → *.mmd                                    │
│                                                                   │
│ agent (probabilistic — LLM via LiteLLM)                           │
│  ├─ query rig.db (rig tool: overview/component/search)            │
│  ├─ embed *.mmd into wiki pages                                   │
│  ├─ write C4-level prose (context/container/component)            │
│  ├─ offload code-level details to platform wiki (gh/git)          │
│  └─ gate: wiki-lint                                               │
│                                                                   │
│ git-push plugin → push to wiki repo                               │
└───────────────────────────────────────────────────────────────────┘

Wiki Instance (CI = lint only)
┌───────────────────────────────────────────────────────────────────┐
│ ci-lint.sh   → markdownlint + remark + mermaid + likec4 + health   │
│ ci-index.sh  → QMD index build + search test                      │
│ NO arch job, NO RIG fetching, NO generation logic                 │
└───────────────────────────────────────────────────────────────────┘
```

### Core layers

| Layer | File | Responsibility |
|-------|------|---------------|
| **Model** | `rig/model.py` | Spade data types (dataclasses): `Component`, `Aggregator`, `Runner`, `TestDefinition`, `Evidence`, `ExternalPackage`, `Artifact` |
| **Builder** | `rig/builder.py` | `RIGBuilder`: ID assignment, evidence cache (dedup), name→ID resolution, auto-evidence, JSON assembly |
| **Validator** | `rig/validator.py` | Generation-time checks: dangling refs, cycles, duplicate IDs, evidence coverage (all ERROR), completeness (WARN) |
| **Extractors** | `rig/extractors/*.py` | One class per build system: `detects()` + `extract(builder)`. Express deps as names; builder resolves to IDs |

### Extractor contract

Each extractor:

1. `detects()` — checks if its build system is present (e.g., `go.mod` exists)
2. `extract(builder)` — parses the build file, registers `Component`s,
   `TestDefinition`s, `Runner`s, `Aggregator`s, `Evidence`, and
   `ExternalPackage`s with the builder

Dependencies are expressed as **names** during extraction. The builder
resolves names → IDs in `build()`, so extractors never track ID maps.

### Spade alignment (paper compliance)

The implementation follows the RIG standard (arXiv:2601.10112,
github.com/Greenfuze/spade):

| Paper requirement | Implementation |
|-------------------|---------------|
| Components are build targets | Each extractor discovers executables/libraries from the build system |
| Every node has evidence | Builder auto-generates evidence (build-file ref + source-file ref) |
| Evidence = file:line refs | `Evidence.line` (flat refs) + `Evidence.call_stack` (ordered chain) |
| No dangling references | Validator: ERROR |
| No circular dependencies | Validator: ERROR (DFS cycle detection) |
| No duplicate IDs | Validator: ERROR |
| Test definitions link to components | `test_framework`, `components_being_tested_ids`, `test_executable_component_id` |
| Runners execute commands | Emitted per language (`go test`, `zig build test`, `cargo test`, `pytest`, `ctest`) with `arguments` |
| Aggregators are meta-targets | Emitted per language (`go-build-all`, `zig-build`, `go-test-all`) |
| External packages have manager metadata | Every package: `package_manager.name` + `package_manager.package_name` |
| Every source file in a component | Completeness check (WARN — repos with mixed languages may have files outside build targets) |

### Schema (`schemas/repo-map.schema.yaml`)

The schema enforces `additionalProperties: false` on every node type. Fields:

- **components**: `id`, `name`, `type` (executable/shared_library/static_library/package_library/vm/interpreted/unknown), `programming_language`, `source_files`, `depends_on_ids`, `external_packages_ids`, `evidence_ids`, `artifacts` (name + relative_path)
- **aggregators**: `id`, `name`, `depends_on_ids`, `evidence_ids`
- **runners**: `id`, `name`, `arguments`, `depends_on_ids`, `evidence_ids`
- **test_definitions**: `id`, `name`, `covers_ids`, `depends_on_ids`, `components_being_tested_ids`, `test_framework`, `test_executable_component_id`, `source_files`, `evidence_ids`
- **evidence**: `id`, `line` (file:line refs), `call_stack` (ordered chain, leaf first)
- **external_packages**: `id`, `name`, `package_manager` (name + package_name)
- **entrypoints**: component IDs (executables)

### Vendoring

The same `emit-rig.py` + `rig/` package is used in two places:

1. **GitHub Action** (`.github/actions/repo-map/`) — project CI publishes RIG
   as a package (the rhesadox `arch.yml` pattern: rig.db in the package
   registry, wiki/kb stages render from the package)
2. **harmostes** (`plugins/rig-emit/`) — in-cluster plugin generates RIG
   deterministically

(The legacy GitOps controller — `deploy/` — was the third consumer; it has
been removed. The auto-update loop it provided will be reimplemented
 cleanly later.)

Changes to the module must be synced to the harmostes vendor copy:
`cp -r .github/actions/repo-map/{emit-rig.py,emit-rig.sh,rig} <harmostes>/plugins/rig-emit/`

## Working in This Module

### Self-checks (run before pushing)

```bash
npm run check    # markdownlint + remark + pytest
```

### Principles

- **`instance/AGENTS.md` is the single source of truth for the wiki schema.**
  Editing it changes every instance on next bootstrap.
- **`scripts/lib/generate.sh` is the single source of truth for generated files.**
  Never hand-edit generated file contents.
- **`ci-consistency.sh` must know about every copied/generated file.** If you
  add a new artifact, update both `generate.sh` and `ci-consistency.sh`.
- **The skill source of truth is `tibrezus/agents`** (git submodule at `.agents/`). Always sync: `cp .agents/skills/wiki/SKILL.md ~/.agents/skills/wiki/SKILL.md`.
- **Backwards compatibility**: a change that breaks existing configs or pages
  will break every instance's CI simultaneously. Coordinate.

### Evolving the schema (`instance/AGENTS.md`)

1. Edit `instance/AGENTS.md`.
2. `npm run lint`.
3. If frontmatter/structure changed, update `schemas/wiki-page.schema.yaml`
   and `tests/test_wiki_health.py`.
4. Commit and push on `main`.

### Evolving the generators (`scripts/lib/generate.sh`)

1. Edit the relevant `generate_*` function.
2. Update `ci-consistency.sh` if new drift checks apply.
3. Smoke-test: `bash scripts/new-wiki.sh /tmp/wiki-smoke`.
4. `npm run check`; push on `main`.

### The retired GitOps controller

The in-cluster operator (`deploy/`: WikiMap CRD, CronJob reconcile loop,
Dapr state/pubsub, Valkey, PVC cache, GLM agent-sync) was **removed** — its
k8s-config deployment was retired and the architecture pipeline moved to the
**package-registry pattern** (project CI publishes rig.db as an immutable
package; wiki stages render from it — see the rhesadox `arch.yml`). The
auto-update loop will be reimplemented cleanly later. The `Dockerfile` stays:
the published controller image is reused by other platform components (e.g.
the fork-maintenance conflict-resolver).

## Propagating a Module Change to Existing Instances

```bash
cd <instance-root>
git -C .llm-wiki fetch origin && git -C .llm-wiki checkout main && git -C .llm-wiki pull
bash .llm-wiki/scripts/bootstrap.sh   # regenerates/copies from config
git add -A
git commit -m "chore: update llm-wiki submodule + regenerate"
git push
# Watch CI: gh run watch (GitHub) / fj actions tasks (Forgejo/Codeberg)
```

A propagated change is not complete until CI is green on every affected instance.
