from pathlib import Path
import importlib.util, json, os, subprocess, sys
ROOT=Path('/home/administrator/FrontierAgent')
OUT=ROOT/'.scratch/m6-current-review-20260923'
BASE=ROOT/'.scratch/corpus-evidence-pipeline/ingestion-rebuild'
os.chdir(ROOT)
sys.path.insert(0,str(ROOT))
name=sys.argv[1]
if name.startswith('validate_'):
    target=BASE/'freezes'/f'{name}.py'
    with (OUT/(name+'.log')).open('w') as log:
        p=subprocess.run([sys.executable,str(target)],stdout=log,stderr=subprocess.STDOUT)
    (OUT/(name+'.exit')).write_text(str(p.returncode))
    print(name,p.returncode)
    print((OUT/(name+'.log')).read_text()[-6000:])
else:
    target=BASE/'audits/20260923-m6-independent-review'/f'{name}.py'
    spec=importlib.util.spec_from_file_location(name,target)
    m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m
    spec.loader.exec_module(m)
    def save(n,v):
        (OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n')
    m.write_once=save
    code=m.main()
    (OUT/(name+'.exit')).write_text(str(code))
    print(name,'exit',code)
