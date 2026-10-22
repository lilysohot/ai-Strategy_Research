"""Inspect, activate, or roll back the local API with bounded health checks."""
import argparse
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

import httpx
import psycopg
from dotenv import dotenv_values, load_dotenv, set_key

ROOT=Path.cwd();HERE=Path(__file__).parent
BACKUP=ROOT/'data/corpus-native-release/20261022-backup'
SETTINGS={
    'CORPUS_TARGET_DB':'postgres','CORPUS_READ_CHAIN':'new',
    'CORPUS_RETRIEVAL_MODE':'lexical','CORPUS_RETRIEVAL_RANKING':'off',
    'CORPUS_NATIVE_RETRIEVAL':'release','CORPUS_NATIVE_TARGET_DB':'postgres',
    'CORPUS_NATIVE_INDEX':str(ROOT/'data/corpus-native-release/20261022/manifest.json'),
    'CORPUS_VECTOR_TARGET_DB':'postgres','CORPUS_VECTOR_TIMEOUT_SECONDS':'15',
}

def save(name,value):
    (HERE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def pid():
    text=subprocess.check_output(['ss','-ltnp','sport = :8000'],text=True)
    match=re.search(r'pid=(\d+)',text)
    return int(match.group(1)) if match else None

def health():
    with httpx.Client(timeout=3) as client:
        return {p:client.get('http://127.0.0.1:8000/'+p).status_code for p in ('healthz','readyz')}

def active_runs():
    load_dotenv()
    from server.config import get_config
    url=get_config().database_url.replace('postgresql+asyncpg://','postgresql://',1)
    assert url.startswith('postgresql://')
    with psycopg.connect(url) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        return conn.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]

def activate(rollback=False):
    if not rollback:
        audit=json.loads((HERE/'audit.json').read_text())
        assert audit['queries']==57 and not audit['regressions'] and audit['publications_unchanged']
    old=pid();assert old,'expected_existing_api'
    assert Path(f'/proc/{old}/cwd').resolve()==ROOT,'unexpected_api_checkout'
    assert active_runs()==0,'active_user_runs_must_finish_before_restart'
    assert health()=={'healthz':200,'readyz':200}
    env=dict(pair.split('=',1) for pair in Path(f'/proc/{old}/environ').read_bytes().decode().split('\0') if '=' in pair)
    env_path=BACKUP/'runtime-env-before.json'
    if not env_path.exists():
        env_path.write_text(json.dumps(env));env_path.chmod(0o600)
    # Rollback preserves the new citation binding and changes only the search switch.
    changes={'CORPUS_NATIVE_RETRIEVAL':'off'} if rollback else SETTINGS
    for k,v in changes.items():set_key(str(ROOT/'.env'),k,v,quote_mode='never')
    env.update({k:v for k,v in dotenv_values(ROOT/'.env').items() if v is not None})
    started=time.monotonic()
    os.kill(old,signal.SIGTERM)
    for _ in range(60):
        if pid() is None:break
        time.sleep(.5)
    else:raise RuntimeError('api_did_not_exit_gracefully')
    log=(HERE/('api-rollback.log' if rollback else 'api-release.log')).open('ab')
    proc=subprocess.Popen([str(ROOT/'.venv/bin/uvicorn'),'server.app:app','--host','0.0.0.0','--port','8000'],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    for _ in range(50):
        if proc.poll() is not None:raise RuntimeError('new_api_failed_to_start')
        try:
            if health()=={'healthz':200,'readyz':200}:break
        except httpx.HTTPError:pass
        time.sleep(.5)
    else:raise RuntimeError('api_not_ready')
    report={'old_pid':old,'new_pid':proc.pid,'checkout':str(ROOT),'settings':changes,'health':health(),'active_runs_before':0,'restart_seconds':round(time.monotonic()-started,2)}
    save('runtime-rollback.json' if rollback else 'runtime-release.json',report)
    print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=('inspect','activate','rollback'));args=p.parse_args()
    if args.command=='inspect':print(json.dumps({'pid':pid(),'health':health(),'active_runs':active_runs()}))
    else:activate(args.command=='rollback')
