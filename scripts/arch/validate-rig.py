#!/usr/bin/env python3
"""Validate a fetched RIG JSON against the module's schema.

Usage: validate-rig.py <rig.db | rig.json>

rig.db (canonical SQLite artifact) is loaded via the rig package's
roundtrip reader; rig.json (legacy/compat) is loaded directly. Both are
checked against the same schema.

Exits 0 if valid, 1 if invalid. Errors are printed to stderr.
"""

import json
import sys
from pathlib import Path

_ACTION_DIR = (Path(__file__).resolve().parent.parent.parent /
               ".github" / "actions" / "repo-map")
sys.path.insert(0, str(_ACTION_DIR))

_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "schemas" / "repo-map.schema.yaml"


def _load_schema():
    import yaml
    with open(_SCHEMA_PATH) as f:
        return yaml.safe_load(f)


def validate_rig(rig_path):
    errors = []
    rig_path = Path(rig_path)
    try:
        if rig_path.suffix == ".db":
            from rig.db import read_db
            rig = read_db(rig_path)
        else:
            with open(rig_path) as f:
                rig = json.load(f)
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]
    except Exception as e:
        return [f"Cannot load RIG: {e}"]

    schema = _load_schema()

    try:
        import jsonschema
        jsonschema.validate(rig, schema)
    except ImportError:
        errors = _validate_manual(rig, schema)
        return errors
    except jsonschema.ValidationError as e:
        path = "/".join(str(p) for p in e.absolute_path) or "(root)"
        return [f"{e.message} (at {path})"]

    # Cross-reference check: all depends_on_ids / covers_ids / external_packages_ids
    # must resolve to an existing node.
    all_ids = set()
    for key in ("components", "aggregators", "runners", "test_definitions", "external_packages"):
        for node in rig.get(key, []):
            if "id" in node:
                all_ids.add(node["id"])

    # Duplicate ID check (paper: rig_validator._validate_duplicate_node_ids)
    id_counts: dict[str, int] = {}
    for key in ("components", "aggregators", "runners", "test_definitions", "external_packages"):
        for node in rig.get(key, []):
            nid = node.get("id")
            if nid:
                id_counts[nid] = id_counts.get(nid, 0) + 1
    for nid, count in id_counts.items():
        if count > 1:
            errors.append(f"Duplicate node ID: '{nid}' used by {count} nodes")

    for comp in rig.get("components", []):
        for ref_key in ("depends_on_ids", "external_packages_ids"):
            for ref in comp.get(ref_key, []):
                if ref not in all_ids:
                    errors.append(f"Dangling reference: component '{comp.get('name','?')}'.{ref_key} -> '{ref}' (not found)")
    for agg in rig.get("aggregators", []):
        for ref in agg.get("depends_on_ids", []):
            if ref not in all_ids:
                errors.append(f"Dangling reference: aggregator '{agg.get('name','?')}'.depends_on_ids -> '{ref}'")
    for test in rig.get("test_definitions", []):
        for ref in test.get("covers_ids", []):
            if ref not in all_ids:
                errors.append(f"Dangling reference: test '{test.get('name','?')}'.covers_ids -> '{ref}'")
    for ep in rig.get("entrypoints", []):
        if ep not in all_ids:
            errors.append(f"Dangling reference: entrypoints -> '{ep}' (not a known component)")

    # Circular dependency check (paper: rig_validator._validate_circular_dependencies)
    graph: dict[str, list[str]] = {}
    for key in ("components", "aggregators", "runners"):
        for node in rig.get(key, []):
            nid = node.get("id", node.get("name", ""))
            graph[nid] = node.get("depends_on_ids", [])

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    has_cycle = [False]

    def _dfs(node):
        color[node] = GRAY
        for neighbor in graph.get(node, []):
            if neighbor not in color:
                continue
            if color[neighbor] == GRAY:
                has_cycle[0] = True
                return
            if color[neighbor] == WHITE:
                _dfs(neighbor)
                if has_cycle[0]:
                    return
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            _dfs(node)
            if has_cycle[0]:
                break
    if has_cycle[0]:
        errors.append("Circular dependency detected in component graph")

    return errors


def _validate_manual(rig, schema):
    """Minimal fallback validation when jsonschema is not installed."""
    errors = []
    for field in schema.get("required", []):
        if field not in rig:
            errors.append(f"Missing required field: {field}")
    if "repository" in rig and not isinstance(rig["repository"], dict):
        errors.append("repository must be an object")
    if "components" in rig:
        if not isinstance(rig["components"], list):
            errors.append("components must be an array")
        elif len(rig["components"]) == 0:
            errors.append("components must not be empty")
    return errors


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: validate-rig.py <rig.json>", file=sys.stderr)
        sys.exit(1)
    errs = validate_rig(sys.argv[1])
    if errs:
        print("=== RIG Validation FAILED ===", file=sys.stderr)
        for e in errs:
            print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print("RIG validation passed.")
