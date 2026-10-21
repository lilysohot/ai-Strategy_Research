from dataclasses import asdict
import psycopg
from common import *
from plugins.corpus.preparation.repository_pg import PgStore
setup(NEW)
with PgStore(connection(NEW),sandbox_db=NEW) as store, psycopg.connect(connection(NEW)) as conn:
    for item in read('inventory.json'):
        result=next(r for r in read('build-results.json') if r['source_id']==item['source_id'])
        if result['status']=='published':
            continue
        current=conn.execute('SELECT current_decision_id FROM corpus.corpus_sources WHERE source_id=%s',(item['source_id'],)).fetchone()[0]
        print(json.dumps({'source_id':item['source_id'],'admission':asdict(store.get_admission(current)),
            'reviews':[asdict(store.get_reviewed_decision(r)) for r in item['review_decision_ids']]},ensure_ascii=False,default=str))
