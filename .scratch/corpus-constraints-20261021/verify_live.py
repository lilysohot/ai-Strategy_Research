"""Real PG retrieval + public service with process-local experimental ranking hooks."""
import sys,json,hashlib,time,os
from pathlib import Path
from dataclasses import asdict
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
PRIOR=ROOT/'.scratch/corpus-clean7-rebuild-20261021'
sys.path[:0]=[str(ROOT),str(PRIOR)]
from common import connection,setup,NEW,publications
import psycopg
from signals import Signals,rerank_pool,guarded_year_order
from rank import restore,scope
from plugins.corpus.retrieval import hybrid
from plugins.corpus.retrieval.embedding import DoubaoEmbedder
from plugins.corpus.retrieval.index_pg import VectorIndex
from plugins.corpus.retrieval.diagnostics import RetrievalTrace
from plugins.corpus.service import CorpusService

def read(p):return json.loads(p.read_text())
def save(name,x): (HERE/name).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str))
cfg=setup(NEW);os.environ['CORPUS_RETRIEVAL_MODE']='hybrid'
prepared=read(HERE/'prepared.json');rank=read(HERE/'rankings.json')
signal=Signals(read(PRIOR/'new-corpus.json'),read(PRIOR/'new-authority.json'),prepared['metadata'])
cache=read(PRIOR/'query-vectors.json')
baseline_status=VectorIndex(connection(NEW),cfg).status()
with psycopg.connect(connection(NEW)) as c:
 c.execute('SET TRANSACTION READ ONLY');assert publications(c)==prepared['publications']
original_search=hybrid.search
original_select=CorpusService._selected_context_hits
def frozen(config,query):
 row=cache[hashlib.sha256((config.profile+'\n'+query).encode()).hexdigest()]
 return tuple(row['vector']),True,{}
results=[]
for q in prepared['queries']:
 intent=signal.intent(q['question'],q['lexemes']);features={}
 def search(*args,**kwargs):
  fused,order,coverage,lexical=original_search(*args,**kwargs)
  assert lexical is not None
  features.update({h.chunk_id:signal.feature(h,intent) for h in fused})
  changed=rerank_pool(fused,features,'entity');words=rerank_pool(lexical,features,'entity')
  if kwargs.get('trace') is not None:kwargs['trace'].fused=changed
  return changed,order,coverage,words
 def select(self,*args,**kwargs):
  hits=original_select(self,*args,**kwargs)
  return guarded_year_order(tuple(sorted(hits,key=lambda h:-features[h.chunk_id]['source_hint'])),features,intent)
 with patch.object(hybrid,'query_vector',frozen),patch.object(hybrid,'search',search),patch.object(CorpusService,'_selected_context_hits',select),patch.object(DoubaoEmbedder,'embed',side_effect=AssertionError('no embeddings')):
  trace=RetrievalTrace();start=time.perf_counter()
  hits,coverage=CorpusService(connection(NEW)).search_with_coverage(q['question'],limit=10,trace=trace)
  elapsed=(time.perf_counter()-start)*1000
 expected=restore(rank['cases'][q['id']]['methods']['guarded']['selected'])
 assert trace.status=='hybrid' and trace.selected==expected,(q['id'],'live differs from offline')
 base=restore(rank['cases'][q['id']]['methods']['baseline']['selected'])
 assert scope(trace.selected)==scope(base)
 assert len(hits)==len(expected)
 for public,h in zip(hits,expected,strict=True):
  assert sum(n for _,n in public.context_by_kind)==len(h.context_chunk_ids)
  assert h.chunk_id in h.context_chunk_ids
 results.append({'case':q['id'],'rows':len(hits),'elapsed_ms':elapsed,'full_scope_preserved':True,'first':expected[0].chunk_id})
 (HERE/'live').mkdir(exist_ok=True)
 save(f'live/{q["id"]}.json',{'hits':[asdict(h) for h in hits],'coverage':coverage,'trace':trace.as_dict(),'query_constraints':intent['constraints'],'constraint_matches':{h.chunk_id:features[h.chunk_id]['constraints'] for h in trace.selected}})
 print(q['id'],'public service matches, scope preserved',flush=True)
with psycopg.connect(connection(NEW)) as c:
 c.execute('SET TRANSACTION READ ONLY');assert publications(c)==prepared['publications']
after=VectorIndex(connection(NEW),cfg).status()
assert after==baseline_status
save('live-verification.json',{'db':NEW,'queries':32,'results':results,'index_unchanged':True,'publication_unchanged':True,'model_calls':0,
 'note':'Process-local ranking hooks only; live candidate search, authority structure and public output assembly; preloaded body-feature cache excludes cache-loading overhead. No production settings or business code changed.'})
