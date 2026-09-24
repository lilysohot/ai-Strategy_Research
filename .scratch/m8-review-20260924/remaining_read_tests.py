"""Attempt remaining database readiness gates with the production session read-only."""
import json
import os
from pathlib import Path
import subprocess
import sys
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
env = os.environ.copy()
env.update({k: v for k, v in dotenv_values(ROOT / '.env').items()
            if k.startswith('CORPUS_') and v is not None})
env.update(PYTHON_DOTENV_DISABLED='1', PYTHONDONTWRITEBYTECODE='1',
           PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=30000',
           OPENAI_API_KEY='no-model', OPENAI_BASE_URL='http://127.0.0.1:1/v1',
           ANTHROPIC_API_KEY='no-model', ANTHROPIC_BASE_URL='http://127.0.0.1:1')
with (OUT / 'remaining-read-tests.log').open('x') as log:
    proc = subprocess.run([sys.executable,'-B','-m','pytest','tests/test_corpus_golden.py',
                           'tests/test_corpus_verify_b7.py','-q','-ra'],
                          cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=120)
(OUT / 'remaining-read-tests.json').write_text(json.dumps({'exit_code': proc.returncode,
    'read_only': True, 'model_calls': 0}, indent=2))
print((OUT / 'remaining-read-tests.log').read_text())
