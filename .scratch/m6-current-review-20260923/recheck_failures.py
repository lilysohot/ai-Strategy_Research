from pathlib import Path
import os, subprocess
ROOT=Path('/home/administrator/FrontierAgent');OUT=ROOT/'.scratch/m6-current-review-20260923'
env=os.environ.copy();env.update(PYTHONPATH=str(ROOT),CORPUS_DSN='postgresql://invalid:invalid@127.0.0.1:1/disabled',CORPUS_I2_DSN='',OPENAI_API_KEY='review-no-model',OPENAI_BASE_URL='http://127.0.0.1:1/v1',OPENAI_MODEL='review-no-model',ANTHROPIC_API_KEY='review-no-model',PYTHON_DOTENV_DISABLED='1')
args=['tests/test_history_t26.py::test_worker_injects_history_as_extra_input','tests/test_history_t26.py::test_worker_no_history_when_absent','tests/test_market_golden.py::test_market_hit_rate_is_100_percent','tests/test_research_discipline.py::test_react_profile_binds_the_finance_tools']
p=subprocess.run([str(ROOT/'.venv/bin/python'),'-m','pytest','-q','--tb=short',*args],cwd=ROOT,env=env,capture_output=True,text=True)
(OUT/'failure-recheck.log').write_text(p.stdout+p.stderr)
print(p.stdout+p.stderr);print('exit',p.returncode)
