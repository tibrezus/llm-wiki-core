#!/usr/bin/env python3
"""Unit tests for the RIG compliance auditor.

These tests create synthetic RIG fixtures (both compliant and deliberately
broken) and assert that rig-compliance.py produces correct verdicts. They run
deterministically in `npm run check` / pytest — no network, no external repos.

The fixtures exercise every check the paper (arXiv:2601.10112) mandates:
  - duplicate IDs
  - dangling references
  - circular dependencies
  - evidence backing
  - test definitions
  - component completeness
  - structural elements (aggregators, package managers, entrypoints)
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Make the scripts importable
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "arch"
sys.path.insert(0, str(SCRIPTS_DIR))

# The module filename uses hyphens, so we load it via importlib.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "rig_compliance", SCRIPTS_DIR / "rig-compliance.py"
)
rig_compliance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rig_compliance)


# ──────────────────────────────────────────────────────────────────
#  Fixture builders — each returns a RIG dict
# ──────────────────────────────────────────────────────────────────

def _base_rig():
    """A minimal but fully-compliant RIG (100% score expected)."""
    return {
        "schema_version": "rig-1.0",
        "repository": {"name": "test-repo", "ref": "main", "language": "go", "build_system": "go-modules"},
        "evidence": [
            {"id": "ev-1", "line": ["main.go:1"]},
            {"id": "ev-2", "line": ["lib.go:1"]},
            {"id": "ev-3", "line": ["main_test.go:1"]},
        ],
        "components": [
            {
                "id": "comp-1", "name": "app", "type": "executable",
                "programming_language": "go",
                "source_files": ["main.go"],
                "depends_on_ids": ["comp-2"],
                "external_packages_ids": ["pkg-1"],
                "evidence_ids": ["ev-1"],
            },
            {
                "id": "comp-2", "name": "lib", "type": "package_library",
                "programming_language": "go",
                "source_files": ["lib.go"],
                "depends_on_ids": [],
                "external_packages_ids": [],
                "evidence_ids": ["ev-2"],
            },
        ],
        "aggregators": [
            {"id": "agg-1", "name": "all", "depends_on_ids": ["comp-1"], "evidence_ids": ["ev-1"]},
        ],
        "runners": [],
        "test_definitions": [
            {
                "id": "test-1", "name": "TestApp",
                "covers_ids": ["comp-1"],
                "depends_on_ids": ["comp-1"],
                "source_files": ["main_test.go"],
                "evidence_ids": ["ev-3"],
            },
        ],
        "external_packages": [
            {
                "id": "pkg-1", "name": "github.com/stretchr/testify",
                "package_manager": {"name": "go-modules", "package_name": "github.com/stretchr/testify"},
            },
        ],
        "entrypoints": ["comp-1"],
    }


def _write_rig_to(rig: dict, path: Path) -> None:
    """Write a RIG dict to a rig.db at an explicit path."""
    _ACTION_DIR = Path(__file__).resolve().parent.parent / ".github" / "actions" / "repo-map"
    sys.path.insert(0, str(_ACTION_DIR))
    from rig import db as rig_db
    rig_db.write_db(rig, path)


def _write_rig(rig: dict) -> str:
    """Write a RIG dict to a temp rig.db and return the path."""
    _ACTION_DIR = Path(__file__).resolve().parent.parent / ".github" / "actions" / "repo-map"
    sys.path.insert(0, str(_ACTION_DIR))
    from rig import db as rig_db
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    rig_db.write_db(rig, Path(path))
    return path


# ──────────────────────────────────────────────────────────────────
#  Tests
# ──────────────────────────────────────────────────────────────────

class TestComplianceChecks(unittest.TestCase):
    """Test each check function individually."""

    def setUp(self):
        self.rig = _base_rig()

    # ── Correctness ──

    def test_duplicate_ids_pass(self):
        result = rig_compliance.check_duplicate_ids(self.rig)
        self.assertEqual(result.severity, "pass")
        self.assertEqual(result.score, 1.0)

    def test_duplicate_ids_fail(self):
        self.rig["components"][1]["id"] = "comp-1"  # duplicate!
        result = rig_compliance.check_duplicate_ids(self.rig)
        self.assertEqual(result.severity, "error")
        self.assertLess(result.score, 1.0)

    def test_dangling_refs_pass(self):
        result = rig_compliance.check_dangling_refs(self.rig)
        self.assertEqual(result.severity, "pass")
        self.assertEqual(result.score, 1.0)

    def test_dangling_refs_fail(self):
        self.rig["components"][0]["depends_on_ids"] = ["comp-nonexistent"]
        result = rig_compliance.check_dangling_refs(self.rig)
        self.assertEqual(result.severity, "error")

    def test_circular_deps_pass(self):
        result = rig_compliance.check_circular_deps(self.rig)
        self.assertEqual(result.severity, "pass")

    def test_circular_deps_fail(self):
        # comp-1 → comp-2 → comp-1 (cycle)
        self.rig["components"][0]["depends_on_ids"] = ["comp-2"]
        self.rig["components"][1]["depends_on_ids"] = ["comp-1"]
        result = rig_compliance.check_circular_deps(self.rig)
        self.assertEqual(result.severity, "error")
        self.assertEqual(result.score, 0.0)

    # ── Maintainability: symbol duplication (DRY) ──

    @staticmethod
    def _sym(name, comp, lang="zig", kind="fn"):
        return {"name": name, "kind": kind,
                "signature": f"{kind} {name}", "file": f"src/{comp}.zig",
                "component_id": comp, "component": comp, "language": lang}

    def test_symbol_duplication_pass_without_map(self):
        result = rig_compliance.check_symbol_duplication(self.rig)
        self.assertEqual(result.severity, "pass")
        self.assertIn("no symbol table", result.detail)

    def test_symbol_duplication_pass_clean(self):
        self.rig["_code_map"] = [
            self._sym("uniqueOne", "comp-1"),
            self._sym("uniqueTwo", "comp-2"),
        ]
        result = rig_compliance.check_symbol_duplication(self.rig)
        self.assertEqual(result.severity, "pass")
        self.assertEqual(result.score, 1.0)

    def test_symbol_duplication_two_components_warn(self):
        rows = [self._sym(f"unique{i}", "comp-1") for i in range(20)]
        rows += [self._sym("parseThing", "comp-1"),
                 self._sym("parseThing", "comp-2")]
        self.rig["_code_map"] = rows
        result = rig_compliance.check_symbol_duplication(self.rig)
        self.assertEqual(result.severity, "warn")
        self.assertIn("parseThing", result.detail)
        self.assertGreater(result.score, 0.9)  # debt visible, score barely hit

    def test_symbol_duplication_severe_errors(self):
        self.rig["_code_map"] = [
            self._sym("parseThing", "comp-1"),
            self._sym("parseThing", "comp-2"),
            self._sym("parseThing", "comp-3"),
        ]
        result = rig_compliance.check_symbol_duplication(self.rig)
        self.assertEqual(result.severity, "error")
        self.assertIn("SEVERE", result.detail)

    def test_symbol_duplication_filters(self):
        # blocked generic name in 3 components, builtin prefix in 2, a
        # cross-language pair, and Go-idiomatic per-package types — none
        # of them are findings
        self.rig["_code_map"] = [
            self._sym("main", "comp-1"), self._sym("main", "comp-2"),
            self._sym("main", "comp-3"),
            self._sym("__builtin_thing", "comp-1"),
            self._sym("__builtin_thing", "comp-2"),
            self._sym("parseThing", "comp-1", lang="zig"),
            self._sym("parseThing", "comp-2", lang="c"),
            self._sym("Event", "comp-1", lang="go", kind="type"),
            self._sym("Event", "comp-2", lang="go", kind="type"),
            self._sym("Event", "comp-3", lang="go", kind="type"),
            self._sym("Result", "comp-1", lang="go", kind="type"),
            self._sym("Result", "comp-2", lang="go", kind="type"),
            self._sym("Result", "comp-3", lang="go", kind="type"),
        ]
        result = rig_compliance.check_symbol_duplication(self.rig)
        self.assertEqual(result.severity, "pass")

    # ── Evidence ──

    def test_evidence_full(self):
        result = rig_compliance.check_evidence_coverage(self.rig)
        self.assertEqual(result.severity, "pass")
        self.assertEqual(result.score, 1.0)

    def test_evidence_missing(self):
        # Remove evidence from ALL nodes (components + aggregator + test)
        for key in ("components", "aggregators", "runners", "test_definitions"):
            for node in self.rig.get(key, []):
                node.pop("evidence_ids", None)
        result = rig_compliance.check_evidence_coverage(self.rig)
        self.assertEqual(result.severity, "warn")
        self.assertEqual(result.score, 0.0)

    def test_evidence_partial(self):
        # Remove evidence from one component only (1 of 4 nodes total)
        self.rig["components"][1].pop("evidence_ids", None)
        result = rig_compliance.check_evidence_coverage(self.rig)
        self.assertEqual(result.severity, "warn")
        self.assertAlmostEqual(result.score, 0.75, places=2)

    # ── Tests ──

    def test_test_coverage_full(self):
        result = rig_compliance.check_test_coverage(self.rig)
        self.assertEqual(result.severity, "pass")

    def test_test_coverage_none(self):
        self.rig["test_definitions"] = []
        result = rig_compliance.check_test_coverage(self.rig)
        self.assertEqual(result.severity, "warn")

    # ── Completeness ──

    def test_completeness_pass(self):
        result = rig_compliance.check_component_completeness(self.rig)
        self.assertEqual(result.severity, "pass")

    def test_completeness_empty_component(self):
        self.rig["components"][1]["source_files"] = []
        result = rig_compliance.check_component_completeness(self.rig)
        self.assertEqual(result.severity, "warn")

    # ── Structural ──

    def test_aggregators_present(self):
        result = rig_compliance.check_aggregators_runners(self.rig)
        self.assertEqual(result.severity, "pass")

    def test_aggregators_absent(self):
        self.rig["aggregators"] = []
        self.rig["runners"] = []
        result = rig_compliance.check_aggregators_runners(self.rig)
        self.assertEqual(result.severity, "warn")

    def test_package_managers_full(self):
        result = rig_compliance.check_external_package_managers(self.rig)
        self.assertEqual(result.severity, "pass")

    def test_package_managers_missing(self):
        self.rig["external_packages"][0]["package_manager"] = {}
        result = rig_compliance.check_external_package_managers(self.rig)
        self.assertEqual(result.severity, "warn")

    def test_entrypoints_complete(self):
        result = rig_compliance.check_entrypoints(self.rig)
        self.assertEqual(result.severity, "pass")

    def test_entrypoints_missing_executable(self):
        self.rig["entrypoints"] = []
        result = rig_compliance.check_entrypoints(self.rig)
        self.assertEqual(result.severity, "warn")


class TestScorecardIntegration(unittest.TestCase):
    """Test the full audit on the fixture file."""

    def test_perfect_rig_grade_a(self):
        path = _write_rig(_base_rig())
        card = rig_compliance.audit_rig(path)
        self.assertGreaterEqual(card.overall_score, 0.95)
        self.assertEqual(card.grade, "A")
        self.assertFalse(card.has_errors)
        os.unlink(path)

    def test_broken_rig_has_errors(self):
        rig = _base_rig()
        rig["components"][0]["depends_on_ids"] = ["ghost"]
        path = _write_rig(rig)
        card = rig_compliance.audit_rig(path)
        self.assertTrue(card.has_errors)
        os.unlink(path)

    def test_cli_single_file(self):
        """The CLI should exit 0 for a warnings-only RIG."""
        rig = _base_rig()
        # Remove evidence to create warnings without errors
        for c in rig["components"]:
            c.pop("evidence_ids", None)
        rig["test_definitions"] = []
        rig["aggregators"] = []
        path = _write_rig(rig)

        import subprocess
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "rig-compliance.py"), path],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, f"Expected exit 0, got {result.returncode}\n{result.stdout}")
        os.unlink(path)

    def test_cli_strict_mode(self):
        """--strict should exit 2 when score < 100%."""
        rig = _base_rig()
        for c in rig["components"]:
            c.pop("evidence_ids", None)
        path = _write_rig(rig)

        import subprocess
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "rig-compliance.py"), path, "--strict"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2, f"Expected exit 2, got {result.returncode}")
        os.unlink(path)

    def test_cli_all_mode(self):
        """--all should find multiple rig.db files."""
        import subprocess
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ("proj-a", "proj-b"):
                projdir = Path(tmpdir) / name
                projdir.mkdir()
                _write_rig_to(_base_rig(), projdir / "rig.db")

            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "rig-compliance.py"), "--all", tmpdir],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)
            # The fixture uses repository.name = "test-repo"
            self.assertIn("test-repo", result.stdout)


class TestEnhancedValidator(unittest.TestCase):
    """Test that validate-rig.py catches the new checks."""

    def test_validator_passes_good_rig(self):
        import subprocess
        path = _write_rig(_base_rig())
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "validate-rig.py"), path],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        os.unlink(path)

    def test_validator_catches_duplicate_ids(self):
        # write_db itself enforces UNIQUE component ids (IntegrityError);
        # the validator check is exercised through a legacy JSON file.
        import subprocess
        rig = _base_rig()
        rig["components"][1]["id"] = "comp-1"
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(rig, f)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "validate-rig.py"), path],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Duplicate", result.stderr)
        os.unlink(path)

    def test_validator_catches_circular_deps(self):
        import subprocess
        rig = _base_rig()
        rig["components"][0]["depends_on_ids"] = ["comp-2"]
        rig["components"][1]["depends_on_ids"] = ["comp-1"]
        path = _write_rig(rig)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "validate-rig.py"), path],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Circular", result.stderr)
        os.unlink(path)


if __name__ == "__main__":
    unittest.main()
