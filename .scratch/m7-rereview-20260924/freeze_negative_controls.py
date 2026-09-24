"""In-memory corruption probes; no frozen file is changed."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import runpy
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / '.scratch/corpus-evidence-pipeline/ingestion-rebuild'
VALIDATOR = BASE / 'freezes/validate_i0c_freeze.py'
targets = [
    BASE / 'audits/20260923-i4-window/i4c-reset-phase2-report.json',
    ROOT / '.scratch/m7-fix-20260924/g3-isolated-restore-verification.json',
    ROOT / '.scratch/m7-fix-20260924/i37-tests-results.json',
]
original = Path.read_bytes
results = []
for target in targets:
    intercepted = []
    def fault(path):
        raw = original(path)
        if path.resolve() == target.resolve():
            intercepted.append(str(path))
            return raw + b'\nCORRUPTION_PROBE\n'
        return raw
    output = io.StringIO()
    with patch.object(Path, 'read_bytes', fault), redirect_stdout(output), redirect_stderr(output):
        try:
            runpy.run_path(str(VALIDATOR), run_name='__main__')
            exit_code = 0
        except SystemExit as exc:
            exit_code = exc.code
    results.append({'target': str(target.relative_to(ROOT)),
                    'hashed_reads_intercepted': len(intercepted), 'exit_code': exit_code,
                    'relevant_output': [line for line in output.getvalue().splitlines()
                                        if target.name in line]})
(Path(__file__).parent / 'freeze-negative-controls.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
print(json.dumps(results, ensure_ascii=False, indent=2))
