# src/fact_layer/core/scanner/indexes.py
"""Data models and I/O for the multi-level scan index system."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from ruamel.yaml import YAML

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.default_flow_style = False

INDEXES_DIR = "indexes"
SOURCE_INDEX_FILE = "source_index.yaml"
EXTRACTION_INDEX_FILE = "extraction_index.yaml"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SourceEntry(BaseModel):
    path: str
    type: Literal["config", "markdown", "code"]
    status: Literal["active", "stale", "removed"]
    content_hash: str
    last_scanned: str
    extracted_count: int


class SourceIndex(BaseModel):
    version: int = 1
    sources: dict[str, SourceEntry] = {}


class ExtractionEntry(BaseModel):
    slot_ref: str
    source_id: str
    source_location: str
    extractor: str
    confidence: Literal["high", "medium", "low"]
    status: Literal["active", "superseded"]
    extracted_at: str
    superseded_by: str | None = None


class ExtractionIndex(BaseModel):
    version: int = 1
    extractions: dict[str, ExtractionEntry] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def compute_content_hash(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return h[:12]


def next_id(prefix: str, existing_keys: dict[str, Any] | set[str]) -> str:
    max_num = 0
    for key in existing_keys:
        if key.startswith(prefix + "-"):
            try:
                num = int(key[len(prefix) + 1 :])
                max_num = max(max_num, num)
            except ValueError:
                continue
    return f"{prefix}-{max_num + 1:03d}"


def _indexes_dir(facts_dir: Path) -> Path:
    return facts_dir / INDEXES_DIR


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def load_source_index(facts_dir: Path) -> SourceIndex:
    path = _indexes_dir(facts_dir) / SOURCE_INDEX_FILE
    if not path.is_file():
        return SourceIndex()
    with path.open("r", encoding="utf-8") as f:
        data = _yaml.load(f)
    if not data:
        return SourceIndex()
    return SourceIndex.model_validate(dict(data))


def save_source_index(facts_dir: Path, index: SourceIndex) -> None:
    idx_dir = _indexes_dir(facts_dir)
    idx_dir.mkdir(parents=True, exist_ok=True)
    path = idx_dir / SOURCE_INDEX_FILE
    with path.open("w", encoding="utf-8") as f:
        _yaml.dump(index.model_dump(mode="json"), f)


def load_extraction_index(facts_dir: Path) -> ExtractionIndex:
    path = _indexes_dir(facts_dir) / EXTRACTION_INDEX_FILE
    if not path.is_file():
        return ExtractionIndex()
    with path.open("r", encoding="utf-8") as f:
        data = _yaml.load(f)
    if not data:
        return ExtractionIndex()
    return ExtractionIndex.model_validate(dict(data))


def save_extraction_index(facts_dir: Path, index: ExtractionIndex) -> None:
    idx_dir = _indexes_dir(facts_dir)
    idx_dir.mkdir(parents=True, exist_ok=True)
    path = idx_dir / EXTRACTION_INDEX_FILE
    with path.open("w", encoding="utf-8") as f:
        _yaml.dump(index.model_dump(mode="json"), f)
