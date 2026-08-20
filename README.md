# llm-wiki-core

A shared tooling module for **LLM Wiki** instances — persistent, compounding
knowledge bases maintained by LLM agents. This repository provides three layers:

1. **Wiki tooling** — schema, lint, CI pipelines, bootstrap, health checks
2. **GitOps controller** — Kubernetes-native RIG generation + LLM agent pipeline
3. **Agent skill** — the `llm-wiki` skill for the pi.dev harness

## Architecture

```text
┌─ Module (this repo) ──────────────────────────────────────────┐
│                                                               │
│  Wiki Tooling          GitOps Controller        Agent Skill    │
│  ─────────────         ─────────────────        ───────────    │
│  instance/AGENTS.md    deploy/chart/            .agents/skills/wiki/SKILL.md │
│  schemas/              deploy/scripts/                         │
│  scripts/              Dockerfile                               │
│  tests/                .github/actions/repo-map/               │
│                                                               │
│  Used by wiki           Used by k8s-config      Used by pi     │
│  instances (submodule)  (Helm chart)            (--skill)      │
└───────────────────────────────────────────────────────────────┘
```text

### Operator pattern separation

- **This module** owns **build logic**: how to generate RIGs, validate diagrams,
  transform inputs into documentation. Ships the Helm chart + scripts + Dockerfile.
- **k8s-config** owns **runtime logic**: which repos map to which wikis
  (WikiMap CR instances), Flux sources, secrets, network policies.

### Runtime: KEDA + Dapr + PVC Cache

The controller runs as a **KEDA ScaledJob** — scale-to-zero when idle, scale
up on cron trigger. Each pod gets:

- **Dapr sidecar** — state store + pub/sub abstraction (Valkey backend).
  The agent uses `localhost:3500` HTTP API; never talks to Valkey directly.
  Enables sub-ms skip checks (`dapr_load`) instead of full clone+emit.
- **PVC cache** (local-path) — bare git clones, Go module cache, npm cache.
  First run clones; subsequent runs `git fetch` (sub-second vs 5-10s clone).
- **CI self-healing loop** — after the agent pushes, monitors CI. If CI fails,
  re-invokes the agent with `ci-consistency.sh` + `ci-lint.sh` to fix and re-push.
- **Event subscriber** (always-on Deployment) — consumes the `wiki.docs.updated`
  pub/sub event published at the end of every successful reconcile and records a
  Kubernetes Event (`reason: DocsSynced`) on the source `WikiMap`, making the
  pipeline observable via `kubectl get events`. First consumer of the event bus.

All four layers are independent Helm chart toggles (`keda.enabled`,
`dapr.enabled`, `cache.enabled`, `subscriber.enabled`) with graceful
degradation when absent.

## Two Documentation Workflows

Every wiki instance supports two workflows:

| Workflow | Diagrams | RIG | LLM command | When to use |
|----------|----------|-----|-------------|-------------|
| **LC4** (Architecture) | LikeC4 → Mermaid | Yes | `arch-sync` | Documenting a project's architecture from code |
| **Generic** | Mermaid only | No | `update` | Documenting concepts, guides, reference from raw sources |

## GitOps RIG Pipeline

The controller runs in Kubernetes and automatically generates documentation:

```text
Project push → Flux sources artifact → CronJob reconciles WikiMap CRs:

  LC4 workflow:                     Generic workflow:
  1. emit-<lang>.sh → rig.json      1. copy source → raw/<project>/
  2. push rig.json to wiki          2. push to wiki
  3. LLM: arch-sync (GLM-5.2)      3. LLM: update (GLM-5.2)
     → model.c4 + Mermaid              → wiki pages + Mermaid
```text

WikiMap CR examples:

```yaml
# LC4 (architecture docs)
apiVersion: llm-wiki.dev/v1alpha1
kind: WikiMap
spec:
  workflow: lc4
  source:
    repo: https://github.com/me/my-service
    language: go
  destination:
    wikiRepo: git@github.com:me/my-wiki.git
    projectDir: raw/arch/my-service

# Generic (general docs)
apiVersion: llm-wiki.dev/v1alpha1
kind: WikiMap
spec:
  workflow: generic
  source:
    repo: https://github.com/me/my-docs
  destination:
    wikiRepo: git@github.com:me/my-wiki.git
    projectDir: raw/my-docs
```text

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
├── deploy/                         # GitOps controller (Helm chart + scripts)
│   ├── chart/                      # The operator Helm chart
│   │   ├── Chart.yaml
│   │   ├── values.yaml
│   │   └── templates/
│   │       ├── crd-wikimap.yaml    # WikiMap CRD (llm-wiki.dev/v1alpha1)
│   │       ├── cronjob.yaml        # Reconciliation CronJob
│   │       ├── role.yaml           # RBAC (read wikimaps + gitrepositories)
│   │       ├── rolebinding.yaml
│   │       ├── serviceaccount.yaml
│   │       └── _helpers.tpl
│   └── scripts/
│       ├── reconcile.sh            # Deterministic: download → emit/copy → push
│       ├── agent-sync.sh           # Interpretive: LLM (GLM-5.2) → docs update
│       └── add-wikimap.sh          # One-command project onboarding
│
├── Dockerfile                      # Controller image (Go + Python3 + Node22 + pi + likec4)
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
git submodule add https://github.com/tibrezus/llm-wiki.git .llm-wiki
# Edit wiki.config.yml, then:
bash .llm-wiki/scripts/bootstrap.sh
```text

### Add a project to the GitOps pipeline

```bash
# In k8s-config, run the add-wikimap helper:
/path/to/llm-wiki/deploy/scripts/add-wikimap.sh my-service \
  https://github.com/me/my-service go --push

# Or for generic documentation:
/path/to/llm-wiki/deploy/scripts/add-wikimap.sh my-docs \
  https://github.com/me/my-docs --workflow generic --push
```text

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
