"""Real public search and real PG candidates; paired persistent query vectors."""
import hashlib
import time
from dataclasses import asdict
from unittest.mock import patch
from common import *
from plugins.corpus.retrieval import hybrid
from plugins.corpus.retrieval.embedding import DoubaoEmbedder,EmbeddingError
from plugins.corpus.retrieval.index_pg import VectorIndex
from plugins.corpus.retrieval.diagnostics import RetrievalTrace
from plugins.corpus.service import CorpusService

manifest_path=ROOT/'.scratch/corpus-vector-acceptance-20261020/manifest.json'
digest=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
assert digest=='50305e59759c13d662dce9ae84001474ae7dec596c55aed1449c9aabf1250a68'
cases=json.loads(manifest_path.read_text())['cases']
cache=read('query-vectors.json') if (HERE/'query-vectors.json').exists() else {}
for db in (OLD,NEW):
    cfg=setup(db)
    status=VectorIndex(connection(db),cfg).status()
    assert status['active_chunks']==status['ready_chunks'],status
    save(f'retrieval-status-{db}.json',status)

def frozen_query(config,question):
    key=hashlib.sha256((config.profile+'\n'+question).encode()).hexdigest()
    if key not in cache:
        started=time.monotonic()
        try:
            result=DoubaoEmbedder(config).embed(question,'query')
            cache[key]={'query':question,'profile':config.profile,'vector':result.vector,'usage':result.usage}
        except EmbeddingError as exc:
            cache[key]={'query':question,'profile':config.profile,'error':exc.code,'uncertain':exc.uncertain}
        cache[key]['elapsed_ms']=(time.monotonic()-started)*1000
        save('query-vectors.json',cache)
    row=cache[key]
    if 'error' in row:
        raise EmbeddingError(row['error'],uncertain=row['uncertain'])
    return tuple(row['vector']),True,{}

with patch.object(hybrid,'query_vector',frozen_query):
    for i,case in enumerate(cases):
        for tag,db in ([('old',OLD),('new',NEW)] if i%2==0 else [('new',NEW),('old',OLD)]):
            cfg=setup(db)
            service=CorpusService(connection(db))
            for mode in ('lexical','hybrid'):
                filename=f'retrieval/{case["id"]}-{tag}-{mode}.json'
                if (HERE/filename).exists():
                    continue
                os.environ['CORPUS_RETRIEVAL_MODE']=mode
                trace=RetrievalTrace()
                start=time.monotonic()
                hits,coverage=service.search_with_coverage(case['question'],limit=10,trace=trace)
                elapsed=(time.monotonic()-start)*1000
                save(filename,{'case':case['id'],'snapshot':tag,'db':db,'mode':mode,'question':case['question'],
                    'manifest_sha256':digest,'profile':cfg.profile,'elapsed_ms':elapsed,
                    'hits':[asdict(h) for h in hits],'coverage':coverage,'trace':trace.as_dict()})
                print(json.dumps({'case':case['id'],'snapshot':tag,'mode':mode,'rows':len(hits),'status':trace.status,
                    'elapsed_ms':round(elapsed)}),flush=True)
