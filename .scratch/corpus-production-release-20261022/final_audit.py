"""Final read-only authority, historical reference, and release-artifact audit."""
import hashlib
import json
import statistics
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()
from plugins.corpus.service import CorpusService, dsn
from plugins.corpus.preparation.read_pg import build_handle, fetch_verbatim

HERE=Path(__file__).parent
read=lambda name:json.loads((HERE/name).read_text())
before=read('inventory.json')['inventory']['production']['publications']
promoted=read('promotion.json')
service=CorpusService()
old_handles=[]
with psycopg.connect(dsn()) as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    assert conn.execute('SELECT current_database()').fetchone()[0]=='postgres'
    after=[list(r) for r in conn.execute('SELECT source_id,active_build_id,generation FROM corpus.corpus_publications ORDER BY source_id')]
    assert after==promoted['publications']
    for sid,bid,generation in before:
        cid=conn.execute('SELECT chunk_id FROM corpus.corpus_chunks WHERE build_id=%s ORDER BY chunk_id LIMIT 1',(bid,)).fetchone()[0]
        evidence=fetch_verbatim(dsn(),build_handle(bid),'chunk:'+cid,sandbox_db='postgres')
        assert evidence.text and evidence.source_id==sid and evidence.build_id==bid
        old_handles.append({'source_id':sid,'build_id':bid,'active':evidence.active,'text_sha256':hashlib.sha256(evidence.text.encode()).hexdigest()})
    counts={t:conn.execute('SELECT count(*) FROM corpus.'+t).fetchone()[0] for t in ('corpus_sources','corpus_builds','corpus_units','corpus_chunks','corpus_publications')}
cases=read('cases.json')
times=sorted(c['elapsed_ms'] for c in cases)
previous={r[0]:r[1] for r in before};current={r[0]:r[1] for r in after}
summary={
    'target':'postgres','sources_before':len(before),'sources_after':len(after),
    'new_sources':len(set(current)-set(previous)),
    'updated_existing_sources':sum(current[s]!=b for s,b in previous.items()),
    'unchanged_existing_sources':sum(current[s]==b for s,b in previous.items()),
    'database_counts':counts,'queries':len(cases),'off_queries':len(read('off-cases.json')),
    'body_characters_max':max(c['body_characters'] for c in cases),
    'blocks_max':max(c['blocks'] for c in cases),
    'fetch_pages':sum(c['fetch_pages'] for c in cases),
    'cached_tool_roundtrip_p50_ms':statistics.median(times),
    'cached_tool_roundtrip_p95_ms':times[int((len(times)-1)*.95)],
    'lost_groups':[{'id':c['id'],'groups':c['lost_groups']} for c in cases if c['lost_groups']],
    'historical_handles':old_handles,'publication_changes_during_verification':False,
}
(HERE/'final-audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='historical_handles'},ensure_ascii=False))
