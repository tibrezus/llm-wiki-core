#!/usr/bin/env python3
"""Unit tests for validate-mermaid.py's browser-unavailable skip path.

The skip path (no launchable chrome) must stay a warning with exit 0 — an
infrastructure gap is not a diagram error (rezuscloud/llm-wiki#15) — but it
must now carry the diagnosis: which chrome binary was found (or NOT FOUND)
and the probe's actual failure line, so runner-image drift is legible from
one CI glance instead of a bare "system libs missing" guess.
"""

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "validate-mermaid.py"

# Hyphenated script name — load by path.
_spec = importlib.util.spec_from_file_location("validate_mermaid", SCRIPT)
validate_mermaid = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate_mermaid)


class _FakeCompleted:
    def __init__(self, returncode=0, stderr="", stdout=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


class TestSkipWarning(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.wiki = Path(self._tmp.name)
        # Isolate HOME: find_chrome() scans ~/.cache/puppeteer — a dev machine
        # with a real cache would otherwise leak a found binary into tests.
        self._env_patcher = mock.patch.dict(os.environ, {"HOME": self._tmp.name})
        self._env_patcher.start()
        (self.wiki / "page.md").write_text("```mermaid\ngraph TD\n  A --> B\n```\n")

    def tearDown(self):
        self._env_patcher.stop()
        self._tmp.cleanup()

    def _run_main(self, fake_run):
        """Run main() with argv/subprocess patched; return (exit_code, stdout)."""
        out = io.StringIO()
        argv = ["validate-mermaid.py", str(self.wiki)]
        with mock.patch.object(validate_mermaid.sys, "argv", argv), \
             mock.patch.object(validate_mermaid.subprocess, "run", side_effect=fake_run):
            try:
                with contextlib.redirect_stdout(out):
                    validate_mermaid.main()
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()

    def test_no_chrome_probe_fails_says_not_found_and_carries_probe_error(self):
        # which() fails for every system chromium name (returncode 1), mmdc
        # probe fails with a library-load error line.
        def fake_run(cmd, **_kw):
            if cmd[0] == "which":
                return _FakeCompleted(returncode=1)
            return _FakeCompleted(
                returncode=1,
                stderr="/home/runner/.cache/puppeteer/chrome/chrome: "
                       "error while loading shared libraries: libasound2: cannot open",
            )

        code, out = self._run_main(fake_run)
        self.assertEqual(code, 0, "skip must stay a warning (exit 0), not a failure")
        self.assertIn("NOT FOUND", out)
        self.assertIn("error while loading shared libraries", out)
        self.assertIn("infrastructure issue", out)

    def test_chrome_found_but_probe_fails_names_the_binary(self):
        # PUPPETEER_EXECUTABLE_PATH points at a (fake) binary file, the mmdc
        # probe still fails — the warning must name the binary it tried.
        fake_chrome = self.wiki / "fake-chrome"
        fake_chrome.write_text("#!/bin/sh\nexit 1\n")
        env_patch = {"PUPPETEER_EXECUTABLE_PATH": str(fake_chrome)}

        def fake_run(cmd, **_kw):
            if cmd[0] == "which":
                return _FakeCompleted(returncode=1)
            return _FakeCompleted(returncode=1, stderr="Host system is missing dependencies")

        with mock.patch.dict(os.environ, env_patch):
            code, out = self._run_main(fake_run)
        self.assertEqual(code, 0)
        self.assertIn("fake-chrome", out)
        self.assertIn("Host system is missing dependencies", out)

    def test_probe_success_runs_the_real_check_without_warning(self):
        # Probe passes and every block renders: no skip warning, exit 0.
        def fake_run(cmd, **_kw):
            return _FakeCompleted(returncode=0)

        code, out = self._run_main(fake_run)
        self.assertEqual(code, 0)
        self.assertNotIn("WARNING", out)


if __name__ == "__main__":
    unittest.main()
