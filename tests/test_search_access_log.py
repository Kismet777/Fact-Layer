"""Search touch-attribution in the access log (slot×op cross-tab + invocation)."""

from pathlib import Path

from fact_layer.core.access_log import compute_access_stats, log_access, log_search, read_access


def test_log_search_writes_invocation_plus_per_hit(tmp_path: Path):
    facts = tmp_path / ".facts"
    log_search(facts, "database", ["tech-stack.database", "data-model.db-type"], via="mcp")

    recs = read_access(facts)
    invocations = [r for r in recs if r["op"] == "search"]
    hits = [r for r in recs if r["op"] == "search-hit"]

    assert len(invocations) == 1
    assert invocations[0].get("slot") is None
    assert len(hits) == 2
    assert {r["slot"] for r in hits} == {"tech-stack.database", "data-model.db-type"}


def test_log_search_empty_result_records_invocation_only(tmp_path: Path):
    facts = tmp_path / ".facts"
    log_search(facts, "zzz", [], via="cli")

    recs = read_access(facts)
    assert [r["op"] for r in recs] == ["search"]
    assert recs[0].get("slot") is None


def test_slot_op_cross_tab(tmp_path: Path):
    facts = tmp_path / ".facts"
    # same slot reached two different ways
    log_access(facts, "get", slot="tech-stack.database", via="mcp")
    log_access(facts, "get", slot="tech-stack.database", via="mcp")
    log_search(facts, "db", ["tech-stack.database"], via="mcp")

    stats = compute_access_stats(facts)
    xtab = stats.by_slot_op
    assert xtab["tech-stack.database"]["get"] == 2
    assert xtab["tech-stack.database"]["search-hit"] == 1


def test_facts_search_mcp_returns_hits_and_logs(tmp_path, monkeypatch):
    """MCP facts_search returns structured hits and writes search access records."""
    from fact_layer.core.access_log import read_access
    from fact_layer.core.init_cmd import init_facts_dir
    from fact_layer.core.writer import dump_yaml
    import fact_layer.mcp_server as srv

    project = tmp_path / "proj"
    project.mkdir()
    init_facts_dir(target=project, project_name="p", language="Python 3.12",
                   enabled_extensions=[], enabled_optional=[])
    facts = project / ".facts"
    dump_yaml(facts / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {"database": {"value": "PostgreSQL 16", "meta": {
            "source": "human", "confidence": "high", "status": "active",
            "updated": "2026-06-09", "verified": "2026-06-09"}}},
    })
    monkeypatch.setattr(srv, "resolve_facts_dir", lambda: facts)

    out = srv.facts_search("database")
    assert any(h["slot_ref"] == "tech-stack.database" for h in out["hits"])

    ops = [r["op"] for r in read_access(facts)]
    assert "search" in ops and "search-hit" in ops


def test_search_empty_rate_and_conversion(tmp_path: Path):
    facts = tmp_path / ".facts"
    # two productive searches, one empty
    log_search(facts, "db", ["tech-stack.database"], via="mcp")
    log_search(facts, "lang", ["tech-stack.language"], via="mcp")
    log_search(facts, "zzz", [], via="mcp")
    # only one of the two surfaced slots is later fetched via get
    log_access(facts, "get", slot="tech-stack.database", via="mcp")

    stats = compute_access_stats(facts)
    assert stats.search_total == 3
    assert stats.search_empty == 1
    assert abs(stats.search_empty_rate - 1 / 3) < 1e-6
    # searched slots: database, language; converted (also get'd): database → 1/2
    assert abs(stats.search_to_get_rate - 0.5) < 1e-6


def test_search_metrics_zero_when_no_searches(tmp_path: Path):
    facts = tmp_path / ".facts"
    log_access(facts, "get", slot="tech-stack.database", via="mcp")
    stats = compute_access_stats(facts)
    assert stats.search_total == 0
    assert stats.search_empty_rate is None
    assert stats.search_to_get_rate is None
