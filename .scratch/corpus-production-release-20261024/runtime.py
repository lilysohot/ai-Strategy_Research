"""Activate the frozen contextual bundle on the existing local API only."""
import argparse
import importlib.util
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import dotenv_values, set_key, unset_key

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
BACKUP = ROOT / 'data/corpus-native-context/20261024-release-backup'
SETTINGS = {
    'CORPUS_NATIVE_INDEX': str(ROOT / 'data/corpus-native-context/20261023/manifest.json'),
    'CORPUS_VECTOR_INPUT_VARIANT': 'contextual-note-v1',
    'CORPUS_NATIVE_SNIPPET_BLOCKS': '2',
}
spec = importlib.util.spec_from_file_location('prior_runtime', ROOT / '.scratch/corpus-production-release-20261022/runtime.py')
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)


def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(data)


def restart(old, env, label):
    started = time.monotonic()
    os.kill(old, signal.SIGTERM)
    for _ in range(60):
        if prior.pid() is None:
            break
        time.sleep(.5)
    else:
        raise RuntimeError('api_did_not_exit_gracefully')
    with (HERE / ('api-' + label + '.log')).open('ab') as log:
        proc = subprocess.Popen([str(ROOT / '.venv/bin/uvicorn'), 'server.app:app',
            '--host', '0.0.0.0', '--port', '8000'], cwd=ROOT, env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(60):
        if proc.poll() is not None:
            raise RuntimeError('api_start_failed')
        try:
            if prior.health() == {'healthz': 200, 'readyz': 200}:
                return proc.pid, round(time.monotonic() - started, 3)
        except httpx.HTTPError:
            pass
        time.sleep(.5)
    raise RuntimeError('api_readiness_timeout')


def main(command):
    old = prior.pid()
    assert old and Path(f'/proc/{old}/cwd').resolve() == ROOT
    assert prior.active_runs() == 0, 'wait_for_active_user_runs'
    assert prior.health() == {'healthz': 200, 'readyz': 200}
    current = dotenv_values(ROOT / '.env')
    original_env = dict(pair.split('=', 1) for pair in Path(f'/proc/{old}/environ').read_bytes().decode().split('\0') if '=' in pair)
    if command == 'activate':
        subprocess.run([str(ROOT / '.venv/bin/python'), str(ROOT / '.scratch/corpus-real-blind-20261023/freeze.py')], check=True)
        assert current['CORPUS_NATIVE_RETRIEVAL'] == 'release'
        assert all(current[k] == 'postgres' for k in ('CORPUS_TARGET_DB', 'CORPUS_NATIVE_TARGET_DB', 'CORPUS_VECTOR_TARGET_DB'))
        BACKUP.mkdir(mode=0o700)
        private_write(BACKUP / 'env-before', (ROOT / '.env').read_bytes())
        private_write(BACKUP / 'process-env-before.json', json.dumps(original_env).encode())
        prior_settings = {k: current.get(k) for k in SETTINGS}
        (HERE / 'settings-before.json').write_text(json.dumps(prior_settings, indent=2) + '\n')
        changes = SETTINGS
    else:
        changes = json.loads((HERE / 'settings-before.json').read_text())
    for k, v in changes.items():
        if v is None:
            unset_key(str(ROOT / '.env'), k)
        else:
            set_key(str(ROOT / '.env'), k, v, quote_mode='never')
    env = original_env.copy()
    for k in SETTINGS:
        env.pop(k, None)
    env.update({k: v for k, v in dotenv_values(ROOT / '.env').items() if v is not None})
    try:
        new, seconds = restart(old, env, command)
    except Exception:
        if command == 'activate':
            for k, v in prior_settings.items():
                unset_key(str(ROOT / '.env'), k) if v is None else set_key(str(ROOT / '.env'), k, v, quote_mode='never')
            # Re-establish the previous configuration if the new listener exists.
            current_pid = prior.pid()
            if current_pid:
                restart(current_pid, original_env, 'automatic-rollback')
        raise
    report = {'time_utc': datetime.now(timezone.utc).isoformat(), 'command': command,
        'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'old_pid': old, 'new_pid': new, 'active_runs_before': 0,
        'settings_changed': changes, 'restart_seconds': seconds, 'health': prior.health(),
        'backup': str(BACKUP), 'data_migration': False}
    (HERE / ('runtime-' + command + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['activate', 'rollback'])
    main(parser.parse_args().command)
