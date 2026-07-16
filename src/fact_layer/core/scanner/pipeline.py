# src/fact_layer/core/scanner/pipeline.py
"""Main scan pipeline: discover → dispatch → extract → dedup → result."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fact_layer.core.scanner.candidates import (
    ExtractResult,
    ScanContext,
    ScanResult,
    ScanStats,
    SlotCandidate,
    UnmappedFact,
)
from fact_layer.core.scanner.dedup import deduplicate
from fact_layer.core.scanner.extractors.config import (
    extract_dockerfile,
    extract_docker_compose,
    extract_github_actions,
    extract_package_json,
    extract_pyproject,
)
from fact_layer.core.scanner.indexes import (
    ExtractionEntry,
    SourceEntry,
    compute_content_hash,
    load_extraction_index,
    load_source_index,
    next_id,
    save_extraction_index,
    save_source_index,
)

CONFIG_FILE_PATTERNS = {
    "pyproject.toml": extract_pyproject,
    "Dockerfile": extract_dockerfile,
    "docker-compose.yaml": extract_docker_compose,
    "docker-compose.yml": extract_docker_compose,
    "compose.yaml": extract_docker_compose,
    "compose.yml": extract_docker_compose,
    "package.json": extract_package_json,
}

GLOB_PATTERNS = {
    ".github/workflows/*.yaml": extract_github_actions,
    ".github/workflows/*.yml": extract_github_actions,
}

MAX_MARKDOWN_SIZE = 102_400  # 100KB

_EXTRACTOR_TYPE_MAP = {
    "config": "config-parser",
    "markdown": "llm-markdown",
}


def _classify_file(path: Path) -> str:
    if path.suffix == ".md":
        return "markdown"
    return "config"


def _discover_files(
    project_root: Path,
    paths: list[str] | None,
    include_markdown: bool = True,
) -> list[Path]:
    if paths:
        found: list[Path] = []
        for p in paths:
            resolved = Path(p)
            if not resolved.is_absolute():
                resolved = project_root / resolved
            if resolved.is_file():
                found.append(resolved)
            elif resolved.is_dir():
                for name in CONFIG_FILE_PATTERNS:
                    candidate = resolved / name
                    if candidate.is_file():
                        found.append(candidate)
                for pattern in GLOB_PATTERNS:
                    found.extend(resolved.glob(pattern))
                if include_markdown:
                    for md in resolved.glob("*.md"):
                        if md.stat().st_size <= MAX_MARKDOWN_SIZE:
                            found.append(md)
        return found

    found: list[Path] = []
    for name in CONFIG_FILE_PATTERNS:
        candidate = project_root / name
        if candidate.is_file():
            found.append(candidate)
    for pattern in GLOB_PATTERNS:
        found.extend(project_root.glob(pattern))
    if include_markdown:
        for md in project_root.glob("*.md"):
            if md.stat().st_size <= MAX_MARKDOWN_SIZE:
                found.append(md)
    return found


def _dispatch(
    path: Path,
    context: ScanContext,
    allowed_extractors: set[str] | None = None,
) -> ExtractResult:
    name = path.name

    if name in CONFIG_FILE_PATTERNS:
        if allowed_extractors and "config-parser" not in allowed_extractors:
            return ExtractResult()
        return CONFIG_FILE_PATTERNS[name](path, context)

    for pattern, extractor in GLOB_PATTERNS.items():
        parts = pattern.split("/")
        if len(parts) >= 2:
            parent_match = parts[-2] if len(parts) == 2 else "/".join(parts[:-1])
            if parent_match in str(path.parent) and path.suffix in (".yaml", ".yml"):
                if allowed_extractors and "config-parser" not in allowed_extractors:
                    return ExtractResult()
                return extractor(path, context)

    if path.suffix == ".md":
        if allowed_extractors and "llm-markdown" not in allowed_extractors:
            return ExtractResult()
        from fact_layer.core.scanner.extractors.markdown import extract_markdown

        return extract_markdown(path, context)

    return ExtractResult()


def _find_source_by_path(
    source_index: dict[str, SourceEntry], rel_path: str,
) -> tuple[str, SourceEntry] | None:
    for sid, entry in source_index.items():
        if entry.path == rel_path:
            return sid, entry
    return None


def _update_extraction_index(
    ext_index: dict[str, ExtractionEntry],
    source_id: str,
    candidates: list[SlotCandidate],
    today: str,
) -> None:
    old_exts = {
        eid: e for eid, e in ext_index.items()
        if e.source_id == source_id and e.status == "active"
    }

    new_by_slot = {c.slot_ref: c for c in candidates}
    old_by_slot = {e.slot_ref: (eid, e) for eid, e in old_exts.items()}

    matched_old_eids: set[str] = set()

    for slot_ref, candidate in new_by_slot.items():
        if slot_ref in old_by_slot:
            old_eid, old_ext = old_by_slot[slot_ref]
            matched_old_eids.add(old_eid)
            old_val = str(old_ext.source_location)
            new_val = str(candidate.value)
            if old_val == new_val or old_ext.source_location == candidate.source:
                ext_index[old_eid] = old_ext.model_copy(update={
                    "extracted_at": today,
                    "confidence": candidate.confidence,
                })
            else:
                new_eid = next_id("EXT", ext_index)
                ext_index[old_eid] = old_ext.model_copy(update={
                    "status": "superseded",
                    "superseded_by": new_eid,
                })
                ext_index[new_eid] = ExtractionEntry(
                    slot_ref=slot_ref,
                    source_id=source_id,
                    source_location=candidate.source,
                    extractor=candidate.extractor,
                    confidence=candidate.confidence,
                    status="active",
                    extracted_at=today,
                )
        else:
            new_eid = next_id("EXT", ext_index)
            ext_index[new_eid] = ExtractionEntry(
                slot_ref=slot_ref,
                source_id=source_id,
                source_location=candidate.source,
                extractor=candidate.extractor,
                confidence=candidate.confidence,
                status="active",
                extracted_at=today,
            )

    for old_eid in set(old_exts.keys()) - matched_old_eids:
        del ext_index[old_eid]


def run_scan(
    project_root: Path,
    paths: list[str] | None = None,
    categories: list[str] | None = None,
    extractors: list[str] | None = None,
    api_key: str | None = None,
    model: str | None = None,
    full: bool = False,
) -> ScanResult:
    allowed_extractors: set[str] | None = None
    if extractors:
        allowed_extractors = set()
        for e in extractors:
            if e in _EXTRACTOR_TYPE_MAP:
                allowed_extractors.add(_EXTRACTOR_TYPE_MAP[e])

    include_markdown = allowed_extractors is None or "llm-markdown" in allowed_extractors

    facts_dir = project_root / ".facts"
    fw = None
    cats = None
    if facts_dir.is_dir() and (facts_dir / "framework.yaml").is_file():
        from fact_layer.core.loader import load_all_categories, load_framework

        fw = load_framework(facts_dir)
        cats = load_all_categories(facts_dir)

    context = ScanContext(
        facts_dir=facts_dir if facts_dir.is_dir() else None,
        framework=fw,
        categories=cats,
        api_key=api_key,
        model=model,
    )

    files = _discover_files(project_root, paths, include_markdown=include_markdown)

    src_index = load_source_index(facts_dir) if facts_dir.is_dir() else None
    ext_index = load_extraction_index(facts_dir) if facts_dir.is_dir() else None
    today = date.today().isoformat()

    all_candidates: list[SlotCandidate] = []
    all_unmapped: list[UnmappedFact] = []
    files_scanned = 0
    skipped_files = 0

    seen_paths: set[str] = set()

    for f in files:
        try:
            rel_path = str(f.relative_to(project_root))
        except ValueError:
            rel_path = str(f)

        seen_paths.add(rel_path)

        if src_index and not full:
            current_hash = compute_content_hash(f)
            match = _find_source_by_path(src_index.sources, rel_path)
            if match:
                sid, entry = match
                if entry.content_hash == current_hash and entry.status == "active":
                    skipped_files += 1
                    continue
                src_index.sources[sid] = entry.model_copy(update={"status": "stale"})

        result = _dispatch(f, context, allowed_extractors)
        if result.candidates or result.unmapped:
            files_scanned += 1
            all_candidates.extend(result.candidates)
            all_unmapped.extend(result.unmapped)

            if src_index is not None and ext_index is not None:
                current_hash = compute_content_hash(f)
                match = _find_source_by_path(src_index.sources, rel_path)
                if match:
                    sid, _ = match
                else:
                    sid = next_id("SRC", src_index.sources)
                src_index.sources[sid] = SourceEntry(
                    path=rel_path,
                    type=_classify_file(f),
                    status="active",
                    content_hash=current_hash,
                    last_scanned=today,
                    extracted_count=len(result.candidates),
                )
                _update_extraction_index(
                    ext_index.extractions, sid, result.candidates, today,
                )
        else:
            files_scanned += 1
            if src_index is not None:
                current_hash = compute_content_hash(f)
                match = _find_source_by_path(src_index.sources, rel_path)
                if match:
                    sid, _ = match
                else:
                    sid = next_id("SRC", src_index.sources)
                src_index.sources[sid] = SourceEntry(
                    path=rel_path,
                    type=_classify_file(f),
                    status="active",
                    content_hash=current_hash,
                    last_scanned=today,
                    extracted_count=0,
                )

    if src_index is not None:
        for sid, entry in list(src_index.sources.items()):
            if entry.path not in seen_paths and entry.status != "removed":
                src_index.sources[sid] = entry.model_copy(update={"status": "removed"})
                if ext_index is not None:
                    orphaned = [
                        eid for eid, e in ext_index.extractions.items()
                        if e.source_id == sid
                    ]
                    for eid in orphaned:
                        del ext_index.extractions[eid]

    if src_index is not None and facts_dir.is_dir():
        save_source_index(facts_dir, src_index)
    if ext_index is not None and facts_dir.is_dir():
        save_extraction_index(facts_dir, ext_index)

    if categories:
        all_candidates = [c for c in all_candidates if c.category in categories]

    merged, conflicts = deduplicate(all_candidates)

    return ScanResult(
        candidates=merged,
        conflicts=conflicts,
        unmapped=all_unmapped,
        stats=ScanStats(
            files_scanned=files_scanned,
            candidates_found=len(merged),
            conflicts=len(conflicts),
            unmapped=len(all_unmapped),
            skipped_files=skipped_files,
        ),
    )
