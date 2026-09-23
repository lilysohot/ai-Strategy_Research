import sys,json,os
from pathlib import Path
ROOT=Path('/home/administrator/FrontierAgent'); sys.path.insert(0,str(ROOT))
import psycopg
from plugins.corpus.service import CorpusService
from plugins.corpus.preparation import guard,read_pg
from plugins.corpus.preparation.chunk import normalize_search_text
BASE=ROOT/'.scratch/corpus-evidence-pipeline/ingestion-rebuild'
records=[json.loads(x) for x in (BASE/'i3-2/query-gold-scoring-v1.jsonl').read_text().splitlines()]
guard.install(BASE/'guards/i3-e2e.json')
dsn='postgresql://postgres:postgres@127.0.0.1:543/i2_sandbox_corpus'
svc=CorpusService(dsn)
results=[]
for q in records:
    if q['query_id'] not in ['company-007','company-008','industry-008']: continue
    with psycopg.connect(dsn,autocommit=True) as c:
        c.execute('SET default_transaction_read_only=on')
        lex=c.execute("SELECT tsvector_to_array(to_tsvector('zhcfg',%s))",(normalize_search_text(q['question']),)).fetchone()[0]
    qry=' OR '.join('"'+x.replace('"',' ')+'"' for x in lex)
    docs,cov=svc.search_bands(qry,limit=2000)
    diffs=[]
    for d in docs:
        for band in d.chunks_by_band:
            for item in band:
                ev=svc.fetch_verbatim(d.doc_handle,read_pg.chunk_locator(item.chunk_id))
                if ev.text != item.text:
                    diffs.append({'source':d.source_id,'build':d.build_id,'chunk':item.chunk_id,'band_chars':len(item.text),'fetch_chars':len(ev.text),'band_text':item.text,'fetch_text':ev.text})
    results.append({'query_id':q['query_id'],'diffs':diffs})
(Path(__file__).resolve().parent / 'm6-spec-fetch-probe-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps([{'qid':r['query_id'],'diffs':len(r['diffs']),'sample':r['diffs'][:1]} for r in results],ensure_ascii=False))
