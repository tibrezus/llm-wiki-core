"""Tests for check-repo-size.sh — the binary/LFS bloat guard.

The guard protects against the failure mode that bloated a real wiki instance:
a ~3 MB SQLite file committed 222 times (~660 MB of history). Git cannot
forget, so the guard runs in CI and locally before large binaries enter.

Contract:
  - A tracked binary > LARGE_KB that is NOT routed to LFS (via .gitattributes
    `filter=lfs`) fails.
  - The same file WITH an LFS attribute passes.
  - Any file above HARD_MB fails regardless of LFS (upper bound on even LFS).
  - Large *text* files pass (log.md-style append-only files delta-compress).
  - In BASE_REF mode only files added/modified by the diff are inspected.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-repo-size.sh"


class RepoSizeGuardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._git("init", "-q")
        # Replicate the instance layout: <root>/.llm-wiki/scripts/<script>
        scripts_dir = self.root / ".llm-wiki" / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "check-repo-size.sh").write_bytes(SCRIPT.read_bytes())
        self._write(".gitignore", "node_modules/\n")
        self._commit("init", add=["."])

    def tearDown(self):
        self._tmp.cleanup()

    # -- helpers ------------------------------------------------------------
    def _git(self, *args, check=True):
        return subprocess.run(
            ["git", "-c", "user.email=test@local", "-c", "user.name=test",
             "-c", "commit.gpgsign=false", *args],
            cwd=self.root, capture_output=True, text=True, check=check,
        )

    def _write(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)

    def _commit(self, message, add=None):
        if add:
            self._git("add", *add)
        else:
            self._git("add", "-A")
        self._git("commit", "-q", "-m", message, "--allow-empty")

    def _run(self, **env):
        import os
        full_env = dict(os.environ)
        full_env.pop("BASE_REF", None)
        full_env.update({k: str(v) for k, v in env.items()})
        return subprocess.run(
            ["bash", ".llm-wiki/scripts/check-repo-size.sh"],
            cwd=self.root, capture_output=True, text=True, env=full_env,
        )

    @staticmethod
    def _binary(kb):
        # 0x00-heavy payload: guaranteed binary by every definition.
        return b"\x00\x01\x02\x03" * (kb * 256)

    # -- tests ----------------------------------------------------------------
    def test_large_non_lfs_binary_fails(self):
        self._write("blob.bin", self._binary(600))
        self._commit("add blob")
        r = self._run()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("blob.bin", r.stdout)
        self.assertIn("not LFS-tracked", r.stdout)

    def test_large_lfs_binary_passes(self):
        self._write(".gitattributes", "*.bin filter=lfs diff=lfs merge=lfs -text\n")
        self._write("blob.bin", self._binary(600))
        self._commit("add lfs blob")
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK (LFS)", r.stdout)

    def test_hard_ceiling_applies_even_to_lfs(self):
        self._write(".gitattributes", "*.bin filter=lfs diff=lfs merge=lfs -text\n")
        self._write("big.bin", self._binary(1200))
        self._commit("add big lfs blob")
        r = self._run(HARD_MB=1)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("HARD_MB", r.stdout)

    def test_large_text_file_passes(self):
        self._write("big.txt", "hello world line\n" * 60000)  # ~1 MB, no NULs
        self._commit("add big text")
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_small_binary_passes(self):
        self._write("small.bin", self._binary(4))  # 4 KB
        self._commit("add small blob")
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_base_ref_mode_flags_only_new_files(self):
        self._commit("marker")
        self._write("new.dat", self._binary(600))
        self._commit("add 600KB non-LFS .dat")
        r = self._run(BASE_REF="HEAD~1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("new.dat", r.stdout)
        self.assertIn("Mode: diff against HEAD~1", r.stdout)

    def test_base_ref_mode_passes_clean_diff(self):
        self._commit("marker")
        self._write("page.md", "# text only\n")
        self._commit("add text")
        r = self._run(BASE_REF="HEAD~1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_base_ref_empty_diff_short_circuits(self):
        # A PR that only touches e.g. log.md must not re-inspect the whole
        # tree (pre-existing legacy blobs would false-positive forever).
        r = self._run(BASE_REF="HEAD")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no files added or modified", r.stdout)
        self.assertNotIn("Mode: whole tracked tree", r.stdout)


if __name__ == "__main__":
    unittest.main()