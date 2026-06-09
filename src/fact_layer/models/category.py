from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from fact_layer.models.slot import SlotValue


class CategoryFile(BaseModel):
    category: str
    tier: Literal["stable", "dynamic", "working"]
    slots: dict[str, SlotValue] = {}
