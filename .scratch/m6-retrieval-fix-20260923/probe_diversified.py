"""Probe a per-source-bounded candidate pool without changing production code."""
from pathlib import Path
import runpy

from plugins.corpus.preparation import search_pg
from plugins.corpus.service import CorpusService
from plugins.corpus.preparation.search_pg import SearchHit
import plugins.corpus.service as service_module

service_module._SELECTION_POOL_MIN = 200

search_pg._SEARCH_SQL = r"""
WITH q AS (
  SELECT websearch_to_tsquery('zhcfg', %(query)s) AS tsq,
         websearch_to_tsquery('zhcfg', %(rank_query)s) AS tsq_rank
), matches AS (
  SELECT p.source_id, c.build_id, c.chunk_id, c.kind, c.title_text, c.section_path,
         c.unit_refs,
         (ts_rank(c.search_tsv, q.tsq_rank)
          + 2 * ts_rank(to_tsvector('zhcfg', array_to_string(s.original_names, ' ')),
                        q.tsq_rank)) AS score,
         ts_headline('zhcfg', c.search_text, q.tsq,
                     'MaxWords=28, MinWords=8, ShortWord=1') AS snippet,
         a.metadata_snapshot->'report_publication'->>'value' AS published
  FROM q
  JOIN corpus.corpus_chunks AS c ON true
  JOIN corpus.corpus_builds AS b ON b.build_id = c.build_id
  JOIN corpus.corpus_publications AS p ON p.active_build_id = c.build_id
  JOIN corpus.corpus_sources AS s ON s.source_id = p.source_id
  JOIN corpus.corpus_admissions AS a ON a.decision_id = b.decision_id
  WHERE (c.search_tsv @@ q.tsq
         OR to_tsvector('zhcfg', array_to_string(s.original_names, ' ')) @@ q.tsq)
    AND (%(domain)s::text IS NULL OR a.research_domain = %(domain)s)
    AND (%(date_from)s::text IS NULL
         OR a.metadata_snapshot->'report_publication'->>'value' >= %(date_from)s)
    AND (%(date_to)s::text IS NULL
         OR a.metadata_snapshot->'report_publication'->>'value' <= %(date_to)s)
), ranked AS (
  SELECT matches.*,
         max(score) OVER (PARTITION BY source_id) AS source_score,
         row_number() OVER (PARTITION BY source_id
                            ORDER BY score DESC, build_id, chunk_id) AS source_position
  FROM matches
)
SELECT source_id, build_id, chunk_id, kind, title_text, section_path, unit_refs,
       score, snippet, published
FROM ranked
WHERE source_position <= 40
ORDER BY source_score DESC, score DESC, build_id, chunk_id
LIMIT %(limit)s
"""

def round_robin(self, raw_hits, chunk_order_by_source, limit):
    bands = self._apply_selection_bands(raw_hits, chunk_order_by_source, limit)
    by_key = {(h.build_id, h.chunk_id): h for h in raw_hits}
    source_order = []
    sequences = {}
    for band in bands:
        if band.source_id not in sequences:
            source_order.append(band.source_id)
            sequences[band.source_id] = []
        ordered = chunk_order_by_source[band.source_id]
        pool_first = sorted(
            band.pool,
            key=lambda position: -by_key[(band.build_id, ordered[position])].score,
        )
        positions = pool_first + [
            position for position in range(band.start, band.end + 1)
            if position not in set(band.pool)
        ]
        for position in positions:
            chunk_id = ordered[position]
            if chunk_id in {item.chunk_id for item in sequences[band.source_id]}:
                continue
            sequences[band.source_id].append(by_key.get((band.build_id, chunk_id)) or SearchHit(
                source_id=band.source_id, build_id=band.build_id, chunk_id=chunk_id, kind='',
                title_text=None, section_path=(), unit_refs=(), score=band.score))
    out = []
    offset = 0
    while len(out) < limit:
        added = False
        for source in source_order:
            if offset < len(sequences[source]):
                out.append(sequences[source][offset])
                added = True
                if len(out) == limit:
                    break
        if not added:
            break
        offset += 1
    return tuple(out)

CorpusService._selected_chunk_hits = round_robin

runpy.run_path(str(Path(__file__).with_name('probe_strategies.py')), run_name='__main__')
