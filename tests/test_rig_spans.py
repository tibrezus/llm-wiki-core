"""Tests for symbol span extraction (symbols.line_end).

Spans power two consumers: rig impact maps diff hunks → symbols via line
ranges, and the clone detector slices symbol bodies without re-parsing
language syntax. The canonical `extract_export_rows` shape (line, sig)
must stay byte-identical — model.c4 golden parity depends on it.
"""

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ACTION_DIR = Path(__file__).resolve().parent.parent / ".github" / "actions" / "repo-map"
sys.path.insert(0, str(ACTION_DIR))

from rig.symbols import (  # noqa: E402
    extract_export_rows,
    extract_export_spans,
)


def _spans(src: str, lang: str) -> list[tuple[int, int, str]]:
    with tempfile.NamedTemporaryFile("w", suffix=".src", delete=False) as f:
        f.write(textwrap.dedent(src))
        path = Path(f.name)
    try:
        return extract_export_spans(path, lang)
    finally:
        path.unlink()


class TestPythonSpans(unittest.TestCase):
    def test_def_body_ends_before_next_def(self):
        spans = _spans("""\
            import os


            def alpha(x):
                y = x + 1

                return helper(y)


            def beta():
                pass
            """, "python")
        self.assertEqual(spans[0][0], 4)          # def alpha
        self.assertEqual(spans[0][1], 7)          # return helper(y)
        self.assertEqual(spans[1][0], 10)         # def beta (blank lines skipped)
        self.assertEqual(spans[1][1], 11)

    def test_one_liner_ends_at_itself(self):
        spans = _spans("def f(): pass\n", "python")
        self.assertEqual(spans, [(1, 1, "def f")])

    def test_class_ends_at_last_method_line(self):
        spans = _spans("""\
            class Widget:
                def a(self):
                    return 1

                def b(self):
                    return 2
            """, "python")
        self.assertEqual(spans, [(1, 6, "class Widget")])


class TestGoSpans(unittest.TestCase):
    def test_func_block(self):
        spans = _spans("""\
            package pkg

            func Run(x int) int {
                if x > 0 {
                    return x
                }
                return 0
            }
            """, "go")
        self.assertEqual(spans, [(3, 8, "func Run")])

    def test_var_scalar_and_type_struct(self):
        spans = _spans("""\
            package pkg

            type Config struct {
                Name string
            }

            var Limit = 10
            """, "go")
        self.assertEqual(spans[0], (3, 5, "type Config"))
        self.assertEqual(spans[1], (7, 7, "Limit"))


class TestZigSpans(unittest.TestCase):
    def test_pub_fn_braces(self):
        spans = _spans("""\
            const std = @import("std");

            pub fn run(x: u32) u32 {
                if (x > 0) {
                    return x;
                }
                return 0;
            }
            """, "zig")
        self.assertEqual(spans, [(3, 8, "fn run")])

    def test_pub_const_struct_vs_scalar(self):
        spans = _spans("""\
            pub const Config = struct {
                name: []const u8,
            };

            pub const VERSION = 3;
            """, "zig")
        self.assertEqual(spans[0], (1, 3, "type Config"))
        self.assertEqual(spans[1], (5, 5, "VERSION"))


class TestCSpans(unittest.TestCase):
    def test_prototype_vs_definition(self):
        spans = _spans("""\
            int proto(int x);

            int real(int x)
            {
                return x + 1;
            }
            """, "c")
        self.assertEqual(spans[0], (1, 1, "fn proto"))
        self.assertEqual(spans[1], (3, 6, "fn real"))


class TestParityShape(unittest.TestCase):
    def test_export_rows_stays_two_tuple(self):
        src = "def alpha(x):\n    return x\n"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(src)
            path = Path(f.name)
        try:
            rows = extract_export_rows(path, "python")
        finally:
            path.unlink()
        self.assertEqual(rows, [(1, "def alpha")])
        self.assertTrue(all(isinstance(r, tuple) and len(r) == 2 for r in rows))


if __name__ == "__main__":
    unittest.main()
