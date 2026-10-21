import time
from common import *
from plugins.corpus.retrieval.embedding import DoubaoEmbedder
from plugins.corpus.retrieval.index_pg import VectorIndex
cfg=setup(NEW)
index=VectorIndex(connection(NEW),cfg)
index.initialize()
before=index.status()
if not (HERE/'vectors-before.json').exists():
    save('vectors-before.json',before)
assert before['sources']==18 and before['invalid_inputs']==0
assert before['uncached_inputs']<=750
provider=DoubaoEmbedder(cfg)
calls=read('vector-calls.json') if (HERE/'vector-calls.json').exists() else []
retry='--retry-uncertain' in sys.argv
if retry:
    with index.connect() as conn:
        assert conn.execute("SELECT count(*) FROM corpus_retrieval.embeddings WHERE profile=%s AND status IN ('running','uncertain') AND attempts>=2",(cfg.profile,)).fetchone()[0]==0
def embed(text,role):
    time.sleep(1)
    start=time.monotonic()
    result=provider.embed(text,role)
    calls.append({'elapsed_ms':round((time.monotonic()-start)*1000),'chars':len(text),'usage':result.usage})
    save('vector-calls.json',calls)
    print(json.dumps({'completed':len(calls),'elapsed_ms':calls[-1]['elapsed_ms']}),flush=True)
    return result
started=time.monotonic()
result=index.build(embed,max_requests=int(before['uncached_inputs']),retry_uncertain=retry)
save(f'vectors-run-{before["attempts"]}.json',{**result,'elapsed_seconds':time.monotonic()-started})
save('vectors-build.json',{**result,'elapsed_seconds':time.monotonic()-started})
save('vectors-after.json',index.status())
print(json.dumps(result,ensure_ascii=False),flush=True)
