"""Independent M7 review; no production writes or model endpoints."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
os.chdir(ROOT)
env = os.environ.copy()
env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1',
           CORPUS_DSN='postgresql://invalid:invalid@127.0.0.1:1/disabled',
           CORPUS_I2_DSN='', CORPUS_TARGET_DB='',
           OPENAI_MODEL='review-no-model', OPENAI_API_KEY='review-no-model',
           OPENAI_BASE_URL='http://127.0.0.1:1/v1',
           ANTHROPIC_API_KEY='review-no-model', ANTHROPIC_BASE_URL='http://127.0.0.1:1',
           THS_API_KEY='', PYTHON_DOTENV_DISABLED='1')
commands = {
    'pytest': ['-m', 'pytest', 'tests', 'apodex/tests', '-q', '--tb=short', '-ra'],
    'ruff': ['-m', 'ruff', 'check', 'frontier_agent/', 'apodex/', 'benchmarks/',
             'workflows/', 'plugins/', 'deploy/', 'tools/', 'scripts/'],
    'format': ['-m', 'ruff', 'format', '--check', 'plugins/corpus/'],
    'pyright': ['-m', 'pyright'],
    'symbols': ['tools/check_symbols.py'],
    'imports1': ['tools/import_smoke.py', '--stage', '1'],
    'imports2': ['tools/import_smoke.py', '--stage', '2'],
    'freeze': ['.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py'],
}
name = sys.argv[1]
with (OUT / (name + '.log')).open('x') as log:
    result = subprocess.run([str(ROOT / '.venv/bin/python'), *commands[name]],
                            env=env, stdout=log, stderr=subprocess.STDOUT)
(OUT / (name + '.exit')).write_text(str(result.returncode))
print(name, 'exit', result.returncode)
print((OUT / (name + '.log')).read_text()[-14000:])
