#!/usr/bin/env python3
"""Unit tests for the zig export-symbol extraction (rig/symbols.py).

Focus: the re-export alias rule (llm-wiki-core#4) — a `pub const` whose
RHS is a bare @import re-publishes an existing symbol and must not count
as a declaration (it created phantom spread-3 duplication on rhesadox's
one-safetensors-reader consolidation). Real declarations keep extracting.
"""

import sys
import unittest
from pathlib import Path

REPO_MAP = Path(__file__).resolve().parent.parent / ".github" / "actions" / "repo-map"
sys.path.insert(0, str(REPO_MAP))

from rig.symbols import _extract_zig_export_spans  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
