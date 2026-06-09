from __future__ import annotations

from pathlib import Path

from fact_layer.core.loader import load_framework
from fact_layer.models.framework import CategoryDef, FrameworkConfig


def get_enabled_categories(config: FrameworkConfig) -> dict[str, CategoryDef]:
    """Return all enabled categories: core + enabled extensions + enabled optional."""
    result: dict[str, CategoryDef] = {}
    result.update(config.core)
    for name in config.extensions.enabled:
        if name in config.extensions.available:
            result[name] = config.extensions.available[name]
    for name in config.optional.enabled:
        if name in config.optional.available:
            result[name] = config.optional.available[name]
    return result


def get_tier_for_category(config: FrameworkConfig, category_name: str) -> str | None:
    cats = get_enabled_categories(config)
    cat_def = cats.get(category_name)
    return cat_def.tier if cat_def else None


def get_stale_threshold(config: FrameworkConfig, tier: str) -> int | None:
    tier_config = config.tiers.get(tier)
    return tier_config.stale_threshold_days if tier_config else None


def resolve_facts_dir(start: Path | None = None) -> Path | None:
    """Walk up from start (default: cwd) to find the nearest .facts/ directory."""
    current = start or Path.cwd()
    for parent in [current, *current.parents]:
        candidate = parent / ".facts"
        if candidate.is_dir() and (candidate / "framework.yaml").is_file():
            return candidate
    return None
