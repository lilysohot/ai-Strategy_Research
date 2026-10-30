"""Hash existing tracked files and important local configuration without printing contents."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
out = Path(__file__).parent / 'outputs'
out.mkdir(exist_ok=True)
paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=repo).decode().split('\0')
paths += [str(p.relative_to(repo)) for p in repo.glob('.env*') if p.is_file()]
paths += ['.venv/pyvenv.cfg', '.venv/uv.lock']
snapshot = {}
for name in sorted(set(filter(None, paths))):
    p = repo / name
    if p.is_file():
        snapshot[name] = hashlib.sha256(p.read_bytes()).hexdigest()
status = subprocess.check_output(['git', 'status', '--porcelain=v1', '-z'], cwd=repo).decode()
payload = {'sha256': snapshot, 'git_status': status}
if sys.argv[1] == 'before':
    (out / 'isolation-before.json').write_text(json.dumps(payload, indent=2), encoding='utf8')
    print(f'Baseline saved: {len(snapshot)} existing files.')
else:
    before = json.loads((out / 'isolation-before.json').read_text(encoding='utf8'))
    changed = [p for p in set(before['sha256']) | set(snapshot)
               if before['sha256'].get(p) != snapshot.get(p)]
    result = {'files_checked': len(snapshot), 'changed_files': sorted(changed),
              'git_status_unchanged': before['git_status'] == status}
    (out / 'isolation-after.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(bool(changed) or not result['git_status_unchanged'])
