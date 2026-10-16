"""Activate the reviewed local implementation after checking no research is running.

Specific to this checked workstation: /home/administrator/FrontierAgent and
the existing pg container. Backups live outside the repository with mode 0600.
"""
import asyncio
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text

from server.config import get_config
from server.store import get_engine

ROOT = Path('/home/administrator/FrontierAgent')
assert Path.cwd().resolve() == ROOT


async def check():
    cfg = get_config()
    url = urlparse(cfg.database_url)
    assert url.hostname == 'localhost' and url.port == 5432 and url.path == '/apodex'
    async with get_engine().connect() as conn:
        active = await conn.scalar(text("select count(*) from runs where status in ('queued','running','waiting_approval')"))
        assert active == 0, 'Active research exists: do not restart the API'
    await get_engine().dispose()
    return url.username


username = asyncio.run(check())
backup = Path.home() / '.local/share/frontier-agent/backups' / ('monitoring-' + datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ'))
backup.mkdir(parents=True, mode=0o700)
env = ROOT / '.env'
original = env.read_text()
(backup / 'server.env').write_text(original)
(backup / 'server.env').chmod(0o600)
with (backup / 'apodex.dump').open('wb') as stream:
    subprocess.run(['docker', 'exec', 'pg', 'pg_dump', '-U', username, '-Fc', 'apodex'], stdout=stream, check=True)
(backup / 'apodex.dump').chmod(0o600)
print('backup_saved', backup)
subprocess.run([sys.executable, '-m', 'alembic', '-c', 'server/alembic.ini', 'upgrade', 'head'], check=True)

changes = {
    'SERVER_MONITOR_ENABLED': 'true', 'SERVER_MONITOR_STREAMS_ENABLED': 'true',
    'SERVER_AUTO_ENABLED': 'true', 'SERVER_MONITOR_VENDOR_TIME_VERIFIED': 'true',
    'SERVER_MONITOR_REDIS_URL': 'redis://127.0.0.1:6379/0',
    'SERVER_MONITOR_POLL_SECONDS': '900', 'SERVER_MONITOR_SESSION_LIMIT': '1',
}
lines = original.splitlines()
for key, value in changes.items():
    lines = [line for line in lines if not line.strip().startswith(key + '=')]
    lines.append(key + '=' + value)
assert env.read_text() == original, 'Configuration changed during deployment'
staged = backup / 'new.env'
staged.write_text('\n'.join(lines) + '\n')
staged.chmod(0o600)
os.replace(staged, env)

# Only the previously inspected API invocation on port 8000, not test services or Runs.
pids = []
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        args = (proc / 'cmdline').read_bytes().split(b'\0')
        if b'server.app:app' in args and b'8000' in args and any(b'uvicorn' in arg for arg in args):
            pids.append(int(proc.name))
    except (OSError, PermissionError):
        continue
for pid in pids:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
time.sleep(2)
logs = Path.home() / '.local/share/frontier-agent/web'
logs.mkdir(parents=True, exist_ok=True)
with (logs / 'api-monitoring.log').open('ab') as output:
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'server.app:app', '--host', '0.0.0.0', '--port', '8000'],
        cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
print('api_pid', process.pid)
units = Path.home() / '.config/systemd/user'
units.mkdir(parents=True, exist_ok=True)
unit = units / 'frontier-monitor.service'
if unit.exists():
    raise RuntimeError('Existing monitor unit requires inspection before replacement')
unit.write_text((ROOT / 'deploy/frontier-monitor.service.example').read_text())
subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
subprocess.run(['systemctl', '--user', 'enable', '--now', 'frontier-monitor.service'], check=True)
print('local_monitor_activated')
