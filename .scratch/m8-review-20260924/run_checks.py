"""Independent M8 checks with production DSNs disabled for the full test suite."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
UV = '/home/administrator/miniconda3/bin/uv'
env = os.environ.copy()
env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1',
           CORPUS_DSN='postgresql://invalid:invalid@127.0.0.1:1/disabled',
           CORPUS_I2_DSN='', CORPUS_TARGET_DB='', PYTHON_DOTENV_DISABLED='1',
           OPENAI_MODEL='review-no-model', OPENAI_API_KEY='review-no-model',
           OPENAI_BASE_URL='http://127.0.0.1:1/v1', ANTHROPIC_API_KEY='review-no-model',
           ANTHROPIC_BASE_URL='http://127.0.0.1:1', THS_API_KEY='')
COMMANDS = {
    'pytest': ['pytest', 'tests', 'apodex/tests', '-q', '--tb=short', '-ra'],
    'ruff': ['ruff', 'check', 'frontier_agent/', 'apodex/', 'benchmarks/',
             'workflows/', 'plugins/', 'deploy/', 'tools/', 'scripts/'],
    'pyright': ['pyright'],
    'symbols': ['python', 'tools/check_symbols.py'],
    'imports1': ['python', 'tools/import_smoke.py', '--stage', '1'],
    'imports2': ['python', 'tools/import_smoke.py', '--stage', '2'],
    'freeze': ['python', '.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py'],
}
name = sys.argv[1]
started = time.time()
with (OUT / (name + '.log')).open('x') as log:
    proc = subprocess.run([UV, 'run', '--frozen', *COMMANDS[name]], cwd=ROOT,
                          env=env, stdout=log, stderr=subprocess.STDOUT)
result = {'command': COMMANDS[name], 'exit_code': proc.returncode,
          'seconds': round(time.time() - started, 2)}
(OUT / (name + '.json')).write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
print((OUT / (name + '.log')).read_text()[-7000:])
