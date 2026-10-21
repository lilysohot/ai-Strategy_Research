import hashlib
import time
import statistics
from unittest.mock import patch
from common import *
from plugins.corpus.service import CorpusService
from plugins.corpus.retrieval import hybrid

cache=read('query-vectors.json')
cases=json.loads((ROOT/'.scratch/corpus-vector-acceptance-20261020/manifest.json').read_text())['cases']
def cached(config,question):
    key=hashlib.sha256((config.profile+'\n'+question).encode()).hexdigest()
    row=cache[key]
    assert 'error' not in row
    return tuple(row['vector']),True,{}
rows=[]
with patch.object(hybrid,'query_vector',cached):
    for turn in range(2):
        for i,case in enumerate(cases):
            for tag,db in ([('old',OLD),('new',NEW)] if (i+turn)%2==0 else [('new',NEW),('old',OLD)]):
                setup(db)
                os.environ['CORPUS_RETRIEVAL_MODE']='hybrid'
                start=time.monotonic()
                hits,coverage=CorpusService(connection(db)).search_with_coverage(case['question'],limit=10)
                rows.append({'round':turn,'case':case['id'],'tag':tag,'elapsed_ms':(time.monotonic()-start)*1000})
        save('latency-raw.json',rows)
        print('completed round',turn,flush=True)
out={}
for tag in ('old','new'):
    values=sorted(r['elapsed_ms'] for r in rows if r['tag']==tag)
    out[tag]={'samples':len(values),'median_ms':statistics.median(values),'p95_ms':values[int((len(values)-1)*.95)],'mean_ms':statistics.mean(values)}
save('latency-summary.json',out)
print(json.dumps(out))
