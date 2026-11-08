"""Publication constraints survive the tool/service boundary and precede retrieval."""

import importlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from plugins.corpus.retrieval import native_live, native_pg
from plugins.corpus.retrieval.native import NativeBlock
from plugins.corpus.service import CorpusService

search_tool = importlib.import_module("plugins.tools.corpus_search")


@pytest.mark.parametrize(
    "start,end",
    [
        ("2024-02-30", None),
        ("yesterday", None),
        ("2024-03-02", "2024-03-01"),
        ("20240301", None),
        ("", None),
    ],
)
async def test_invalid_dates_fail_before_service(monkeypatch, start, end):
    service = Mock()
    monkeypatch.setattr(search_tool, "get_service", service)
    result = json.loads(
        await search_tool.corpus_search.func("topic", published_from=start, published_to=end)
    )
    assert result["ok"] is False
    service.assert_not_called()


async def test_date_only_tool_reaches_native_service(monkeypatch):
    service = object.__new__(CorpusService)
    service._dsn, service._target_db = "unused", "vector_pilot_test"
    monkeypatch.setattr(service, "read_chain", lambda: "new")
    monkeypatch.setenv("CORPUS_NATIVE_RETRIEVAL", "pilot")
    monkeypatch.setattr(native_live, "enabled", lambda _: True)
    backend = Mock(return_value=([], {"native": {"unknown_date_sources": ["private-id"]}}))
    monkeypatch.setattr(native_live, "search", backend)
    monkeypatch.setattr(search_tool, "get_service", lambda: service)
    result = json.loads(
        await search_tool.corpus_search.func(
            "", published_from="2024-02-29", published_to="2024-02-29"
        )
    )
    assert result["ok"]
    assert backend.call_args.kwargs["published_from"] == "2024-02-29"
    assert backend.call_args.kwargs["published_to"] == "2024-02-29"
    assert "private-id" not in json.dumps(result)
    native = result["coverage"]["native"]
    assert native["unknown_date_source_ids_omitted"] is True
    assert "unknown_date_sources_omitted" not in native


def native_fixture(monkeypatch):
    dates = [
        {"source_id": "a", "date": "2024-02-29", "basis": "reviewed_metadata", "names": []},
        {"source_id": "b", "date": "2024-02-29", "basis": "admission", "names": []},
        {"source_id": "c", "date": "2024-02-28", "basis": "admission", "names": []},
        {"source_id": "d", "date": None, "basis": "unknown_retained", "names": []},
        {"source_id": "e", "date": "2024-02-29", "basis": "unambiguous_filename_date", "names": []},
    ]
    chunks = [
        {
            "source_id": d["source_id"],
            "build_id": d["source_id"],
            "chunk_id": str(i),
            "input_hash": str(i),
            "kind": "body",
            "title_text": "title",
            "search_text": "body",
        }
        for d in dates
        for i in range(3)
    ]
    index = SimpleNamespace(
        dates=dates,
        chunks=chunks,
        target="vector_pilot_test",
        manifest={"cutoff": "2024-03-01", "profile": "test"},
        vectors={},
        index_id="snapshot",
    )
    conn = MagicMock()
    conn.__enter__.return_value = conn
    monkeypatch.setattr(native_pg.psycopg, "connect", Mock(return_value=conn))
    monkeypatch.setattr(native_pg, "check_native_target", lambda _: None)
    monkeypatch.setattr(native_pg, "_check_target", lambda *_: None)
    snapshot = Mock()
    monkeypatch.setattr(native_pg, "_snapshot", snapshot)

    def blocks(cur, scoped):
        by_id = {d["source_id"]: d["date"] for d in scoped.dates}
        return {
            (c["build_id"], c["chunk_id"]): NativeBlock(
                c["source_id"],
                c["build_id"],
                c["chunk_id"],
                by_id[c["source_id"]],
                "Some original evidence.",
                (),
            )
            for c in scoped.chunks
        }

    monkeypatch.setattr(native_pg, "_load_blocks", blocks)
    vector = Mock(side_effect=AssertionError("date-only must not embed"))
    monkeypatch.setattr(native_pg, "query_vector", vector)
    monkeypatch.setattr(native_live, "configured_seed", lambda _: index)
    monkeypatch.setattr(native_live, "refresh", lambda *_: index)
    return index, snapshot, vector


def test_date_only_selects_distinct_sources_without_embedding(monkeypatch):
    index, snapshot, vector = native_fixture(monkeypatch)
    result = native_pg.search_native(
        "", index.target, "", index, published_from="2024-02-29", published_to="2024-02-29"
    )
    assert [b.source_id for b in result.blocks] == ["a", "b"]
    assert result.retrieval_mode == "publication_date"
    assert result.unknown_date_sources == ("d",)
    vector.assert_not_called()
    snapshot.assert_called()
    assert len(index.chunks) == 15  # no shared-index mutation


def test_date_only_coverage_distinguishes_unknown_inferred_and_matches(monkeypatch):
    native_fixture(monkeypatch)
    hits, coverage = native_live.search(
        "", "vector_pilot_test", "", 1, published_from="2024-02-29", published_to="2024-02-29"
    )
    assert len(hits) == 1
    date_filter = coverage["date_filter"]
    assert date_filter["unknown_date_source_count"] == 1
    assert date_filter["inferred_date_source_count"] == 1
    assert date_filter["matching_source_count"] == 2
    assert date_filter["unknown_date_policy"] == "excluded"
    assert date_filter["scope"] == "native_source_allowlist"
    assert hits[0].publication_date_basis == "reviewed_metadata"


def test_date_miss_does_not_claim_global_absence(monkeypatch):
    native_fixture(monkeypatch)
    hits, coverage = native_live.search(
        "", "vector_pilot_test", "", 10, published_from="2025-01-01", published_to="2025-01-01"
    )
    assert hits == []
    assert coverage["availability"] == "unknown"
    assert coverage["date_filter"]["matching_source_count"] == 0


def test_date_only_requires_a_bound(monkeypatch):
    index, _, _ = native_fixture(monkeypatch)
    with pytest.raises(ValueError):
        native_pg.search_native("", index.target, "", index)


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (None, "2024-02-28", {"c"}),
        ("2024-02-29", None, {"a", "b"}),
        ("2024-02-28", "2024-02-29", {"a", "b", "c"}),
    ],
)
def test_open_and_inclusive_ranges(monkeypatch, start, end, expected):
    index, _, _ = native_fixture(monkeypatch)
    result = native_pg.search_native(
        "", index.target, "", index, published_from=start, published_to=end
    )
    assert {b.source_id for b in result.blocks} == expected


def test_keyword_date_filter_precedes_both_retrieval_channels(monkeypatch):
    index, _, _ = native_fixture(monkeypatch)
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
        "", index.target, "topic", index, published_from="2024-02-29", published_to="2024-02-29"
    )
    scoped = prepared.call_args.args[1]
    assert {c["source_id"] for c in scoped.chunks} == {"a", "b"}
    sql = [c.args[0] for c in cur.execute.call_args_list]
    assert any("pg_temp.native_chunks AS c" in q for q in sql)
    assert any("pg_temp.native_chunks c" in q and "distance" in q for q in sql)
    assert len(index.chunks) == 15


def test_date_only_uses_snapshot_guard(monkeypatch):
    index, snapshot, _ = native_fixture(monkeypatch)
    from plugins.corpus.preparation.read_pg import WithdrawnError

    snapshot.side_effect = WithdrawnError("withdrawn")
    with pytest.raises(WithdrawnError):
        native_pg.search_native("", index.target, "", index, published_from="2024-02-29")


def test_non_native_date_only_skips_semantic_selection(monkeypatch):
    from plugins.corpus.preparation import read_pg, search_pg

    service = object.__new__(CorpusService)
    service._dsn, service._target_db = "unused", "vector_pilot_test"
    monkeypatch.setattr(service, "read_chain", lambda: "new")
    monkeypatch.setenv("CORPUS_NATIVE_RETRIEVAL", "off")
    monkeypatch.setenv("CORPUS_RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("CORPUS_RETRIEVAL_RANKING", "off")
    hit = search_pg.SearchHit("a", "b", "c", "body", "title", (), (), 0.0, published="2024-02-29")
    backend = Mock(return_value=((hit,), {"a": ("c",)}, {"availability": "unknown"}))
    monkeypatch.setattr(read_pg, "search_with_coverage_bands", backend)
    monkeypatch.setattr(read_pg, "fetch_chunk_kinds", lambda *args, **kwargs: {("b", "c"): "body"})
    monkeypatch.setattr(
        service, "_selected_context_hits", Mock(side_effect=AssertionError("no ranking"))
    )
    monkeypatch.setattr(
        service, "_abstain_decision", Mock(side_effect=AssertionError("no embedding"))
    )
    hits, coverage = service.search_with_coverage("  ", published_from="2024-02-29")
    assert hits[0].published == "2024-02-29"
    assert hits[0].context_locators == ("chunk:c",)
    assert backend.call_args.args[1] == ""
    assert backend.call_args.kwargs["published_from"] == "2024-02-29"
    assert coverage["date_filter"]["unknown_date_source_count"] is None
    assert search_pg.build_search_params("  ", published_from="2024-02-29")["query"] == ""


def test_legacy_filter_rejected_instead_of_silently_ignored(monkeypatch):
    service = object.__new__(CorpusService)
    monkeypatch.setattr(service, "read_chain", lambda: "legacy")
    monkeypatch.setenv("CORPUS_NATIVE_RETRIEVAL", "off")
    with pytest.raises(Exception, match="requires_new_read_chain"):
        service.search("topic", published_from="2024-02-29")


def test_agent_schema_exposes_date_only_lookup():
    params = search_tool.corpus_search.to_openai_schema()["function"]["parameters"]
    assert {"query", "published_from", "published_to"} <= params["properties"].keys()
    assert "query" not in params.get("required", [])


async def test_tool_preserves_date_basis_in_native_evidence(monkeypatch, tmp_path):
    from dataclasses import asdict

    from plugins.corpus import search_refs
    from plugins.corpus.retrieval.embedding import text_hash
    from plugins.corpus.retrieval.native import NativeSpan
    from plugins.corpus.retrieval.native_live import locator_for
    from plugins.corpus.service import SearchHit

    text = "Verified original passage."
    span = NativeSpan("u", 1, 0, len(text), text_hash(text))
    loc = locator_for("c", text, [asdict(span)])
    hit = SearchHit(
        "cv2:b",
        loc,
        "Title",
        text,
        0.0,
        "2024-02-29",
        source_id="a",
        build_id="b",
        chunk_id="c",
        context_locators=(loc,),
        evidence_spans=(
            {
                "member": 1,
                "start": 0,
                "end": len(text),
                "snippet_start": 0,
                "snippet_end": len(text),
                "text_chars": len(text),
                "text_sha256": text_hash(text),
                "quote_sha256": text_hash(text),
            },
        ),
        publication_date_basis="reviewed_metadata",
    )
    # Use the actual v2 serializer with a local receipt store.
    monkeypatch.setenv("CORPUS_SEARCH_REF_ROOT", str(tmp_path))
    service = Mock()
    service.search_with_coverage.return_value = ([hit], {"native": {}})
    # A nonempty native contract selects native evidence serialization.
    service.search_with_coverage.return_value[1]["native"]["policy"] = "native1"
    monkeypatch.setattr(search_tool, "get_service", lambda: service)
    result = json.loads(await search_tool.corpus_search.func("", published_from="2024-02-29"))
    assert result["ok"]
    assert result["hits"][0]["publication_date_basis"] == "reviewed_metadata"
    assert result["hits"][0]["evidence_contract"] == search_refs.CONTRACT
