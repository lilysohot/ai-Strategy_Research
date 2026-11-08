"""Independent ingestion dates: API propagation, local-day boundaries and pre-ranking scope."""

import importlib
import json
from datetime import UTC
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_corpus_publication_range import native_fixture

from plugins.corpus.ingestion_dates import ingestion_range
from plugins.corpus.retrieval import native_live, native_pg
from plugins.corpus.service import CorpusService

search_tool = importlib.import_module("plugins.tools.corpus_search")


@pytest.mark.parametrize(
    "options",
    [
        {"ingested_from": "2024-02-30"},
        {"ingested_to": ""},
        {"ingested_from": "2024-03-02", "ingested_to": "2024-03-01"},
        {"ingested_to": "9999-12-31"},
        {"ingested_from": "20240301"},
        {"ingested_from": "2024-03-01", "ingested_timezone": "Mars/Base"},
    ],
)
async def test_bad_ingestion_filter_never_opens_service(monkeypatch, options):
    service = Mock()
    monkeypatch.setattr(search_tool, "get_service", service)
    result = json.loads(await search_tool.corpus_search.func("", **options))
    assert result["ok"] is False
    assert "ingested_" in result["error"]
    service.assert_not_called()


def test_local_day_boundaries_and_dst():
    bounds = ingestion_range("2024-03-01", "2024-03-01")
    assert bounds.matches("2024-02-29T16:00:00+00:00")
    assert bounds.matches("2024-03-01T15:59:59.999999+00:00")
    assert not bounds.matches("2024-02-29T15:59:59.999999+00:00")
    assert not bounds.matches("2024-03-01T16:00:00+00:00")
    assert not bounds.matches(None)
    dst = ingestion_range("2024-03-10", "2024-03-10", "America/New_York")
    assert (dst.end.astimezone(UTC) - dst.start.astimezone(UTC)).total_seconds() == 23 * 3600


def ingestion_fixture(monkeypatch):
    index, snapshot, vector = native_fixture(monkeypatch)
    times = [
        None,
        "2024-03-01T16:00:00+00:00",
        "2024-02-29T15:59:59+00:00",
        "2024-02-29T16:00:00+00:00",
        "2024-03-01T15:59:59+00:00",
    ]
    for record, stamp in zip(index.dates, times, strict=True):
        record["ingested_at"] = stamp
    monkeypatch.setattr(native_live, "refresh", lambda *args, **kwargs: index)
    return index, snapshot, vector


def test_ingestion_only_includes_unknown_and_inferred_publication(monkeypatch):
    index, snapshot, vector = ingestion_fixture(monkeypatch)
    result = native_pg.search_native(
        "", index.target, "", index, ingested_from="2024-03-01", ingested_to="2024-03-01"
    )
    assert {b.source_id for b in result.blocks} == {"d", "e"}
    assert result.retrieval_mode == "ingestion_date"
    assert len(index.chunks) == 15
    vector.assert_not_called()
    snapshot.assert_called()


def test_combined_filters_take_intersection(monkeypatch):
    index, _, _ = ingestion_fixture(monkeypatch)
    result = native_pg.search_native(
        "",
        index.target,
        "",
        index,
        published_from="2024-02-29",
        ingested_from="2024-03-01",
        ingested_to="2024-03-02",
    )
    assert {b.source_id for b in result.blocks} == {"b"}
    assert result.retrieval_mode == "metadata_date"


def test_ingestion_coverage_and_timestamp_survive_native_facade(monkeypatch):
    ingestion_fixture(monkeypatch)
    hits, coverage = native_live.search(
        "", "vector_pilot_test", "", 10, ingested_from="2024-03-01", ingested_to="2024-03-01"
    )
    assert {h.source_id for h in hits} == {"d", "e"}
    assert all(h.ingested_at for h in hits)
    assert coverage["ingestion_filter"]["unknown_time_source_count"] == 1
    assert coverage["ingestion_filter"]["matching_source_count"] == 2
    assert "date_filter" not in coverage


def test_ingestion_keyword_filters_before_both_candidate_channels(monkeypatch):
    index, _, _ = ingestion_fixture(monkeypatch)
    conn = native_pg.psycopg.connect.return_value
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (["topic"],)
    cur.fetchall.return_value = []
    config = SimpleNamespace(target_db=index.target, profile="test", dimensions=2)
    monkeypatch.setattr(native_pg.VectorConfig, "from_env", lambda: config)
    monkeypatch.setattr(native_pg, "query_vector", Mock(return_value=([1.0, 0.0], None, None)))
    prepared = Mock()
    monkeypatch.setattr(native_pg, "_prepare", prepared)
    native_pg.search_native(
        "", index.target, "topic", index, ingested_from="2024-03-01", ingested_to="2024-03-01"
    )
    scoped = prepared.call_args.args[1]
    assert {c["source_id"] for c in scoped.chunks} == {"d", "e"}
    sql = [call.args[0] for call in cur.execute.call_args_list]
    assert any("pg_temp.native_chunks AS c" in q for q in sql)
    assert any("pg_temp.native_chunks c" in q and "distance" in q for q in sql)


async def test_tool_service_forwards_both_ranges(monkeypatch):
    service = object.__new__(CorpusService)
    service._dsn, service._target_db = "unused", "vector_pilot_test"
    monkeypatch.setattr(service, "read_chain", lambda: "new")
    monkeypatch.setenv("CORPUS_NATIVE_RETRIEVAL", "pilot")
    monkeypatch.setattr(native_live, "enabled", lambda _: True)
    backend = Mock(return_value=([], {"native": {"policy": "native1"}}))
    monkeypatch.setattr(native_live, "search", backend)
    monkeypatch.setattr(search_tool, "get_service", lambda: service)
    result = json.loads(
        await search_tool.corpus_search.func(
            "", published_to="2024-02-29", ingested_from="2024-03-01", ingested_timezone="UTC"
        )
    )
    assert result["ok"]
    assert backend.call_args.kwargs == dict(
        published_from=None,
        published_to="2024-02-29",
        ingested_from="2024-03-01",
        ingested_to=None,
        ingested_timezone="UTC",
    )


async def test_http_date_only_and_invalid_range(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from server.routes import corpus

    app = FastAPI()
    app.include_router(corpus.router)
    app.dependency_overrides[corpus.get_current_user] = lambda: SimpleNamespace(id=1)
    service = Mock()
    service.search_with_coverage.return_value = ([], {"availability": "unknown"})
    monkeypatch.setattr(corpus, "_corpus_service", lambda: service)
    with TestClient(app) as client:
        response = client.get("/api/corpus/search", params={"ingested_from": "2024-03-01"})
        assert response.status_code == 200
        assert service.search_with_coverage.call_args.kwargs["ingested_from"] == "2024-03-01"
        service.reset_mock()
        assert client.get("/api/corpus/search", params={"ingested_from": "bad"}).status_code == 422
        assert client.get("/api/corpus/search").status_code == 422
        service.search_with_coverage.assert_not_called()


def test_legacy_ingestion_filter_fails_explicitly(monkeypatch):
    service = object.__new__(CorpusService)
    monkeypatch.setattr(service, "read_chain", lambda: "legacy")
    monkeypatch.setenv("CORPUS_NATIVE_RETRIEVAL", "off")
    with pytest.raises(Exception, match="requires_new_read_chain"):
        service.search("topic", ingested_from="2024-03-01")


def test_non_native_ingestion_only_is_forwarded_and_skips_ranking(monkeypatch):
    from plugins.corpus.preparation import read_pg, search_pg

    service = object.__new__(CorpusService)
    service._dsn, service._target_db = "unused", "vector_pilot_test"
    monkeypatch.setattr(service, "read_chain", lambda: "new")
    monkeypatch.setenv("CORPUS_NATIVE_RETRIEVAL", "off")
    monkeypatch.setenv("CORPUS_RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("CORPUS_RETRIEVAL_RANKING", "off")
    hit = search_pg.SearchHit(
        "a", "b", "c", "body", "title", (), (), 0.0, ingested_at="2024-03-01T00:00:00+00:00"
    )
    backend = Mock(return_value=((hit,), {"a": ("c",)}, {"availability": "unknown"}))
    monkeypatch.setattr(read_pg, "search_with_coverage_bands", backend)
    monkeypatch.setattr(read_pg, "fetch_chunk_kinds", lambda *a, **kw: {("b", "c"): "body"})
    monkeypatch.setattr(
        service, "_selected_context_hits", Mock(side_effect=AssertionError("ranking"))
    )
    hits, cov = service.search_with_coverage("", ingested_from="2024-03-01")
    assert hits[0].ingested_at == hit.ingested_at
    assert hits[0].published == "undated"
    assert cov["retrieval_mode"] == "ingestion_date"
    assert "date_filter" not in cov
    assert backend.call_args.kwargs["ingested_from"] == "2024-03-01"


def test_agent_schema_exposes_both_independent_date_ranges():
    schema = search_tool.corpus_search.to_openai_schema()["function"]["parameters"]
    assert {
        "published_from",
        "published_to",
        "ingested_from",
        "ingested_to",
        "ingested_timezone",
    } <= schema["properties"].keys()
    assert "query" not in schema.get("required", [])


def test_native_snapshot_rejects_changed_ingestion_time():
    from datetime import UTC, datetime

    from plugins.corpus.preparation.read_pg import IntegrityError

    cur = Mock()
    cur.fetchall.side_effect = [
        [("a", "build", 1)],
        [("a", "in_scope", [], None, "in_scope", None)],
        [("a", datetime(2024, 3, 2, tzinfo=UTC))],
    ]
    index = SimpleNamespace(
        manifest={"publications": [["a", "build", 1]], "source_allowlist": ["a"]},
        dates=[
            dict(
                source_id="a",
                names=[],
                date=None,
                basis="unknown_retained",
                ingested_at="2024-03-01T00:00:00+00:00",
            )
        ],
    )
    with pytest.raises(IntegrityError, match="ingestion_changed"):
        native_pg._snapshot(cur, index)
