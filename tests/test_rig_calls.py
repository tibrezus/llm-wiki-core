#!/usr/bin/env python3
"""Tests for regex-v1 call-edge extraction (rig/calls.py, llm-wiki-core#17).

The rhesadox#2085 review's decisive question — who calls the C export the
PR fenced — was unanswerable because `calls` was empty. These tests pin the
resolution contract: same-file preference, globally-unique exact-name (the
FFI bridge), ambiguity refusal, keyword exclusion, determinism, and the
store path (rows + `calls_source` meta + stable canonical hash).
"""

import sqlite3
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_MAP = Path(__file__).resolve().parent.parent / ".github" / "actions" / "repo-map"
sys.path.insert(0, str(REPO_MAP))

from rig import db as rig_db  # noqa: E402
from rig.calls import build_call_edges, compute_and_store, scan_calls  # noqa: E402
from rig.symbols import extract_export_spans  # noqa: E402


def _mk(root: Path, rel: str, src: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(src))


class _Tree:
    """rhesadox-shaped tree: c/ export, cuda/ kernels, src/ zig bridge."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        _mk(root, "c/recycle.c", """\
            /* recycle: LRU bookkeeping (lookup / pick_victim / bind) */
            #include "recycle.h"
            int rhesadox_rec_pick_victim(Rec *r, int stream) {
                if (stream < 0) return -1;
                return r->lru_head;
            }
            """)
        _mk(root, "cuda/expert_cache.cu", """\
            /* expert cache: async layer DMA */
            extern "C" int rhesadox_rec_pick_victim(Rec*, int);
            extern "C" int rhesadox_cuda_ensure_layer_async_dev(
                int device, const void* gate) {
                int s = rhesadox_rec_pick_victim(0, device);
                return s;
            }
            """)
        _mk(root, "src/cuda_bridge.zig", """\
            //! bridge: zig front-end → CUDA backend (extern "C" ABI)
            extern fn rhesadox_cuda_ensure_layer_async_dev(device: c_int, gate: ?*const anyopaque) c_int;
            pub fn ensureLayerAsyncDev(device: c_int, gate: ?*const anyopaque) c_int {
                return rhesadox_cuda_ensure_layer_async_dev(device, gate);
            }
            """)
        _mk(root, "src/ambiguous.zig", """\
            // `helper` is defined in TWO files — a call from this file has no
            // local definition and must resolve to NO edge (precision).
            pub fn caller() void {
                helper();
            }
            """)
        _mk(root, "src/helper.zig", """\
            pub fn helper() void {}
            """)
        return root

    def __exit__(self, *exc):
        self._tmp.cleanup()


def _symbols(root: Path) -> list[dict]:
    """Symbol rows exactly as the emit pass stores them (cap=None)."""
    rows = []
    for f, lang in (("c/recycle.c", "c"), ("cuda/expert_cache.cu", "cuda"),
                    ("src/cuda_bridge.zig", "zig"), ("src/ambiguous.zig", "zig"),
                    ("src/helper.zig", "zig")):
        for line, end, sig in extract_export_spans(root / f, lang, cap=None):
            kind, _, name = sig.partition(" ")
            rows.append({"file": f, "name": name or sig, "kind": kind,
                         "line": line, "line_end": end, "signature": sig})
    return rows


class TestScanCalls(unittest.TestCase):
    def test_keywords_never_yield_calls(self):
        found = scan_calls(["if (x) { while (y) return f(x); }"], 1, 1)
        self.assertEqual(found, {"f"})

    def test_multiline_range(self):
        # scan semantics are conservative: the callee identifier must sit
        # directly before '(' on some scanned line — `beta` in `alpha(\n beta);`
        # is a reference, not a call site.
        found = scan_calls(["int x = alpha(", "    beta);"], 1, 2)
        self.assertEqual(found, {"alpha"})
        found = scan_calls(["return beta(x);"], 1, 1)
        self.assertEqual(found, {"beta"})


class TestBuildCallEdges(unittest.TestCase):
    def test_ffi_bridge_zig_wrapper_to_c_export(self):
        # THE #2085 edge: src/cuda_bridge.zig:ensureLayerAsyncDev → the C
        # export rhesadox_cuda_ensure_layer_async_dev — resolution is the
        # globally-unique exact name (the ABI is the name).
        with _Tree() as root:
            edges = build_call_edges(_symbols(root), root)
            self.assertIn(
                ("src/cuda_bridge.zig:ensureLayerAsyncDev",
                 "cuda/expert_cache.cu:rhesadox_cuda_ensure_layer_async_dev"),
                edges)

    def test_cuda_calls_c_export_same_component(self):
        with _Tree() as root:
            edges = build_call_edges(_symbols(root), root)
            self.assertIn(
                ("cuda/expert_cache.cu:rhesadox_cuda_ensure_layer_async_dev",
                 "c/recycle.c:rhesadox_rec_pick_victim"),
                edges)

    def test_ambiguous_name_no_edge(self):
        # `helper()` from src/ambiguous.zig: defined once globally but NOT
        # in the caller's file... helper.zig defines it once — unique → edge.
        # The precision case is TWO definitions, none in the caller's file.
        with _Tree() as root:
            _mk(root, "src/helper2.zig", "pub fn helper() void {}\n")
            syms = _symbols(root)
            syms.append({"file": "src/helper2.zig", "name": "helper",
                         "kind": "fn", "line": 1, "line_end": 1,
                         "signature": "fn helper"})
            edges = build_call_edges(syms, root)
            self.assertNotIn(("src/ambiguous.zig:caller", "src/helper.zig:helper"),
                             edges)
            self.assertNotIn(("src/ambiguous.zig:caller", "src/helper2.zig:helper"),
                             edges)

    def test_same_file_beats_global(self):
        # a call to `tick` where the caller's file defines its own tick:
        # same-file definition wins even when another file also defines one.
        with _Tree() as root:
            _mk(root, "src/tick.zig", "pub fn tick() void {}\n")
            _mk(root, "src/loop.zig", """\
                fn tick() void {}
                pub fn loopOnce() void { tick(); }
                """)
            syms = _symbols(root) + [
                {"file": "src/loop.zig", "name": "tick", "kind": "fn",
                 "line": 1, "line_end": 1, "signature": "fn tick"},
                {"file": "src/loop.zig", "name": "loopOnce", "kind": "fn",
                 "line": 2, "line_end": 2, "signature": "fn loopOnce"},
            ]
            edges = build_call_edges(syms, root)
            self.assertIn(("src/loop.zig:loopOnce", "src/loop.zig:tick"), edges)
            self.assertNotIn(("src/loop.zig:loopOnce", "src/tick.zig:tick"), edges)

    def test_deterministic_order(self):
        with _Tree() as root:
            e1 = build_call_edges(_symbols(root), root)
            e2 = build_call_edges(_symbols(root), root)
            self.assertEqual(e1, e2)
            self.assertEqual(e1, sorted(e1))


class TestComputeAndStore(unittest.TestCase):
    def test_store_rows_meta_and_hash_stability(self):
        with _Tree() as root:
            db1, db2 = root / "a.db", root / "b.db"
            for db in (db1, db2):
                rig_db.write_db({"components": [], "external_packages": [],
                                 "entrypoints": [], "evidence": [],
                                 "test_definitions": [], "runners": []}, db)
                rig_db.add_symbols(db, _symbols(root))
                n = compute_and_store(db, root)
                self.assertGreaterEqual(n, 2)
            for db in (db1,):
                con = sqlite3.connect(db)
                rows = con.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
                src = con.execute(
                    "SELECT value FROM meta WHERE key='calls_source'").fetchone()
                con.close()
                self.assertEqual(rows, n)
                self.assertEqual(src, ("regex-v1",))
            self.assertEqual(rig_db.canonical_hash(db1), rig_db.canonical_hash(db2))


if __name__ == "__main__":
    unittest.main()
