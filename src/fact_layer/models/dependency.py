from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DependencyTarget(BaseModel):
    slot: str
    type: Literal[
        "derives-from",
        "constrains",
        "references",
        "implies",
        "conflicts-with",
    ]


class DependencyRule(BaseModel):
    source: str
    targets: list[DependencyTarget]


class DependencyGraph(BaseModel):
    static: list[DependencyRule] = []
