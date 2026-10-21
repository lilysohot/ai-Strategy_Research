"""Load body features on the candidate transaction; cache immutable snapshots only."""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from types import SimpleNamespace
from typing import TYPE_CHECKING

from plugins.corpus.preparation import read_pg
from plugins.corpus.retrieval.ranking import REVISION, RankingCorpus, RankingSource, scoring_body

if TYPE_CHECKING:
    import psycopg

# Build contents are immutable. Include every mutable input (admission, pointer,
# generation, original names, metadata) in the signature, even when vectors do
# not use a context prefix. Never cache hits, active IDs, or authorization decisions.
_SNAPSHOT_SQL = """
SELECT p.source_id, p.active_build_id, p.generation, p.current_decision_id,
       a.decision, s.original_names, m.institution, m.metadata_hash
FROM corpus.corpus_publications p
JOIN corpus.corpus_sources s ON s.source_id=p.source_id
LEFT JOIN corpus.corpus_admissions a ON a.decision_id=p.current_decision_id
LEFT JOIN corpus_retrieval.source_metadata m ON m.source_id=p.source_id
ORDER BY p.source_id
"""
_CACHE: OrderedDict[tuple[str, ...], RankingCorpus] = OrderedDict()
_LOCK = threading.Lock()


def load_corpus_on(cur: psycopg.Cursor) -> tuple[RankingCorpus, bool]:
    """Use only the caller's checked, repeatable-read connection; no nested reads."""
    cur.execute(_SNAPSHOT_SQL)
    rows = cur.fetchall()
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, default=str).encode()).hexdigest()
    info = cur.connection.info
    key = (
        info.host,
        str(info.port),
        info.dbname,
        info.user,
        REVISION,
        read_pg.AUTHORITY_REV,
        digest,
    )
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached, True
    active = [r for r in rows if r[1] is not None and r[4] == "in_scope"]
    build_ids = [r[1] for r in active]
    cur.execute(
        "SELECT build_id, unit_id, kind, raw_text, location, content_hash "
        "FROM corpus.corpus_units WHERE build_id=ANY(%s::text[]) ORDER BY build_id, ordinal, unit_id",
        (build_ids,),
    )
    units: dict[str, dict[str, tuple[str, str]]] = {bid: {} for bid in build_ids}
    for bid, uid, kind, raw, location, content_hash in cur.fetchall():
        read_pg.verified_unit(bid, uid, raw, location, content_hash)
        units[bid][uid] = (kind, raw)
    cur.execute(
        "SELECT build_id, chunk_id, context_refs FROM corpus.corpus_chunks "
        "WHERE build_id=ANY(%s::text[]) ORDER BY build_id, chunk_id",
        (build_ids,),
    )
    chunks: dict[str, dict[str, tuple[str, ...]]] = {bid: {} for bid in build_ids}
    for bid, cid, refs in cur.fetchall():
        chunks[bid][cid] = tuple(refs)
    order = {r[0]: tuple(chunks[r[1]]) for r in active}
    bands = tuple(
        SimpleNamespace(source_id=r[0], build_id=r[1], start=0, end=len(order[r[0]]) - 1)
        for r in active
        if order[r[0]]
    )
    evidence = read_pg.fetch_bands_on(cur, bands, order)
    kinds = {bid: {uid: kind for uid, (kind, _) in rows.items()} for bid, rows in units.items()}
    bodies = {
        (ev.build_id, ev.chunk_id): scoring_body(
            ev,
            chunks[ev.build_id][ev.chunk_id],
            kinds[ev.build_id],
        )
        for ev in evidence
    }
    corpus = RankingCorpus(
        tuple(
            RankingSource(
                r[0],
                r[1],
                tuple(r[5]),
                r[6],
                tuple((uid, raw) for uid, (_, raw) in units[r[1]].items()),
            )
            for r in active
        ),
        bodies,
    )
    with _LOCK:
        _CACHE[key] = corpus
        _CACHE.move_to_end(key)
        while len(_CACHE) > 2:
            _CACHE.popitem(last=False)
    return corpus, False
