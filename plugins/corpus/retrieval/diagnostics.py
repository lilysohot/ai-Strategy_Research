"""Opt-in retrieval observations and pure offline selection experiments.

Never included in agent responses; no database writes or model calls here.
Candidate ranks refer to the bounded SQL pools, not the whole corpus.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

from plugins.corpus.preparation.search_pg import SearchHit
from plugins.corpus.preparation.selection import (
    BandPolicy,
    SelectedBand,
    SelectionPolicy,
    select_band,
)


@dataclass
class RetrievalTrace:
    """Caller-owned observations; use one trace per query."""

    lexical: tuple[SearchHit, ...] = ()
    dense: tuple[SearchHit, ...] = ()
    fused: tuple[SearchHit, ...] = ()
    selected: tuple[SearchHit, ...] = ()
    selectable_bands: tuple[SelectedBand, ...] = ()
    source_limit: int = 5
    chunk_order: dict[str, tuple[str, ...]] = field(default_factory=dict)
    status: str = "not_captured"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def global_rrf(trace: RetrievalTrace) -> tuple[SearchHit, ...]:
    """Experimental global chunk RRF; unlike production, ranks cross sources."""
    scores: dict[tuple[str, str], float] = {}
    hits: dict[tuple[str, str], SearchHit] = {}
    for channel in (trace.lexical, trace.dense):
        seen: set[tuple[str, str]] = set()
        for hit in channel:
            key = (hit.build_id, hit.chunk_id)
            if key in seen:
                continue
            seen.add(key)
            scores[key] = scores.get(key, 0.0) + 1 / (60 + len(seen))
            hits.setdefault(key, hit)
    return tuple(
        replace(hits[key], score=scores[key])
        for key in sorted(hits, key=lambda key: (-scores[key], key))
    )


def relevance_bands(
    trace: RetrievalTrace, *, limit: int = 10, source_cap: int = 3
) -> tuple[SearchHit, ...]:
    """Offline alternative: global chunk RRF, all sources, bounded source share.

    This jointly changes fusion and selection, so it is NOT a scheduling-only
    ablation. Existing band formation and per-source band cap are retained.
    source_cap is fixed before evaluation; unused slots are not backfilled.
    """
    if trace.status != "hybrid":
        raise ValueError("hybrid_trace_required")
    if limit < 1 or source_cap < 1:
        raise ValueError("positive_selection_limits_required")
    ranked = global_rrf(trace)
    bands = select_band(
        ranked,
        SelectionPolicy(top_k=max(1, len(trace.chunk_order))),
        BandPolicy(),
        chunk_order_by_source=trace.chunk_order,
    )
    by_key = {(hit.build_id, hit.chunk_id): hit for hit in ranked}
    used: dict[str, int] = {}
    result: list[SearchHit] = []
    for band in sorted(bands, key=lambda band: (-band.score, band.source_id, band.start)):
        if used.get(band.source_id, 0) >= source_cap:
            continue
        ordered = trace.chunk_order[band.source_id]
        anchor = max(
            (by_key[(band.build_id, ordered[pos])] for pos in band.pool),
            key=lambda hit: (hit.score, hit.chunk_id),
        )
        result.append(replace(anchor, context_chunk_ids=ordered[band.start : band.end + 1]))
        used[band.source_id] = used.get(band.source_id, 0) + 1
        if len(result) >= limit:
            break
    return tuple(result)


def candidate_fates(
    trace: RetrievalTrace, selected: tuple[SearchHit, ...] | None = None
) -> list[dict[str, object]]:
    """Explain candidate delivery without treating unlabelled material as wrong."""
    selected = trace.selected if selected is None else selected
    delivered = {
        (hit.build_id, chunk)
        for hit in selected
        for chunk in (hit.context_chunk_ids or (hit.chunk_id,))
    }
    anchors = {(hit.build_id, hit.chunk_id) for hit in selected}
    first_sources = list(dict.fromkeys(hit.source_id for hit in trace.fused))[
        : trace.source_limit
    ]
    selectable = {
        (band.build_id, chunk)
        for band in trace.selectable_bands
        for chunk in trace.chunk_order[band.source_id][band.start : band.end + 1]
    }
    ranks = [
        {(hit.build_id, hit.chunk_id): i + 1 for i, hit in enumerate(channel)}
        for channel in (trace.lexical, trace.dense, trace.fused)
    ]
    result: list[dict[str, object]] = []
    for hit in trace.fused:
        key = (hit.build_id, hit.chunk_id)
        result.append(
            {
                "source_id": hit.source_id,
                "build_id": hit.build_id,
                "chunk_id": hit.chunk_id,
                "lexical_rank": ranks[0].get(key),
                "dense_rank": ranks[1].get(key),
                "fused_rank": ranks[2].get(key),
                "delivery": (
                    "anchor" if key in anchors else "context" if key in delivered else "omitted"
                ),
                "baseline_source_gate": hit.source_id in first_sources,
                "omission_stage": (
                    None
                    if key in delivered
                    else "source_gate"
                    if hit.source_id not in first_sources
                    else "output_limit"
                    if key in selectable
                    else "band_selection"
                ),
            }
        )
    return result
