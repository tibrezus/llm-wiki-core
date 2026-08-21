---
title: LLM Wiki Schema
---

# AGENTS.md — LLM Wiki Schema

This document is the authoritative schema for any LLM Wiki instance. Any LLM
agent working in a wiki repository must follow these conventions exactly.

The wiki is a **persistent, compounding artifact** — not a RAG index. Knowledge
is compiled once and kept current, not re-derived on every query. The human
curates sources and asks questions; you do all the writing, cross-referencing,
filing, and bookkeeping. This principle comes from `llm-wiki.md` (read it for
the full founding idea).

## Project Context

Each wiki instance defines its project-specific context in `wiki.config.yml` at
the repository root. **Read it at the start of every session** to understand the
domain (project name, description, URL), search-embedding contexts (QMD), CI
configuration, and which architecture projects are declared (if any).

## Repository Structure

```text
<instance-root>/
├── .llm-wiki/                    # Git submodule (shared tooling + schema)
│   ├── instance/AGENTS.md        # Source of THIS file (copied to instance root)
│   ├── llm-wiki.md               # Founding pattern document
│   ├── schemas/                  # JSON Schema for frontmatter + config
│   ├── scripts/                  # CI pipelines, health checks, arch tooling
│   └── .markdownlint.yaml        # Shared markdown rules
├── wiki.config.yml               # Project-specific configuration
├── AGENTS.md                     # Copied from .llm-wiki/instance/AGENTS.md
├── qmd.yml / package.json        # Generated from wiki.config.yml
├── index.md                      # Content-oriented catalog of all wiki pages
├── log.md                        # Chronological append-only activity log
├── raw/                          # Raw source documents (IMMUTABLE — never modify)
│   └── arch/                     # Harmostes-generated RIG + C4 model + Mermaid
└── wiki/                         # All wiki pages organized by entity type
    ├── entities/                 # Specific technologies and products
    ├── concepts/                 # Patterns and design principles
    ├── guides/                   # Step-by-step procedures
    └── reference/                # Catalogs, comparisons, lookup tables
```

## Three Layers

1. **Raw sources** (`raw/`) — Immutable. You read from them but NEVER modify,
   move, or delete. This is the source of truth, including CI-generated code
   RIG JSONs in `raw/arch/`.
2. **The wiki** (`wiki/`) — LLM-generated markdown pages. You own this layer
   entirely. You create pages, update them, maintain cross-references, and keep
   everything consistent.
3. **The schema** (`AGENTS.md` + `wiki.config.yml`) — Tells you how the wiki is
   structured and what workflows to follow.

### How to Understand a Project

When you need to grasp a project — whether for a feature, fix, or review —
read in this order:

1. **Structure first (if available)** — Query `raw/arch/<project>/rig.db`
   exists. If yes, read it. This deterministic code graph shows components,
   their types, dependencies, and entrypoints. It is the most efficient way to
   understand *what* exists and *how* it connects (1–15K tokens).

2. **Reasoning second** — Read relevant `wiki/` pages to understand *why*
   decisions were made, trade-offs, and operational context. The wiki does not
   duplicate structure; it captures intent.

If no RIG exists, use the wiki directly and route to the minimal source via
qmd search. The "least-context routing" table in the llm-wiki skill shows
how to choose the right pages.

## Entity Types

Pages are organized by **what kind of knowledge** they represent:

| Directory | Type | Search Intent | Classification Rule |
|-----------|------|--------------|-------------------|
| `entities/` | `entity` | "What is X?" — searched by name | Specific technology, product, or system |
| `concepts/` | `concept` | "How does X work?" — searched by description | Cross-cutting idea, pattern, or principle |
| `guides/` | `guide` | "How to X?" — searched by intent | Step-by-step procedure the reader follows |
| `reference/` | `reference` | "Compare/Lookup X" — searched by topic | Catalog, comparison, or lookup table |

## Page Format

Every wiki page must follow this exact structure:

```markdown
---
title: Descriptive Specific Title
type: entity | concept | guide | reference
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: []
tags: [type-tag, tag2, tag3]
---

# Descriptive Specific Title

Dense keyword-rich summary paragraph (2-3 sentences). Include primary search
terms and synonyms. This becomes the first and most important qmd chunk.

## Section Title

Body content with [Markdown links](../type/page-name.md) to other wiki pages.

## See Also

- [related-page-1](../type/related-page-1.md) — Brief description
- [related-page-2](../type/related-page-2.md) — Brief description
```

### Frontmatter Rules

- `title` — Specific and descriptive. Embedded with every qmd chunk. Required.
- `type` — One of `entity`, `concept`, `guide`, `reference`. Must match the
  directory. Required.

- `created` — Date first created (YYYY-MM-DD). Never change after creation. Required.
- `updated` — Date of last meaningful content update. Update on every modification. Required.
- `sources` — Array of filenames from `raw/` that contributed. Empty array if none. Required.
- `tags` — 2-7 lowercase tags (pattern `^[a-z0-9][a-z0-9-]*$`). First tag must match the type. Required.

### Body Rules

- **Title rule**: `# Title` must be specific and descriptive — it becomes the
  embedding prefix for every qmd chunk.

- **Summary rule**: First paragraph must be a dense 2-3 sentence summary with
  primary keywords.

- **Section rule**: Each `## Section` should be 200-900 tokens. `##` headings are
  qmd chunk boundaries.

- **Cross-reference rule**: Include context with links — "See
  [cilium](../entities/cilium.md) for Cilium CNI configuration" not just
  "See [cilium](../entities/cilium.md)".

- **See Also rule**: Every page ends with `## See Also` linking to at least 2
  related pages.

- **Never use `#` headings** in body (reserved for title).
- **Use Markdown links** for internal references: `[page-name](../type/page-name.md)`.
  These render as clickable links on Codeberg, GitHub, and Forgejo. Do NOT use
  `[[wikilinks]]` — they only work in Obsidian, not on web platforms.

## Naming Conventions

- File names: lowercase, hyphen-separated, `.md` extension.
- **Unique filenames** — no two files in `wiki/` may share a name, regardless of
  directory.

- Never use spaces, uppercase, or special characters.

## Cross-Referencing Rules

1. **Use Markdown links**: `[page-name](../type/page-name.md)` — relative path
   from the current file. These render on Codeberg/GitHub/Forgejo.
2. **When creating a page**, scan all existing pages and add Markdown links where relevant.
3. **When updating a page**, check if new content mentions concepts with pages and
   add Markdown links.
4. **Every page must have `## See Also`** with at least 2 related pages.
5. **Bidirectional linking**: if A links to B, B should link back to A.
6. **Pipe wikilinks in tables**: avoid `[[page|display]]` inside markdown tables —
   the `|` conflicts with column delimiters.

---

## Documentation Workflows

The wiki supports distinct **documentation workflows**. Each workflow defines
its own inputs, diagram tool, and CI validation. A project can use one or both.
Additional workflows can be added following the same pattern (inputs → diagram
tool → CI validation → page conventions).

All workflows share the same **page format**, **entity types**, **naming**,
**cross-referencing rules**, and **shared operations** (Ingest, Query, Lint)
described above. What differs is the source of knowledge and how diagrams are
produced.

### Shared Operations

These operations apply regardless of which workflow you are in.

**Ingest** — When a new source arrives (any type):

1. Save the source to `raw/` with a descriptive filename. NEVER modify `raw/`.
2. Read the source thoroughly.
3. Update existing pages that should reflect the new information.
4. Create new pages for topics not yet covered.
5. Update `index.md` and append to `log.md`.

**Query** — When the human asks a question:

1. Use qmd to search: `qmd query "question" --json -n 10`.
2. Read relevant pages in full.
3. Synthesize an answer with citations.
4. If the answer is substantial, offer to file it as a new page.

**Lint** — Periodically health-check:

1. Run native linters: `markdownlint-cli2`, `mdlint --vault wiki/`, `npx remark
   wiki/ --frail`.
2. Run wiki health: `python3 .llm-wiki/scripts/wiki-health.py wiki/`.
3. Check for contradictions, orphan pages, missing cross-references.
4. Append a summary to `log.md`.

---

### Workflow 1: Generic Documentation

**For documenting anything that is not driven by a code graph.** This is the
default workflow. It covers entities (technologies, products), concepts
(patterns, principles), guides (procedures), and reference material (catalogs,
comparisons) — written from raw sources like articles, READMEs, conversations,
design docs, and observations.

- **Inputs**: raw sources in `raw/` (markdown articles, text files, images,
  design docs, etc.). Generic — anything the human curates.

- **Diagram tool**: **Mermaid only**. Mermaid renders natively on GitHub and in
  Obsidian (the primary surfaces for these wikis) and offers purpose-built
  diagram types. No LikeC4 models in this workflow.

- **CI validation**: the wiki CI validates that every page's markdown is
  well-formed and every Mermaid block is syntactically valid. This is the
  source of determinism for this workflow — the LLM writes freely, CI catches
  broken markdown/diagrams.

#### Mermaid diagrams (Generic Workflow)

Embed diagrams as fenced ` ```mermaid ` blocks inline in the page, next to the
prose they illustrate — like figures in a textbook, not a separate section.

Choose the Mermaid type that matches what the diagram *is*:

| Content | Mermaid type | Examples |
|---------|-------------|----------|
| Time-ordered triggers (A causes B causes C) | `sequenceDiagram` | request flows, session flows, release pipelines |
| Nested topology / containment | `flowchart TD` + `subgraph` | service trees, deployment topology |
| Linear pipeline / fan-out | `flowchart LR` | data pipelines, build chains |
| Dependency chain (layers) | `flowchart TD` | kustomization chains, tier dependencies |
| Decision branches (yes/no) | `flowchart TD` with `{rhombus}` | verification logic, gating |
| State transitions | `stateDiagram-v2` | lifecycle, pod states |
| Schema / relationships | `erDiagram`, `classDiagram` | data models, type hierarchies |
| Timeline / phases | `gantt`, `journey` | rollout plans, user flows |

Use ` ```text ` (not a diagram block) for **file trees, numbered procedures,
pseudo-code, command output, and templates** — those are not graphs.

---

### Workflow 2: Architecture Documentation (LC4)

> **⚠ CRITICAL — READ THIS BEFORE DOING ANYTHING IN THIS WORKFLOW ⚠**
>
> The deterministic **rig.db** in `raw/arch/<project>/rig.db` is the
> **ONLY source of truth** for architecture diagrams. Every component, every
> dependency, every boundary you model in a C4 diagram **MUST be traceable
> to a specific node in the RIG**.
>
> **NEVER write architecture diagrams from your training data, from memory,
> or from what you "know" the project looks like.** Your knowledge of the
> project is irrelevant — the RIG is the source of truth. If the RIG says
> something different from what you remember, the RIG is right.
>
> **No graph = no architecture workflow.** If `raw/arch/<project>/rig.db` does
> not exist for the project you are documenting, you **cannot** use this
> workflow. Use Workflow 1 (Generic Documentation) instead. Do not invent
> architecture diagrams.

**For documenting a project's architecture from its code, driven by a
deterministic code graph (RIG).** This workflow applies only to projects
declared in the `arch:` block of `wiki.config.yml` for which a RIG JSON exists
in `raw/arch/`.

#### Prerequisite gate (do this first, every time)

Before writing or updating any architecture diagram:

1. **Verify the graph exists**: `ls raw/arch/<project>/rig.db`. If missing →
   **STOP**. You cannot use this workflow. Tell the human the RIG is missing
   and must be generated by CI first.
2. **Query the graph**: `rig overview` / `rig component <name>` / `rig search '<term>'`
   (pi `rig` tool; else `python3 .llm-wiki/.github/actions/repo-map/rig-query.py
   raw/arch/<project>/rig.db overview`). This is your input —
   a deterministic, evidence-backed architectural map of the project's build
   structure (components, dependencies, external packages, entrypoints).
3. **Every diagram you produce must be derived from what you read in the RIG.**
   Components, dependencies, external packages — all come from the RIG nodes.
   You assign C4 levels to RIG entities; you do not invent entities.

- **Inputs**: a **rig.db** (`raw/arch/<project>/rig.db`) — a queryable
  [RIG](https://arxiv.org/abs/2601.10112) (Repository Intelligence Graph)
  produced deterministically by the project's CI and published as an artifact.
  It is small enough to read whole (typically 1–15K tokens). No rollup, no
  budgeting, no intermediate processing — you read it directly.

- **Model tool**: **LikeC4 DSL** exclusively. You write a `.c4` model file
  (`raw/arch/<project>/model.c4`) derived from the RIG. LikeC4 enforces C4 structure
  by construction — `softwareSystem`, `container`, `component` are typed
  elements with strict nesting rules. The model is the single source of truth
  for all architecture diagrams.

- **Diagram output**: **Mermaid** (generated from the LikeC4 model via
  `likec4 gen mermaid`). Mermaid renders natively on GitHub, Forgejo, and
  Obsidian. Each LikeC4 view becomes one Mermaid diagram embedded in a wiki
  page.

- **CI validation**: `likec4 format --check` validates the C4 model
  (structure, types, references). This is deterministic — the DSL parser
  enforces C4 rules that free-text diagrams cannot guarantee.

#### The C4 model in LikeC4

C4 defines four zoom levels of architecture. In LikeC4, each level is a
**view** of the same underlying model — not a separate diagram. The RIG's node
types map to C4 element kinds:

| C4 Level | Scope | RIG node types | LikeC4 element/view |
|----------|-------|---------------|---------------------|
| **Context** | the whole system + external actors | `entrypoints` + `external_packages` | `system` elements; `view` with `include *` |
| **Container** | one project / deployable system | `components` of type `executable` / `shared_library` | `container` nested in `system`; `view of <system>` |
| **Component** | modules within a container | `components` of type `package_library` + `depends_on_ids` | `component` nested in `container`; `view of <container>` |
| **Code** | a few source files | `source_files` within a component | individual `component` details; `view of <component>` |

The model is defined once; views are **projections** that show different
levels of detail. This is the key advantage over hand-drawn diagrams: the
model enforces consistency across all views automatically.

#### How C4 levels are assigned (from the RIG, not from memory)

**This is your job as the LLM** — the core value-add. But the value you add is
**interpreting the RIG**, not replacing it. The RIG gives you components,
their dependencies, and their types. You read it, translate it into a LikeC4
model, and define views at each C4 level.

What you are doing: taking deterministic RIG data and building a typed C4
model from it (mapping RIG components to LikeC4 elements, defining which are
systems/containers/components).

What you are **NOT** doing: describing the architecture from your training
data, guessing what modules exist, or drawing what you think the project looks
like. If a component or dependency is not in the RIG, it does not go in the
model. If the RIG shows a structure you don't expect, you model what the RIG
shows.

#### RIG → C4 mapping rules

Follow these rules to produce architecturally rich, not just structurally
accurate, C4 models:

**Context view (Level 1):**

- Create one `softwareSystem` for the project.
- Model significant `external_packages` as `externalSystem` nodes. Group
  related packages (e.g., all `docker/*` → "Docker Engine", all `openai/*`
  → "OpenAI API"). Skip trivial packages (logging, testing utilities).

- Connect the system to external systems using the `external_packages_ids`
  from `entrypoint` components.

- Mention `entrypoints` in the system description.

**Container view (Level 2):**

- Map each `executable` component → one `container`.
- Group `package_library` / `static_library` / `shared_library` components
  into functional containers based on source paths and naming conventions:
  - Components under `api/` or `handler/` → "API Layer" container
  - Components under `state/` or `store/` → "State Management" container
  - Components under `tf/` or `terraform/` → "Infrastructure Adapter"
  - CUDA/`.cu` sources → "GPU Backend" container
  - C/`.c` sources → "C Interop" container
- Draw build-level dependency edges (`depends_on_ids`) between containers.

**Component view (Level 3, one per container):**

- Each RIG component within the container → a `component` node.
- Write SYNTHESIZED descriptions (not verbatim RIG quotes). Use the component
  name, type, source file paths, and dependency pattern to describe its
  architectural role in 1-2 sentences. Example:
  - Instead of: `comp-6 machine — internal/api/machine/handlers.go`
  - Write: `machine — REST API handlers for machine lifecycle CRUD; depends
    on state store and patch resolver for declarative updates`

- List source files compactly in the description.
- Include the RIG component ID as a comment for traceability: `// RIG comp-N`.
- Model `external_packages_ids` as relationships to the external systems
  defined in the Context view.

**Views to generate:**

1. Context view (system + external systems)
2. Container view (all containers + inter-container edges)
3. One component view per major container
4. If the project has multiple languages (e.g., Zig + CUDA), a per-language
   backend view

#### Architecture-Sync workflow

Diagrams are **fully deterministic** — generated by harmostes, not the LLM.
The RIG, model.c4, and *.mmd files in `raw/arch/<project>/` are produced by
the harmostes rig-emit plugin and never hand-written.

When the RIG changes:

1. **Query the graph** — `rig overview` (+ `component`/`search` drill-downs).
2. **Diagrams are already generated** — model.c4 + *.mmd are deterministic.
3. **Update wiki pages** — embed the Mermaid blocks from `raw/arch/<project>/*.mmd`, write a short summary of what changed.
4. **C4 boundary** — llm-wiki carries context/container/component level only. Code-level details go to the platform wiki via `gh`/`git`.
5. **Update `index.md`** and **append to `log.md`**.

#### Graph pipeline (harmostes-managed)

A project enters this workflow via a **harmostes LC4 Workflow**. Harmostes is
the documentation engine — it clones the project source, generates the RIG
and C4 artifacts, and pushes them to the wiki:

- **RIG** — generated by `emit-rig.py` (deterministic, from the code graph)
- **model.c4** — generated by `rig-to-c4.py` (deterministic, from RIG + code comments)
- **Mermaid** — generated by `likec4 gen mermaid` (deterministic, from model.c4)
- **Wiki prose** — written by the LLM agent (summarizes changes, embeds diagrams)

The wiki CI does **lint only** — no RIG fetching, no generation.

#### Multi-project

A wiki can document several projects. Each has its own RIG. Context-level
figures routinely span projects (project A calls project B); resolve
cross-project dependencies through the RIG's `external_packages` and
component names, never by ambiguous local names from memory.

---

### Adding new workflows

Additional documentation workflows can follow the same pattern: define the
**inputs** (what feeds the LLM), the **diagram tool** (if any), and the **CI
validation** (what the pipeline checks). Keep shared operations, page format,
and cross-referencing rules universal.

---

## Tooling Reference

### Validation Tools

| Tool | Purpose |
|------|---------|
| markdownlint-cli2 | Markdown formatting rules |
| mdlint-obsidian | Obsidian wikilinks, frontmatter, embeds |
| remark-lint-frontmatter-schema | Frontmatter validation against JSON Schema |
| qmd | Local search engine (BM25 + vector + reranking) |
| likec4 CLI | C4 model validation (Architecture workflow) |
| mmdc (mermaid-cli) | Mermaid diagram render validation |
| RIG JSON | Repository Intelligence Graph — the architecture artifact (see *Graph Contract*) |

### CI Pipeline

The instance CI (`.github/workflows/wiki-ci.yml`) calls the module's reusable
workflows from `@main`:

1. **lint** — consistency → config validation → markdownlint → mdlint-obsidian →
   remark → unique filenames → raw/ immutability → wiki-health.
2. **index** — qmd setup → update → embed → status → search test.
3. **arch** (only when `arch:` is configured) — clones/fetches each project →
   rig.db → validates → commits `raw/arch/<project>/rig.db`

The reusable workflows live in the module repo; updating them there updates all
instances. The consistency check (`ci-consistency.sh`) detects drift.

## File: index.md

Content-oriented catalog organized by entity type. Every wiki page must be
listed. Update on every ingest or page creation.

## File: log.md

Chronological append-only log:

```markdown
## [YYYY-MM-DD] operation | Short Title

- **Operation**: ingest | query | lint | create | update | arch-sync
- **Pages affected**: list of wiki pages
- **Summary**: what happened and why
```

## What NOT to Do

- **Never modify files in `raw/`** after placement
- **Never delete wiki pages** without explicit instruction
- **Never use inline HTML** in wiki pages
- **Never use `#` headings** in body (reserved for title)
- **Use Markdown links** for internal references: `[name](../type/name.md)`
- **Never leave a page without frontmatter**
- **Never create a page without `## See Also`**
- **Never skip updating `index.md`** after page changes
- **Never scatter docs in the project repo** (`docs/`, ADRs) — move them to
  the wiki (structure + reasoning) or the platform wiki (important ADRs via
  `gh`/`fj`). Root files (`README.md`, `AGENTS.md`, `CONTEXT.md`) are
  **indexes** that link to the real docs, not documentation themselves.

## Agent-Generated vs Manual Content

Wiki pages for LC4 projects contain two types of content:

1. **Agent-generated** (managed by `arch-sync`):
   - The `## Architecture (C4D2 — RIG + LikeC4)` section
   - All embedded Mermaid diagrams derived from the LikeC4 model
   - Component descriptions traceable to RIG IDs

2. **Manual** (human-authored, preserved across syncs):
   - Everything else — deployment notes, configuration examples,
     operational runbooks, performance benchmarks, ADRs

**The agent preserves manual content.** Only the architecture diagram
section is replaced on each sync. Humans can safely add sections anywhere
outside the `## Architecture (C4D2 — RIG + LikeC4)` block — they will
survive every `arch-sync` run.

If you need to annotate or correct the architecture section, add a separate
`## Architecture Notes` section instead of editing the generated one.

- **Never skip appending to `log.md`** after any operation
- **Never use LikeC4 models in the Generic workflow** — Mermaid only
- **Never hand-write Mermaid for C4 architecture diagrams** — generate from
  the LikeC4 model via `likec4 gen mermaid`

- **Never write architecture diagrams from memory or training data** — every
  component, dependency, and boundary MUST come from the RIG in `raw/arch/`

- **Never use the Architecture workflow if no graph exists** — if
  `raw/arch/<project>/rig.db` is missing, use Generic Documentation instead

- **Never place a page in the wrong entity type directory**
