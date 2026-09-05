#!/usr/bin/env python3
"""Unit tests for the Zig extractor's import scanning (llm-wiki-core#3).

A doc comment that QUOTES an import (`/// see @import("miss").miss_policy`)
is documentation, not a dependency edge. #3: the raw-text regex created
phantom edges from prose, which surfaced as a false `compute <-> miss`
cycle in rhesadox's architecture graph and failed every arch publish.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_MAP = Path(__file__).resolve().parent.parent / ".github" / "actions" / "repo-map"
sys.path.insert(0, str(REPO_MAP))

from rig.extractors.zig import strip_zig_line_comments, ZigExtractor  # noqa: E402
from rig.builder import RIGBuilder  # noqa: E402


BUILD_ZIG = """\
const std = @import("std");
const a_mod = b.addModule("a", .{
    .root_source_file = b.path("src/a/root.zig"),
});
const b_mod = b.addModule("b", .{
    .root_source_file = b.path("src/b/root.zig"),
});
"""


class StripCommentsTest(unittest.TestCase):
    def test_plain_comment_removed(self):
        self.assertEqual(strip_zig_line_comments("x = 1; // @import(\"b\")\ny = 2;\n"),
                         "x = 1; \ny = 2;\n")

    def test_string_with_slashes_survives(self):
        line = 'const url = "https://x.test/a//b";\n'
        self.assertEqual(strip_zig_line_comments(line), line)

    def test_escaped_quote_then_comment(self):
        line = 'const s = "not \\" // a comment"; // real comment\n'
        self.assertEqual(strip_zig_line_comments(line), 'const s = "not \\" // a comment"; \n')

    def test_multiline_string_line_untouched(self):
        line = "    \\\\ data // not a comment\n"
        self.assertEqual(strip_zig_line_comments(line), line)


class PhantomEdgeTest(unittest.TestCase):
    def _extract(self, a_root: str):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src" / "a").mkdir(parents=True)
            (root / "src" / "b").mkdir(parents=True)
            (root / "build.zig").write_text(BUILD_ZIG)
            (root / "src" / "a" / "root.zig").write_text(a_root)
            (root / "src" / "b" / "root.zig").write_text("pub const x: u8 = 1;\n")
            # the extractor reads build.zig and resolves paths against CWD
            cwd = os.getcwd()
            os.chdir(root)
            try:
                builder = RIGBuilder()
                ZigExtractor().extract(builder)
            finally:
                os.chdir(cwd)
            return {c.name: c for c in builder.components}

    def test_doc_comment_mention_creates_no_edge(self):
        comps = self._extract(
            '/// The policy layer (the `b` module, @import("b").x) so all\n'
            "pub const y: u8 = 2;\n"
        )
        self.assertNotIn("b", comps["a"].depends_on)

    def test_real_import_creates_edge(self):
        comps = self._extract(
            'const b = @import("b");\npub const y: u8 = b.x;\n'
        )
        self.assertIn("b", comps["a"].depends_on)


if __name__ == "__main__":
    unittest.main()
