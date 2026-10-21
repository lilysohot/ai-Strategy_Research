"""Undo only our incomplete-review-chain attempt in the new clone."""
import psycopg
from common import *

assert read('clone.json')['to']==NEW
restored=[]
with psycopg.connect(connection(NEW)) as conn:
    assert conn.execute('SELECT current_database()').fetchone()[0]==NEW
    for item in read('inventory.json'):
        if item['admission']['policy_rev']!='v2-dev-20260920':
            continue
        sid=item['source_id']
        current=conn.execute('SELECT current_decision_id FROM corpus.corpus_sources WHERE source_id=%s FOR UPDATE',(sid,)).fetchone()[0]
        row=conn.execute('SELECT decision,reason_codes,review_ref FROM corpus.corpus_admissions WHERE decision_id=%s',(current,)).fetchone()
        assert row==('review_required',['conflicting_review'],None)
        pub=conn.execute('SELECT active_build_id FROM corpus.corpus_publications WHERE source_id=%s',(sid,)).fetchone()[0]
        assert pub==item['old_build']
        old=item['admission']['decision_id']
        conn.execute('UPDATE corpus.corpus_sources SET current_decision_id=%s WHERE source_id=%s AND current_decision_id=%s',(old,sid,current))
        restored.append({'source_id':sid,'from':current,'to':old,'reason':'Undo runner omission of superseded review ancestor; original review/admission rows unchanged'})
save('admission-recovery.json',restored)
print('Restored two pre-run admission pointers; no review records changed')
