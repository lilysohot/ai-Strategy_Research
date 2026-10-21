from dataclasses import asdict
from collections import Counter
from types import SimpleNamespace
import psycopg
from common import *
from plugins.corpus.preparation.repository_pg import PgStore
from plugins.corpus.preparation.read_pg import fetch_bands

snapshots={}
for tag,db in [('old',OLD),('new',NEW)]:
    setup(db)
    sources=[]
    with PgStore(connection(db),sandbox_db=db) as store,psycopg.connect(connection(db)) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        pubs=publications(conn)
        for sid,bid,gen in pubs:
            if not bid:
                continue
            source=store.get_source(sid)
            build=store.get_build(bid)
            sources.append({'source_id':sid,'build_id':bid,'generation':gen,'source':asdict(source),
                'build':asdict(build),'units':[asdict(u) for u in store.get_units(bid)],
                'chunks':[asdict(c) for c in store.get_chunks(bid)]})
    snapshots[tag]={s['source_id']:s for s in sources}
    save(f'{tag}-corpus.json',sources)
    save(f'{tag}-publications-check.json',pubs)
    order={s['source_id']:tuple(c['chunk_id'] for c in s['chunks']) for s in sources}
    bands=tuple(SimpleNamespace(source_id=s['source_id'],build_id=s['build_id'],start=0,end=len(s['chunks'])-1) for s in sources)
    authority=fetch_bands(connection(db),bands,order,sandbox_db=db)
    assert len(authority)==sum(len(s['chunks']) for s in sources)
    save(f'{tag}-authority.json',{c.chunk_id:asdict(c) for c in authority})
changes=[]
for sid,old in snapshots['old'].items():
    new=snapshots['new'][sid]
    old_text=Counter(u['raw_text'] for u in old['units'])
    new_text=Counter(u['raw_text'] for u in new['units'])
    changes.append({'source_id':sid,'updated':old['build_id']!=new['build_id'],
        'old_units':len(old['units']),'new_units':len(new['units']),
        'old_chunks':len(old['chunks']),'new_chunks':len(new['chunks']),
        'raw_units_removed':sum((old_text-new_text).values()),'raw_units_added':sum((new_text-old_text).values()),
        'parse_rev_changed':old['build']['parse_rev']!=new['build']['parse_rev']})
save('corpus-delta.json',changes)
print(json.dumps(changes,ensure_ascii=False,indent=2))
