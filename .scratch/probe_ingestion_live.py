import asyncio,importlib,json,os,sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from dotenv import load_dotenv
load_dotenv('.env')
import psycopg
from plugins.corpus.service import dsn,CorpusService
from plugins.corpus.ingestion_dates import ingestion_range
from plugins.corpus.preparation.read_pg import fetch_verbatim
search = importlib.import_module('plugins.tools.corpus_search').corpus_search
async def main():
 with psycopg.connect(dsn()) as c:
  c.execute('SET TRANSACTION READ ONLY')
  stats=c.execute("SELECT (s.ingested_at AT TIME ZONE 'Asia/Shanghai')::date,count(*) FROM corpus.corpus_sources s JOIN corpus.corpus_publications p USING(source_id) WHERE p.active_build_id IS NOT NULL GROUP BY 1 ORDER BY 1").fetchall()
  print('by_ingestion_date',[(str(d),n) for d,n in stats])
  days=[str(d) for d,n in stats if d is not None][-2:]
 reports=[]
 for day in days:
  result=json.loads(await search.func('',ingested_from=day,ingested_to=day))
  assert result['ok'],result
  assert result['coverage']['ingestion_filter']['unknown_time_source_count']==8
  assert all(ingestion_range(day,day).matches(h['ingested_at']) for h in result['hits'])
  reports.append(dict(day=day,count=result['count'],mode=result['coverage']['retrieval_mode'],filter=result['coverage']['ingestion_filter'],
      timestamps=[h['ingested_at'] for h in result['hits']],publication_bases=[h['publication_date_basis'] for h in result['hits']],contracts=[h.get('evidence_contract') for h in result['hits']]))
 # Compare an absent date and intersection against actual live database.
 result=json.loads(await search.func('',ingested_from='2020-01-01',ingested_to='2020-01-01'))
 assert result['ok'] and result['count']==0
 assert result['coverage']['availability']=='unknown'
 result=json.loads(await search.func('',ingested_from=days[-1],ingested_to=days[-1],published_from='2020-01-01',published_to='2020-01-01'))
 assert result['ok'] and result['count']==0
 # Non-native path must apply SQL date bounds and return separate timestamps too.
 os.environ['CORPUS_NATIVE_RETRIEVAL']='off'
 hits,coverage=CorpusService().search_with_coverage('',ingested_from=days[-1],ingested_to=days[-1])
 assert hits and all(ingestion_range(days[-1],days[-1]).matches(h.ingested_at) for h in hits)
 reports.append(dict(non_native=True,count=len(hits),mode=coverage['retrieval_mode'],filter=coverage['ingestion_filter']))
 path=Path('.scratch/ingestion-search-live-20261108.json')
 path.write_text(json.dumps(dict(checked_at=datetime.now(timezone.utc).isoformat(),reports=reports),ensure_ascii=False,indent=2))
 print(json.dumps(reports,ensure_ascii=False,indent=2))
asyncio.run(main())
