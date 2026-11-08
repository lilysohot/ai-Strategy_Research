import asyncio,json,os,signal,subprocess,sys,time,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import create_async_engine
from server.config import get_config
from server.store import Run
async def idle():
 engine=create_async_engine(get_config().database_url)
 try:
  async with engine.connect() as conn:
   count=(await conn.execute(select(func.count()).select_from(Run).where(Run.status.in_(['queued','running'])))).scalar_one()
   assert count==0, 'active runs appeared; refusing restart'
 finally:
  await engine.dispose()
asyncio.run(idle())
pid=85627
proc=Path('/proc')/str(pid)
args=[x.decode() for x in (proc/'cmdline').read_bytes().split(b'\0') if x]
assert args[1].endswith('/FrontierAgent/.venv/bin/uvicorn') and args[2:]==['server.app:app','--host','0.0.0.0','--port','8000'], 'process changed'
cwd=(proc/'cwd').resolve()
assert cwd==Path.cwd()
env=dict(x.decode().split('=',1) for x in (proc/'environ').read_bytes().split(b'\0') if x)
os.kill(pid,signal.SIGTERM)
for _ in range(100):
 if not proc.exists(): break
 time.sleep(.1)
else: raise RuntimeError('server did not exit gracefully')
log=Path('.scratch/ingestion-search-server.log').open('ab')
child=subprocess.Popen(args,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
for _ in range(100):
 try:
  with urllib.request.urlopen('http://127.0.0.1:8000/openapi.json',timeout=1) as r: spec=json.load(r)
  names={p['name'] for p in spec['paths']['/api/corpus/search']['get']['parameters']}
  assert {'ingested_from','ingested_to','ingested_timezone','published_from','published_to'}<=names
  with urllib.request.urlopen('http://127.0.0.1:8000/readyz',timeout=3) as r: assert r.status==200
  print(json.dumps({'server_pid':child.pid,'ready':True,'search_parameters':sorted(names)}))
  break
 except (OSError,AssertionError):
  if child.poll() is not None: raise RuntimeError('new server stopped; see local log')
  time.sleep(.2)
else: raise RuntimeError('new server not ready; see local log')
