"""Read-only production acceptance; independent output, no source-file reads."""
import asyncio
import dataclasses
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys
from fractions import Fraction

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = ROOT / '.scratch/corpus-evidence-pipeline/ingestion-rebuild'
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
mode = sys.argv[1]
from dotenv import dotenv_values
config = dotenv_values(ROOT / '.env')
for key, value in config.items():
    if key.startswith('CORPUS_') and value is not None:
        os.environ.setdefault(key, value)
os.environ['PGOPTIONS'] = '-c default_transaction_read_only=on -c statement_timeout=30000'
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
explicit_in_config = bool(os.environ.get('CORPUS_TARGET_DB', '').strip())
if mode == 'explicit':
    os.environ['CORPUS_TARGET_DB'] = 'postgres'

class DenyModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic'} or fullname.startswith(
            ('plugins.corpus.material_semantics', 'plugins.corpus._r2_')
        ):
            raise RuntimeError('Model module forbidden during M7 read-only review')
sys.meta_path.insert(0, DenyModels())

import psycopg
from plugins.corpus.service import dsn, get_service
from plugins.corpus.preparation.pg_target import resolve_target_db
from plugins.tools import get_builtin_tools
from plugins.corpus.scoring import gold_from_records, score, ScoringPolicy
from tools.corpus_product_observations import ProductQuery, collect_query

def counts():
    with psycopg.connect(dsn()) as conn:
        assert conn.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
        assert conn.execute('SELECT current_database()').fetchone()[0] == 'postgres'
        tables = ['documents', 'blocks', 'claims', 'claim_block_runs',
                  'claims_v2', 'claim_block_runs_v2', 'corpus_evidence_runs',
                  'ingest_runs', 'ingest_failures', 'docs', 'chinese_docs']
        result = {t: conn.execute(f'SELECT count(*) FROM public.{t}').fetchone()[0]
                  for t in tables}
        result['new_chain'] = {t: conn.execute(f'SELECT count(*) FROM corpus.{t}').fetchone()[0]
                              for t in ['corpus_sources', 'corpus_builds', 'corpus_units',
                                        'corpus_chunks', 'corpus_publications']}
        result['active'] = [list(r) for r in conn.execute(
            'SELECT source_id, active_build_id FROM corpus.corpus_publications '
            'WHERE active_build_id IS NOT NULL ORDER BY source_id').fetchall()]
        return result

async def main():
    result = {'mode': mode, 'target_db_config_present': explicit_in_config,
              'resolved_target': resolve_target_db(), 'pre_counts': counts()}
    registry = get_builtin_tools()
    raw = await registry['corpus_search'].func(query='半导体划片机', limit=10)
    result['search'] = json.loads(raw)
    try:
        result['stats'] = get_service().stats()
    except Exception as exc:
        result['stats_error'] = str(exc)
    if mode == 'explicit':
        spec = importlib.util.spec_from_file_location('m7_scoring_input', BASE / 'i3s2_scoring_input.py')
        loader = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = loader
        spec.loader.exec_module(loader)
        gold = gold_from_records(loader.load_scoring_input(BASE / 'i3-2/scoring-input-manifest.json'))
        aliases = sorted({s for q in gold for s in q.relevant_sources} |
                         {t.source_id for q in gold for t in q.evidence_targets if t.source_id})
        def alias(source):
            matches = [a for a in aliases if source.startswith(a.rsplit('_', 1)[-1])]
            assert len(matches) <= 1
            return matches[0] if matches else source
        cfg = json.loads((BASE / 'audits/20260920-i33-calibration/calibration-plan-v2.json').read_text())['policy']
        cfg['min_rate'] = Fraction(cfg['min_rate'])
        observed, traces = [], []
        for q in gold:
            collected = await collect_query(ProductQuery(q.query_id, q.question),
                                            search=registry['corpus_search'],
                                            fetch=registry['corpus_fetch'], limit=10)
            observed.append(dataclasses.replace(collected.observation, documents=tuple(
                dataclasses.replace(d, source_id=alias(d.source_id))
                for d in collected.observation.documents)))
            traces.append(dataclasses.asdict(collected))
        report = score(gold, observed, ScoringPolicy(**cfg))
        result['product'] = {'passed': report.passed,
                             'qp': report.overall.question_pass_counts,
                             'ep': report.overall.evidence_pass_counts,
                             'false_positives': len(report.false_positives),
                             'failed_queries': sum(o.outcome.value == 'failed' for o in observed),
                             'executed_queries': len(traces),
                             'report': dataclasses.asdict(report)}
        (OUT / 'product-trace.json').write_text(json.dumps(traces, ensure_ascii=False, indent=2, default=str))
    result['post_counts'] = counts()
    result['counts_unchanged'] = result['pre_counts'] == result['post_counts']
    result['models_absent'] = not any(x in sys.modules for x in ['openai', 'anthropic'])
    text = json.dumps(result, ensure_ascii=False, indent=2, default=str).replace(dsn(), '<REDACTED>')
    (OUT / f'live-{mode}.json').write_text(text)
    print(json.dumps({k: v for k, v in result.items() if k not in {'pre_counts', 'post_counts', 'search', 'product'}}, ensure_ascii=False))
    print('search', result['search'].get('ok'), result['search'].get('error'), len(result['search'].get('hits', [])))
    if 'product' in result:
        print(json.dumps({k:v for k,v in result['product'].items() if k != 'report'}, default=str))

asyncio.run(main())
