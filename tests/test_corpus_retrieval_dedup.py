"""Evidence-preserving compaction, including version and header boundaries."""

from dataclasses import replace
from itertools import permutations

from plugins.corpus.preparation.search_pg import SearchHit
from plugins.corpus.retrieval.dedup import dedupe_contained_hits


def hit(scope=(), **changes):
    value = SearchHit(
        "source", "build", "anchor", "table", "title", (), (), 1.0, context_chunk_ids=scope
    )
    return replace(value, **changes)


def identities(hits):
    return {
        (h.source_id, h.build_id, c) for h in hits for c in (h.context_chunk_ids or (h.chunk_id,))
    }


def test_superset_keeps_first_rank_metadata_and_table_header():
    first = hit(("anchor",), score=9.0, snippet="first")
    other = hit(("other",), chunk_id="other")
    later = hit(("header", "anchor", "next"), score=1.0)
    result = dedupe_contained_hits((first, other, later))
    assert result == (replace(first, context_chunk_ids=later.context_chunk_ids), other)
    assert identities(result) == identities((first, other, later))


def test_overlapping_scopes_only_collapse_when_an_existing_superset_arrives():
    left = hit(("left", "anchor"))
    right = hit(("anchor", "right"))
    assert dedupe_contained_hits((left, right)) == (left, right)
    superset = hit(("left", "anchor", "right"))
    for values in permutations((left, right, superset, hit())):
        result = dedupe_contained_hits(values)
        assert len(result) == 1
        assert result[0].context_chunk_ids == superset.context_chunk_ids
        assert identities(result) == identities(values)
        assert dedupe_contained_hits(result) == result


def test_versions_sources_and_distinct_anchors_are_never_merged():
    base = hit(("anchor", "next"))
    values = (
        base,
        replace(base, build_id="new-build"),
        replace(base, source_id="other-source"),
        replace(base, chunk_id="next"),
    )
    assert dedupe_contained_hits(values) == values


def test_empty_inputs_and_missing_identity_do_not_invent_evidence():
    assert dedupe_contained_hits(()) == ()
    assert dedupe_contained_hits((hit(), hit())) == (hit(),)
    unknown = hit(build_id="")
    assert dedupe_contained_hits((unknown, unknown)) == (unknown, unknown)


def test_public_search_compacts_after_enrichment_and_recomputes_scope(monkeypatch):
    from plugins.corpus.preparation import read_pg, search_pg
    from plugins.corpus.retrieval.diagnostics import RetrievalTrace
    from plugins.corpus.service import CorpusService

    service = CorpusService.__new__(CorpusService)
    service._dsn, service._target_db = "unused", "unused"
    monkeypatch.setenv("CORPUS_RETRIEVAL_MODE", "lexical")
    monkeypatch.setattr(service, "read_chain", lambda: "new")
    monkeypatch.setattr(service, "_abstain_decision", lambda query: False)
    monkeypatch.setattr(search_pg, "query_lexemes", lambda *a, **kw: ("营收",))
    first = hit(("anchor", "next"), kind="body")
    second = hit(("header", "anchor"), kind="body")
    before = (first, second)  # Incomparable until enrichment adds the header.
    order = {"source": ("header", "anchor", "next")}
    monkeypatch.setattr(read_pg, "search_with_coverage_bands", lambda *a, **kw: (before, order, {}))
    monkeypatch.setattr(service, "_selected_context_hits", lambda *a, **kw: before)

    def enrich(hits, chunk_order, structures):
        assert hits == before
        return (replace(first, context_chunk_ids=("header", "anchor", "next")), second)

    monkeypatch.setattr(service, "_attach_table_header_context", enrich)
    monkeypatch.setattr(read_pg, "fetch_chunk_kinds", lambda dsn, pairs, **kw: {
        pair: "table" if pair[1] == "header" else "body" for pair in pairs
    })
    trace = RetrievalTrace()
    public, _ = service.search_with_coverage("营收", limit=2, trace=trace)
    assert len(public) == len(trace.selected) == 1
    assert public[0].context_locators == tuple(
        read_pg.chunk_locator(c) for c in ("header", "anchor", "next")
    )
    assert dict(public[0].context_by_kind) == {"body": 2, "table": 1}
    assert trace.selected[0].context_chunk_ids == ("header", "anchor", "next")
