#!/usr/bin/env python3
"""Findings-level tests for `rig brief` (rig-query.py, llm-wiki-core#18).

The fixture is #2085-shaped: a zig wrapper FFI-calling a CUDA export over a
C core. The tests assert the FINDINGS a reviewer needs — live-caller fan-in
surfaced, orphaned new exports flagged, clone edges reported, cross-component
hops ranked HIGH — plus the freshness contract (stale graph → exit 3), the
honest refusal when the call graph is empty, and the hard text cap.
"""

import json
import sqlite3
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ACTION_DIR = Path(__file__).resolve().parent.parent / ".github" / "actions" / "repo-map"
sys.path.insert(0, str(ACTION_DIR))

from rig import db as rig_db  # noqa: E402
from rig.symbols import extract_export_spans  # noqa: E402
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "rig_query", ACTION_DIR / "rig-query.py")
rq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rq)


_FILES = [  # (path, language, component_id)
    ("c/recycle.c", "c", "comp-2"),
    ("cuda/expert_cache.cu", "cuda", "comp-1"),
    ("src/cuda_bridge.zig", "zig", "comp-3"),
    ("src/loop.zig", "zig", "comp-3"),
]


def _mk_tree(root: Path) -> None:
    (root / "c").mkdir(parents=True)
    (root / "cuda").mkdir()
    (root / "src").mkdir()
    (root / "c/recycle.c").write_text(textwrap.dedent("""\
        /* recycle: LRU bookkeeping */
        int rhesadox_rec_pick_victim(Rec *r, int stream) {
            if (stream < 0) return -1;
            return r->lru_head;
        }
        """))
    (root / "cuda/expert_cache.cu").write_text(textwrap.dedent("""\
        /* expert cache */
        extern "C" int rhesadox_rec_pick_victim(Rec*, int);
        extern "C" int rhesadox_cuda_ensure_layer_async_dev(int device) {
            int s = rhesadox_rec_pick_victim(0, device);
            return s;
        }
        """))
    (root / "src/cuda_bridge.zig").write_text(textwrap.dedent("""\
        extern fn rhesadox_cuda_ensure_layer_async_dev(device: c_int) c_int;
        pub fn ensureLayerAsyncDev(device: c_int) c_int {
            return rhesadox_cuda_ensure_layer_async_dev(device);
        }
        """))
    (root / "src/loop.zig").write_text(textwrap.dedent("""\
        pub fn orphanedNewExport() void {}
        pub fn loopOnce() void {
            var i: u32 = 0;
            i += 1;
            return;
        }
        """))


def _symbols(root: Path) -> list[dict]:
    rows = []
    for f, lang, _cid in _FILES:
        for line, end, sig in extract_export_spans(root / f, lang, cap=None):
            kind, _, name = sig.partition(" ")
            rows.append({"file": f, "name": name or sig, "kind": kind,
                         "line": line, "line_end": end, "signature": sig})
    return rows


def _build_db(root: Path, name: str = "rig.db", source_sha: str | None = None,
              with_calls: bool = True) -> Path:
    db = root / name
    rig = {"schema_version": "rig-1.0",
           "repository": {"name": "rhesadox", "language": "zig"},
           "components": [
               {"id": "comp-1", "name": "cuda-backend", "type": "shared_library",
                "programming_language": "cuda"},
               {"id": "comp-2", "name": "c-kernels", "type": "static_library",
                "programming_language": "c"},
               {"id": "comp-3", "name": "zig-backend", "type": "package_library",
                "programming_language": "zig"},
           ],
           "external_packages": [], "entrypoints": [], "evidence": [],
           "test_definitions": [], "runners": []}
    rig_db.write_db(rig, db)
    rig_db.add_symbols(db, _symbols(root))
    rig_db.add_files(db, [{"path": f, "component_id": cid, "language": lang}
                          for f, lang, cid in _FILES])
    if with_calls:
        import sys as _sys
        _sys.path.insert(0, str(ACTION_DIR))
        from rig.calls import compute_and_store
        compute_and_store(db, root)
    if source_sha:
        rig_db.set_meta(db, "source_sha", source_sha)
    return db


# The #2085-shaped diff: touches the CUDA export's definition hunk
_DIFF_FFI = """\
diff --git a/cuda/expert_cache.cu b/cuda/expert_cache.cu
--- a/cuda/expert_cache.cu
+++ b/cuda/expert_cache.cu
@@ -2,4 +2,5 @@
 extern "C" int rhesadox_rec_pick_victim(Rec*, int);
 extern "C" int rhesadox_cuda_ensure_layer_async_dev(int device) {
+    /* fence the victim pick before the DMA */
     int s = rhesadox_rec_pick_victim(0, device);
     return s;
"""

# A diff that adds a brand-new export nobody calls (the P3 orphan shape)
_DIFF_ORPHAN = """\
diff --git a/src/loop.zig b/src/loop.zig
--- a/src/loop.zig
+++ b/src/loop.zig
@@ -1,3 +1,5 @@
+pub fn orphanedNewExport() void {}
+
 pub fn loopOnce() void {
     var i: u32 = 0;
"""


class _Brief:
    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _mk_tree(self.root)
        self.db = _build_db(self.root, source_sha="abc123")
        self.con = sqlite3.connect(self.db)
        self.con.row_factory = sqlite3.Row
        return self

    def __exit__(self, *exc):
        self.con.close()
        self._tmp.cleanup()


class TestBriefFindings(unittest.TestCase):
    def test_live_caller_fan_in_surfaces_and_ranks_high(self):
        # the P2 shape: the touched CUDA export has a live zig caller across
        # the component boundary — the brief must say so in ONE call
        with _Brief() as b:
            out = rq.brief_rows(b.con, _DIFF_FFI)
            by_name = {r["name"]: r for r in out["risk"]}
            dev = by_name["rhesadox_cuda_ensure_layer_async_dev"]
            self.assertGreaterEqual(dev["fan_in"], 1)   # the zig wrapper calls it
            self.assertGreaterEqual(dev["cross_component_hops"], 1)
            self.assertEqual(dev["risk"], "high")
            self.assertIn("cross-component", dev["reasons"])

    def test_orphaned_new_export_flagged(self):
        with _Brief() as b:
            out = rq.brief_rows(b.con, _DIFF_ORPHAN)
            names = [d["name"] for d in out["orphaned"]]
            self.assertIn("orphanedNewExport", names)
            self.assertEqual(out["exit"], 1)

    def test_clone_edge_reported_for_touched_symbol(self):
        with _Brief() as b:
            # seed a near-clone edge onto a touched symbol (clone storage
            # itself is pinned in test_rig_clones; this is the query layer)
            b.con.execute(
                "INSERT INTO similar(src, dst, jaccard, scope) VALUES (?,?,?,?)",
                ("cuda/expert_cache.cu:rhesadox_cuda_ensure_layer_async_dev",
                 "metal/expert.m:ensureLayerAsync", 0.87, "cross-component"))
            b.con.commit()
            out = rq.brief_rows(b.con, _DIFF_FFI)
            self.assertTrue(any(c["match"].endswith("ensureLayerAsync")
                                for c in out["clones"]))

    def test_coverage_gap_flagged(self):
        diff = (_DIFF_FFI + "diff --git a/docs/notes.md b/docs/notes.md\n"
                "--- a/docs/notes.md\n+++ b/docs/notes.md\n@@ -1 +1,2 @@\n"
                "+note\n")
        with _Brief() as b:
            out = rq.brief_rows(b.con, diff)
            self.assertIn("docs/notes.md", out["touched"]["outside_components"])

    def test_ffi_edge_reachable_in_risk_reasons(self):
        with _Brief() as b:
            out = rq.brief_rows(b.con, _DIFF_FFI)
            self.assertIn("regex-v1", out["calls_source"])


class TestBriefContract(unittest.TestCase):
    def test_stale_graph_exit_3(self):
        with _Brief() as b:
            out = rq.brief_rows(b.con, _DIFF_FFI, expect_sha="cafe999")
            self.assertTrue(out["provenance"]["stale"])
            self.assertEqual(out["exit"], 3)
            text = rq._render_brief(out)
            self.assertIn("STALE", text)

    def test_fresh_graph_exit_1_with_findings(self):
        with _Brief() as b:
            out = rq.brief_rows(b.con, _DIFF_FFI, expect_sha="abc123")
            self.assertFalse(out["provenance"]["stale"])
            self.assertEqual(out["exit"], 1)

    def test_empty_diff_exit_0(self):
        with _Brief() as b:
            out = rq.brief_rows(b.con, "")
            self.assertEqual(out["exit"], 0)

    def test_unknown_provenance_reported_honestly(self):
        # db emitted before source_sha existed → brief cannot verify
        # freshness; it must say so, not claim "fresh"
        with _Brief() as b:
            b.con.execute("DELETE FROM meta WHERE key='source_sha'")
            b.con.commit()
            out = rq.brief_rows(b.con, _DIFF_FFI, expect_sha="abc123")
            self.assertFalse(out["provenance"]["stale"])
            self.assertFalse(out["provenance"]["known"])
            self.assertIn("unknown", rq._render_brief(out))

    def test_no_call_data_honest_refusal(self):
        with _Brief() as b:
            b.con.execute("DELETE FROM calls")
            b.con.commit()
            out = rq.brief_rows(b.con, _DIFF_FFI)
            self.assertIsNone(out["calls_source"])
            text = rq._render_brief(out)
            self.assertIn("call graph empty", text)

    def test_text_output_hard_capped(self):
        with _Brief() as b:
            # 60 touched symbols, each carrying a near-clone edge → the
            # un-capped render alone would exceed the cap
            many = "".join(
                f"\npub fn genFn{i:03d}() void {{ return; }}"
                for i in range(60))
            (b.root / "src/loop.zig").write_text(many + "\n")
            rows = []
            for line, end, sig in extract_export_spans(
                    b.root / "src/loop.zig", "zig", cap=None):
                kind, _, name = sig.partition(" ")
                rows.append({"file": "src/loop.zig", "name": name or sig,
                             "kind": kind, "line": line, "line_end": end,
                             "signature": sig})
            rig_db.add_symbols(b.db, rows)
            big_diff = (
                "diff --git a/src/loop.zig b/src/loop.zig\n"
                "--- a/src/loop.zig\n+++ b/src/loop.zig\n"
                "@@ -1,5 +1,65 @@\n"
                + "".join(f"+pub fn genFn{i:03d}() void {{ return; }}\n"
                          for i in range(60)))
            for i in range(60):
                b.con.execute(
                    "INSERT INTO similar(src, dst, jaccard, scope) "
                    "VALUES (?,?,?,?)",
                    (f"src/loop.zig:genFn{i:03d}",
                     f"metal/gen.m:genFn{i:03d}Clone", 0.81, "cross-component"))
            b.con.commit()
            out = rq.brief_rows(b.con, big_diff)
            self.assertGreater(len(json.dumps(out)), 3000)  # JSON is uncapped
            text = rq._render_brief(out)
            self.assertLessEqual(len(text), 3000)
            self.assertTrue(text.startswith("# brief:"))
            self.assertTrue(text.rstrip().endswith("rig component <name>"))


if __name__ == "__main__":
    unittest.main()
