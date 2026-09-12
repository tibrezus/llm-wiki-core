"""Tests for the rig-query instruments: dead, impact, trace, clones.

Query helpers are pure functions over a crafted rig.db so the CLI layer
stays thin and the evidence contracts stay testable.
"""

import importlib.util
import sqlite3
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ACTION_DIR = Path(__file__).resolve().parent.parent / ".github" / "actions" / "repo-map"
sys.path.insert(0, str(ACTION_DIR))

_spec = importlib.util.spec_from_file_location(
    "rig_query", ACTION_DIR / "rig-query.py")
rig_query = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rig_query)

from rig import db as rig_db  # noqa: E402
clone_rows = rig_query.clone_rows
dead_rows = rig_query.dead_rows
impact_rows = rig_query.impact_rows
parse_diff_spans = rig_query.parse_diff_spans
trace_paths = rig_query.trace_paths


def _rig() -> dict:
    return {
        "schema_version": "rig-1.0",
        "repository": {"name": "t", "ref": "r", "language": "python",
                       "build_system": "pip",
                       "generated_at": "2026-01-01T00:00:00Z",
                       "generator": "test"},
        "evidence": [], "components": [
            {"id": "comp-1", "name": "svc", "type": "executable",
             "programming_language": "python", "source_files": ["main.py"],
             "depends_on_ids": ["comp-2"], "external_packages_ids": [],
             "evidence_ids": [], "artifacts": []},
            {"id": "comp-2", "name": "lib", "type": "library",
             "programming_language": "python", "source_files": ["lib.py"],
             "depends_on_ids": [], "external_packages_ids": [],
             "evidence_ids": [], "artifacts": []},
        ],
        "aggregators": [], "runners": [], "test_definitions": [],
        "external_packages": [], "entrypoints": [],
    }


class TestInstruments(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "rig.db"
        rig_db.write_db(_rig(), self.db)
        rig_db.add_files(self.db, [
            {"path": "main.py", "component_id": "comp-1", "language": "python"},
            {"path": "lib.py", "component_id": "comp-2", "language": "python"},
        ])
        rig_db.add_symbols(self.db, [
            {"file": "main.py", "name": "boot", "kind": "def",
             "line": 11, "line_end": 13, "signature": "def boot"},
            {"file": "main.py", "name": "run", "kind": "def",
             "line": 1, "line_end": 5, "signature": "def run"},
            {"file": "main.py", "name": "orphan", "kind": "def",
             "line": 7, "line_end": 9, "signature": "def orphan"},
            {"file": "lib.py", "name": "exported_api", "kind": "def",
             "line": 1, "line_end": 4, "signature": "def exported_api"},
            {"file": "lib.py", "name": "unused_helper", "kind": "def",
             "line": 6, "line_end": 9, "signature": "def unused_helper"},
        ])
        con = sqlite3.connect(self.db)
        con.execute("UPDATE components SET entrypoint=1 WHERE id='comp-1'")
        con.executemany("INSERT INTO calls(caller, callee) VALUES (?,?)",
                        [("main.py:run", "lib.py:exported_api"),
                         ("main.py:boot", "main.py:run")])
        con.commit()
        con.close()
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        self.con = con

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    # ── dead ─────────────────────────────────────────────────────────

    def test_dead_two_tier_reasons(self):
        rows = dead_rows(self.con)
        by_name = {r["name"]: r for r in rows}
        self.assertNotIn("run", by_name)            # called by boot
        self.assertNotIn("exported_api", by_name)   # called by run
        self.assertEqual(by_name["orphan"]["reason"], "no-callers")
        self.assertEqual(by_name["orphan"]["component"], "svc")
        self.assertEqual(by_name["unused_helper"]["reason"],
                         "exported-unreferenced")
        self.assertEqual(by_name["unused_helper"]["component"], "lib")

    def test_dead_refuses_without_call_data(self):
        con = self.con
        con.execute("DELETE FROM calls")
        con.commit()
        self.assertIsNone(dead_rows(con))
        con.execute("INSERT INTO calls(caller, callee) VALUES ('a','b')")
        con.commit()

    def test_dead_component_filter(self):
        rows = dead_rows(self.con, "lib")
        self.assertEqual([r["name"] for r in rows], ["unused_helper"])

    # ── impact ───────────────────────────────────────────────────────

    def test_parse_diff_spans(self):
        diff = textwrap.dedent("""\
            --- a/main.py
            +++ b/main.py
            @@ -1,3 +1,4 @@
             context
            -old
            +new
            +added
            """)
        self.assertEqual(parse_diff_spans(diff), [("main.py", 1, 4)])

    def test_impact_ranks_cross_component_high(self):
        diff = ("+++ b/main.py\n"
                "@@ -1,2 +1,2 @@\n"
                "-x\n+y\n"
                "@@ -7,1 +7,1 @@\n"
                "-a\n+b\n")
        rows = impact_rows(self.con, diff)
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(by_name["run"]["risk"], "high")
        self.assertIn("cross-component", by_name["run"]["reasons"])
        self.assertEqual(by_name["run"]["fan_in"], 1)
        self.assertEqual(by_name["orphan"]["risk"], "low")

    def test_impact_empty_diff(self):
        self.assertEqual(impact_rows(self.con, ""), [])

    # ── trace ────────────────────────────────────────────────────────

    def test_trace_forward_path(self):
        rows = trace_paths(self.con, "run", "exported_api")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["direction"], "→")
        self.assertEqual(rows[0]["length"], 1)
        self.assertEqual(rows[0]["path"], ["main.py:run", "lib.py:exported_api"])

    def test_trace_unreachable_target(self):
        rows = trace_paths(self.con, "exported_api", "orphan")
        self.assertEqual(rows, [])

    def test_trace_no_path(self):
        rows = trace_paths(self.con, "orphan", "run")
        self.assertEqual(rows, [])

    # ── clones ───────────────────────────────────────────────────────

    def test_clone_lookup_by_bare_name(self):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO similar(src, dst, jaccard, scope) "
                    "VALUES ('lib.py:exported_api','main.py:orphan',0.9,"
                    "'cross-component')")
        con.commit()
        con.close()
        rows = clone_rows(self.con, "orphan")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["match"], "lib.py:exported_api")
        self.assertEqual(rows[0]["jaccard"], 0.9)


if __name__ == "__main__":
    unittest.main()
