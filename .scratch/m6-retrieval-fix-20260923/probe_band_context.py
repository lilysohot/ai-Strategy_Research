"""Diagnostic: score bounded selected bands for every query, including negatives."""
from pathlib import Path
import dataclasses
import importlib.util
import json
import os
import sys
from fractions import Fraction

ROOT = Path('/home/administrator/FrontierAgent')
BASE = ROOT / '.scratch/corpus-evidence-pipeline/ingestion-rebuild'
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
env = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines()
           if '=' in line and not line.lstrip().startswith('#'))
credential = env['CORPUS_DSN'].split('://', 1)[1].rsplit('@', 1)[0]
dsn = f'postgresql://{credential}@127.0.0.1:543/i2_sandbox_corpus'
os.environ['PGOPTIONS'] = '-c default_transaction_read_only=on'
from plugins.corpus.preparation.guard import install
install(BASE / 'guards/i3-e2e.json')
from plugins.corpus.preparation import search_pg
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
from plugins.corpus.scoring import (FetchedEvidence, ObservationOutcome, QueryObservation,
                                    RetrievedDocument, ScoringPolicy, gold_from_records, score)
from plugins.corpus.service import CorpusService
import plugins.corpus.service as service_module
service_module._SELECTION_POOL_MIN = 200

def fair_bands(self, raw_hits, chunk_order_by_source, limit):
    from plugins.corpus.preparation.selection import BandPolicy, SelectionPolicy, select_band
    bands = select_band(raw_hits, SelectionPolicy(), BandPolicy(),
                        chunk_order_by_source=chunk_order_by_source)
    grouped = {}
    order = []
    for band in bands:
        if band.source_id not in grouped:
            grouped[band.source_id] = []
            order.append(band.source_id)
        grouped[band.source_id].append(band)
    selected = []
    offset = 0
    while len(selected) < limit:
        added = False
        for source in order:
            if offset < len(grouped[source]):
                selected.append(grouped[source][offset])
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        offset += 1
    return tuple(selected)

CorpusService._apply_selection_bands = fair_bands

spec = importlib.util.spec_from_file_location('frozen_input_loader', BASE / 'i3s2_scoring_input.py')
loader = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = loader
spec.loader.exec_module(loader)
gold = gold_from_records(loader.load_scoring_input(BASE / 'i3-2/scoring-input-manifest.json'))
aliases = sorted({s for q in gold for s in q.relevant_sources}
                 | {t.source_id for q in gold for t in q.evidence_targets if t.source_id})
def alias(source):
    matches = [a for a in aliases if source.startswith(a.rsplit('_', 1)[-1])]
    return matches[0] if len(matches) == 1 else source
raw_policy = json.loads((BASE / 'audits/20260920-i33-calibration/calibration-plan-v2.json').read_text())['policy']
raw_policy['min_rate'] = Fraction(raw_policy['min_rate'])
policy = ScoringPolicy(**raw_policy)
svc = CorpusService(dsn)
observations = []
diagnostic_hits = {}
coverage_rows = []
for query in gold:
    lexemes = search_pg.query_lexemes(dsn, query.question)
    from plugins.corpus.preparation.negative_query import abstain_content_lexemes
    lexemes = abstain_content_lexemes(lexemes)
    executed = ' OR '.join('"' + token.replace('"', ' ') + '"' for token in lexemes)
    if query.query_id in {'company-008', 'industry-008'}:
        diagnostic_hits[query.query_id] = [
            vars(hit) for hit in search_pg.search_chunks(dsn, executed, limit=200)
        ]
    docs, _ = svc.search_bands(executed, limit=40)
    doc_coverage = []
    for doc in docs:
        corpus_text = ''.join(
            item.text for band_items in doc.chunks_by_band for item in band_items
        ).replace(' ', '').replace('\n', '').lower()
        matched = [token for token in lexemes if token.replace(' ', '').lower() in corpus_text]
        doc_coverage.append({'source_id': alias(doc.source_id), 'matched': matched,
            'missing': [token for token in lexemes if token not in matched],
            'count': len(matched), 'total': len(lexemes),
            'ratio': len(matched) / len(lexemes) if lexemes else 0})
    doc_coverage.sort(key=lambda item: -item['count'])
    coverage_rows.append({'query_id': query.query_id,
        'answer_existence': query.answer_existence.value, 'documents': doc_coverage})
    converted = []
    for doc in docs:
        evidence = []
        items_by_chunk = {}
        for selected, band_items in sorted(zip(doc.bands, doc.chunks_by_band, strict=True),
                                           key=lambda pair: pair[0].start):
            for item in band_items:
                items_by_chunk.setdefault(item.chunk_id, item)
        all_items = list(items_by_chunk.values())
        if all_items:
            evidence.append(FetchedEvidence('\n'.join(item.text for item in all_items),
                tuple(f'page:{page}' for page in sorted({p for item in all_items for p in item.pages})), True))
        for cell in doc.cells:
            locators = ([] if cell.page is None else [f'page:{cell.page}'])
            locators += [f'row:{cell.row}', f'col:{cell.col}', f'cell:{cell.row}×{cell.col}']
            evidence.append(FetchedEvidence(cell.text, tuple(locators), True))
        converted.append(RetrievedDocument(alias(doc.source_id), tuple(evidence), doc.build_id))
    observations.append(QueryObservation(query.query_id,
        ObservationOutcome.OK if converted else ObservationOutcome.NO_MATCH, tuple(converted)))
report = score(gold, observations, policy)
result = {'summary': {'qp': report.overall.question_pass_counts,
    'ep': report.overall.evidence_pass_counts, 'fp': len(report.false_positives)},
    'questions': [vars(item) for item in report.questions],
    'observations': [dataclasses.asdict(item) for item in observations],
    'diagnostic_hits': diagnostic_hits, 'coverage': coverage_rows}
(OUT / 'band-context.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str)+'\n')
print(json.dumps(result['summary']))
