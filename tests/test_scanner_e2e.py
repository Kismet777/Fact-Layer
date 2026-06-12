# tests/test_scanner_e2e.py
"""End-to-end integration test: scan a realistic project, verify full pipeline."""

from pathlib import Path

from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.scanner.pipeline import run_scan


def _build_realistic_project(tmp_path: Path) -> Path:
    proj = tmp_path / "realistic-project"
    proj.mkdir()
    init_facts_dir(
        target=proj,
        project_name="realistic-project",
        language="Python 3.12",
        enabled_extensions=["data-model", "build-deploy", "api-contracts", "testing"],
        enabled_optional=["decisions"],
    )

    (proj / "pyproject.toml").write_text("""\
[project]
name = "realistic-project"
requires-python = ">=3.12"

[project.dependencies]
fastapi = ">=0.111"
pydantic = ">=2.0"
sqlalchemy = ">=2.0"
alembic = ">=1.13"
uvicorn = ">=0.30"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = ["pytest>=8.0", "httpx>=0.27"]
""")

    (proj / "Dockerfile").write_text("""\
FROM python:3.12-slim AS builder
RUN pip install uv
COPY . .
RUN uv sync

FROM python:3.12-slim
COPY --from=builder /app /app
CMD ["uvicorn", "app.main:app"]
""")

    (proj / "docker-compose.yaml").write_text("""\
services:
  app:
    build: .
    ports:
      - "8000:8000"
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: myapp
  redis:
    image: redis:7-alpine
""")

    wf_dir = proj / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "ci.yaml").write_text("""\
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
      - run: pytest
""")

    return proj


class TestEndToEnd:
    def test_full_scan(self, tmp_path: Path):
        proj = _build_realistic_project(tmp_path)
        result = run_scan(proj)

        assert result.stats.files_scanned >= 4

        slot_refs = {c.slot_ref for c in result.candidates}
        assert "tech-stack.language" in slot_refs
        assert "tech-stack.framework" in slot_refs
        assert "tech-stack.key-libraries" in slot_refs
        assert "tech-stack.package-manager" in slot_refs
        assert "build-deploy.build-tool" in slot_refs
        assert "build-deploy.docker" in slot_refs
        assert "build-deploy.ci" in slot_refs

        db_candidates = [
            c for c in result.candidates if c.slot == "database"
        ] + [
            c for cg in result.conflicts for c in cg.candidates if c.slot == "database"
        ]
        assert len(db_candidates) >= 1

    def test_category_filter_reduces_output(self, tmp_path: Path):
        proj = _build_realistic_project(tmp_path)
        full = run_scan(proj)
        filtered = run_scan(proj, categories=["build-deploy"])
        assert filtered.stats.candidates_found <= full.stats.candidates_found
        for c in filtered.candidates:
            assert c.category == "build-deploy"

    def test_all_candidates_have_evidence(self, tmp_path: Path):
        proj = _build_realistic_project(tmp_path)
        result = run_scan(proj)
        for c in result.candidates:
            assert c.evidence, f"Missing evidence for {c.slot_ref}"
            assert c.source, f"Missing source for {c.slot_ref}"
            assert c.extractor == "config-parser"
            assert c.confidence in ("high", "medium", "low")

    def test_scan_result_serializable(self, tmp_path: Path):
        import json

        proj = _build_realistic_project(tmp_path)
        result = run_scan(proj)
        data = result.model_dump(mode="json")
        json_str = json.dumps(data)
        roundtrip = json.loads(json_str)
        assert roundtrip["stats"]["files_scanned"] == result.stats.files_scanned
