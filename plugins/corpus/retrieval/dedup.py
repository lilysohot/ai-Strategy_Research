"""Compact repeated evidence anchors without changing their evidence union."""

from __future__ import annotations

from dataclasses import replace

from plugins.corpus.preparation.search_pg import SearchHit


def dedupe_contained_hits(hits: tuple[SearchHit, ...]) -> tuple[SearchHit, ...]:
    """Keep maximal existing scopes per versioned anchor, at the earliest position.

    Run after context enrichment and output selection. No backfill, synthesized
    ranges or merging of different anchors: every retained scope already existed
    in the input. Incomparable scopes survive even when they overlap.
    """
    output: list[SearchHit] = []
    for hit in hits:
        key = (hit.source_id, hit.build_id, hit.chunk_id)
        if not all(key):
            output.append(hit)
            continue
        current = set(hit.context_chunk_ids or (hit.chunk_id,))
        peers = [
            (i, set(old.context_chunk_ids or (old.chunk_id,)))
            for i, old in enumerate(output)
            if (old.source_id, old.build_id, old.chunk_id) == key
        ]
        if any(current <= previous for _, previous in peers):
            continue
        contained = [i for i, previous in peers if previous <= current]
        if contained:
            first = contained[0]
            output[first] = replace(output[first], context_chunk_ids=hit.context_chunk_ids)
            for i in reversed(contained[1:]):
                del output[i]
        else:
            output.append(hit)
    return tuple(output)
