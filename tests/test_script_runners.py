#!/usr/bin/env python3
"""Unit tests for the .rig-runners script-runner manifest (llm-wiki-core#6).

The file-graph cannot see shell-script CI (GPU validation scripts, parity
probes, serve checks). The manifest declares them as first-class Runner nodes
with truthful evidence, so graph coverage stops claiming those components are
untested.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_MAP = Path(__file__).resolve().parent.parent / ".github" / "actions" / "repo-map"
sys.path.insert(0, str(REPO_MAP))

from rig.builder import RIGBuilder  # noqa: E402
from rig.model import Component  # noqa: E402

# emit-rig.py is a hyphenated script — load it by path.
_spec = importlib.util.spec_from_file_location(
    "emit_rig", REPO_MAP / "emit-rig.py")
emit_rig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(emit_rig)


def _builder_with_components(*names: str) -> RIGBuilder:
    b = RIGBuilder()
    for n in names:
        b.add_component(Component(
            name=n, type="static_library", programming_language="c",
            source_files=[f"{n}.c"]))
    return b


class TestScriptRunners(unittest.TestCase):
    def test_manifest_declares_runner_with_resolved_covers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".rig-runners.json").write_text(json.dumps({"runners": [{
                "name": "gpu-integration",
                "command": ["bash", "tools/gpu.sh"],
                "script": "tools/gpu.sh",
                "covers": ["cuda-backend", "c-kernels"],
            }]}))
            (root / "tools").mkdir()
            (root / "tools" / "gpu.sh").write_text("#!/bin/sh\n")
            b = _builder_with_components("cuda-backend", "c-kernels")
            emit_rig._add_script_runners(b, root)
            runners = [r for r in b.runners if r.name == "gpu-integration"]
            self.assertEqual(len(runners), 1)
            self.assertEqual(runners[0].arguments, ["bash", "tools/gpu.sh"])
            self.assertEqual(runners[0].depends_on, {"cuda-backend", "c-kernels"})
            self.assertTrue(runners[0].evidence[0].line[0].startswith("tools/gpu.sh:1"))

    def test_unknown_covers_are_skipped_with_warning(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".rig-runners.json").write_text(json.dumps({"runners": [{
                "name": "probe", "script": "probe.sh", "covers": ["cuda-backend", "nope"],
            }]}))
            (root / "probe.sh").write_text("#!/bin/sh\n")
            b = _builder_with_components("cuda-backend")
            emit_rig._add_script_runners(b, root)
            runner = next(r for r in b.runners if r.name == "probe")
            self.assertEqual(runner.depends_on, {"cuda-backend"})

    def test_missing_script_is_an_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".rig-runners.json").write_text(json.dumps({"runners": [{
                "name": "ghost", "script": "nope.sh", "covers": [],
            }]}))
            b = _builder_with_components()
            with self.assertRaises(SystemExit):
                emit_rig._add_script_runners(b, root)

    def test_node_name_collision_is_an_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".rig-runners.json").write_text(json.dumps({"runners": [{
                "name": "cuda-backend", "script": "dup.sh", "covers": [],
            }]}))
            (root / "dup.sh").write_text("#!/bin/sh\n")
            b = _builder_with_components("cuda-backend")
            with self.assertRaises(SystemExit):
                emit_rig._add_script_runners(b, root)

    def test_runner_without_name_or_script_is_an_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".rig-runners.json").write_text(json.dumps({"runners": [
                {"name": "no-script"}, {"script": "x.sh"}]}))
            b = _builder_with_components()
            with self.assertRaises(SystemExit):
                emit_rig._add_script_runners(b, root)

    def test_command_defaults_to_bash_script(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".rig-runners.json").write_text(json.dumps({"runners": [{
                "name": "serve", "script": "tools/serve-once.sh"}]}))
            (root / "tools").mkdir()
            (root / "tools" / "serve-once.sh").write_text("#!/bin/sh\n")
            b = _builder_with_components()
            emit_rig._add_script_runners(b, root)
            runner = next(r for r in b.runners if r.name == "serve")
            self.assertEqual(runner.arguments, ["bash", "tools/serve-once.sh"])

    def test_no_manifest_is_a_noop(self):
        with tempfile.TemporaryDirectory() as td:
            b = _builder_with_components("c-kernels")
            n = len(b.runners)
            emit_rig._add_script_runners(b, Path(td))
            self.assertEqual(len(b.runners), n)


if __name__ == "__main__":
    unittest.main()
