"""In-memory fault injection: never edits a bound asset or historical snapshot."""
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch
import io
import json
import runpy

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
VALIDATOR = ROOT / '.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py'
original_bytes = Path.read_bytes
original_text = Path.read_text
results = []
for name, target, expected in [
    ('current-code', ROOT/'plugins/corpus/preparation/read_pg.py',
        'i0c-current.binding[m6_repair_implementation]'),
    ('historical-archive', OUT/'before/plugins/corpus/preparation/read_pg.py',
        'r4r read_pg authoritative hash mismatch'),
    ('false-business-pass', OUT/'repair-manifest.json',
        'r5d repair identity/verdict mismatch'),
]:
    def modified_bytes(path):
        data = original_bytes(path)
        return data + b'\n# injected corruption\n' if path == target else data
    def modified_text(path, *args, **kwargs):
        text = original_text(path, *args, **kwargs)
        if name == 'false-business-pass' and path == target:
            data = json.loads(text)
            data['business_accepted'] = True
            return json.dumps(data)
        return text
    stream = io.StringIO()
    code = 0
    with patch.object(Path, 'read_bytes', modified_bytes), \
         patch.object(Path, 'read_text', modified_text), \
         redirect_stdout(stream), redirect_stderr(stream):
        try:
            runpy.run_path(str(VALIDATOR), run_name='__main__')
        except SystemExit as exc:
            code = exc.code
    rejected = code != 0 and expected in stream.getvalue()
    results.append({'control': name, 'injection': 'in-memory only',
        'exit_code': code, 'expected_diagnostic': expected, 'rejected': rejected})
    if not rejected:
        raise RuntimeError(f'{name} unexpectedly accepted: {stream.getvalue()}')
(OUT/'freeze-negative-controls.json').write_text(json.dumps(results, indent=2)+'\n')
print(json.dumps(results, indent=2))
