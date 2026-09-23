"""Execute real registered tools for every query; score only after collection."""
from pathlib import Path
import asyncio, dataclasses, hashlib, importlib.util, json, os, sys
from fractions import Fraction
from unittest.mock import patch
ROOT=Path('/home/administrator/FrontierAgent');OUT=Path(__file__).resolve().parent;BASE=ROOT/'.scratch/corpus-evidence-pipeline/ingestion-rebuild'
sys.path.insert(0,str(ROOT));os.chdir(ROOT)
env=dict(line.split('=',1) for line in (ROOT/'.env').read_text().splitlines() if '=' in line and not line.lstrip().startswith('#'))
cred=env['CORPUS_DSN'].split('://',1)[1].rsplit('@',1)[0]
dsn=f'postgresql://{cred}@127.0.0.1:543/i2_sandbox_corpus'
os.environ['PGOPTIONS']='-c default_transaction_read_only=on'
from plugins.corpus.preparation.guard import install
install(BASE/'guards/i3-e2e.json')
from plugins.tools import get_builtin_tools
from plugins.corpus.preparation import search_pg
from plugins.corpus.scoring import gold_from_records, score, ScoringPolicy, format_report
from tools.corpus_product_observations import ProductQuery,collect_query
spec=importlib.util.spec_from_file_location('frozen_input_loader',BASE/'i3s2_scoring_input.py');loader=importlib.util.module_from_spec(spec);sys.modules[spec.name]=loader;spec.loader.exec_module(loader)
records=loader.load_scoring_input(BASE/'i3-2/scoring-input-manifest.json')
gold=gold_from_records(records)
# Truth labels are deliberately not passed to collection.
queries=tuple(ProductQuery(q.query_id,q.question) for q in gold)
aliases=sorted({s for q in gold for s in q.relevant_sources}|{t.source_id for q in gold for t in q.evidence_targets if t.source_id})
cfg=json.loads((BASE/'audits/20260920-i33-calibration/calibration-plan-v2.json').read_text())['policy'];cfg['min_rate']=Fraction(cfg['min_rate']);policy=ScoringPolicy(**cfg)
registry=get_builtin_tools()
def alias(source):
 matches=[a for a in aliases if source.startswith(a.rsplit('_',1)[-1])]
 if len(matches)>1:raise ValueError('ambiguous identity alias')
 return matches[0] if matches else source
async def main():
 summaries=[]
 for label,abstain,limit,expand in [('default','off',10,False),('explicit-or-diagnostic','off',20,True),('known-abstain-limit','on',10,False)]:
  os.environ['CORPUS_ABSTAIN_NO_ANSWER']=abstain
  observed=[];trace=[]
  with patch('plugins.corpus.service.dsn',return_value=dsn):
   for query in queries:
    text=query.text
    if expand:
     text=' OR '.join('"'+x.replace('"',' ')+'"' for x in search_pg.query_lexemes(dsn,text))
    collected=await collect_query(ProductQuery(query.query_id,text),search=registry['corpus_search'],fetch=registry['corpus_fetch'],limit=limit)
    obs=dataclasses.replace(collected.observation,documents=tuple(dataclasses.replace(d,source_id=alias(d.source_id)) for d in collected.observation.documents))
    observed.append(obs);trace.append({'query':dataclasses.asdict(query),'executed_query':text,**dataclasses.asdict(collected)})
  report=score(gold,observed,policy)
  result={'configuration':{'label':label,'abstain':abstain,'limit':limit,'query_policy':'all-query-zhcfg-or' if expand else 'unchanged','registry':'plugins.tools.get_builtin_tools','dsn':'postgresql://<REDACTED>@127.0.0.1:543/i2_sandbox_corpus'},'report':dataclasses.asdict(report),'summary':dataclasses.asdict(report.overall),'observations':[dataclasses.asdict(o) for o in observed]}
  (OUT/f'product-{label}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
  (OUT/f'product-{label}-trace.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2,default=str).replace(dsn,'<REDACTED>')+'\n')
  (OUT/f'product-{label}.txt').write_text(format_report(report))
  summary={'configuration':label,'passed':report.passed,'qp':report.overall.question_pass_counts,'ep':report.overall.evidence_pass_counts,'fp':len(report.false_positives),'failed_queries':sum(o.outcome.value=='failed' for o in observed),'executed_queries':len(trace)}
  summaries.append(summary);print(json.dumps(summary),flush=True)
 (OUT/'product-evaluation-summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
 # Semantic verdict is nonzero if the default product gate is not satisfied.
 return 0 if summaries[0]['passed'] else 1
raise SystemExit(asyncio.run(main()))
