"""Tests for near-clone detection (rig/clones.py).

Invariants: detection of a planted near-duplicate, rejection of
dissimilar bodies, determinism (identical input → identical similar
table), and rerun idempotence.
"""

import sqlite3
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ACTION_DIR = Path(__file__).resolve().parent.parent / ".github" / "actions" / "repo-map"
sys.path.insert(0, str(ACTION_DIR))

from rig import db as rig_db  # noqa: E402
from rig.clones import compute_and_store  # noqa: E402


def _clone_body(name: str, token: str) -> str:
    """A 12-line function body; `token` is the only difference between twins."""
    return textwrap.dedent(f"""\
        def {name}(items, limit):
            total = 0
            count = 0
            for item in items:
                if item.{token}:
                    total += item.value
                    count += 1
                if count >= limit:
                    break
            return total, count
        """)


def _dissimilar_body(name: str) -> str:
    return textwrap.dedent(f"""\
        def {name}(cfg):
            with open(cfg.path, "rb") as fh:
                head = fh.read(8)
            if not head:
                raise ValueError("empty")
            return head.hex()
        """)


def _make_repo(root: Path, bodies: dict[str, str]) -> None:
    for fname, body in bodies.items():
        (root / fname).write_text(body)


def _rig(components: list[dict]) -> dict:
    return {
        "schema_version": "rig-1.0",
        "repository": {"name": "t", "ref": "r", "language": "python",
                       "build_system": "pip",
                       "generated_at": "2026-01-01T00:00:00Z",
                       "generator": "test"},
        "evidence": [], "components": components, "aggregators": [],
        "runners": [], "test_definitions": [], "external_packages": [],
        "entrypoints": [],
    }


def _component(cid: str, name: str, files: list[str]) -> dict:
    return {"id": cid, "name": name, "type": "library",
            "programming_language": "python", "source_files": files,
            "depends_on_ids": [], "external_packages_ids": [],
            "evidence_ids": [], "artifacts": []}


def _build_db(root: Path, files: dict[str, str]) -> Path:
    db = root / "rig.db"
    comps = [_component(f"comp-{i+1}", f"c{i+1}", [f])
             for i, f in enumerate(files)]
    rig_db.write_db(_rig(comps), db)
    rig_db.add_files(db, [{"path": f, "component_id": f"comp-{i+1}",
                           "language": "python"}
                          for i, f in enumerate(files)])
    from rig.symbols import extract_export_spans
    syms = []
    for f, body in files.items():
        for line, end, sig in extract_export_spans(root / f, "python"):
            kind, _, name = sig.partition(" ")
            syms.append({"file": f, "name": name, "kind": kind,
                         "line": line, "line_end": end, "signature": sig})
    rig_db.add_symbols(db, syms)
    return db


class TestCloneDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_near_duplicate_detected_cross_component(self):
        files = {
            "a.py": _clone_body("alpha", "kind"),
            "b.py": _clone_body("beta", "kind"),
            "c.py": _dissimilar_body("gamma"),
        }
        _make_repo(self.root, files)
        db = _build_db(self.root, files)
        n = compute_and_store(db, self.root)
        con = sqlite3.connect(db)
        rows = con.execute("SELECT src, dst, jaccard, scope FROM similar").fetchall()
        con.close()
        self.assertEqual(n, len(rows))
        self.assertEqual(len(rows), 1)
        src, dst, jac, scope = rows[0]
        self.assertTrue({src, dst} == {"a.py:alpha", "b.py:beta"})
        self.assertGreaterEqual(jac, 0.80)
        self.assertEqual(scope, "cross-component")

    def test_dissimilar_bodies_not_flagged(self):
        files = {"a.py": _dissimilar_body("alpha"),
                 "b.py": _dissimilar_body("beta")}
        _make_repo(self.root, files)
        db = _build_db(self.root, files)
        n = compute_and_store(db, self.root)
        self.assertEqual(n, 0)

    def test_short_bodies_skipped(self):
        files = {"a.py": "def alpha():\n    return 1\n",
                 "b.py": "def beta():\n    return 1\n"}
        _make_repo(self.root, files)
        db = _build_db(self.root, files)
        self.assertEqual(compute_and_store(db, self.root), 0)

    def test_deterministic_and_idempotent(self):
        files = {"a.py": _clone_body("alpha", "kind"),
                 "b.py": _clone_body("beta", "kind"),
                 "c.py": _clone_body("gamma", "kind")}
        _make_repo(self.root, files)
        db = _build_db(self.root, files)
        compute_and_store(db, self.root)
        con = sqlite3.connect(db)
        first = con.execute("SELECT * FROM similar ORDER BY src, dst").fetchall()
        con.close()
        # rerun on the same db: INSERT OR IGNORE → no growth, same content
        compute_and_store(db, self.root)
        con = sqlite3.connect(db)
        second = con.execute("SELECT * FROM similar ORDER BY src, dst").fetchall()
        con.close()
        self.assertEqual(first, second)
        # rebuild from scratch → identical table (canonical-hash stability)
        db2 = _build_db(self.root, files)
        compute_and_store(db2, self.root)
        con = sqlite3.connect(db2)
        third = con.execute("SELECT * FROM similar ORDER BY src, dst").fetchall()
        con.close()
        self.assertEqual(first, third)


if __name__ == "__main__":
    unittest.main()
