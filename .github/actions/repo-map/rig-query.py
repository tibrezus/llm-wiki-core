#!/usr/bin/env python3
"""rig-query.py — query a rig.db without loading it into context.

THE point of the SQLite artifact: an agent answers structural questions with
targeted queries instead of reading a 100K+-token JSON file. Commands print
compact, human/agent-readable text (use --json for machine output).

Usage:
    rig-query.py <rig.db> overview
    rig-query.py <rig.db> component <id-or-name>
    rig-query.py <rig.db> deps <id-or-name> [--reverse]
    rig-query.py <rig.db> files <glob-pattern>
    rig-query.py <rig.db> search <fts5-query>     # symbol search (name/doc)
    rig-query.py <rig.db> calls <name>            # if archmap calls present
    rig-query.py <rig.db> dead [component]        # zero-caller exports
    rig-query.py <rig.db> clones [symbol] [--top N]  # near-clone pairs
    rig-query.py <rig.db> impact --diff <patch|->    # diff → touched symbols + risk
    rig-query.py <rig.db> trace <a> <b>           # call paths between symbols
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path


def _connect(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.exists():
        print(f"Error: {db_path} not found", file=sys.stderr)
        sys.exit(1)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _resolve(con, ident: str) -> str | None:
    """Resolve a component ID or name (case-insensitive) to its ID."""
    row = con.execute(
        "SELECT id FROM components WHERE id = ? COLLATE NOCASE "
        "UNION SELECT id FROM components WHERE name = ? COLLATE NOCASE "
        "LIMIT 1", (ident, ident)).fetchone()
    return row["id"] if row else None


def _out(rows: list[dict], as_json: bool, title: str = "") -> None:
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    if title:
        print(title)
    if not rows:
        print("  (no results)")
    for r in rows:
        cells = "  ".join(f"{k}={v}" for k, v in r.items())
        print(f"  {cells}")


def cmd_overview(con, args) -> None:
    meta = {r["key"]: r["value"] for r in con.execute("SELECT * FROM meta")}
    comps = con.execute(
        "SELECT c.id, c.name, c.type, c.language, c.entrypoint, "
        "  (SELECT COUNT(*) FROM component_files f WHERE f.component_id = c.id) AS files, "
        "  (SELECT COUNT(*) FROM deps d WHERE d.src = c.id) AS deps, "
        "  (SELECT COUNT(*) FROM symbols s JOIN component_files f ON s.file = f.path "
        "   WHERE f.component_id = c.id) AS symbols "
        "FROM components c ORDER BY c.seq").fetchall()
    counts = {
        "repo": meta.get("repo_name", "?"),
        "language": meta.get("repo_language", "?"),
        "build_system": meta.get("build_system", "?"),
        "components": len(comps),
        "edges": con.execute("SELECT COUNT(*) FROM deps").fetchone()[0],
        "files": con.execute("SELECT COUNT(*) FROM files").fetchone()[0],
        "symbols": con.execute("SELECT COUNT(*) FROM symbols").fetchone()[0],
        "tests": con.execute("SELECT COUNT(*) FROM tests").fetchone()[0],
        "packages": con.execute("SELECT COUNT(*) FROM packages").fetchone()[0],
    }
    print(f"# {counts['repo']} — {counts['build_system']} ({counts['language']})")
    print(f"# {counts['components']} components, {counts['edges']} edges, "
          f"{counts['files']} files, {counts['symbols']} symbols, "
          f"{counts['tests']} tests, {counts['packages']} packages")
    _out([dict(r) for r in comps], args.json)


def cmd_component(con, args) -> None:
    cid = _resolve(con, args.ident)
    if not cid:
        print(f"Error: no component matches {args.ident!r}", file=sys.stderr)
        sys.exit(1)
    c = con.execute("SELECT * FROM components WHERE id = ?", (cid,)).fetchone()
    data: dict = {
        "id": c["id"], "name": c["name"], "type": c["type"],
        "language": c["language"], "entrypoint": bool(c["entrypoint"]),
    }
    data["depends_on"] = [dict(r) for r in con.execute(
        "SELECT d.dst AS id, c2.name FROM deps d "
        "JOIN components c2 ON c2.id = d.dst WHERE d.src = ? ORDER BY d.dst", (cid,))]
    data["depended_on_by"] = [dict(r) for r in con.execute(
        "SELECT d.src AS id, c2.name FROM deps d "
        "JOIN components c2 ON c2.id = d.src WHERE d.dst = ? ORDER BY d.src", (cid,))]
    data["files"] = [dict(r) for r in con.execute(
        "SELECT f.path, f.lines, "
        "  (SELECT COUNT(*) FROM symbols s WHERE s.file = f.path) AS symbols "
        "FROM component_files cf JOIN files f ON f.path = cf.path "
        "WHERE cf.component_id = ? ORDER BY cf.seq", (cid,))]
    data["evidence"] = [dict(r) for r in con.execute(
        "SELECT e.id, e.line FROM component_evidence ce "
        "JOIN evidence e ON e.id = ce.evidence_id "
        "WHERE ce.component_id = ? ORDER BY ce.seq", (cid,))]
    data["tests"] = [dict(r) for r in con.execute(
        "SELECT t.id, t.name, t.framework FROM test_covers tc "
        "JOIN tests t ON t.id = tc.test_id WHERE tc.component_id = ?", (cid,))]
    if args.json:
        print(json.dumps(data, indent=2))
        return
    print(f"{data['id']}: {data['name']} ({data['type']}, {data['language']})"
          + (" [entrypoint]" if data["entrypoint"] else ""))
    print("depends_on:      " + (", ".join(d["name"] for d in data["depends_on"]) or "—"))
    print("depended_on_by: " + (", ".join(d["name"] for d in data["depended_on_by"]) or "—"))
    print(f"files ({len(data['files'])}):")
    for f in data["files"]:
        print(f"  {f['path']}  ({f['lines'] or '?'} lines, {f['symbols']} symbols)")
    print(f"tests: " + (", ".join(t["name"] for t in data["tests"]) or "—"))
    for e in data["evidence"]:
        print(f"evidence: {e['id']}  {e['line']}")


def cmd_deps(con, args) -> None:
    cid = _resolve(con, args.ident)
    if not cid:
        print(f"Error: no component matches {args.ident!r}", file=sys.stderr)
        sys.exit(1)
    if args.reverse:
        rows = con.execute(
            "SELECT d.src AS id, c.name, c.type FROM deps d "
            "JOIN components c ON c.id = d.src WHERE d.dst = ? ORDER BY c.name", (cid,))
    else:
        rows = con.execute(
            "SELECT d.dst AS id, c.name, c.type FROM deps d "
            "JOIN components c ON c.id = d.dst WHERE d.src = ? ORDER BY c.name", (cid,))
    _out([dict(r) for r in rows], args.json)


def cmd_files(con, args) -> None:
    pattern = args.pattern.replace("*", "%").replace("?", "_")
    rows = con.execute(
        "SELECT f.path, f.language, f.lines, "
        "  (SELECT c.name FROM components c WHERE c.id = f.component_id) AS component "
        "FROM files f WHERE f.path LIKE ? ORDER BY f.path", (pattern,))
    _out([dict(r) for r in rows], args.json)


def cmd_search(con, args) -> None:
    try:
        rows = con.execute(
            "SELECT s.file, s.name, s.kind, s.line, s.signature "
            "FROM symbols_fts fts JOIN symbols s ON s.seq = fts.rowid "
            "WHERE symbols_fts MATCH ? ORDER BY s.file, s.line LIMIT 50",
            (args.query,))
        _out([dict(r) for r in rows], args.json)
    except sqlite3.OperationalError as e:
        print(f"Error: {e} (FTS5 index missing — regenerate the DB)", file=sys.stderr)
        sys.exit(1)


def cmd_calls(con, args) -> None:
    key = f"%{args.name}"
    rows = con.execute(
        "SELECT caller, callee FROM calls "
        "WHERE caller LIKE ? OR callee LIKE ? ORDER BY caller, callee LIMIT 50",
        (key, key))
    _out([dict(r) for r in rows], args.json)


# ── Dead exports — zero-caller exported symbols ──────────────────────
#
# Two-tier honesty: in an entrypoint component (binary / main service) an
# exported symbol nobody calls is dead ('no-callers'); in a library
# component cross-repo callers are invisible to a per-repo graph, so it is
# only 'exported-unreferenced'. Requires call data (archmap); with an
# empty calls table we refuse to guess.

_DEAD_NAME_MARKERS = ("main", "__main__")
_DEAD_SUFFIX_MARKERS = ("handler", "listener", "callback", "_test", "test_")


def _has_call_data(con) -> bool:
    return con.execute("SELECT COUNT(*) FROM calls").fetchone()[0] > 0


def dead_rows(con, component: str | None = None) -> list[dict] | None:
    """Zero-caller exported symbols. None ⇒ no call graph available."""
    if not _has_call_data(con):
        return None
    where, params = "", []
    if component:
        cid = _resolve(con, component)
        if not cid:
            return []
        where, params = "WHERE f.component_id = ?", [cid]
    inbound: dict[str, int] = dict(con.execute(
        "SELECT callee, COUNT(*) FROM calls GROUP BY callee"))
    rows = con.execute(
        "SELECT s.file, s.name, s.kind, s.line, s.line_end, s.signature, "
        "       c.entrypoint, c.name AS component, c.id AS component_id "
        "FROM symbols s "
        "LEFT JOIN files f ON f.path = s.file "
        "LEFT JOIN components c ON c.id = f.component_id "
        + where + " ORDER BY s.file, s.line", params).fetchall()
    out = []
    for s in rows:
        name = s["name"]
        if s["kind"] == "test":
            continue
        low = name.lower()
        if name in _DEAD_NAME_MARKERS or low.endswith(_DEAD_SUFFIX_MARKERS) \
                or low.startswith("test_"):
            continue
        if inbound.get(f"{s['file']}:{name}"):
            continue
        out.append({
            "file": s["file"], "name": name, "line": s["line"],
            "component": s["component"],
            "reason": ("no-callers" if s["entrypoint"]
                       else "exported-unreferenced"),
        })
    return out


def cmd_dead(con, args) -> None:
    rows = dead_rows(con, args.component)
    if rows is None:
        print("note: calls table is empty (archmap data absent) — "
              "dead detection needs a call graph; refusing to guess")
        return
    _out(rows, args.json, f"dead/unused exports ({len(rows)}):" if rows else "")


# ── Near-clone edges ─────────────────────────────────────────────────

def clone_rows(con, ident: str | None = None,
               top: int = 20) -> list[dict]:
    """Near-clone pairs (similar table), for one symbol or the top of the repo."""
    if ident:
        exact = con.execute(
            "SELECT file, name FROM symbols WHERE name = ? ORDER BY seq LIMIT 1",
            (ident,)).fetchone()
        keys = {f"{exact['file']}:{exact['name']}"} if exact else {ident}
        rows = []
        for key in keys:
            for r in con.execute(
                    "SELECT src, dst, jaccard, scope FROM similar "
                    "WHERE src = ? OR dst = ? ORDER BY jaccard DESC", (key, key)):
                other = r["dst"] if r["src"] == key else r["src"]
                rows.append({"match": other, "jaccard": r["jaccard"],
                             "scope": r["scope"]})
        return rows
    return [dict(r) for r in con.execute(
        "SELECT src, dst, jaccard, scope FROM similar "
        "ORDER BY jaccard DESC, src LIMIT ?", (top,))]


def cmd_clones(con, args) -> None:
    rows = clone_rows(con, args.symbol, args.top)
    _out(rows, args.json, f"near-clone pairs ({len(rows)}):" if rows and not args.symbol else "")


# ── Diff impact — hunks → symbols → blast radius + risk ─────────────

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @")


def parse_diff_spans(diff_text: str) -> list[tuple[str, int, int]]:
    """[(file, start, end)] on the new side of a unified diff."""
    spans: list[tuple[str, int, int]] = []
    path = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            path = line[4:].split("\t")[0].strip()
            if path.startswith("b/"):
                path = path[2:]
        elif line.startswith("@@") and path:
            m = _HUNK_RE.search(line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2) or "1")
                if count:
                    spans.append((path, start, start + count - 1))
    return spans


def touched_symbol_rows(con, diff_text: str) -> list[dict]:
    """Symbols whose [line, line_end] span intersects any added-side hunk.

    The single hunk→symbol mapping (used by impact ranking and by rig brief
    for orphan/clone intersection) — rows: file, name, kind, line, line_end,
    component_id, key.
    """
    touched: dict[str, dict] = {}
    for path, start, end in parse_diff_spans(diff_text):
        for s in con.execute(
                "SELECT s.file, s.name, s.kind, s.line, s.line_end, "
                "       f.component_id "
                "FROM symbols s LEFT JOIN files f ON f.path = s.file "
                "WHERE s.file = ? AND s.line <= ? "
                "  AND COALESCE(s.line_end, s.line) >= ?",
                (path, end, start)):
            touched[f"{s['file']}:{s['name']}"] = dict(s)
    return list(touched.values())


def impact_rows(con, diff_text: str, depth: int = 3,
                top: int = 10) -> list[dict]:
    """Map diff hunks to symbols, then blast radius + deterministic risk.

    Risk: high — touches cross-component hops or fan-in ≥ 5; medium — has
    inbound callers or outbound reach; low — isolated. Dead symbols (no
    callers, no reach) floor at low by definition: nothing can break.
    """
    touched_rows = touched_symbol_rows(con, diff_text)
    touched: dict[str, dict] = {f"{s['file']}:{s['name']}": s
                                for s in touched_rows}
    if not touched:
        return []

    out_adj: dict[str, list[str]] = {}
    in_deg: dict[str, int] = {}
    for r in con.execute("SELECT caller, callee FROM calls"):
        out_adj.setdefault(r["caller"], []).append(r["callee"])
        in_deg[r["callee"]] = in_deg.get(r["callee"], 0) + 1
    comp_of = dict(con.execute("SELECT path, component_id FROM files"))

    results = []
    for key, s in touched.items():
        # outbound closure, depth-limited
        seen, frontier, cross = {key}, {key}, 0
        my_comp = s["component_id"]
        for _ in range(depth):
            nxt: set[str] = set()
            for node in frontier:
                for nb in out_adj.get(node, ()):
                    if nb not in seen:
                        seen.add(nb)
                        nxt.add(nb)
                        nb_file = nb.split(":", 1)[0]
                        if comp_of.get(nb_file) and comp_of[nb_file] != my_comp:
                            cross += 1
            frontier = nxt
            if not frontier:
                break
        fan_in = in_deg.get(key, 0)
        reasons = []
        if cross:
            reasons.append(f"{cross} cross-component hop(s)")
        if fan_in:
            reasons.append(f"fan-in {fan_in}")
        if len(seen) > 1:
            reasons.append(f"reach {len(seen) - 1}")
        if fan_in >= 5 or cross:
            risk = "high"
        elif fan_in or len(seen) > 1:
            risk = "medium"
        else:
            risk = "low"
            reasons.append("no callers in graph")
        results.append({
            "file": s["file"], "name": s["name"], "line": s["line"],
            "risk": risk, "fan_in": fan_in, "reach": len(seen) - 1,
            "cross_component_hops": cross, "reasons": "; ".join(reasons),
        })
    rank = {"high": 0, "medium": 1, "low": 2}
    results.sort(key=lambda r: (rank[r["risk"]], -r["fan_in"],
                                r["file"], r["line"] or 0))
    return results[:top]


def cmd_impact(con, args) -> None:
    diff_text = (sys.stdin.read() if args.diff == "-"
                 else Path(args.diff).read_text(encoding="utf-8",
                                                errors="replace"))
    rows = impact_rows(con, diff_text)
    if not _has_call_data(con):
        print("note: calls table is empty (archmap data absent) — "
              "risk covers touched symbols only, no blast radius")
    _out(rows, args.json, f"touched symbols by risk ({len(rows)}):" if rows else "")


# ── Brief — the one-call review orientation (llm-wiki-core#18) ──────

_BRIEF_CAP = 3000


def brief_rows(con, diff_text: str,
               expect_sha: str | None = None) -> dict:
    """Assemble the one-call review orientation. Pure: returns the sections,
    the exit code, and nothing printed.

    Sections, in fixed order: provenance (graph freshness), touched
    (files → components + coverage gaps), risk (impact ranking),
    orphaned (new exports with zero callers), clones (near-clone edges
    touching touched code). Exit: 3 stale graph (freshness first — the
    consumer should re-emit, not review a stale graph); 1 findings;
    0 clean. Honest refusals: empty calls table degrades the orphan
    section to a note, never silent zeros.
    """
    meta = {r["key"]: r["value"] for r in con.execute("SELECT * FROM meta")}
    stale = bool(expect_sha and meta.get("source_sha")
                 and meta["source_sha"] != expect_sha)

    spans = parse_diff_spans(diff_text)
    diff_files = sorted({f for f, _s, _e in spans})
    comp_of_file = dict(con.execute("SELECT path, component_id FROM files"))
    comp_name = dict(con.execute("SELECT id, name FROM components"))
    touched_comps = sorted({comp_name[cid] for f in diff_files
                            if (cid := comp_of_file.get(f))})
    outside = [f for f in diff_files if f not in comp_of_file]

    impacts = impact_rows(con, diff_text)
    touched_full = touched_symbol_rows(con, diff_text)
    touched_keys = sorted({f"{s['file']}:{s['name']}" for s in touched_full})

    has_calls = _has_call_data(con)
    orphans: list[dict] = []
    if has_calls:
        dead_by_key = {f"{d['file']}:{d['name']}": d for d in (dead_rows(con) or [])}
        orphans = [dead_by_key[k] for k in sorted(dead_by_key)
                   if k in set(touched_keys)]

    clones: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    for key in touched_keys:
        for c in clone_rows(con, key, top=5):
            pair = tuple(sorted((key, c["match"])))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            clones.append({"symbol": key, **c})

    counts = {
        "components": con.execute("SELECT COUNT(*) FROM components").fetchone()[0],
        "symbols": con.execute("SELECT COUNT(*) FROM symbols").fetchone()[0],
    }
    findings = bool(impacts or orphans or clones or outside)
    code = 3 if stale else (1 if findings else 0)
    return {
        "repo": meta.get("repo_name", "?"),
        "counts": counts,
        "calls_source": meta.get("calls_source") if has_calls else None,
        "provenance": {
            "source_sha": meta.get("source_sha"),
            "expect_sha": expect_sha,
            "stale": stale,
            "known": bool(meta.get("source_sha")),
        },
        "touched": {"files": diff_files, "components": touched_comps,
                    "outside_components": outside},
        "risk": impacts,
        "orphaned": orphans,
        "clones": clones,
        "exit": code,
    }


def _render_brief(b: dict, cap: int = _BRIEF_CAP) -> str:
    """Human text, hard-capped: a triage instrument, not a report."""
    lines: list[str] = []
    p = b["provenance"]
    calls = f"calls: {b['calls_source']}" if b["calls_source"] else "calls: empty"
    lines.append(f"# brief: {b['repo']} — {b['counts']['components']} comps, "
                 f"{b['counts']['symbols']} syms, {calls}")
    if p["stale"]:
        lines.append(f"# provenance: STALE — graph @ {p['source_sha']}, "
                     f"expected {p['expect_sha']} → re-emit before reviewing")
    elif not p["known"]:
        lines.append("# provenance: unknown (emit predates source_sha) — "
                     "verify the wiki checkout freshness yourself")
    else:
        lines.append(f"# provenance: graph @ {p['source_sha']} — fresh")
    t = b["touched"]
    line = (f"touched: {len(t['files'])} files → {len(t['components'])} "
            f"components"
            + (f": {', '.join(t['components'])}" if t["components"] else ""))
    lines.append(line)
    for f in t["outside_components"]:
        lines.append(f"  WARN outside any component: {f}")
    if b["risk"]:
        lines.append(f"risk ({len(b['risk'])}):")
        for r in b["risk"]:
            lines.append(f"  {r['risk'].upper():5} {r['file']}:{r['name']}  "
                         f"fan_in={r['fan_in']} reach={r['reach']} "
                         f"hops={r['cross_component_hops']}")
    elif t["files"]:
        lines.append("risk: no symbols matched the diff hunks")
    if not b["calls_source"]:
        lines.append("orphaned: call graph empty — dead detection unavailable")
    elif b["orphaned"]:
        lines.append(f"orphaned new exports ({len(b['orphaned'])}):")
        for d in b["orphaned"]:
            lines.append(f"  {d['file']}:{d['name']}  {d['reason']}")
    else:
        lines.append("orphaned: none among touched symbols")
    if b["clones"]:
        lines.append(f"near-clones ({len(b['clones'])}):")
        for c in b["clones"]:
            lines.append(f"  {c['symbol']} ~ {c['match']}  "
                         f"j={c['jaccard']:.2f} {c['scope']}")
    lines.append("next: rig impact --diff - · rig trace <a> <b> · "
                 "rig dead <comp> · rig clones <sym> · rig component <name>")
    while sum(len(l) + 1 for l in lines) > cap and len(lines) > 4:
        del lines[-2]  # drop from the tail, keep the header + next-menu
    if sum(len(l) + 1 for l in lines) > cap:
        lines[-2] = "… (use --json)"
    return "\n".join(lines)


def cmd_brief(con, args) -> int:
    diff_text = (sys.stdin.read() if args.diff == "-"
                 else Path(args.diff).read_text(encoding="utf-8",
                                                errors="replace"))
    b = brief_rows(con, diff_text, args.expect_sha)
    if args.json:
        print(json.dumps(b, indent=2))
    else:
        print(_render_brief(b, args.cap))
    return b["exit"]


# ── Trace — call paths between two symbols ──────────────────────────

def _symbol_key(con, ident: str) -> str | None:
    if ":" in ident:
        return ident
    row = con.execute(
        "SELECT file, name FROM symbols WHERE name = ? ORDER BY seq LIMIT 1",
        (ident,)).fetchone()
    return f"{row['file']}:{row['name']}" if row else None


def trace_paths(con, a: str, b: str, depth: int = 5,
                max_paths: int = 3) -> list[dict]:
    """Shortest call paths between two symbols ("file:name" or bare name).

    Tries a → b over outbound calls; if none, tries b → a and reports the
    paths reversed. BFS with predecessor reconstruction; up to max_paths
    shortest paths, deterministic order.
    """
    ka, kb = _symbol_key(con, a), _symbol_key(con, b)
    if not ka or not kb:
        return []
    out_adj: dict[str, list[str]] = {}
    for r in con.execute("SELECT caller, callee FROM calls"):
        out_adj.setdefault(r["caller"], []).append(r["callee"])

    def shortest(src: str, dst: str) -> list[list[str]] | None:
        dist: dict[str, int] = {src: 0}
        frontier = [src]
        for d in range(1, depth + 1):
            nxt: list[str] = []
            for node in frontier:
                for nb in out_adj.get(node, ()):
                    if nb not in dist:
                        dist[nb] = d
                        nxt.append(nb)
            if dst in dist:
                break
            frontier = nxt
        if dst not in dist:
            return None
        # predecessors at exactly dist-1, deterministic order
        rev: dict[str, list[str]] = {}
        for caller_ in sorted(out_adj):
            for nb in sorted(out_adj[caller_]):
                if nb in dist and dist.get(caller_, depth + 1) == dist[nb] - 1:
                    rev.setdefault(nb, []).append(caller_)

        paths: list[list[str]] = []

        def walk(node: str, acc: list[str]) -> None:
            if len(paths) >= max_paths:
                return
            if node == src:
                paths.append([src] + acc)
                return
            for p in rev.get(node, []):
                walk(p, [node] + acc)

        walk(dst, [])
        return paths

    paths = shortest(ka, kb)
    direction = "→"
    if paths is None:
        paths = shortest(kb, ka)
        direction = "←"
        if paths:
            paths = [list(reversed(p)) for p in paths]
    return [{"direction": direction, "length": len(p) - 1, "path": p}
            for p in (paths or [])][:max_paths]


def cmd_trace(con, args) -> None:
    rows = trace_paths(con, args.a, args.b)
    if not rows:
        print("  (no call path found — or calls table empty)")
        return
    _out(rows, args.json)


def main() -> None:
    parser = argparse.ArgumentParser(description="Query a rig.db")
    parser.add_argument("db", help="Path to rig.db")
    parser.add_argument("--json", action="store_true", help="JSON output")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("overview", help="repo summary + component list")
    p = sub.add_parser("component", help="one component in full detail")
    p.add_argument("ident", help="component id or name")
    p = sub.add_parser("deps", help="dependencies of a component")
    p.add_argument("ident")
    p.add_argument("--reverse", action="store_true", help="who depends on it")
    p = sub.add_parser("files", help="files matching a glob")
    p.add_argument("pattern")
    p = sub.add_parser("search", help="FTS5 symbol search")
    p.add_argument("query", help="FTS5 expression, e.g. 'parse' or 'decod*'")
    p = sub.add_parser("calls", help="call edges matching a name (archmap)")
    p.add_argument("name")
    p = sub.add_parser("dead", help="zero-caller exported symbols (needs call data)")
    p.add_argument("component", nargs="?", help="limit to a component")
    p = sub.add_parser("clones", help="near-clone pairs (MinHash+LSH, similar table)")
    p.add_argument("symbol", nargs="?", help="symbol name or file:name key")
    p.add_argument("--top", type=int, default=20, help="repo-wide top N pairs")
    p = sub.add_parser("impact", help="diff → touched symbols, blast radius, risk")
    p.add_argument("--diff", required=True,
                   help="unified diff path, or '-' for stdin")
    p = sub.add_parser("trace", help="call paths between two symbols")
    p.add_argument("a", help="symbol ('file:name' or bare name)")
    p.add_argument("b", help="symbol ('file:name' or bare name)")
    p = sub.add_parser("brief", help="one-call review orientation "
                                    "(diff → provenance, risk, orphans, clones)")
    p.add_argument("--diff", required=True,
                   help="unified diff path, or '-' for stdin")
    p.add_argument("--expect-sha", default=None,
                   help="PR head SHA; graph mismatch → exit 3 (stale)")
    p.add_argument("--cap", type=int, default=_BRIEF_CAP,
                   help="text output char cap (default 3000)")

    args = parser.parse_args()
    con = _connect(args.db)
    try:
        rc = {"overview": cmd_overview, "component": cmd_component,
              "deps": cmd_deps, "files": cmd_files,
              "search": cmd_search, "calls": cmd_calls,
              "dead": cmd_dead, "clones": cmd_clones,
              "impact": cmd_impact, "trace": cmd_trace,
              "brief": cmd_brief}[args.cmd](con, args)
    finally:
        con.close()
    if rc:
        sys.exit(rc)


if __name__ == "__main__":
    main()
