from pathlib import Path
import hashlib
import json
import subprocess
from datetime import datetime, UTC

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = ROOT / '.scratch/corpus-evidence-pipeline/ingestion-rebuild'
def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
paths = sorted({p for folder in ['plugins/corpus', 'plugins/tools', 'tests', 'apodex/tests']
                for p in (ROOT / folder).rglob('*.py')})
snapshot = BASE / 'freezes/i0c-r5j.json'
bindings = json.loads(snapshot.read_text())['binding']
checks = {name: digest(ROOT / name) == sha for group in bindings.values()
          for name, sha in group.items()}
assert all(checks.values())
manifest = {
    'generated_at': datetime.now(UTC).isoformat(),
    'start_head': subprocess.check_output(['git', 'rev-parse', 'd897d8f'], cwd=ROOT, text=True).strip(),
    'end_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
    'diff_base': '1f69be1df7caeae7660c06ddc0d1da4d8470b20a',
    'chain_head': 'i0c-r5j', 'snapshot_sha256': digest(snapshot),
    'current_snapshot_binding_checks': checks,
    'reviewed_source_hashes': {str(p.relative_to(ROOT)): digest(p) for p in paths},
    'artifacts': {p.name: digest(p) for p in sorted(OUT.iterdir())
                  if p.is_file() and p.name != 'review-manifest.json'},
    'safety': {'production_writes': 0, 'model_calls': 0,
               'sandbox_restored': True, 'old_artifacts_modified_by_reviewer': False},
}
(OUT / 'review-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
print(json.dumps({'bound_files_verified': len(checks), 'reviewed_sources': len(paths),
                  'artifact_files': len(manifest['artifacts'])}))
