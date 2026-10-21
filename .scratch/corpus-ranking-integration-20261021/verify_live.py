"""Real opt-in service; only query embeddings are replaced with the paid cache."""
import sys,json,hashlib,time,os
from pathlib import Path
from dataclasses import asdict
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
PRIOR=ROOT/'.scratch/corpus-clean7-rebuild-20261021'
sys.path[:0]=[str(ROOT),str(PRIOR)]
from common import connection,setup,NEW,publications
import psycopg
sys.path.insert(0,str(ROOT/'.scratch/corpus-body-ranking-20261021'))
from rank import restore,scope
from plugins.corpus.retrieval import hybrid
from plugins.corpus.retrieval.embedding import DoubaoEmbedder
from plugins.corpus.retrieval.index_pg import VectorIndex
from plugins.corpus.retrieval.diagnostics import RetrievalTrace
from plugins.corpus.service import CorpusService

def read(p):return json.loads(p.read_text())
def save(name,x): (HERE/name).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str))
cfg=setup(NEW);os.environ['CORPUS_RETRIEVAL_MODE']='hybrid'
PREVIOUS=ROOT/'.scratch/corpus-constraints-20261021'
prepared=read(PREVIOUS/'prepared.json');rank=read(PREVIOUS/'rankings.json')
os.environ['CORPUS_RETRIEVAL_RANKING']='body-constraints-v1'
os.environ['CORPUS_RETRIEVAL_RANKING_TARGET_DB']=NEW
cache=read(PRIOR/'query-vectors.json')
baseline_status=VectorIndex(connection(NEW),cfg).status()
with psycopg.connect(connection(NEW)) as c:
 c.execute('SET TRANSACTION READ ONLY');assert publications(c)==prepared['publications']
def frozen(config,query):
 row=cache[hashlib.sha256((config.profile+'\n'+query).encode()).hexdigest()]
 return tuple(row['vector']),True,{}
results=[]
for q in prepared['queries']:
 with patch.object(hybrid,'query_vector',frozen),patch.object(DoubaoEmbedder,'embed',side_effect=AssertionError('no embeddings')):
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
 results.append({'case':q['id'],'rows':len(hits),'elapsed_ms':elapsed,'full_scope_preserved':True,'first':expected[0].chunk_id,'feature_cache_hit':coverage['ranking']['feature_cache_hit']})
 (HERE/'live').mkdir(exist_ok=True)
 save(f'live/{q["id"]}.json',{'hits':[asdict(h) for h in hits],'coverage':coverage,'trace':trace.as_dict()})
 print(q['id'],'public service matches, scope preserved',flush=True)
with psycopg.connect(connection(NEW)) as c:
 c.execute('SET TRANSACTION READ ONLY');assert publications(c)==prepared['publications']
after=VectorIndex(connection(NEW),cfg).status()
assert after==baseline_status
save('live-verification.json',{'db':NEW,'queries':32,'results':results,'index_unchanged':True,'publication_unchanged':True,'model_calls':0,
 'note':'Real business ranking and PG feature loading, no ranking monkeypatch. Cached existing query embeddings only; loading overhead included.'})
