"""B-002: dependency-edge editing interface.

FL had no way to add/remove edges in dependencies.yaml — the only recourse was
hand-editing the file, which the project's ironclad rule forbids. That gap meant
the dangling edges B-001 detects could never be repaired through FL. This module
closes it, routing edge edits through the same roundtrip writer as slot edits.
"""

from __future__ import annotations

from pathlib import Path

from fact_layer.core.checker import _slot_exists
from fact_layer.core.editor import load_yaml_roundtrip, save_yaml_roundtrip
from fact_layer.core.loader import load_all_categories, load_dependencies
from fact_layer.models.dependency import DependencyGraph

VALID_EDGE_TYPES = (
    "derives-from",
    "constrains",
    "references",
    "implies",
    "conflicts-with",
)


def _deps_path(facts_dir: Path) -> Path:
    return facts_dir / "dependencies.yaml"


def add_dependency(facts_dir: Path, source: str, target: str, edge_type: str) -> None:
    """Add edge source -> target of edge_type.

    Validate-then-write: rejects an unknown edge type and refuses to create a
    dangling edge (either endpoint slot missing) — the exact defect B-001 detects.
    Rejects a duplicate (same source+target, regardless of type).
    """
    if edge_type not in VALID_EDGE_TYPES:
        raise ValueError(
            f"Invalid edge type '{edge_type}'. Must be one of: {', '.join(VALID_EDGE_TYPES)}"
        )

    categories = load_all_categories(facts_dir)
    if not _slot_exists(source, categories):
        raise ValueError(f"Source slot '{source}' does not exist")
    if not _slot_exists(target, categories):
        raise ValueError(f"Target slot '{target}' does not exist")

    path = _deps_path(facts_dir)
    data = load_yaml_roundtrip(path) or {}
    static = data.get("static")
    if static is None:
        static = []
        data["static"] = static

    rule = next((r for r in static if r.get("source") == source), None)
    if rule is None:
        rule = {"source": source, "targets": []}
        static.append(rule)

    targets = rule.setdefault("targets", [])
    if any(t.get("slot") == target for t in targets):
        raise ValueError(f"Edge {source} -> {target} already exists")

    targets.append({"slot": target, "type": edge_type})
    save_yaml_roundtrip(path, data)


def remove_dependency(facts_dir: Path, source: str, target: str) -> bool:
    """Remove edge source -> target. Return True if removed, False if absent.

    Does NOT validate endpoint existence: a dangling edge (endpoint slot gone)
    must stay removable, or B-001 findings could never be repaired via FL.
    When a source rule loses its last target, the rule itself is dropped.
    """
    path = _deps_path(facts_dir)
    data = load_yaml_roundtrip(path)
    if not data or not data.get("static"):
        return False
    static = data["static"]

    rule = next((r for r in static if r.get("source") == source), None)
    if rule is None:
        return False

    targets = rule.get("targets", [])
    kept = [t for t in targets if t.get("slot") != target]
    if len(kept) == len(targets):
        return False  # edge not present

    if kept:
        rule["targets"] = kept
    else:
        static.remove(rule)

    save_yaml_roundtrip(path, data)
    return True


def list_dependencies(facts_dir: Path) -> DependencyGraph:
    """Return the current dependency graph (thin read wrapper)."""
    return load_dependencies(facts_dir)
