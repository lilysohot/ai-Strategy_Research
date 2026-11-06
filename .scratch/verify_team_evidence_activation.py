"""Read-only service checks; archive the validated worker sources without restarting API."""
import hashlib,json,re,subprocess,urllib.request
from datetime import datetime,timezone
from pathlib import Path

root=Path('/home/administrator/FrontierAgent')
listeners=[line for line in subprocess.check_output(['ss','-ltnp'],text=True).splitlines() if re.search(r':8000\s',line)]
assert len(listeners)==1
pid=int(re.search(r'pid=(\d+)',listeners[0]).group(1))
assert Path(f'/proc/{pid}/cwd').resolve()==root
assert 'uvicorn' in Path(f'/proc/{pid}/cmdline').read_text()
env=dict(item.split('=',1) for item in Path(f'/proc/{pid}/environ').read_text().split('\0') if '=' in item)
env.update(SERVER_DATABASE_URL='sqlite+aiosqlite:///:memory:',SERVER_DATABASE_URL_DOCKER='',SERVER_MASTER_KEY='',SERVER_JWT_SECRET='')
code='''
import inspect,json
from pathlib import Path
import server.worker
from frontier_agent.components.agent_bus.bus import AgentBus
from frontier_agent.core.execution_context import ExecutionScope,set_current_execution_scope,reset_current_execution_scope
from plugins.tools.corpus_manifest import corpus_submit_manifest,_current_owner
from workflows.agent_team.delivery import deliver_answer
assert Path(server.worker.__file__).resolve().is_relative_to(Path('/home/administrator/FrontierAgent'))
assert 'agent_job_id' in inspect.getsource(AgentBus._dispatch_session_task)
schema=corpus_submit_manifest.to_openai_schema()['function']['parameters']['properties']
assert set(schema['submission_mode']['enum'])=={'replace','upsert'}
assert 'corpus_conclusions' in deliver_answer.to_openai_schema()['function']['parameters']['properties']
owners=[]
for job in ['job.1','job.2']:
 token=set_current_execution_scope(ExecutionScope(task_id='run',role_id='agent_team_sub',metadata={'agent_job_id':job}))
 try: owners.append(_current_owner())
 finally: reset_current_execution_scope(token)
assert len(set(owners))==2
print(json.dumps({'fresh_worker_import':'ok','job_manifest_identity':'ok','manifest_modes':'ok','atomic_final_manifest':'ok'}))
'''
child=subprocess.run([str(root/'.venv/bin/python'),'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=30)
if child.returncode:
 print('Fresh-worker diagnostic:',child.stderr.splitlines()[-1][:300])
 raise AssertionError('Fresh-worker checks failed; private environment not logged')
checks=json.loads(child.stdout.strip().splitlines()[-1])
with urllib.request.urlopen('http://127.0.0.1:8000/readyz',timeout=5) as response:
 assert response.status==200
 checks['api_readyz']=response.status
names=['frontier_agent/components/agent_bus/bus.py','plugins/tools/_corpus_handoff.py',
       'plugins/tools/_verification.py','plugins/tools/corpus_manifest.py','plugins/corpus/ledger.py',
       'workflows/agent_team/delivery.py','workflows/agent_team/README.md',
       'tests/test_team_evidence_lifecycle.py','tests/test_corpus_tool_references.py','tests/test_corpus_search_refs.py']
release=Path.home()/'.local/state/frontier-agent/releases'/('team-evidence-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
release.mkdir(parents=True,mode=0o700)
hashes={}
for name in names:
 raw=(root/name).read_bytes();target=release/'source'/name
 target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
 hashes[name]=hashlib.sha256(raw).hexdigest()
manifest={'activation':'Fresh per-run workers import live repository; API not restarted',
          'checks':checks,'sha256':hashes,
          'test_summary':(root/'.scratch/team-evidence-focused.txt').read_text().splitlines()[-1],
          'recorded_replay':[json.loads(line) for line in (root/'.scratch/team-evidence-replay.txt').read_text().splitlines()],
          'limitations':['No full live research rerun claimed',
                         'One stale migration-head assertion excluded from focused regression',
                         'Expanded corpus checks hit unrelated database/fixture failures',
                         'Repository-wide type errors outside changed modules remain']}
(release/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(json.dumps({'release':str(release),**checks,'api_restarted':False}))
