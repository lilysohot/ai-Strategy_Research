import hashlib
from dataclasses import asdict
import psycopg
from common import *
from plugins.corpus.preparation.repository_pg import PgStore
from plugins.corpus.retrieval.index_pg import VectorIndex

cfg=setup(OLD)
index=VectorIndex(connection(OLD),cfg)
status=index.status()
assert status['active_chunks']==status['ready_chunks']==703
save('old-vector-status.json',status)
with psycopg.connect(connection('postgres')) as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    save('production-before.json',publications(conn))
with psycopg.connect(connection(OLD)) as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    pubs=publications(conn)
save('old-publications.json',pubs)
assert len([p for p in pubs if p[1]])==18
base=json.loads((ROOT/'.scratch/corpus-clean-boundary-20261021/baseline.json').read_text())
checkpoints={s['source_id']:json.loads(s['checkpoint']) for s in base}
files=list((ROOT/'data/corpus').rglob('*'))
files=[p for p in files if p.is_file() and p.suffix.lower() in ('.pdf','.md','.docx')]
inventory=[]
with PgStore(connection(OLD),sandbox_db=OLD) as store:
    for sid,bid,generation in pubs:
        if not bid:
            continue
        source=store.get_source(sid)
        build=store.get_build(bid)
        admission=store.get_admission(build.decision_id)
        cp=checkpoints[sid]
        candidates=[Path(cp['source_path'])]
        candidates += [ROOT/'data/vector-pilot-20261020/archive'/source.archive_path,ROOT/'data/corpus-archive'/source.archive_path]
        candidates += [p for p in files if p.name in source.original_names]
        path=next((p for p in candidates if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==sid),None)
        reviews=tuple([admission.review_ref] if admission.review_ref else [])
        for rid in reviews:
            assert store.get_reviewed_decision(rid) is not None
        inventory.append({'source_id':sid,'old_build':bid,'generation':generation,
            'source':asdict(source),'admission':asdict(admission),'build':asdict(build),
            'path':str(path) if path else None,'checkpoint_schema':cp['checkpoint_schema_rev'],
            'review_decision_ids':reviews})
save('inventory.json',inventory)
for r in inventory:
    print(json.dumps({'source':r['source_id'][:8],'found':bool(r['path']),
        'policy':r['admission']['policy_rev'],'review':r['review_decision_ids'],
        'schema':r['checkpoint_schema'],'scope':r['admission']['scope_ref']},ensure_ascii=False))
assert all(r['path'] for r in inventory),'missing source file'
print(json.dumps(status,ensure_ascii=False))
