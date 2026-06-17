from __future__ import annotations

import copy
import importlib.resources
import logging
from datetime import date
from pathlib import Path

from ruamel.yaml import YAML

logger = logging.getLogger(__name__)

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.default_flow_style = False

CORE_CATEGORIES = [
    "project-overview",
    "tech-stack",
    "architecture",
    "conventions",
    "work-in-progress",
]

EXTENSION_CATEGORIES = {
    "data-model": "Project uses a database",
    "api-contracts": "Project exposes APIs",
    "testing": "Project has a test suite",
    "build-deploy": "Project has build/deploy pipeline",
    "security": "Project has auth/security",
}

OPTIONAL_CATEGORIES = {
    "decisions": "Decision log",
}


def _templates_dir() -> Path:
    return Path(str(importlib.resources.files("fact_layer") / "templates"))


def _load_template(name: str) -> dict:
    path = _templates_dir() / name
    with path.open("r", encoding="utf-8") as f:
        return _yaml.load(f)


def _copy_template_raw(name: str, dest: Path) -> None:
    """Copy template file preserving comments by reading/writing raw YAML."""
    src = _templates_dir() / name
    with src.open("r", encoding="utf-8") as f:
        data = _yaml.load(f)
    with dest.open("w", encoding="utf-8") as f:
        _yaml.dump(data, f)


def _build_framework(
    project_name: str,
    enabled_extensions: list[str],
    enabled_optional: list[str],
) -> dict:
    tmpl = _load_template("framework.yaml")
    tmpl["project_name"] = project_name
    tmpl["extensions"]["enabled"] = enabled_extensions
    tmpl["optional"]["enabled"] = enabled_optional
    return tmpl


def _filter_dependencies(
    enabled_categories: set[str],
) -> dict:
    tmpl = copy.deepcopy(_load_template("dependencies.yaml"))
    filtered = []
    for rule in tmpl.get("static", []):
        source_cat = rule["source"].split(".")[0]
        if source_cat not in enabled_categories:
            continue
        kept_targets = []
        for target in rule.get("targets", []):
            target_cat = target["slot"].split(".")[0]
            if target_cat in enabled_categories:
                kept_targets.append(target)
        if kept_targets:
            rule["targets"] = kept_targets
            filtered.append(rule)
    tmpl["static"] = filtered
    return tmpl


def _patch_canonical(data: dict, project_name: str, language: str) -> dict:
    """Pre-fill project-overview slots with user input."""
    today = date.today().isoformat()
    slots = data.get("slots", {})
    if "name" in slots:
        slots["name"]["value"] = project_name
        slots["name"]["meta"]["updated"] = today
        slots["name"]["meta"]["verified"] = today
        slots["name"]["meta"]["status"] = "active"
        slots["name"]["meta"]["confidence"] = "high"
    if "language" in slots:
        slots["language"]["value"] = language
        slots["language"]["meta"]["updated"] = today
        slots["language"]["meta"]["verified"] = today
        slots["language"]["meta"]["status"] = "active"
        slots["language"]["meta"]["confidence"] = "high"
    return data


def init_facts_dir(
    target: Path,
    project_name: str,
    language: str,
    enabled_extensions: list[str],
    enabled_optional: list[str],
) -> list[str]:
    """Create .facts/ directory structure. Returns list of created category names."""
    facts_dir = target / ".facts"
    canonical_dir = facts_dir / "canonical"
    canonical_dir.mkdir(parents=True, exist_ok=True)

    from fact_layer.core.scanner.indexes import (
        ExtractionIndex,
        SourceIndex,
        save_extraction_index,
        save_source_index,
    )

    save_source_index(facts_dir, SourceIndex())
    save_extraction_index(facts_dir, ExtractionIndex())

    framework = _build_framework(project_name, enabled_extensions, enabled_optional)
    with (facts_dir / "framework.yaml").open("w", encoding="utf-8") as f:
        _yaml.dump(framework, f)

    all_enabled = set(CORE_CATEGORIES + enabled_extensions + enabled_optional)
    deps = _filter_dependencies(all_enabled)
    with (facts_dir / "dependencies.yaml").open("w", encoding="utf-8") as f:
        _yaml.dump(deps, f)

    created: list[str] = []
    for cat_name in CORE_CATEGORIES + enabled_extensions + enabled_optional:
        filename = f"{cat_name}.yaml"
        src_path = _templates_dir() / "canonical" / filename
        if not src_path.exists():
            logger.warning("Template file missing for category '%s': %s", cat_name, src_path)
            continue
        with src_path.open("r", encoding="utf-8") as f:
            data = _yaml.load(f)
        if cat_name == "project-overview":
            data = _patch_canonical(data, project_name, language)
        elif cat_name == "tech-stack":
            data = _patch_canonical(data, project_name, language)
        dest = canonical_dir / filename
        with dest.open("w", encoding="utf-8") as f:
            _yaml.dump(data, f)
        created.append(cat_name)

    return created
