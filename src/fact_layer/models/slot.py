from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class SlotMeta(BaseModel):
    source: Literal["human", "agent-analysis", "code-extracted"] = "human"
    confidence: Literal["high", "medium", "low"] = "high"
    status: Literal["active", "uncertain", "stale", "superseded"] = "active"
    updated: date = Field(default_factory=date.today)
    verified: date = Field(default_factory=date.today)
    reason: str | None = None


ACTIVE_STATUSES = ("active", "uncertain")


def is_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == []


class SlotValue(BaseModel):
    value: Any
    meta: SlotMeta = Field(default_factory=SlotMeta)
