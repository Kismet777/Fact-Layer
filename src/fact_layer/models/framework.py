from __future__ import annotations

from pydantic import BaseModel


class TierConfig(BaseModel):
    description: str
    stale_threshold_days: int


class CategoryDef(BaseModel):
    file: str
    tier: str
    required_slots: list[str] = []


class ExtensionsConfig(BaseModel):
    enabled: list[str] = []
    available: dict[str, CategoryDef] = {}


class OptionalConfig(BaseModel):
    enabled: list[str] = []
    available: dict[str, CategoryDef] = {}


class FrameworkConfig(BaseModel):
    version: int = 1
    project_name: str = ""
    tiers: dict[str, TierConfig] = {}
    core: dict[str, CategoryDef] = {}
    extensions: ExtensionsConfig = ExtensionsConfig()
    optional: OptionalConfig = OptionalConfig()
