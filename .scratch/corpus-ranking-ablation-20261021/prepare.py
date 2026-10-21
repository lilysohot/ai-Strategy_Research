"""Read-only isolated PG ablations; frozen dense pools; no model requests."""
import hashlib
import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


prior = module('prior_acceptance', ROOT / '.scratch/corpus-vector-acceptance-20261020/run_eval.py')
capture = module('capture_replay', ROOT / '.scratch/corpus-selection-audit-20261021/run.py')
from plugins.corpus.preparation import search_pg, read_pg
from plugins.corpus.preparation.negative_query import retrieval_query
from plugins.corpus.retrieval.embedding import VectorConfig, DoubaoEmbedder
from plugins.corpus.retrieval.index_pg import VectorIndex
from plugins.corpus.retrieval.diagnostics import RetrievalTrace
from plugins.corpus.retrieval.dedup import dedupe_contained_hits
from plugins.corpus.service import CorpusService

cases, dsn, digest, profile = prior.setup()
cfg = VectorConfig.from_env()
index = VectorIndex(dsn, cfg)
sources = json.loads((ROOT / '.scratch/corpus-vector-acceptance-20261020/corpus.json').read_text())
structures = {s['source_id']: read_pg.fetch_chunk_structures(dsn, s['active_build_id'],
    [c['chunk_id'] for c in s['chunks']], sandbox_db=cfg.target_db) for s in sources}
save(HERE / 'structures.json', {s: {c: asdict(v) for c,v in rows.items()} for s,rows in structures.items()})
with index.connect() as conn:
    institutions = [r[0] for r in conn.execute('SELECT DISTINCT institution FROM corpus_retrieval.source_metadata WHERE institution IS NOT NULL').fetchall()]
institution_terms = set()
for name in institutions:
    institution_terms.update(search_pg.query_lexemes(dsn, name, sandbox_db=cfg.target_db))
# Do not suppress generic financial concepts as if they were institution names.
institution_terms -= {'证券', '股份', '有限', '公司', '研究', '金融', '银行'}
sql = search_pg._SEARCH_SQL
assert sql.count('+ 2 * ts_rank') == 1
service = CorpusService(dsn)
payload = {'manifest_sha256': digest, 'profile': profile, 'institution_terms': sorted(institution_terms), 'cases': {}}

for case in cases:
    cid, question = case['id'], case['question']
    path = ROOT / f'.scratch/corpus-selection-audit-20261021/captures/{cid}.json'
    frozen = json.loads(path.read_text())
    assert frozen['profile'] == profile and frozen['manifest_sha256'] == digest
    trace = capture.restore(frozen['trace'])
    lexemes = search_pg.query_lexemes(dsn, question, sandbox_db=cfg.target_db)
    query = retrieval_query(lexemes) or question
    # Re-read the unchanged baseline to detect drift before comparing SQL variants.
    lexical = search_pg.search_chunks(dsn, query, limit=200, sandbox_db=cfg.target_db)
    assert [(h.build_id,h.chunk_id,h.score) for h in lexical] == [(h.build_id,h.chunk_id,h.score) for h in trace.lexical], cid
    with patch.object(search_pg, '_SEARCH_SQL', sql.replace('+ 2 * ts_rank', '+ 0 * ts_rank')):
        filename_zero = search_pg.search_chunks(dsn, query, limit=200, sandbox_db=cfg.target_db)
    # Change ranking terms only; candidate WHERE and source coverage stay fixed.
    original_rank_query = search_pg._rank_query_on
    def without_institutions(cur, value):
        rank_query = original_rank_query(cur, value)
        kept = [t for t in rank_query.split(' OR ') if t.strip('"') not in institution_terms]
        return ' OR '.join(kept) or rank_query
    with patch.object(search_pg, '_rank_query_on', without_institutions):
        institution_zero = search_pg.search_chunks(dsn, query, limit=200, sandbox_db=cfg.target_db)
    # Exercise the PUBLIC service, including enrichment, trace and scope summaries,
    # against captured retrieval pools. Ordinary no-answer handling still executes.
    import os
    os.environ['CORPUS_RETRIEVAL_MODE'] = 'hybrid'
    with patch('plugins.corpus.retrieval.hybrid.search', return_value=(trace.fused, trace.chunk_order,
            frozen['coverage'], trace.lexical if trace.status == 'hybrid' else None)), \
         patch.object(DoubaoEmbedder, 'embed', side_effect=AssertionError('no embedding calls')):
        live_trace = RetrievalTrace()
        public, _ = service.search_with_coverage(question, limit=10, trace=live_trace)
    expected = dedupe_contained_hits(trace.selected)
    assert live_trace.selected == expected, cid
    assert len(public) == len(expected), cid
    for h, original in zip(public, expected, strict=True):
        assert h.context_locators == tuple(read_pg.chunk_locator(c) for c in original.context_chunk_ids)
        assert sum(count for kind,count in h.context_by_kind) == len(original.context_chunk_ids)
    payload['cases'][cid] = {'capture_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'lexemes': lexemes, 'filename_zero': [asdict(h) for h in filename_zero],
        'institution_zero': [asdict(h) for h in institution_zero],
        'public_replay_rows': len(public), 'status': trace.status}
    print(cid, trace.status, len(trace.selected), '->', len(public), flush=True)
save(HERE / 'prepared.json', payload)
