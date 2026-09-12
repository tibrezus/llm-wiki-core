#!/usr/bin/env python3
"""Unit tests for the zig export-symbol extraction (rig/symbols.py).

Focus: the re-export alias rule (llm-wiki-core#4) — a `pub const` whose
RHS is a bare @import re-publishes an existing symbol and must not count
as a declaration (it created phantom spread-3 duplication on rhesadox's
one-safetensors-reader consolidation). Real declarations keep extracting.
"""

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_MAP = Path(__file__).resolve().parent.parent / ".github" / "actions" / "repo-map"
sys.path.insert(0, str(REPO_MAP))

from rig.symbols import (  # noqa: E402
    _MAX_EXPORTS,
    _extract_zig_export_spans,
    extract_export_rows,
    extract_export_spans,
)


class TestZigReexportAlias(unittest.TestCase):
    def _names(self, src: str) -> list[str]:
        return [sig.partition(" ")[2] or sig
                for _, _, sig in _extract_zig_export_spans(src)]

    def test_accessor_alias_skipped(self):
        # the rhesadox #4 case: StDtype re-exported by both converter mains
        src = 'pub const StDtype = @import("safetensors").StDtype;\n'
        self.assertEqual(self._names(src), [])

    def test_module_alias_skipped(self):
        src = 'pub const io = @import("io.zig");\n'
        self.assertEqual(self._names(src), [])

    def test_star_deref_alias_skipped(self):
        src = 'pub const http = @import("serve/http.zig").*;\n'
        self.assertEqual(self._names(src), [])

    def test_spaced_alias_skipped(self):
        src = 'pub const  Tensor  =  @import( "model/tensor.zig" ) . Tensor ;\n'
        self.assertEqual(self._names(src), [])

    def test_real_const_survives(self):
        src = (
            "pub const MAX_SHARDS = 48;\n"
            "pub const Header = struct { magic: [4]u8 };\n"
            "pub const Gguf = @This();\n"
        )
        self.assertEqual(self._names(src), ["MAX_SHARDS", "Header", "Gguf"])

    def test_import_with_call_is_not_alias(self):
        # RHS uses the import (a function call) — a real declaration
        src = 'pub const emit = @import("emit.zig").emitJson;\npub const x = foo(1);\n'
        names = self._names(src)
        self.assertIn("x", names)

    def test_alias_with_trailing_use_not_swallowed(self):
        # import + extra expression on the line — conservative: not the
        # bare one-liner idiom, still extracted
        src = 'pub const b = @import("a.zig").a + 1;\n'
        self.assertEqual(self._names(src), ["b"])

    def test_non_pub_const_unaffected(self):
        src = 'const StDtype = @import("safetensors").StDtype;\n'
        self.assertEqual(self._names(src), [])


class TestDisplayCapVsQuerySurface(unittest.TestCase):
    """The _MAX_EXPORTS cap exists for model.c4 display only; rig.db's symbol
    table must be complete (llm-wiki-core#17 — the #2085 review's decisive
    export sat past the cap in a 101-function file, invisible to the graph)."""

    def _write(self, root: Path, rel: str, src: str) -> Path:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(src))
        return p

    def test_rows_capped_for_display_spans_uncapped_for_db(self):
        with tempfile.TemporaryDirectory() as td:
            fns = "\n".join(f"int fn_{i}(void) {{ return {i}; }}" for i in range(30))
            path = self._write(Path(td), "big.c", fns + "\n")
            rows = extract_export_rows(path, "c")
            spans = extract_export_spans(path, "c", cap=None)
            self.assertEqual(len(rows), _MAX_EXPORTS)      # display cap holds
            self.assertEqual(len(spans), 30)               # db table complete

    def test_decisive_export_beyond_cap_is_extracted(self):
        # the #2085 shape: many functions first, the important one last
        with tempfile.TemporaryDirectory() as td:
            body = "\n".join(f"static void pad_{i}(void) {{}}" for i in range(25))
            path = self._write(Path(td), "expert.c", body + (
                "\nextern \"C\" int rhesadox_cuda_ensure_layer_async_dev("
                "int device) { return device; }\n"))
            spans = extract_export_spans(path, "cuda", cap=None)
            names = [sig.partition(" ")[2] for _, _, sig in spans]
            self.assertIn("rhesadox_cuda_ensure_layer_async_dev", names)


if __name__ == "__main__":
    unittest.main()
