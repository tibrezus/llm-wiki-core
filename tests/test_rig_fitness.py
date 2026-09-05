#!/usr/bin/env python3
"""Unit tests for the graph-fitness module (rig/fitness.py + rig-fitness.py).

Builds a minimal rig.db with sqlite3 (components/files/symbols/deps only —
the tables the fitness queries touch) and verifies:

  - shape metrics (components, edges, cycles, fan-in, sizes)
  - the duplication report (blocklist, builtins, cross-language, spread)
  - Markdown rendering (Architecture.md section)
  - the CLI (--json machine payload, Markdown default)
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_MAP = Path(__file__).resolve().parent.parent / ".github" / "actions" / "repo-map"
sys.path.insert(0, str(REPO_MAP))

from rig.fitness import (  # noqa: E402
    SEVERE_COMPONENT_SPREAD,
    duplication_report,
    fitness_snapshot,
    graph_metrics,
    read_code_map,
    render_markdown,
)

SCHEMA = """
CREATE TABLE components(
  id TEXT PRIMARY KEY, seq INTEGER NOT NULL, name TEXT NOT NULL,
  type TEXT, language TEXT, entrypoint INTEGER NOT NULL DEFAULT 0);
CREATE TABLE files(
  path TEXT PRIMARY KEY, component_id TEXT, language TEXT,
  bytes INTEGER, lines INTEGER, doc TEXT);
CREATE TABLE symbols(
  seq INTEGER PRIMARY KEY, file TEXT NOT NULL, name TEXT NOT NULL,
  kind TEXT, line INTEGER, signature TEXT, doc TEXT);
CREATE TABLE deps(src TEXT NOT NULL, dst TEXT NOT NULL);
"""


def _sym(name, kind="fn", sig=None):
    return {"name": name, "kind": kind, "signature": sig if sig is not None
            else (f"{kind} {name}" if kind in ("fn", "type", "var") else name)}


class _Db:
    """Fluent builder for a minimal rig.db fixture."""

    def __init__(self):
        self.fd, self.path = tempfile.mkstemp(suffix=".db")
        import sqlite3
        self.con = sqlite3.connect(self.path)
        self.con.executescript(SCHEMA)

    def component(self, cid, name=None, lang="zig", entrypoint=0):
        self.con.execute(
            "INSERT INTO components VALUES (?,?,?,?,?,?)",
            (cid, cid.split("-")[-1], name or cid, "library", lang, entrypoint))
        return self

    def file(self, path, cid, lang="zig"):
        self.con.execute("INSERT INTO files VALUES (?,?,?,?,?,?)",
                         (path, cid, lang, 100, 10, ""))
        return self

    def symbol(self, path, row, line=1):
        self.con.execute("INSERT INTO symbols VALUES (?,?,?,?,?,?,?)",
                         (None, path, row["name"], row["kind"], line,
                          row["signature"], ""))
        return self

    def dep(self, src, dst):
        self.con.execute("INSERT INTO deps VALUES (?,?)", (src, dst))
        return self

    def done(self):
        self.con.commit()
        self.con.close()
        return Path(self.path)


def _fixture_db():
    """3 components; parseDup in comps 1+2 (warn); triDup in 1+2+3 (severe);
    main x3 (blocked); c-only builtin x2 langs (cross-language, ignored)."""
    db = _Db()
    for cid in ("comp-a", "comp-b", "comp-c"):
        db.component(cid)
        db.file(f"src/{cid}/mod.zig", cid, "zig")
        db.file(f"src/{cid}/main.zig", cid, "zig")
        db.symbol(f"src/{cid}/mod.zig", _sym("triDup"))
        db.symbol(f"src/{cid}/main.zig", _sym("main"))
    db.symbol("src/comp-a/mod.zig", _sym("parseDup"))
    db.symbol("src/comp-b/mod.zig", _sym("parseDup"))
    # same name in a THIRD component but a different language — the c row
    # must NOT extend the zig duplication (spread stays 2, warn not severe)
    db.file("src/comp-c/shim.c", "comp-c", "c")
    db.symbol("src/comp-c/shim.c", _sym("parseDup"))
    # __-prefixed builtin as REAL rows in both languages — blocked by prefix
    db.symbol("src/comp-a/mod.zig", _sym("__builtin_amdgcn_sdot4"))
    db.symbol("src/comp-c/shim.c", _sym("__builtin_amdgcn_sdot4"))
    # junk-kind row (kind = the name itself, bare signature) must be ignored
    db.symbol("src/comp-a/mod.zig", {"name": "junkRow", "kind": "junkRow",
                                     "signature": "junkRow"})
    # fan-in: comp-a is depended on by b and c → hub
    db.dep("comp-b", "comp-a").dep("comp-c", "comp-a")
    return db.done()


class TestGraphMetrics(unittest.TestCase):
    def setUp(self):
        self.db = _fixture_db()

    def tearDown(self):
        import os
        os.unlink(self.db)

    def test_counts_and_fan_in(self):
        m = graph_metrics(self.db)
        self.assertEqual(m["components"], 3)
        self.assertEqual(m["edges"], 2)
        self.assertEqual(m["cycles"], [])
        self.assertEqual(m["max_fan_in"][0]["component"], "comp-a")
        self.assertEqual(m["max_fan_in"][0]["count"], 2)

    def test_cycle_detection(self):
        db = _Db()
        db.component("x").component("y")
        db.file("x.zig", "x").file("y.zig", "y")
        db.dep("x", "y").dep("y", "x")
        p = db.done()
        m = graph_metrics(p)
        self.assertEqual(len(m["cycles"]), 1)
        import os
        os.unlink(p)

    def test_real_rows_only(self):
        # 3*triDup + 2*parseDup(zig) + 1*parseDup(c) + 3*main + 2 builtin = 11
        # rows; the junk-kind row (kind = its own name, bare signature) is
        # excluded at read time — semantic filters live in duplication_report.
        rows = read_code_map(self.db)
        names = [r["name"] for r in rows]
        self.assertNotIn("junkRow", names)
        self.assertEqual(names.count("triDup"), 3)


class TestDuplicationReport(unittest.TestCase):
    def setUp(self):
        self.db = _fixture_db()
        self.rows = read_code_map(self.db)

    def tearDown(self):
        import os
        os.unlink(self.db)

    def test_severe_and_warn_levels(self):
        rep = duplication_report(self.rows)
        names = {d["name"] for d in rep["duplicated"]}
        self.assertEqual(names, {"triDup", "parseDup"})
        self.assertEqual(len(rep["severe"]), 1)
        self.assertEqual(rep["severe"][0]["name"], "triDup")
        self.assertEqual(rep["severe"][0]["spread"], SEVERE_COMPONENT_SPREAD)
        # the c-language parseDup copy did not extend the zig group
        parse = next(d for d in rep["duplicated"] if d["name"] == "parseDup")
        self.assertEqual(parse["spread"], 2)
        self.assertEqual(parse["language"], "zig")

    def test_blocked_builtin_crosslanguage_ignored(self):
        rep = duplication_report(self.rows)
        names = {d["name"] for d in rep["duplicated"]}
        self.assertNotIn("main", names)
        self.assertNotIn("__builtin_amdgcn_sdot4", names)

    def test_blocked_codec_find_verbs_ignored(self):
        # decode/encode/find: same English verb, unrelated capabilities per
        # layer (rhesadox #1850 calibration — wire-frame decode vs tokenizer
        # encode vs registry find). Name-equality across components must not
        # raise them, no matter the spread.
        rows = self.rows + [
            {"name": "decode", "kind": "fn", "signature": "fn decode", "file": "a.zig", "component_id": "c1", "language": "zig", "component": "one"},
            {"name": "decode", "kind": "fn", "signature": "fn decode", "file": "b.zig", "component_id": "c2", "language": "zig", "component": "two"},
            {"name": "decode", "kind": "fn", "signature": "fn decode", "file": "c.zig", "component_id": "c3", "language": "zig", "component": "three"},
            {"name": "encode", "kind": "fn", "signature": "fn encode", "file": "a.zig", "component_id": "c1", "language": "zig", "component": "one"},
            {"name": "encode", "kind": "fn", "signature": "fn encode", "file": "b.zig", "component_id": "c2", "language": "zig", "component": "two"},
            {"name": "encode", "kind": "fn", "signature": "fn encode", "file": "c.zig", "component_id": "c3", "language": "zig", "component": "three"},
            {"name": "find", "kind": "fn", "signature": "fn find", "file": "a.zig", "component_id": "c1", "language": "zig", "component": "one"},
            {"name": "find", "kind": "fn", "signature": "fn find", "file": "b.zig", "component_id": "c2", "language": "zig", "component": "two"},
            {"name": "find", "kind": "fn", "signature": "fn find", "file": "c.zig", "component_id": "c3", "language": "zig", "component": "three"},
        ]
        rep = duplication_report(rows)
        names = {d["name"] for d in rep["duplicated"]}
        for verb in ("decode", "encode", "find"):
            self.assertNotIn(verb, names)


class TestRendering(unittest.TestCase):
    def setUp(self):
        self.db = _fixture_db()

    def tearDown(self):
        import os
        os.unlink(self.db)

    def test_markdown_section(self):
        md = render_markdown(fitness_snapshot(self.db))
        self.assertTrue(md.startswith("## Graph Fitness"))
        self.assertIn("| Components | 3 |", md)
        self.assertIn("`triDup` **SEVERE**", md)
        self.assertIn("parseDup", md)
        self.assertIn("FAILS CI", md)

    def test_markdown_clean(self):
        db = _Db()
        db.component("solo")
        db.file("solo.zig", "solo")
        db.symbol("solo.zig", _sym("onlyOne"))
        p = db.done()
        md = render_markdown(fitness_snapshot(p))
        self.assertIn("None — no cross-component symbol duplication.", md)
        import os
        os.unlink(p)

    def test_cli_json_and_markdown(self):
        for args, check in (
            (["--json"], lambda out: json.loads(out)),
            ([], lambda out: out),
        ):
            res = subprocess.run(
                [sys.executable, str(REPO_MAP / "rig-fitness.py"), str(self.db)] + args,
                capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            out = check(res.stdout)
            if args:
                self.assertEqual(out["metrics"]["components"], 3)
                self.assertEqual(len(out["duplication"]["severe"]), 1)
            else:
                self.assertTrue(out.startswith("## Graph Fitness"))


if __name__ == "__main__":
    unittest.main()
