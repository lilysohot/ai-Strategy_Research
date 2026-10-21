"""Trace delivery and offline relevance experiments, without provider calls."""

from dataclasses import replace

import pytest

from plugins.corpus.preparation.search_pg import SearchHit
from plugins.corpus.preparation.selection import SelectedBand
from plugins.corpus.retrieval.diagnostics import (
    RetrievalTrace,
    candidate_fates,
    global_rrf,
    relevance_bands,
)
from plugins.corpus.retrieval.hybrid import fuse
from plugins.corpus.service import CorpusService


def hit(source, position):
    return SearchHit(source, "build-" + source, str(position), "paragraph", "", (), (), 1.0)


def test_recording_does_not_change_selection_and_explains_dropped_candidates():
    lexical = tuple(hit(source, position) for source in "abcdef" for position in (0, 6))
    fused = fuse(lexical, lexical)
    trace = RetrievalTrace(
        lexical=lexical, dense=lexical, fused=fused,
        chunk_order={s: tuple(str(i) for i in range(10)) for s in "abcdef"},
        status="hybrid",
    )
    service = CorpusService.__new__(CorpusService)
    kwargs = dict(limit=5, lexical_fallback_hits=lexical)
    without = service._selected_context_hits(fused, trace.chunk_order, **kwargs)
    trace.selected = service._selected_context_hits(
        fused, trace.chunk_order, trace=trace, **kwargs
    )
    assert trace.selected == without
    assert len(trace.selectable_bands) == 10
    fates = candidate_fates(trace)
    assert {row["omission_stage"] for row in fates} == {None, "source_gate", "output_limit"}
    assert all(row["omission_stage"] == "source_gate" for row in fates if row["source_id"] == "f")


def test_global_rank_can_deliver_source_outside_baseline_gate_and_bounds_share():
    lexical = tuple(hit(s, 0) for s in "abcdef")
    dense = (hit("f", 0), hit("f", 5), hit("f", 10), hit("f", 15))
    trace = RetrievalTrace(
        lexical=lexical, dense=dense, fused=fuse(lexical, dense),
        chunk_order={s: tuple(str(i) for i in range(20)) for s in "abcdef"},
        status="hybrid",
    )
    selected = relevance_bands(trace, limit=10, source_cap=2)
    assert selected[0].source_id == "f"
    assert sum(h.source_id == "f" for h in selected) <= 2
    assert len(selected) <= 10
    assert len({h.source_id for h in selected}) == 6
    assert global_rrf(trace) == global_rrf(replace(trace, lexical=(*lexical, lexical[0])))
    with pytest.raises(ValueError, match="hybrid_trace_required"):
        relevance_bands(replace(trace, status="lexical_fallback"))


def test_context_delivery_is_not_mistaken_for_dropped_anchor():
    first, adjacent, distant = hit("a", 0), hit("a", 1), hit("a", 8)
    trace = RetrievalTrace(
        lexical=(first, adjacent, distant), fused=(first, adjacent, distant),
        selected=(replace(first, context_chunk_ids=("0", "1")),),
        selectable_bands=(SelectedBand("a", "build-a", 0, 1, 1, (0, 1)),),
        chunk_order={"a": tuple(str(i) for i in range(10))},
    )
    rows = candidate_fates(trace)
    assert rows[1]["delivery"] == "context"
    assert rows[1]["omission_stage"] is None
    assert rows[2]["omission_stage"] == "band_selection"
