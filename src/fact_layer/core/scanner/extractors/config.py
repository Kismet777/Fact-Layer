# src/fact_layer/core/scanner/extractors/config.py
"""Deterministic config-file extractors (zero LLM)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from fact_layer.core.scanner.candidates import SlotCandidate

_yaml = YAML()
_yaml.preserve_quotes = True

KNOWN_FRAMEWORKS = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "starlette": "Starlette",
    "litestar": "Litestar",
    "sanic": "Sanic",
    "tornado": "Tornado",
}

KNOWN_BUILD_BACKENDS = {
    "hatchling": "hatch",
    "setuptools": "setuptools",
    "flit_core": "flit",
    "pdm": "pdm",
    "maturin": "maturin",
    "poetry": "poetry",
}


def _candidate(
    category: str, slot: str, value: Any,
    source: str, evidence: str,
    confidence: str = "high",
) -> SlotCandidate:
    return SlotCandidate(
        category=category, slot=slot, value=value,
        confidence=confidence, source=source,
        extractor="config-parser", evidence=evidence,
    )


def extract_pyproject(path: Path) -> list[SlotCandidate]:
    """Extract facts from pyproject.toml."""
    if not path.is_file():
        return []
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except Exception:
        return []
    if not data:
        return []

    results: list[SlotCandidate] = []
    src = str(path)

    project = data.get("project", {})
    poetry = data.get("tool", {}).get("poetry", {})

    # --- tech-stack.language ---
    requires_python = project.get("requires-python", "")
    poetry_python = poetry.get("dependencies", {}).get("python", "")
    if requires_python:
        version = requires_python.lstrip(">=^~! ")
        results.append(_candidate(
            "tech-stack", "language", f"Python {version}",
            source=src, evidence=f'requires-python = "{requires_python}"',
        ))
    elif poetry_python:
        version = poetry_python.lstrip(">=^~! ")
        results.append(_candidate(
            "tech-stack", "language", f"Python {version}",
            source=src, evidence=f'python = "{poetry_python}"',
        ))

    # --- tech-stack.key-libraries + tech-stack.framework ---
    deps: dict[str, str] = {}
    if project.get("dependencies"):
        for dep in project["dependencies"]:
            name = dep.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip()
            deps[name.lower()] = dep
    if poetry.get("dependencies"):
        for name, ver in poetry["dependencies"].items():
            if name.lower() != "python":
                deps[name.lower()] = f"{name} {ver}" if isinstance(ver, str) else name

    if deps:
        framework = None
        for key, display in KNOWN_FRAMEWORKS.items():
            if key in deps:
                framework = display
                break
        if framework:
            results.append(_candidate(
                "tech-stack", "framework", framework,
                source=src, evidence=f"dependency: {framework.lower()}",
            ))

        lib_names = sorted(deps.keys())
        results.append(_candidate(
            "tech-stack", "key-libraries", lib_names,
            source=src, evidence=f"{len(lib_names)} dependencies found",
        ))

    # --- build-deploy.build-tool ---
    build_backend = data.get("build-system", {}).get("build-backend", "")
    if build_backend:
        for backend_key, tool_name in KNOWN_BUILD_BACKENDS.items():
            if backend_key in build_backend:
                results.append(_candidate(
                    "build-deploy", "build-tool", tool_name,
                    source=src, evidence=f'build-backend = "{build_backend}"',
                ))
                break

    # --- tech-stack.package-manager ---
    tool = data.get("tool", {})
    if "uv" in tool:
        results.append(_candidate(
            "tech-stack", "package-manager", "uv",
            source=src, evidence="[tool.uv] section found",
        ))
    elif "poetry" in tool:
        results.append(_candidate(
            "tech-stack", "package-manager", "poetry",
            source=src, evidence="[tool.poetry] section found",
        ))
    elif "pdm" in tool:
        results.append(_candidate(
            "tech-stack", "package-manager", "pdm",
            source=src, evidence="[tool.pdm] section found",
        ))

    return results


def extract_dockerfile(path: Path) -> list[SlotCandidate]:
    """Extract facts from a Dockerfile."""
    if not path.is_file():
        return []

    results: list[SlotCandidate] = []
    src = str(path)

    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("FROM "):
            image = stripped.split()[1] if len(stripped.split()) > 1 else ""
            if image and image.lower() != "scratch":
                results.append(_candidate(
                    "build-deploy", "docker", image,
                    source=src, evidence=stripped,
                ))
                break

    return results


def extract_docker_compose(path: Path) -> list[SlotCandidate]:
    """Extract facts from docker-compose.yaml."""
    if not path.is_file():
        return []

    try:
        with path.open("r", encoding="utf-8") as f:
            data = _yaml.load(f)
    except Exception:
        return []

    if not data or not isinstance(data, dict):
        return []

    results: list[SlotCandidate] = []
    src = str(path)
    services = data.get("services", {})

    db_images = {
        "postgres": "PostgreSQL",
        "mysql": "MySQL",
        "mariadb": "MariaDB",
        "mongo": "MongoDB",
        "redis": "Redis",
    }

    for svc_name, svc_config in (services or {}).items():
        if not isinstance(svc_config, dict):
            continue
        image = svc_config.get("image", "")
        if not image:
            continue

        for db_key, db_name in db_images.items():
            if db_key in image.lower():
                version_part = image.split(":")[1] if ":" in image else ""
                version_clean = version_part.split("-")[0] if version_part else ""
                display = f"{db_name} {version_clean}".strip() if version_clean else db_name
                results.append(_candidate(
                    "tech-stack", "database", display,
                    source=f"{src}:{svc_name}",
                    evidence=f"image: {image}",
                ))

    return results


def extract_package_json(path: Path) -> list[SlotCandidate]:
    """Extract facts from package.json."""
    if not path.is_file():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not data or not isinstance(data, dict):
        return []

    results: list[SlotCandidate] = []
    src = str(path)

    deps = {}
    deps.update(data.get("dependencies", {}))

    js_frameworks = {
        "next": "Next.js",
        "react": "React",
        "vue": "Vue",
        "angular": "Angular",
        "express": "Express",
        "fastify": "Fastify",
        "nuxt": "Nuxt",
        "svelte": "Svelte",
    }

    if deps:
        for key, display in js_frameworks.items():
            if key in deps:
                results.append(_candidate(
                    "tech-stack", "framework", display,
                    source=src, evidence=f'"{key}": "{deps[key]}"',
                ))
                break

        lib_names = sorted(deps.keys())
        results.append(_candidate(
            "tech-stack", "key-libraries", lib_names,
            source=src, evidence=f"{len(lib_names)} dependencies found",
        ))

    engines = data.get("engines", {})
    node_ver = engines.get("node", "")
    if node_ver:
        version = node_ver.lstrip(">=^~! ")
        results.append(_candidate(
            "tech-stack", "language", f"Node.js {version}",
            source=src, evidence=f'"node": "{node_ver}"',
        ))
    elif deps:
        results.append(_candidate(
            "tech-stack", "language", "JavaScript/TypeScript",
            source=src, evidence="package.json with dependencies",
            confidence="medium",
        ))

    return results


def extract_github_actions(path: Path) -> list[SlotCandidate]:
    """Extract facts from a GitHub Actions workflow file."""
    if not path.is_file():
        return []

    try:
        with path.open("r", encoding="utf-8") as f:
            data = _yaml.load(f)
    except Exception:
        return []

    if not data or not isinstance(data, dict):
        return []

    src = str(path)
    workflow_name = data.get("name", path.stem)
    triggers = list(data.get("on", {}).keys()) if isinstance(data.get("on"), dict) else []
    trigger_str = ", ".join(triggers) if triggers else "unknown"

    return [_candidate(
        "build-deploy", "ci", "GitHub Actions",
        source=src,
        evidence=f"workflow: {workflow_name} (on: {trigger_str})",
    )]
