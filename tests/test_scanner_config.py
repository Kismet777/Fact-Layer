# tests/test_scanner_config.py
"""Tests for config-file extractors (deterministic, zero LLM)."""

from pathlib import Path

from fact_layer.core.scanner.extractors.config import (
    extract_dockerfile,
    extract_docker_compose,
    extract_github_actions,
    extract_package_json,
    extract_pyproject,
)


class TestExtractPyproject:
    def test_basic_python_project(self, tmp_path: Path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text("""\
[project]
name = "my-app"
requires-python = ">=3.12"

[project.dependencies]
fastapi = ">=0.111"
pydantic = ">=2.0"
sqlalchemy = ">=2.0"
""")
        results = extract_pyproject(toml)
        by_slot = {c.slot: c for c in results}

        assert "language" in by_slot
        assert "3.12" in by_slot["language"].value

        assert "key-libraries" in by_slot
        libs = by_slot["key-libraries"].value
        assert "fastapi" in libs or any("fastapi" in str(l) for l in libs)

        for c in results:
            assert c.extractor == "config-parser"
            assert c.confidence == "high"
            assert "pyproject.toml" in c.source

    def test_with_poetry(self, tmp_path: Path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text("""\
[tool.poetry]
name = "my-poetry-app"

[tool.poetry.dependencies]
python = "^3.11"
django = "^5.0"
celery = "^5.3"
""")
        results = extract_pyproject(toml)
        by_slot = {c.slot: c for c in results}
        assert "language" in by_slot
        assert "key-libraries" in by_slot

    def test_with_build_backend(self, tmp_path: Path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text("""\
[project]
name = "my-app"
requires-python = ">=3.12"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
""")
        results = extract_pyproject(toml)
        by_slot = {c.slot: c for c in results}
        assert "build-tool" in by_slot
        assert "hatch" in by_slot["build-tool"].value.lower()

    def test_missing_file(self, tmp_path: Path):
        results = extract_pyproject(tmp_path / "nonexistent.toml")
        assert results == []

    def test_empty_file(self, tmp_path: Path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text("")
        results = extract_pyproject(toml)
        assert results == []

    def test_detects_framework(self, tmp_path: Path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text("""\
[project]
name = "my-app"
requires-python = ">=3.12"

[project.dependencies]
flask = ">=3.0"
""")
        results = extract_pyproject(toml)
        by_slot = {c.slot: c for c in results}
        assert "framework" in by_slot
        assert "flask" in by_slot["framework"].value.lower()

    def test_package_manager_uv(self, tmp_path: Path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text("""\
[project]
name = "my-app"
requires-python = ">=3.12"

[tool.uv]
dev-dependencies = ["pytest"]
""")
        results = extract_pyproject(toml)
        by_slot = {c.slot: c for c in results}
        assert "package-manager" in by_slot
        assert by_slot["package-manager"].value == "uv"


class TestExtractDockerfile:
    def test_basic_dockerfile(self, tmp_path: Path):
        df = tmp_path / "Dockerfile"
        df.write_text("FROM python:3.12-slim\nRUN pip install poetry\n")
        results = extract_dockerfile(df)
        assert len(results) >= 1
        by_slot = {c.slot: c for c in results}
        assert "docker" in by_slot
        assert "python:3.12-slim" in by_slot["docker"].value

    def test_multi_stage(self, tmp_path: Path):
        df = tmp_path / "Dockerfile"
        df.write_text("FROM node:20-alpine AS builder\nRUN npm ci\nFROM node:20-alpine\n")
        results = extract_dockerfile(df)
        assert len(results) >= 1
        assert "node:20-alpine" in results[0].value

    def test_missing_file(self, tmp_path: Path):
        results = extract_dockerfile(tmp_path / "Dockerfile")
        assert results == []

    def test_scratch_image(self, tmp_path: Path):
        df = tmp_path / "Dockerfile"
        df.write_text("FROM scratch\nCOPY binary /\n")
        results = extract_dockerfile(df)
        assert results == []


class TestExtractDockerCompose:
    def test_postgres_service(self, tmp_path: Path):
        dc = tmp_path / "docker-compose.yaml"
        dc.write_text("""\
services:
  db:
    image: postgres:16-alpine
  app:
    build: .
""")
        results = extract_docker_compose(dc)
        by_slot = {c.slot: c for c in results}
        assert "database" in by_slot
        assert "PostgreSQL" in by_slot["database"].value
        assert "16" in by_slot["database"].value

    def test_redis_service(self, tmp_path: Path):
        dc = tmp_path / "docker-compose.yaml"
        dc.write_text("""\
services:
  cache:
    image: redis:7-alpine
""")
        results = extract_docker_compose(dc)
        assert any("Redis" in c.value for c in results)

    def test_no_db_services(self, tmp_path: Path):
        dc = tmp_path / "docker-compose.yaml"
        dc.write_text("""\
services:
  app:
    build: .
""")
        results = extract_docker_compose(dc)
        assert results == []

    def test_missing_file(self, tmp_path: Path):
        results = extract_docker_compose(tmp_path / "docker-compose.yaml")
        assert results == []


class TestExtractPackageJson:
    def test_react_project(self, tmp_path: Path):
        pj = tmp_path / "package.json"
        pj.write_text("""\
{
  "name": "my-app",
  "dependencies": {
    "react": "^18.2",
    "react-dom": "^18.2"
  },
  "engines": {
    "node": ">=20"
  }
}
""")
        results = extract_package_json(pj)
        by_slot = {c.slot: c for c in results}
        assert "framework" in by_slot
        assert "React" in by_slot["framework"].value
        assert "language" in by_slot
        assert "20" in by_slot["language"].value

    def test_express_project(self, tmp_path: Path):
        pj = tmp_path / "package.json"
        pj.write_text("""\
{
  "dependencies": {
    "express": "^4.18",
    "cors": "^2.8"
  }
}
""")
        results = extract_package_json(pj)
        by_slot = {c.slot: c for c in results}
        assert "framework" in by_slot
        assert "Express" in by_slot["framework"].value

    def test_missing_file(self, tmp_path: Path):
        results = extract_package_json(tmp_path / "package.json")
        assert results == []


class TestExtractGitHubActions:
    def test_basic_workflow(self, tmp_path: Path):
        wf = tmp_path / "ci.yaml"
        wf.write_text("""\
name: CI
on:
  push:
    branches: [main]
  pull_request: {}
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
""")
        results = extract_github_actions(wf)
        assert len(results) == 1
        assert results[0].slot == "ci"
        assert results[0].value == "GitHub Actions"
        assert "CI" in results[0].evidence

    def test_missing_file(self, tmp_path: Path):
        results = extract_github_actions(tmp_path / "ci.yaml")
        assert results == []
