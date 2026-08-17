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
"""

from __future__ import annotations

import argparse
import json
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

    args = parser.parse_args()
    con = _connect(args.db)
    try:
        {"overview": cmd_overview, "component": cmd_component,
         "deps": cmd_deps, "files": cmd_files,
         "search": cmd_search, "calls": cmd_calls}[args.cmd](con, args)
    finally:
        con.close()


if __name__ == "__main__":
    main()
