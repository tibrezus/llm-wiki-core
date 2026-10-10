"""Tests for generate_gitattributes — the shipped LFS starter set.

The .gitattributes template is the *declaration* layer of the binary-bloat
defense (check-repo-size.sh is the *enforcement* layer). These tests pin the
properties that make the declaration safe:

  1. Every non-comment line routes to LFS (filter=lfs ... -text).
  2. Coverage of the realistic wiki binary classes (db, pdf, images, archives,
     model weights, media, executables, fonts, profiler artifacts).
  3. Text formats are NOT routed: svg/json/csv/ipynb/lock/code delta-compress
     and belong in plain git.
  4. No conflicting duplicates of the same pattern.
"""

import subprocess
import unittest


REPO = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True, check=True,
).stdout.strip()


def generate():
    """Run generate_gitattributes into a temp dir, return its content."""
    script = (
        f'source "{REPO}/scripts/lib/generate.sh"\n'
        'generate_gitattributes "$1"\n'
    )
    r = subprocess.run(
        ["bash", "-c", script, "generate", "/tmp"],
        capture_output=True, text=True, check=True,
    )
    with open("/tmp/.gitattributes") as f:
        return f.read()


class GenerateGitattributesTest(unittest.TestCase):
    def setUp(self):
        self.content = generate()
        # Every line that declares a pattern (skip comments/blank).
        self.lines = [
            line for line in self.content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def test_every_pattern_routes_to_lfs(self):
        self.assertGreater(len(self.lines), 50)
        for line in self.lines:
            self.assertRegex(
                line, r"^\*\.[A-Za-z0-9.-]+\s+filter=lfs diff=lfs merge=lfs -text$",
                msg=f"bad pattern line: {line!r}")

    def test_covers_realistic_wiki_binary_classes(self):
        for ext in (".db", ".sqlite3", ".pdf", ".png", ".jpg", ".zip", ".gz",
                    ".parquet", ".onnx", ".safetensors", ".mp4", ".so",
                    ".woff2", ".nsys-rep", ".docx", ".7z"):
            self.assertIn(f"*{ext} ", self.content, msg=f"missing *{ext}")

    def test_text_formats_not_routed(self):
        for ext in (".svg", ".json", ".jsonl", ".csv", ".ipynb", ".md",
                    ".yaml", ".yml", ".c4", ".lock"):
            self.assertNotIn(f"*{ext} ", self.content,
                             msg=f"*{ext} must stay in plain git")

    def test_no_duplicate_patterns(self):
        patterns = [line.split()[0] for line in self.lines]
        self.assertEqual(len(patterns), len(set(patterns)))

    def test_nul_heavy_extensions_all_binary(self):
        # Sanity: every routed extension is one git treats as opaque content;
        # a text format slipping in here would silently move diffs to LFS.
        known_text = {".md", ".txt", ".html", ".xml", ".svg", ".json", ".csv"}
        for line in self.lines:
            ext = line.split()[0][1:]
            self.assertNotIn(ext, known_text, msg=f"*{ext} is a text format")


if __name__ == "__main__":
    unittest.main()