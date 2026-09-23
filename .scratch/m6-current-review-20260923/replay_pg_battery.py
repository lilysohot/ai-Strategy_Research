"""Replay the frozen M4/M5 battery, placing every new output in this review directory."""
from pathlib import Path
import importlib.util, json, os, subprocess, sys
ROOT=Path('/home/administrator/FrontierAgent');OUT=ROOT/'.scratch/m6-current-review-20260923';OLD=ROOT/'.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify'
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
m=load('frozen_battery',OLD/'run_tests.py')
m.HERE=OUT
m.load_i37_rebuild=lambda:load('frozen_rebuild',OLD/'i37_rebuild.py')
def restore():
 p=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--restore'],cwd=ROOT,env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LANG':'C.UTF-8','PYTHONPATH':str(ROOT),'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=1200)
 (OUT/'lane-restore.txt').write_text(p.stdout+p.stderr)
 if p.returncode:raise RuntimeError('Restore failed; inspect lane-restore.txt')
 return json.loads(p.stdout.strip().splitlines()[-1])
m.restore_via_subprocess=restore
if '--restore' in sys.argv:
 print(json.dumps(m.restore_real_sources()))
else:
 try:
  rc=m.main()
  (OUT/'pg-battery.exit').write_text(str(rc))
 finally:
  # Also recover if a lane raises rather than returning a test failure.
  if not (OUT/'i37-tests-results.json').exists():
   m.drop_d2d6_db();restore()
