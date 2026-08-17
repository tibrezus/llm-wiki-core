"""Tests for rig.db — the canonical SQLite RIG artifact.

Covers the three invariants that make the DB artifact trustworthy:
  1. Determinism — identical input → identical file bytes + canonical hash.
  2. Roundtrip  — read_db(write_db(rig)) == rig modulo volatile fields.
  3. Parity     — model.c4 from rig.db == model.c4 from rig.json
                  (same symbols implementation, both paths).
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ACTION_DIR = Path(__file__).resolve().parent.parent / ".github" / "actions" / "repo-map"
sys.path.insert(0, str(ACTION_DIR))

from rig import db as rig_db  # noqa: E402


def _sample_rig() -> dict:
    """A minimal but complete RIG covering every node type and >9 evidence
    entries (to catch lexical-sort bugs like evidence-10 < evidence-2)."""
    evidence = [{"id": f"evidence-{i}", "line": [f"build.zig:{i}"], "call_stack": []}
                for i in range(1, 12)]
    return {
        "schema_version": "rig-1.0",
        "repository": {
            "name": "sample", "ref": "abc1234", "language": "zig",
            "build_system": "zig", "generated_at": "2026-08-17T00:00:00Z",
            "generator": "test",
        },
        "evidence": evidence,
        "components": [
            {"id": "comp-1", "name": "app", "type": "executable",
             "programming_language": "zig",
             "source_files": ["src/main.zig", "src/util.zig"],
             "depends_on_ids": ["comp-2"],
             "external_packages_ids": ["pkg-1"],
             "evidence_ids": ["evidence-1", "evidence-2", "evidence-10"],
             "artifacts": [{"name": "app", "relative_path": "zig-out/bin/app"}]},
            {"id": "comp-2", "name": "lib", "type": "static_library",
             "programming_language": "zig",
             "source_files": ["src/lib.zig"],
             "depends_on_ids": [], "external_packages_ids": [],
             "evidence_ids": ["evidence-3"], "artifacts": []},
        ],
        "aggregators": [
            {"id": "agg-1", "name": "all", "depends_on_ids": ["comp-1", "comp-2"],
             "evidence_ids": ["evidence-4"]},
        ],
        "runners": [
            {"id": "runner-1", "name": "zig build test", "arguments": ["zig", "build", "test"],
             "depends_on_ids": ["comp-2"], "evidence_ids": ["evidence-5"]},
        ],
        "test_definitions": [
            {"id": "test-1", "name": "lib_test", "depends_on_ids": ["comp-2"],
             "components_being_tested_ids": ["comp-2"],
             "source_files": ["src/test.zig"], "evidence_ids": ["evidence-6"],
             "test_framework": "zig-test", "test_executable_component_id": "comp-2",
             "covers_ids": ["comp-2"]},
        ],
        "external_packages": [
            {"id": "pkg-1", "name": "clap",
             "package_manager": {"name": "zig-modules", "package_name": "clap"}},
        ],
        "entrypoints": ["comp-1"],
    }


def _strip_volatile(rig: dict) -> dict:
    out = json.loads(json.dumps(rig))
    out["repository"]["generated_at"] = ""
    out["repository"]["ref"] = ""
    return out


class TestRigDb(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_determinism(self):
        rig = _sample_rig()
        a, b = self.dir / "a.db", self.dir / "b.db"
        rig_db.write_db(rig, a)
        rig_db.write_db(rig, b)
        self.assertEqual(a.read_bytes(), b.read_bytes(),
                         "identical input must give byte-identical DB")
        self.assertEqual(rig_db.canonical_hash(a), rig_db.canonical_hash(b))

    def test_roundtrip(self):
        rig = _sample_rig()
        p = self.dir / "rig.db"
        rig_db.write_db(rig, p)
        loaded = rig_db.read_db(p)
        self.assertEqual(loaded, _strip_volatile(rig))

    def test_evidence_ordering_above_nine(self):
        """evidence-10 must NOT sort before evidence-2 (lexical trap)."""
        rig = _sample_rig()
        p = self.dir / "rig.db"
        rig_db.write_db(rig, p)
        loaded = rig_db.read_db(p)
        self.assertEqual(loaded["components"][0]["evidence_ids"],
                         ["evidence-1", "evidence-2", "evidence-10"])
        self.assertEqual([e["id"] for e in loaded["evidence"]][-1], "evidence-11")

    def test_fts_search(self):
        rig = _sample_rig()
        p = self.dir / "rig.db"
        rig_db.write_db(rig, p)
        rig_db.add_symbols(p, [
            {"file": "src/lib.zig", "name": "parseConfig", "kind": "fn",
             "line": 3, "signature": "fn parseConfig", "doc": "Parse the config"},
        ])
        import sqlite3
        con = sqlite3.connect(p)
        hits = con.execute(
            "SELECT s.name FROM symbols_fts fts JOIN symbols s ON s.seq = fts.rowid "
            "WHERE symbols_fts MATCH 'parse*'").fetchall()
        con.close()
        self.assertEqual(hits, [("parseConfig",)])

    def test_load_rig_dispatch(self):
        rig = _sample_rig()
        dbp = self.dir / "rig.db"
        jp = self.dir / "rig.json"
        rig_db.write_db(rig, dbp)
        jp.write_text(json.dumps(_strip_volatile(rig)))
        self.assertEqual(rig_db.load_rig(dbp), rig_db.load_rig(jp))


class TestModelParity(unittest.TestCase):
    """model.c4 from rig.db must equal model.c4 from rig.json."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        # A tiny source tree so symbols/doc extraction has real input.
        src = self.dir / "src"
        src.mkdir()
        (src / "lib.zig").write_text(
            "//! A library.\npub fn parse(x: u32) u32 { return x; }\n"
            "pub const Config = struct { a: u32 };\n")
        (src / "main.zig").write_text(
            "//! The app.\nconst std = @import(\"std\");\n")
        rig = _sample_rig()
        rig["repository"]["language"] = "zig"
        self.db_path = self.dir / "rig.db"
        self.json_path = self.dir / "rig.json"
        rig_db.write_db(rig, self.db_path)
        self.json_path.write_text(json.dumps(rig))
        # Populate symbols + docs exactly like emit-rig.py does.
        from rig import symbols as rig_symbols
        rig_db.add_symbols(self.db_path, rig_symbols.extract_symbols(rig, self.dir))
        file_rows = []
        for c in rig["components"]:
            for sf in c.get("source_files", []):
                f = self.dir / sf
                if f.is_file():
                    file_rows.append({
                        "path": sf, "component_id": c["id"], "language": "zig",
                        "bytes": f.stat().st_size,
                        "lines": f.read_text().count("\n") + 1,
                        "doc": rig_symbols.extract_doc_comment(f, "zig"),
                    })
        rig_db.add_files(self.db_path, file_rows)
        self.rig = rig

    def _run(self, *args):
        r = subprocess.run(
            [sys.executable, str(ACTION_DIR / "rig-to-c4.py"), *args],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_json_db_parity(self):
        from_json = self._run(str(self.json_path), "--source-dir", str(self.dir))
        from_db = self._run(str(self.db_path), "--source-dir", str(self.dir))
        self.assertEqual(from_json, from_db)

    def test_model_is_time_deterministic(self):
        """No timestamp in the header — regeneration must be diff-free."""
        m1 = self._run(str(self.db_path), "--source-dir", str(self.dir))
        m2 = self._run(str(self.db_path), "--source-dir", str(self.dir))
        self.assertEqual(m1, m2)
        self.assertNotIn("Generated:", m1)


if __name__ == "__main__":
    unittest.main()
