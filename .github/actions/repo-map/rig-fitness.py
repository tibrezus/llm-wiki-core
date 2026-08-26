#!/usr/bin/env python3
"""rig-fitness.py — graph-fitness snapshot from a rig.db.

Usage:
    rig-fitness.py <rig.db>              # Markdown (## Graph Fitness)
    rig-fitness.py <rig.db> --json       # machine payload (delta diffs)

Markdown is appended to the CI registry (Architecture.md appendix) by the
arch pipeline — one immutable snapshot per SHA, so consecutive pages diff
into the modularity trend (radiator). The *gate* (severe duplication →
error) lives in scripts/arch/rig-compliance.py; both share rig/fitness.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rig.fitness import fitness_snapshot, render_markdown  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic graph-fitness snapshot from a rig.db")
    parser.add_argument("rig_db", help="Path to rig.db")
    parser.add_argument("--json", action="store_true",
                        help="Emit the machine payload instead of Markdown")
    args = parser.parse_args()

    db = Path(args.rig_db)
    if not db.exists():
        print(f"error: {db} not found", file=sys.stderr)
        return 1

    snapshot = fitness_snapshot(db)
    if args.json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        print(render_markdown(snapshot), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
