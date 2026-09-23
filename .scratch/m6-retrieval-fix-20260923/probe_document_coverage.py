"""Measure gold-blind lexical coverage, then label rows only for diagnostic reporting."""
from pathlib import Path
import importlib.util
import json
import os
import sys

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
from plugins.corpus.preparation import read_pg, search_pg
from plugins.corpus.preparation.negative_query import abstain_content_lexemes
import psycopg

spec = importlib.util.spec_from_file_location('frozen_input_loader', BASE / 'i3s2_scoring_input.py')
loader = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = loader
spec.loader.exec_module(loader)
records = loader.load_scoring_input(BASE / 'i3-2/scoring-input-manifest.json')
with psycopg.connect(dsn, autocommit=True) as conn:
    rows = conn.execute('SELECT p.source_id,p.active_build_id FROM corpus.corpus_publications p '
        'WHERE p.active_build_id IS NOT NULL ORDER BY p.source_id').fetchall()
documents = {str(source): read_pg.fetch_document(dsn, read_pg.build_handle(str(build))).text
             for source, build in rows}
aliases = sorted({str(s) for r in records for s in r.get('relevant_sources', [])})
def alias(source):
    found = [a for a in aliases if source.startswith(a.rsplit('_', 1)[-1])]
    return found[0] if len(found) == 1 else source
results = []
for record in records:
    tokens = abstain_content_lexemes(search_pg.query_lexemes(dsn, record['question']))
    ranked = []
    for source, text in documents.items():
        compact = ''.join(text.split()).lower()
        matched = [token for token in tokens if ''.join(token.split()).lower() in compact]
        ranked.append({'source_id': alias(source), 'matched': matched,
            'missing': [token for token in tokens if token not in matched],
            'count': len(matched), 'total': len(tokens),
            'ratio': len(matched) / len(tokens) if tokens else 0})
    ranked.sort(key=lambda item: (-item['count'], item['source_id']))
    results.append({'query_id': record['query_id'], 'kind': record['answer_existence'],
        'relevant_sources': record.get('relevant_sources', []), 'tokens': tokens, 'documents': ranked})
(OUT / 'document-coverage.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
for item in results:
    best = item['documents'][0]
    relevant = next((d for d in item['documents'] if d['source_id'] in item['relevant_sources']), None)
    print(json.dumps({'id': item['query_id'], 'kind': item['kind'],
        'best': [best['source_id'], best['count'], best['total'], round(best['ratio'], 3)],
        'relevant': None if relevant is None else [relevant['source_id'], relevant['count'],
            relevant['total'], round(relevant['ratio'], 3)],
        'best_missing': best['missing']}, ensure_ascii=False))
