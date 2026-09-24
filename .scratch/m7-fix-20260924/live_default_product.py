"""M7 复核修复（G1/S1）后 default 模式验收：新进程、仅加载 .env 的 CORPUS_* 默认配置。

只读（PGOPTIONS 强制 default_transaction_read_only=on）、零模型（import 陷阱）、
输出独立落本目录。search→fetch 往返 + 30 道冻结题产品门（与复核 live_review.py
同口径，但不再要求显式 CORPUS_TARGET_DB——G1 交付后默认配置即指向生产新链）。
"""
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
mode = sys.argv[1] if len(sys.argv) > 1 else 'default'
from dotenv import dotenv_values
config = dotenv_values(ROOT / '.env')
for key, value in config.items():
    if key.startswith('CORPUS_') and value is not None:
        os.environ.setdefault(key, value)
os.environ['PGOPTIONS'] = '-c default_transaction_read_only=on -c statement_timeout=30000'
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
target_from_env = bool(os.environ.get('CORPUS_TARGET_DB', '').strip())
if mode == 'explicit':
    os.environ['CORPUS_TARGET_DB'] = 'postgres'

class DenyModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic'} or fullname.startswith(
            ('plugins.corpus.material_semantics', 'plugins.corpus._r2_')
        ):
            raise RuntimeError('Model module forbidden during M7 fix acceptance')
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
    result = {'mode': mode, 'target_db_config_present': target_from_env,
              'resolved_target': resolve_target_db(), 'pre_counts': counts()}
    registry = get_builtin_tools()
    raw = await registry['corpus_search'].func(query='半导体划片机', limit=10)
    search = json.loads(raw)
    result['search'] = {'ok': search.get('ok'), 'count': search.get('count'),
                        'error': search.get('error')}
    # G1 验收：search→fetch 往返（真实注册工具、default 配置、零显式注入）
    hit = (search.get('hits') or [None])[0]
    if hit:
        fetched = json.loads(await registry['corpus_fetch'].func(
            doc_id=hit['doc_id'], locator=hit['locator']))
        result['fetch'] = {'ok': fetched.get('ok'), 'error': fetched.get('error'),
                           'units': len(fetched.get('units') or []),
                           'text_chars': len(fetched.get('text') or '')}
    try:
        result['stats'] = get_service().stats()
    except Exception as exc:
        result['stats_error'] = str(exc)
    # 30 道冻结题产品门（原题干、limit=10、真实注册工具）
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
    (OUT / f'product-trace-{mode}.json').write_text(json.dumps(traces, ensure_ascii=False, indent=2, default=str))
    result['post_counts'] = counts()
    result['counts_unchanged'] = result['pre_counts'] == result['post_counts']
    result['models_absent'] = not any(x in sys.modules for x in ['openai', 'anthropic'])
    text = json.dumps(result, ensure_ascii=False, indent=2, default=str).replace(dsn(), '<REDACTED>')
    (OUT / f'live-{mode}.json').write_text(text)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in {'pre_counts', 'post_counts', 'search', 'fetch', 'stats', 'product'}},
                     ensure_ascii=False))
    print('search', result['search'].get('ok'), result['search'].get('error'), result['search'].get('count'))
    print('fetch', result.get('fetch', {}).get('ok'), result.get('fetch', {}).get('units'))
    print(json.dumps({k: v for k, v in result['product'].items() if k != 'report'}, default=str))

asyncio.run(main())
