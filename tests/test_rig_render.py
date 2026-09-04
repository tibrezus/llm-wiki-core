#!/usr/bin/env python3
"""Unit tests for the architecture render pipeline.

Covers two fidelity defects (llm-wiki-core#1):

  1. Same-name components (e.g. a Zig executable and its same-named root
     module) must render with distinct display names — likec4's mermaid
     generator keys nodes by name, so identical names collapse distinct
     containers into one and their edges render as self-loops.
  2. StandaloneCExtractor must not re-group files already claimed by a
     build-system extractor into phantom twins (`c-sources` vs `c-kernels`);
     only the unclaimed remainder is emitted.
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_MAP = Path(__file__).resolve().parent.parent / ".github" / "actions" / "repo-map"
sys.path.insert(0, str(REPO_MAP))

from rig.builder import RIGBuilder  # noqa: E402
from rig.extractors.cmake import StandaloneCExtractor  # noqa: E402
from rig.model import Component, Evidence  # noqa: E402

# rig-to-c4.py is a hyphenated script — load it by path.
_spec = importlib.util.spec_from_file_location(
    "rig_to_c4", REPO_MAP / "rig-to-c4.py")
rig_to_c4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rig_to_c4)


def _two_rhesadox_rig() -> dict:
    """Minimal rig shaped like every Zig project: exe + same-named root module."""
    return {
        "repository": {"name": "zigproj", "build_system": "zig"},
        "components": [
            {
                "id": "comp-1", "name": "rhesadox", "type": "executable",
                "programming_language": "zig", "source_files": ["src/main.zig"],
                "depends_on_ids": ["comp-10"], "artifacts": [],
            },
            {
                "id": "comp-10", "name": "rhesadox", "type": "package_library",
                "programming_language": "zig", "source_files": ["src/lib.zig"],
                "depends_on_ids": [], "artifacts": [],
            },
        ],
        "test_definitions": [],
        "evidence": [],
        "entrypoints": [],
    }


class TestDisplayNameCollision(unittest.TestCase):
    def test_colliding_names_get_type_qualified(self):
        out = rig_to_c4.generate_c4(_two_rhesadox_rig(), source_dir=None)
        self.assertIn("container 'rhesadox (exe)'", out)
        self.assertIn("container 'rhesadox (lib)'", out)
        # No bare duplicated name remains as a container title.
        self.assertEqual(out.count("= container 'rhesadox' {"), 0)

    def test_edge_renders_between_two_distinct_nodes(self):
        out = rig_to_c4.generate_c4(_two_rhesadox_rig(), source_dir=None)
        # The exe→lib edge must connect two different idents — the regression
        # signature of the rendered self-loop.
        self.assertIn("rhesadoxExe -> rhesadoxLib 'imports'", out)
        self.assertNotRegex(out, r"^  (\w+) -> \1 'imports'", )

    def test_unique_names_stay_unqualified(self):
        rig = _two_rhesadox_rig()
        rig["components"][0]["name"] = "rhesadox-cli"
        out = rig_to_c4.generate_c4(rig, source_dir=None)
        self.assertIn("container 'rhesadox-cli'", out)
        self.assertIn("container 'rhesadox'", out)

    def test_depends_on_description_uses_display_names(self):
        out = rig_to_c4.generate_c4(_two_rhesadox_rig(), source_dir=None)
        self.assertIn("depends on: rhesadox (lib)", out)


class TestStandaloneCRemainder(unittest.TestCase):
    def _builder_with_claimed(self, claimed: list[str]) -> RIGBuilder:
        b = RIGBuilder()
        b.add_component(Component(
            name="c-kernels", type="static_library", programming_language="c",
            source_files=list(claimed),
            evidence=[Evidence(line=[f"{claimed[0]}:1"] if claimed else [])],
        ))
        return b

    def test_fully_claimed_language_emits_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "claimed.c").write_text("int f(void);\n")
            free = os.getcwd()
            os.chdir(td)
            try:
                b = self._builder_with_claimed(["claimed.c"])
                n_before = len(b.components)
                StandaloneCExtractor().extract(b)
                self.assertEqual(len(b.components), n_before)
            finally:
                os.chdir(free)

    def test_unclaimed_remainder_is_emitted(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "claimed.c").write_text("int f(void);\n")
            Path(td, "free.c").write_text("int g(void);\n")
            free = os.getcwd()
            os.chdir(td)
            try:
                b = self._builder_with_claimed(["claimed.c"])
                StandaloneCExtractor().extract(b)
                twins = [c for c in b.components if c.name == "c-sources"]
                self.assertEqual(len(twins), 1)
                self.assertEqual(twins[0].source_files, ["free.c"])
            finally:
                os.chdir(free)

    def test_standalone_project_without_build_system_emits_everything(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "solo.c").write_text("int f(void);\n")
            free = os.getcwd()
            os.chdir(td)
            try:
                b = RIGBuilder()  # nothing claimed — the genuine fallback case
                StandaloneCExtractor().extract(b)
                self.assertEqual([c.name for c in b.components], ["c-sources"])
                self.assertEqual(b.components[0].source_files, ["solo.c"])
            finally:
                os.chdir(free)


if __name__ == "__main__":
    unittest.main()
