"""Uniform query-rewrite probes through the registered tools; no label-driven branch."""
from pathlib import Path
import asyncio
import dataclasses
import importlib.util
import json
import os
import sys
from fractions import Fraction
from unittest.mock import patch

ROOT = Path('/home/administrator/FrontierAgent')
OUT = Path(__file__).resolve().parent
BASE = ROOT / '.scratch/corpus-evidence-pipeline/ingestion-rebuild'
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
env = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines()
           if '=' in line and not line.lstrip().startswith('#'))
credential = env['CORPUS_DSN'].split('://', 1)[1].rsplit('@', 1)[0]
dsn = f'postgresql://{credential}@127.0.0.1:543/i2_sandbox_corpus'
os.environ['PGOPTIONS'] = '-c default_transaction_read_only=on'

from plugins.corpus.preparation.guard import install
install(BASE / 'guards/i3-e2e.json')
from plugins.corpus.preparation import search_pg
from plugins.corpus.preparation.negative_query import abstain_content_lexemes, rank_lexemes
from plugins.corpus.scoring import ScoringPolicy, gold_from_records, score
from plugins.tools import get_builtin_tools
from tools.corpus_product_observations import ProductQuery, collect_query

spec = importlib.util.spec_from_file_location('frozen_input_loader', BASE / 'i3s2_scoring_input.py')
loader = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = loader
spec.loader.exec_module(loader)
gold = gold_from_records(loader.load_scoring_input(BASE / 'i3-2/scoring-input-manifest.json'))
aliases = sorted({s for q in gold for s in q.relevant_sources}
                 | {t.source_id for q in gold for t in q.evidence_targets if t.source_id})
raw_policy = json.loads((BASE / 'audits/20260920-i33-calibration/calibration-plan-v2.json').read_text())['policy']
raw_policy['min_rate'] = Fraction(raw_policy['min_rate'])
policy = ScoringPolicy(**raw_policy)
registry = get_builtin_tools()

def alias(source):
    matches = [a for a in aliases if source.startswith(a.rsplit('_', 1)[-1])]
    if len(matches) > 1:
        raise ValueError('ambiguous identity alias')
    return matches[0] if matches else source

def disjunction(tokens):
    return ' OR '.join('"' + t.replace('"', ' ') + '"' for t in tokens)

async def main():
    summaries = []
    configs = [('product-raw-default', 'on', None)]
    for label, abstain, prune in configs:
        os.environ['CORPUS_ABSTAIN_NO_ANSWER'] = abstain
        observed = []
        with patch('plugins.corpus.service.dsn', return_value=dsn):
            for item in gold:
                query = item.question
                if prune is not None:
                    lexemes = search_pg.query_lexemes(dsn, item.question)
                    query = disjunction(prune(lexemes))
                collected = await collect_query(ProductQuery(item.query_id, query),
                    search=registry['corpus_search'], fetch=registry['corpus_fetch'], limit=10)
                observed.append(dataclasses.replace(collected.observation,
                    documents=tuple(dataclasses.replace(d, source_id=alias(d.source_id))
                                    for d in collected.observation.documents)))
        report = score(gold, observed, policy)
        summary = {'configuration': label, 'abstain': abstain, 'passed': report.passed,
            'qp': report.overall.question_pass_counts, 'ep': report.overall.evidence_pass_counts,
            'fp': len(report.false_positives),
            'failed': sum(o.outcome.value == 'failed' for o in observed)}
        summaries.append(summary)
        (OUT / f'{label}-details.json').write_text(json.dumps({
            'summary': summary,
            'questions': [dataclasses.asdict(item) for item in report.questions],
            'observations': [dataclasses.asdict(item) for item in observed],
        }, ensure_ascii=False, indent=2, default=str) + '\n')
        print(json.dumps(summary), flush=True)
    (OUT / 'strategy-probe.json').write_text(json.dumps(summaries, indent=2) + '\n')

asyncio.run(main())
