"""Read-only product-path differential probe; never uses gold to choose query behaviour."""
from pathlib import Path
import asyncio, importlib, importlib.util, json, os, sys
ROOT=Path('/home/administrator/FrontierAgent'); BASE=ROOT/'.scratch/corpus-evidence-pipeline/ingestion-rebuild'; OUT=ROOT/'.scratch/m6-current-review-20260923'
sys.path.insert(0,str(ROOT)); os.chdir(ROOT)
env=dict(line.split('=',1) for line in (ROOT/'.env').read_text().splitlines() if '=' in line and not line.lstrip().startswith('#'))
cred=env['CORPUS_DSN'].split('://',1)[1].rsplit('@',1)[0]
dsn=f'postgresql://{cred}@127.0.0.1:543/i2_sandbox_corpus'
os.environ['PGOPTIONS']='-c default_transaction_read_only=on'
from plugins.corpus.preparation.guard import install
install(BASE/'guards/i3-e2e.json')
os.environ['CORPUS_ABSTAIN_NO_ANSWER']='off'
from plugins.corpus.service import CorpusService
from plugins.corpus.preparation import read_pg, search_pg
from plugins.corpus.scoring import gold_from_records, AnswerExistence
svc=CorpusService(dsn)
spec=importlib.util.spec_from_file_location('scoring_input',BASE/'i3s2_scoring_input.py'); loader=importlib.util.module_from_spec(spec);sys.modules[spec.name]=loader;spec.loader.exec_module(loader)
qs=gold_from_records(loader.load_scoring_input(BASE/'i3-2/scoring-input-manifest.json'))
search_mod=importlib.import_module('plugins.tools.corpus_search');fetch_mod=importlib.import_module('plugins.tools.corpus_fetch')
search_mod.get_service=lambda:svc;fetch_mod.get_service=lambda:svc
async def main():
 results=[]; diffs={}
 for q in qs:
  raw=json.loads(await search_mod.corpus_search.ainvoke({'query':q.question,'limit':20}))
  lex=search_pg.query_lexemes(dsn,q.question)
  expanded=' OR '.join('"'+t.replace('"',' ')+'"' for t in lex)
  or_result=json.loads(await search_mod.corpus_search.ainvoke({'query':expanded,'limit':20}))
  docs,_=svc.search_bands(expanded,limit=2000)
  for doc in docs:
   for band in doc.chunks_by_band:
    for item in band:
     key=(doc.build_id,item.chunk_id)
     if key in diffs: continue
     ev=svc.fetch_verbatim(doc.doc_handle,read_pg.chunk_locator(item.chunk_id))
     if item.text!=ev.text:
      tool=json.loads(await fetch_mod.corpus_fetch.ainvoke({'doc_id':doc.doc_handle,'locator':read_pg.chunk_locator(item.chunk_id)}))
      targets=[t.target_id for t in q.evidence_targets if ''.join(t.quote.split()) in ''.join(item.text.split()) and ''.join(t.quote.split()) not in ''.join(ev.text.split())]
      diffs[key]={'query_id':q.query_id,'build_id':doc.build_id,'chunk_id':item.chunk_id,'band_chars':len(item.text),'fetch_chars':len(ev.text),'tool_equals_plain_fetch':tool['text']==ev.text,'lost_target_quotes':targets,'added_unit_text_examples':[line for line in item.text.splitlines() if line and line not in ev.text][:3]}
  row={'query_id':q.query_id,'negative':q.answer_existence is AnswerExistence.NO_ANSWER,'raw_ok':raw['ok'],'raw_hits':len(raw['hits']),'or_hits':len(or_result['hits']),'band_documents':len(docs)}
  results.append(row);print(json.dumps(row),flush=True)
 out={'configuration':{'abstain':'off','tool_limit':20,'band_limit':2000,'readonly':True},'rows':results,'different_chunk_evidence':list(diffs.values())}
 (OUT/'product-path-probe.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
 print('DIFFERING CHUNKS',len(diffs),flush=True)
 for v in diffs.values():
  if v['lost_target_quotes']: print(json.dumps(v,ensure_ascii=False),flush=True)
asyncio.run(main())
