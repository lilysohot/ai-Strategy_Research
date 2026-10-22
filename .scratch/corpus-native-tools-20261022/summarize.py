"""Audit final serialized tool messages and produce reproducible report metrics."""
import json,sys,statistics,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from plugins.corpus.ledger import ConsumptionLedger
def read(name):return json.loads((HERE/name).read_text())
rows=read('results.json');cases=read('cases.json');audits=[]
for r in rows:
    ledger=ConsumptionLedger()
    ledger.record_search(json.dumps(r['search'],ensure_ascii=False))
    messages=[]
    for page in r['fetch_pages']:
        body=json.dumps(page,ensure_ascii=False)
        ledger.record_fetch_result(body)
        messages.append({'role':'tool','content':body})
    ledger.finalize(messages)
    scopes=ledger.range_completeness()
    assert scopes and all(s['complete'] for s in scopes), (r['id'],scopes)
    audits.append({'id':r['id'],'all_scopes_complete':True,'fragments':len(ledger.fetched)})
summary={'queries':len(rows),'off_queries':len(read('off-cases.json')),
         'ledger_complete_queries':len(audits),
         'search_messages_max_chars':max(len(json.dumps(r['search'],ensure_ascii=False)) for r in rows),
         'fetch_pages':sum(len(r['fetch_pages']) for r in rows),
         'max_page_chars':max(len(json.dumps(p,ensure_ascii=False)) for r in rows for p in r['fetch_pages']),
         'max_body_chars':max(c['body_characters'] for c in cases),
         'elapsed_includes_all_fetches_cached_embeddings_ms':{'p50':statistics.median(c['elapsed_ms'] for c in cases),'p95':sorted(c['elapsed_ms'] for c in cases)[math.ceil(len(cases)*.95)-1]},
         'sync_first':read('sync-first.json'),'sync_repeat':read('sync-repeat.json')}
(HERE/'delivery-ledger.json').write_text(json.dumps(audits,ensure_ascii=False,indent=2)+'\n')
(HERE/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
