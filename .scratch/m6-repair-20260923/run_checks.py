from pathlib import Path
import json, os, subprocess, sys
ROOT = Path('/home/administrator/FrontierAgent')
OUT = ROOT / '.scratch/m6-repair-20260923'
os.chdir(ROOT)
env = os.environ.copy()
env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1', CORPUS_DSN='postgresql://invalid:invalid@127.0.0.1:1/disabled', CORPUS_I2_DSN='', OPENAI_MODEL='review-no-model', OPENAI_API_KEY='review-no-model', OPENAI_BASE_URL='http://127.0.0.1:1/v1', ANTHROPIC_API_KEY='review-no-model', THS_API_KEY='', PYTHON_DOTENV_DISABLED='1')
commands = {
 'full-pytest': ['-m','pytest','tests','apodex/tests','-q','--tb=short','-ra'],
 'ruff': ['-m','ruff','check','frontier_agent/','apodex/','server/','benchmarks/','workflows/','plugins/','deploy/','tools/','scripts/'],
 'pyright': ['-m','pyright'],
 'symbols': ['tools/check_symbols.py'],
 'imports1': ['tools/import_smoke.py','--stage','1'],
 'imports2': ['tools/import_smoke.py','--stage','2'],
}
name=sys.argv[1]
with (OUT/(name+'.log')).open('w') as log:
 p=subprocess.run([str(ROOT/'.venv/bin/python'),*commands[name]],env=env,stdout=log,stderr=subprocess.STDOUT)
(OUT/(name+'.exit')).write_text(str(p.returncode))
print(name, 'exit', p.returncode)
print((OUT/(name+'.log')).read_text()[-18000:])


