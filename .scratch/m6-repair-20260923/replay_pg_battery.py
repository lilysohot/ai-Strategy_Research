"""Replay the frozen M4/M5 battery, placing every new output in this review directory."""
from pathlib import Path
import importlib.util, json, os, subprocess, sys
ROOT=Path('/home/administrator/FrontierAgent');OUT=ROOT/'.scratch/m6-repair-20260923';OLD=ROOT/'.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify'
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
def label_current_run():
 result_path=OUT/'i37-tests-results.json'
 result=json.loads(result_path.read_text())
 result['artifact']='m6-repair-regression-tests'
 result['reused_data_baseline']=result.pop('frozen_version',result.get('reused_data_baseline',{}))
 result['tested_version']={'authority_rev':'authority-context-2','candidate_snapshot':'i0c-r5d','manifest':'.scratch/m6-repair-20260923/repair-manifest.json'}
 result['discipline']['test_files']='fullchain 12 tests unchanged; authority_pg adds 2 integrity/context cases, selection fixtures now contain real hashes'
 result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
if '--restore' in sys.argv:
 print(json.dumps(m.restore_real_sources()))
elif '--label-current-run' in sys.argv:
 label_current_run()
else:
 try:
  rc=m.main()
  label_current_run()
  (OUT/'pg-battery.exit').write_text(str(rc))
 finally:
  # Also recover if a lane raises rather than returning a test failure.
  if not (OUT/'i37-tests-results.json').exists():
   m.drop_d2d6_db();restore()

