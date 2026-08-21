#!/usr/bin/env python3
"""RIG Compliance Auditor — measures a RIG against the paper's standard.

The RIG standard (arXiv:2601.10112, github.com/Greenfuze/Spade) defines a
Repository Intelligence Graph as a graph of *evidence-backed* build and test
artifacts.  This script audits any RIG JSON against the six dimensions the
paper prescribes and produces a compliance scorecard.

Usage:
    rig-compliance.py <rig.db> [--strict]
    rig-compliance.py --all <dir-containing-raw/arch/*/>

Exit codes:
    0  — all checks pass (or warnings only)
    1  — at least one ERROR-level check failed
    2  --strict mode and any check is not 100%
"""

import sys
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any


# ──────────────────────────────────────────────────────────────────────
#  Data structures
# ──────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    name: str
    category: str
    severity: str  # "pass" | "warn" | "error"
    score: float   # 0.0–1.0
    detail: str = ""
    measured: int = 0
    total: int = 0


@dataclass
class Scorecard:
    rig_path: str
    repository: str = "?"
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def overall_score(self) -> float:
        if not self.checks:
            return 0.0
        weights = {"error": 3.0, "warn": 1.0, "pass": 0.0}
        # Weighted average: error-category checks weigh more
        total_weight = 0.0
        total_score = 0.0
        for c in self.checks:
            w = 1.0
            # Structural completeness checks are foundational
            if c.category == "structural":
                w = 2.0
            total_weight += w
            total_score += c.score * w
        return total_score / total_weight if total_weight else 0.0

    @property
    def grade(self) -> str:
        s = self.overall_score
        if s >= 0.95: return "A"
        if s >= 0.85: return "B"
        if s >= 0.70: return "C"
        if s >= 0.50: return "D"
        return "F"

    @property
    def has_errors(self) -> bool:
        return any(c.severity == "error" for c in self.checks)


# ──────────────────────────────────────────────────────────────────────
#  Individual checks (one per paper requirement)
# ──────────────────────────────────────────────────────────────────────

def _all_node_ids(rig: dict) -> set[str]:
    """Collect all node IDs across every node type."""
    ids: set[str] = set()
    for key in ("components", "aggregators", "runners", "test_definitions", "external_packages"):
        for node in rig.get(key, []):
            if "id" in node:
                ids.add(node["id"])
    return ids


def check_duplicate_ids(rig: dict) -> CheckResult:
    """Paper: all node IDs must be unique (rig_validator._validate_duplicate_node_ids)."""
    seen: dict[str, str] = {}  # id → first owner
    dupes: list[str] = []
    for key in ("components", "aggregators", "runners", "test_definitions", "external_packages"):
        for node in rig.get(key, []):
            nid = node.get("id")
            if nid is None:
                continue
            if nid in seen:
                dupes.append(nid)
            else:
                seen[nid] = f"{key}/{node.get('name', '?')}"
    total = len(seen) + len(dupes)
    unique = len(seen)
    score = unique / total if total else 1.0
    return CheckResult(
        name="Unique node IDs",
        category="correctness",
        severity="error" if dupes else "pass",
        score=score,
        measured=unique,
        total=total,
        detail=f"{len(dupes)} duplicate ID(s)" if dupes else "All IDs unique",
    )


def check_dangling_refs(rig: dict) -> CheckResult:
    """Paper: all depends_on_ids / covers_ids / external_packages_ids must resolve."""
    all_ids = _all_node_ids(rig)
    dangling = 0
    total_refs = 0
    broken: list[str] = []

    for comp in rig.get("components", []):
        for ref_key in ("depends_on_ids", "external_packages_ids"):
            for ref in comp.get(ref_key, []):
                total_refs += 1
                if ref not in all_ids:
                    dangling += 1
                    broken.append(f"{comp.get('name', '?')}.{ref_key} → {ref}")
    for agg in rig.get("aggregators", []):
        for ref in agg.get("depends_on_ids", []):
            total_refs += 1
            if ref not in all_ids:
                dangling += 1
    for test in rig.get("test_definitions", []):
        for ref_key in ("covers_ids", "depends_on_ids"):
            for ref in test.get(ref_key, []):
                total_refs += 1
                if ref not in all_ids:
                    dangling += 1
    for ep in rig.get("entrypoints", []):
        total_refs += 1
        if ep not in all_ids:
            dangling += 1

    score = (total_refs - dangling) / total_refs if total_refs else 1.0
    return CheckResult(
        name="No dangling references",
        category="correctness",
        severity="error" if dangling else "pass",
        score=score,
        measured=total_refs - dangling,
        total=total_refs,
        detail=f"{dangling} dangling ref(s)" + (f": {broken[0]}…" if broken else ""),
    )


def check_circular_deps(rig: dict) -> CheckResult:
    """Paper: no circular dependencies (rig_validator._validate_circular_dependencies)."""
    # Build adjacency list from components + aggregators + runners
    graph: dict[str, list[str]] = {}
    for key in ("components", "aggregators", "runners"):
        for node in rig.get(key, []):
            nid = node.get("id", node.get("name", ""))
            graph[nid] = node.get("depends_on_ids", [])

    # DFS cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in graph}
    has_cycle = [False]

    def dfs(node: str):
        color[node] = GRAY
        for neighbor in graph.get(node, []):
            if neighbor not in color:
                continue
            if color[neighbor] == GRAY:
                has_cycle[0] = True
                return
            if color[neighbor] == WHITE:
                dfs(neighbor)
                if has_cycle[0]:
                    return
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            dfs(node)
            if has_cycle[0]:
                break

    node_count = len(graph)
    return CheckResult(
        name="No circular dependencies",
        category="correctness",
        severity="error" if has_cycle[0] else "pass",
        score=0.0 if has_cycle[0] else 1.0,
        measured=node_count,
        total=node_count,
        detail="Cycle detected" if has_cycle[0] else "Acyclic",
    )


def check_evidence_coverage(rig: dict) -> CheckResult:
    """Paper: every node MUST have evidence (rig_validator._validate_evidence_consistency).

    Evidence = GitHub-style line references (file:line) in build system files,
    proving the node is defined by the build system — not assumed.
    """
    evidence = rig.get("evidence", [])
    evidence_ids = {e.get("id") for e in evidence} if isinstance(evidence, list) else set()

    total_nodes = 0
    nodes_with_evidence = 0
    missing: list[str] = []

    for key in ("components", "aggregators", "runners", "test_definitions"):
        for node in rig.get(key, []):
            total_nodes += 1
            ev_ids = node.get("evidence_ids", [])
            if ev_ids and any(eid in evidence_ids for eid in ev_ids):
                nodes_with_evidence += 1
            else:
                missing.append(f"{key}/{node.get('name', '?')}")

    score = nodes_with_evidence / total_nodes if total_nodes else 0.0
    return CheckResult(
        name="Evidence backing (every node traceable to build system)",
        category="evidence",
        severity="warn" if score < 1.0 else "pass",
        score=score,
        measured=nodes_with_evidence,
        total=total_nodes,
        detail=f"{total_nodes - nodes_with_evidence} node(s) lack evidence"
               + (f": {missing[0]}…" if missing else ""),
    )


def check_test_coverage(rig: dict) -> CheckResult:
    """Paper: test_definitions link test executables to components being tested.

    Measures both DIRECT coverage (component has a test_definition) and
    TRANSITIVE coverage (component depends on a tested component).
    Transitive coverage is meaningful because testing a library exercises
    all code reachable through its dependency chain.
    """
    tests = rig.get("test_definitions", [])
    components = rig.get("components", [])
    comp_ids = {c.get("id") for c in components}

    # Directly tested components
    directly_tested: set[str] = set()
    for t in tests:
        for ref_key in ("covers_ids", "components_being_tested_ids"):
            directly_tested.update(t.get(ref_key, []))

    # Build dependency graph for transitive coverage
    deps: dict[str, list[str]] = {}
    for c in components:
        deps[c.get("id", "")] = c.get("depends_on_ids", [])

    def has_tested_dep(cid: str, visited: set[str] | None = None) -> bool:
        """True if cid or any transitive dependency is directly tested.

        Checks BOTH directions:
        - Forward: component depends on a tested component (thin wrappers)
        - Reverse: a tested component depends on this component (native deps
          exercised through integration)
        """
        if visited is None:
            visited = set()
        if cid in visited:
            return False
        visited.add(cid)
        if cid in directly_tested:
            return True
        # Forward: my dependencies are tested
        if any(has_tested_dep(d, visited) for d in deps.get(cid, [])):
            return True
        # Reverse: something that depends on me is tested
        for other_cid, other_deps in deps.items():
            if cid in other_deps and has_tested_dep(other_cid, visited):
                return True
        return False

    # Count transitive coverage
    transitively_covered = {cid for cid in comp_ids if has_tested_dep(cid)}
    score = len(transitively_covered) / len(comp_ids) if comp_ids else 0.0

    meaningful_tests = sum(
        1 for t in tests
        if t.get("covers_ids") or t.get("components_being_tested_ids")
    )

    direct_count = len(directly_tested & comp_ids)
    return CheckResult(
        name="Test definitions (direct + transitive coverage)",
        category="tests",
        severity="warn" if len(tests) == 0 else ("pass" if score > 0 else "warn"),
        score=score,
        measured=len(transitively_covered),
        total=len(comp_ids),
        detail=(f"{len(tests)} test(s), {direct_count} direct + "
                f"{len(transitively_covered) - direct_count} transitive = "
                f"{len(transitively_covered)}/{len(comp_ids)} covered")
                if tests else "No test_definitions emitted",
    )


def check_component_completeness(rig: dict) -> CheckResult:
    """Paper: every source file in the repo appears in at least one component.

    This is the 'completeness' invariant — the RIG must account for ALL
    source files, not a subset. Files excluded by the build system (tests,
    generated code, vendored) should still be in test_definitions or
    explicitly excluded.
    """
    components = rig.get("components", [])
    total_files = sum(len(c.get("source_files", [])) for c in components)

    # We can't check against the actual repo here (no repo path), but we
    # can check that every component HAS source files.
    empty = sum(1 for c in components if not c.get("source_files"))

    score = (len(components) - empty) / len(components) if components else 0.0
    return CheckResult(
        name="Component source files (no empty components)",
        category="completeness",
        severity="warn" if empty else "pass",
        score=score,
        measured=len(components) - empty,
        total=len(components),
        detail=f"{empty} component(s) with no source files, {total_files} files total",
    )


def check_aggregators_runners(rig: dict) -> CheckResult:
    """Paper: aggregators (meta-targets) and runners (command executors) are
    first-class RIG nodes. Their presence indicates the build graph is
    fully captured, not just the leaf components."""
    aggs = len(rig.get("aggregators", []))
    runners = len(rig.get("runners", []))
    has_both = aggs > 0 or runners > 0

    return CheckResult(
        name="Aggregators / runners (meta-targets)",
        category="structural",
        severity="warn" if not has_both else "pass",
        score=1.0 if has_both else 0.0,
        measured=aggs + runners,
        total=1,
        detail=f"{aggs} aggregator(s), {runners} runner(s)" if has_both
               else "Not emitted (build graph captures leaf components only)",
    )


def check_external_package_managers(rig: dict) -> CheckResult:
    """Paper: external packages must link to a package_manager with name +
    package_name. This enables deterministic dependency resolution."""
    packages = rig.get("external_packages", [])
    with_pm = sum(
        1 for p in packages
        if p.get("package_manager", {})
        and p["package_manager"].get("name")
        and p["package_manager"].get("package_name")
    )
    score = with_pm / len(packages) if packages else 1.0
    return CheckResult(
        name="External packages have package_manager metadata",
        category="structural",
        severity="warn" if score < 1.0 else "pass",
        score=score,
        measured=with_pm,
        total=len(packages),
        detail=f"{with_pm}/{len(packages)} packages have full manager metadata" if packages
               else "No external packages",
    )


def check_entrypoints(rig: dict) -> CheckResult:
    """Paper: entrypoints identify where execution begins (executable components)."""
    components = rig.get("components", [])
    executables = [c for c in components if c.get("type") == "executable"]
    entrypoints = rig.get("entrypoints", [])
    eps_set = set(entrypoints)
    exec_ids = {c["id"] for c in executables if "id" in c}

    # Every executable should be an entrypoint
    missing_eps = exec_ids - eps_set
    score = (len(exec_ids) - len(missing_eps)) / len(exec_ids) if exec_ids else 1.0

    return CheckResult(
        name="Entrypoints (every executable is an entrypoint)",
        category="structural",
        severity="warn" if missing_eps else "pass",
        score=score,
        measured=len(exec_ids) - len(missing_eps),
        total=len(exec_ids) if exec_ids else 1,
        detail=f"{len(executables)} executable(s), {len(entrypoints)} entrypoint(s)"
               + (f", {len(missing_eps)} executable(s) not in entrypoints" if missing_eps else ""),
    )


# ──────────────────────────────────────────────────────────────────────
#  Orchestrator
# ──────────────────────────────────────────────────────────────────────

ALL_CHECKS = [
    check_duplicate_ids,
    check_dangling_refs,
    check_circular_deps,
    check_evidence_coverage,
    check_test_coverage,
    check_component_completeness,
    check_aggregators_runners,
    check_external_package_managers,
    check_entrypoints,
]


def _load_rig(rig_path: str) -> dict:
    """Load a RIG from rig.db (canonical)."""
    _ACTION_DIR = (Path(__file__).resolve().parent.parent.parent /
                   ".github" / "actions" / "repo-map")
    sys.path.insert(0, str(_ACTION_DIR))
    from rig.db import load_rig
    return load_rig(Path(rig_path))


def audit_rig(rig_path: str) -> Scorecard:
    rig = _load_rig(rig_path)

    repo_name = rig.get("repository", {}).get("name", "?")
    card = Scorecard(rig_path=rig_path, repository=repo_name)

    for check_fn in ALL_CHECKS:
        card.checks.append(check_fn(rig))

    return card


# ──────────────────────────────────────────────────────────────────────
#  Reporting
# ──────────────────────────────────────────────────────────────────────

SEVERITY_ICONS = {"pass": "✅", "warn": "⚠️", "error": "❌"}


def format_scorecard(card: Scorecard, verbose: bool = False) -> str:
    lines: list[str] = []
    repo = card.repository
    pct = card.overall_score * 100

    lines.append(f"┌─ RIG Compliance: {repo} ─────────────────────────────")
    lines.append(f"│ Score: {pct:.0f}% (Grade {card.grade})")
    lines.append(f"│ Source: {card.rig_path}")
    lines.append(f"├─────────────────────────────────────────────────────")

    current_cat = ""
    for c in card.checks:
        if c.category != current_cat:
            current_cat = c.category
            lines.append(f"│ ── {current_cat.upper()} ──")

        icon = SEVERITY_ICONS.get(c.severity, "?")
        score_pct = c.score * 100
        bar_len = 20
        filled = int(c.score * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        lines.append(f"│ {icon} {c.name:<48} {score_pct:5.1f}% {bar}")

        if verbose or c.severity != "pass":
            lines.append(f"│    {c.detail}")

    lines.append(f"├─────────────────────────────────────────────────────")

    # Category summaries
    categories: dict[str, list[float]] = {}
    for c in card.checks:
        categories.setdefault(c.category, []).append(c.score)
    for cat, scores in sorted(categories.items()):
        avg = sum(scores) / len(scores) * 100
        lines.append(f"│  {cat:<16} {avg:5.1f}%")

    lines.append(f"└─────────────────────────────────────────────────────")
    return "\n".join(lines)


def format_compact(card: Scorecard) -> str:
    pct = card.overall_score * 100
    error_count = sum(1 for c in card.checks if c.severity == "error")
    warn_count = sum(1 for c in card.checks if c.severity == "warn")
    return f"{card.repository:<20} {pct:5.1f}%  Grade {card.grade}  {error_count} err  {warn_count} warn"


# ──────────────────────────────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RIG Compliance Auditor (paper: arXiv:2601.10112)")
    parser.add_argument("rig_path", nargs="?", help="Path to a rig.db file")
    parser.add_argument("--all", metavar="DIR", help="Audit all rig.db files under DIR (e.g. wiki root)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show details for passing checks too")
    parser.add_argument("--strict", action="store_true", help="Exit 2 if any check is below 100%%")
    args = parser.parse_args()

    if args.all:
        base = Path(args.all)
        rig_files = sorted(base.glob("**/rig.db"))
        if not rig_files:
            print(f"No rig.db files found under {base}", file=sys.stderr)
            sys.exit(1)

        print(f"Found {len(rig_files)} RIG file(s)\n")
        cards = [audit_rig(str(f)) for f in rig_files]

        print(f"{'Repository':<20} {'Score':>6}  {'Grade':<7} {'Errors':<6} {'Warnings'}")
        print("─" * 60)
        for card in cards:
            print(format_compact(card))
        print()

        for card in cards:
            if card.has_errors or args.verbose:
                print(format_scorecard(card, verbose=args.verbose))
                print()

        any_errors = any(c.has_errors for c in cards)
        sys.exit(1 if any_errors else 0)

    if not args.rig_path:
        parser.error("rig_path or --all is required")

    card = audit_rig(args.rig_path)
    print(format_scorecard(card, verbose=args.verbose))

    if card.has_errors:
        sys.exit(1)
    if args.strict and card.overall_score < 1.0:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
