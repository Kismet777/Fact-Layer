# src/fact_layer/core/scanner/pipeline.py
"""Main scan pipeline: discover → dispatch → extract → dedup → result."""

from __future__ import annotations

from pathlib import Path

from fact_layer.core.scanner.candidates import ScanResult, ScanStats, SlotCandidate
from fact_layer.core.scanner.dedup import deduplicate
from fact_layer.core.scanner.extractors.config import (
    extract_dockerfile,
    extract_docker_compose,
    extract_github_actions,
    extract_package_json,
    extract_pyproject,
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


def _discover_files(project_root: Path, paths: list[str] | None) -> list[Path]:
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
        return found

    found = []
    for name in CONFIG_FILE_PATTERNS:
        candidate = project_root / name
        if candidate.is_file():
            found.append(candidate)
    for pattern in GLOB_PATTERNS:
        found.extend(project_root.glob(pattern))
    return found


def _dispatch(path: Path) -> list[SlotCandidate]:
    name = path.name
    if name in CONFIG_FILE_PATTERNS:
        return CONFIG_FILE_PATTERNS[name](path)

    for pattern, extractor in GLOB_PATTERNS.items():
        parts = pattern.split("/")
        if len(parts) >= 2:
            parent_match = parts[-2] if len(parts) == 2 else "/".join(parts[:-1])
            if parent_match in str(path.parent) and path.suffix in (".yaml", ".yml"):
                return extractor(path)

    return []


def run_scan(
    project_root: Path,
    paths: list[str] | None = None,
    categories: list[str] | None = None,
    extractors: list[str] | None = None,
) -> ScanResult:
    files = _discover_files(project_root, paths)

    all_candidates: list[SlotCandidate] = []
    files_scanned = 0

    for f in files:
        candidates = _dispatch(f)
        if candidates:
            files_scanned += 1
            all_candidates.extend(candidates)

    if categories:
        all_candidates = [c for c in all_candidates if c.category in categories]

    merged, conflicts = deduplicate(all_candidates)

    return ScanResult(
        candidates=merged,
        conflicts=conflicts,
        unmapped=[],
        stats=ScanStats(
            files_scanned=files_scanned,
            candidates_found=len(merged),
            conflicts=len(conflicts),
            unmapped=0,
        ),
    )
