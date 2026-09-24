from pathlib import Path
import hashlib
import json
import subprocess
from datetime import datetime, UTC

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
def digest(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
paths = sorted({p for folder in ['plugins/corpus', 'plugins/tools', 'tests', 'apodex/tests']
                for p in (ROOT / folder).rglob('*.py')})
version = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
manifest = {'generated_at': datetime.now(UTC).isoformat(), 'head': version,
    'diff_base': 'be74cbf8fb40b94d97b3702ca987712e832b13ad',
    'chain_head': 'i0c-r5i',
    'reviewed_source_hashes': {str(p.relative_to(ROOT)): digest(p) for p in paths},
    'artifacts': {p.name: digest(p) for p in sorted(OUT.iterdir())
                  if p.is_file() and p.name != 'review-manifest.json'}}
(OUT / 'review-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
live = json.loads((OUT / 'live-explicit.json').read_text())
print(json.dumps({'production_counts': live['post_counts'],
                  'unchanged': live['counts_unchanged'],
                  'artifacts': len(manifest['artifacts']),
                  'source_files': len(paths)}, ensure_ascii=False))
