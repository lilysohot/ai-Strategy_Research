"""Publication, cache idempotence, current-version retrieval and cost audit."""
from collections import Counter
import hashlib
import psycopg
from common import *
from plugins.corpus.retrieval.index_pg import VectorIndex

for db,name in [('postgres','production-before.json'),(OLD,'old-publications.json')]:
    with psycopg.connect(connection(db)) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        assert publications(conn)==read(name)
cfg=setup(NEW)
index=VectorIndex(connection(NEW),cfg)
before=index.status()
def forbidden(*args):
    raise AssertionError('Unexpected model call on cached repeat')
repeat=index.build(forbidden,max_requests=0)
after=index.status()
assert repeat['requests_this_run']==0
assert before['attempts']==after['attempts']
assert after['active_chunks']==after['ready_chunks']==684
assert after['uncached_inputs']==0
save('cache-repeat.json',repeat)
old=read('old-corpus.json')
new=read('new-corpus.json')
updated=[s['source_id'] for s in new if s['build_id']!=next(o['build_id'] for o in old if o['source_id']==s['source_id'])]
assert len(updated)==16
for tag,corpus in [('old',old),('new',new)]:
    current={s['source_id']:s['build_id'] for s in corpus}
    for path in (HERE/'retrieval').glob(f'*-{tag}-*.json'):
        record=json.loads(path.read_text())
        for channel in ('lexical','dense','fused','selected'):
            assert all(h['build_id']==current[h['source_id']] for h in record['trace'][channel])
assert len(list((HERE/'retrieval').glob('*.json')))==128
assert hashlib.sha256((ROOT/'.scratch/corpus-vector-acceptance-20261020/manifest.json').read_bytes()).hexdigest()=='50305e59759c13d662dce9ae84001474ae7dec596c55aed1449c9aabf1250a68'
queries=read('query-vectors.json')
assert len(queries)==32 and all('error' not in v for v in queries.values())
oldstatus=read('old-vector-status.json')
calls=read('vector-calls.json')
cost={'document_successes':len(calls),'document_attempts':after['attempts']-oldstatus['attempts'],
      'document_reported_tokens':after['reported_total_tokens']-oldstatus['reported_total_tokens'],
      'query_successes':len(queries),'query_reported_tokens':sum(v['usage'].get('total_tokens',0) for v in queries.values()),
      'uncertain_attempts_retried_once':2,'billing_note':'Provider billing of the 2 transport-uncertain attempts is unknown; usage is provider-reported, not monetary cost.'}
save('verification.json',{'old_and_production_publications_unchanged':True,'updated_sources':len(updated),
 'active_sources':len(new),'active_chunks':after['active_chunks'],'ready_chunks':after['ready_chunks'],
 'captures':128,'query_count':32,'all_candidates_match_active_build':True,'idempotent_document_requests':0,
 'cost':cost})
changes=[]
for n in new:
    o=next(s for s in old if s['source_id']==n['source_id'])
    aa=Counter(u['raw_text'] for u in o['units'])
    bb=Counter(u['raw_text'] for u in n['units'])
    if aa!=bb:
        changes.append({'source_id':n['source_id'],'removed':list((aa-bb).elements()),'added':list((bb-aa).elements())})
save('reparse-raw-delta.json',changes)
print(json.dumps({'verification':read('verification.json'),'reparse_raw_changes':changes},ensure_ascii=False,indent=2))
