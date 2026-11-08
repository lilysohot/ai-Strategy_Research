import sys,json,asyncio
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import create_async_engine
from server.config import get_config
from server.store import Run
async def main():
 engine=create_async_engine(get_config().database_url)
 async with engine.connect() as conn:
  print('run_status_counts',[(a,b) for a,b in (await conn.execute(select(Run.status,func.count()).group_by(Run.status))).all()])
 await engine.dispose()
 data=json.loads(Path('/tmp/frontier-ingestion-openapi.json').read_text())
 print('live_search_parameters',[p['name'] for p in data['paths']['/api/corpus/search']['get']['parameters']])
asyncio.run(main())
