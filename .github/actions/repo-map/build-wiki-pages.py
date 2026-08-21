#!/usr/bin/env python3
"""build-wiki-pages.py — Build the ONE human-facing architecture page.

Everything a human needs about a project's architecture lands in a single
Architecture.md: rendered C4 views (Mermaid), the complete source map,
per-component diagrams, the LikeC4 model (appendix), and the CI registry
(appendix). No page sprawl, no separate C4-Model/Component pages.

The machine-facing artifact is rig.db (query it with rig-query.py / the pi
`rig` tool) — this script never touches it beyond the source map.

Usage:
    build-wiki-pages.py <mmd-dir> [--output-dir <dir>] [--project-name <name>]
        [--rig-file <rig.db>] [--model-file <model.c4>] [--ci-file <CI.md>]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def parse_mmd(path: Path) -> tuple[str | None, str]:
    """Parse a .mmd file, returning (title, mermaid_body)."""
    text = path.read_text(encoding="utf-8")
    title: str | None = None
    body = text

    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            frontmatter = body[3:end].strip()
            body = body[end + 4 :].lstrip("\n")
            m = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', frontmatter, re.MULTILINE)
            if m:
                title = m.group(1).strip().strip("'\"")

    return title, body.strip()


def slugify(title: str) -> str:
    """Convert a title to a heading-safe anchor slug."""
    name = title.split(" — ")[0].split(" - ")[0]
    name = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return name or "diagram"


def sanitize_mermaid_id(name: str) -> str:
    """Make a string safe for use as a Mermaid node/subgraph ID."""
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def load_graph_from_db(rig_path: Path) -> tuple[list[dict], list[dict]]:
    """Load components + files + deps from a rig.db."""
    import sqlite3

    con = sqlite3.connect(rig_path)
    con.row_factory = sqlite3.Row
    try:
        components = []
        for c in con.execute("SELECT id, name, type FROM components ORDER BY seq"):
            files = [r["path"] for r in con.execute(
                "SELECT path FROM files WHERE component_id = ? ORDER BY path", (c["id"],))]
            components.append({
                "id": c["id"], "name": c["name"], "type": c["type"],
                "source_files": files,
            })
        deps = [
            {"from_id": r["src"], "to_id": r["dst"], "type": "depends on"}
            for r in con.execute("SELECT src, dst FROM deps")
        ]
        return components, deps
    finally:
        con.close()


def build_source_map(components: list[dict], deps: list[dict],
                     max_files_per_component: int = 50) -> str | None:
    """Generate a Mermaid diagram showing ALL source files grouped by
    build-target component.

    This is the 'complete repository structure' — every source file visible
    in one graph, organized by component. likec4's system-level view only
    shows build targets; this goes deeper.
    """
    if not components:
        return None

    lines: list[str] = ["graph TB"]
    used_ids: set[str] = set()

    def unique_id(name: str) -> str:
        base = sanitize_mermaid_id(name)
        sid = base
        i = 2
        while sid in used_ids:
            sid = f"{base}{i}"
            i += 1
        used_ids.add(sid)
        return sid

    for comp in components:
        comp_name = comp.get("name", comp.get("id", "unknown"))
        comp_type = comp.get("type", "")
        comp_id = unique_id(f"comp_{comp_name}")
        label = f'{comp_name} ({comp_type})' if comp_type else comp_name

        srcs = comp.get("source_files", [])
        if not srcs:
            # Component with no source files — just a box
            lines.append(f'  {comp_id}["`{label}`"]')
            continue

        # Subgraph for this component's source files
        lines.append(f'  subgraph {comp_id}["`{label}`"]')

        shown = 0
        skipped = len(srcs) - max_files_per_component
        for sf in srcs[:max_files_per_component]:
            sf_name = Path(sf).name
            sf_id = unique_id(f"{comp_id}_{sf_name}")
            lines.append(f'    {sf_id}["`{sf_name}`"]')
            shown += 1

        if skipped > 0:
            lines.append(f'    {comp_id}_more["`... +{skipped} more files`"]')

        lines.append("  end")

    # Add dependency edges between components
    comp_name_to_id: dict[str, str] = {}
    for comp in components:
        cname = comp.get("name", comp.get("id", ""))
        cid = sanitize_mermaid_id(f'comp_{cname}')
        if any(l.strip().startswith(f"subgraph {cid}") for l in lines):
            comp_name_to_id[comp.get("id", cname)] = cid

    for dep in deps:
        src_id = comp_name_to_id.get(dep.get("from_id") or dep.get("source_id", ""))
        tgt_id = comp_name_to_id.get(dep.get("to_id") or dep.get("target_id", ""))
        if src_id and tgt_id:
            dep_type = dep.get("type", "depends on")
            lines.append(f'  {src_id} -. "`{dep_type}`" .-> {tgt_id}')

    return "\n".join(lines) if len(lines) > 1 else None


def strip_h1(text: str) -> str:
    """Remove a leading H1 (the merged page has exactly one)."""
    return re.sub(r"^# .+?\n+", "", text, count=1)


def build_page(
    mmd_dir: Path,
    output_dir: Path,
    project_name: str,
    rig_path: Path | None = None,
    model_path: Path | None = None,
    ci_path: Path | None = None,
) -> Path | None:
    """Build the single Architecture.md. Returns its path."""
    mmd_files = sorted(mmd_dir.glob("*.mmd"))

    structure_body: str | None = None
    context_body: str | None = None
    container_body: str | None = None
    component_views: list[tuple[str, str]] = []  # (title, body)

    for mmd in mmd_files:
        if mmd.stem == "index":
            continue

        title, body = parse_mmd(mmd)
        stem = mmd.stem.lower()
        tl = (title or "").lower()
        if stem == "structure" or "repository structure" in tl:
            structure_body = body
        elif stem == "context" or "context" in tl:
            context_body = body
        elif stem == "containers" or "containers" in tl:
            container_body = body
        else:
            component_views.append((title or mmd.stem, body))

    # Source map from rig.db if available
    source_map: str | None = None
    if rig_path and rig_path.exists():
        comps, dep_edges = load_graph_from_db(rig_path)
        source_map = build_source_map(comps, dep_edges)

    output_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        f"# Architecture — {project_name}",
        "",
        "> Auto-generated from source code analysis. "
        "Regenerated on every push to `main`.",
        "> The machine-facing graph is `rig.db` (query it — don't read it).",
        "",
    ]

    # Structure / context / container view
    if structure_body:
        lines += ["## Repository Structure", "", "```mermaid", structure_body, "```", ""]
    else:
        if context_body:
            lines += ["## System Context", "", "```mermaid", context_body, "```", ""]
        if container_body and container_body != context_body:
            lines += ["## Containers", "", "```mermaid", container_body, "```", ""]

    # Source map — the complete file-level structure (the "detail" view)
    if source_map:
        lines += [
            "## Source Files",
            "",
            "Every source file in the repository, grouped by build target:",
            "",
            "```mermaid",
            source_map,
            "```",
            "",
        ]

    # Per-component diagrams — inline sections, one page
    if component_views:
        lines += ["## Component Views", ""]
        for title, body in component_views:
            display = title.split(" — ")[0] if " — " in title else title
            lines += [f"### {display}", "", "```mermaid", body, "```", ""]

    # Appendix: the full LikeC4 model (semantic view for agents + humans)
    if model_path and model_path.exists():
        model_text = model_path.read_text(encoding="utf-8")
        lines += [
            "## Appendix: LikeC4 Model",
            "",
            "The full model, generated deterministically from the RIG. Every",
            "component description, doc comment, and export is derived from the",
            "source code — nothing invented.",
            "",
            "```likec4",
            model_text,
            "```",
            "",
        ]

    # Appendix: CI registry — the other human-facing surface, merged in
    if ci_path and ci_path.exists():
        ci_text = ci_path.read_text(encoding="utf-8").strip()
        if ci_text:
            lines += ["## Appendix: CI Registry", "", strip_h1(ci_text), ""]

    arch_path = output_dir / "Architecture.md"
    arch_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        f"[build-wiki-pages] Architecture.md: {len(mmd_files)} .mmd views"
        + (f", source map from {rig_path.name}" if source_map else "")
        + (", LikeC4 appendix" if model_path and model_path.exists() else "")
        + (", CI registry appendix" if ci_path and ci_path.exists() else "")
    )
    return arch_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the single human-facing Architecture.md page."
    )
    parser.add_argument("mmd_dir", type=Path, help="Directory containing .mmd files")
    parser.add_argument("--output-dir", type=Path, default=Path("wiki-out"))
    parser.add_argument("--project-name", default="Project")
    parser.add_argument("--rig-file", type=Path, default=None, help="rig.db for the source map")
    parser.add_argument("--model-file", type=Path, default=None, help="model.c4 for the LikeC4 appendix")
    parser.add_argument("--ci-file", type=Path, default=None, help="CI registry markdown, merged as an appendix")
    args = parser.parse_args()

    if not args.mmd_dir.is_dir():
        print(f"Error: {args.mmd_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    page = build_page(args.mmd_dir, args.output_dir, args.project_name,
                      args.rig_file, args.model_file, args.ci_file)
    if not page:
        sys.exit(1)


if __name__ == "__main__":
    main()
