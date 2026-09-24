"""Seal independent review outputs and confirm source/config bytes did not change."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
manifest = json.loads((OUT / 'run-manifest.json').read_text())
changed = [p for p, digest in manifest['sha256'].items()
           if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != digest]
assert not changed, changed
pg = json.loads((OUT / 'pg-results.json').read_text())
assert pg['sandbox_restored_exact_table_contents']
assert json.loads((OUT / 'cleanup.json').read_text())['all_absent']
assert json.loads((OUT / 'compat-probe.json').read_text())['temporary_db_removed']
assert json.loads((OUT / 'live-default.json').read_text())['counts_unchanged']
result = {'head': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
          'original_bound_inputs_unchanged': True,
          'tracked_diff_paths': subprocess.check_output(['git','diff','--name-only','HEAD'], cwd=ROOT, text=True).splitlines(),
          'output_sha256': {str(p.relative_to(OUT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(OUT.iterdir()) if p.is_file() and p.name != 'final-inventory.json'}}
(OUT / 'final-inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps({k:v for k,v in result.items() if k != 'output_sha256'}))
