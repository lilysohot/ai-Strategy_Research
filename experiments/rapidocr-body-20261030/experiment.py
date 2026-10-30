"""Offline, bounded experiment. The production reader is only a comparison."""
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path
from body_reader import read_page
ROOT=Path('/lab'); OUT=ROOT/'outputs'
sys.path.insert(0,'/previous')
import lab as old
old.OUT=OUT; old.PYTHON=sys.executable

def write(name,value):
    p=OUT/name; p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

def native_reader(path,page):
    from pypdf import PdfReader
    return PdfReader(path).pages[page-1].extract_text() or ''

def ocr_reader(path,page):
    try:
        completed=subprocess.run([sys.executable,'/prior/test_ocr.py','worker','--pdf',path,
                                  '--page',str(page),'--size','small'],capture_output=True,timeout=65)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError('OCR exceeded 65 seconds; child killed and reaped') from exc
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode('utf8','replace')[-1500:])
    return json.loads(completed.stdout)

def command(item,extra=None):
    return [sys.executable,'/lab/experiment.py','worker','--pdf',item['path'],'--page',str(item['page'])]+(extra or [])

def items():
    original=json.loads(Path('/expanded/manifest.json').read_text())
    extra=[]
    for doc,page in [('d061',5),('d068',4),('d021',5),('d065',4)]:
        template=next(x for x in original if x['doc_id']==doc)
        extra.append({**template,'id':f'{doc}-p{page:02d}','page':page,'held_out':True})
    return original+extra

def prepare():
    import pymupdf
    selected=items(); write('manifest.json',selected)
    for item in selected:
        if not item.get('held_out'): continue
        with pymupdf.open(item['path']) as doc:
            p=doc[item['page']-1]
            p.get_pixmap(dpi=120,alpha=False).save(OUT/f"{item['id']}.png")
            (OUT/f"{item['id']}-preview-native.txt").write_text(p.get_text('text',sort=True),encoding='utf8')

def baseline(selected,phase):
    result={}
    for item in selected:
        result.update(old.baseline([{'id':item['id'],'path':item['path'],'pages':[item['page']]}],phase))
    write(f'baseline-{phase}.json',result)
    return result

def run():
    selected=items()
    hashes={x['path']:old.digest(x['path']) for x in selected}
    frozen=old.digest(ROOT/'heldout-reference.json')
    before=baseline(selected[:26],'before')
    print('Baseline: 78 cases recorded',flush=True)
    records=[]
    for i,item in enumerate(selected,1):
        result=old.measured(command(item),timeout=90)
        write(f"runs/{item['id']}.json",result)
        (OUT/f"{item['id']}.txt").write_text(result.get('text',''),encoding='utf8')
        records.append({'id':item['id'],'held_out':item.get('held_out',False),'result':result})
        write('results.json',records)
        print(json.dumps({'page':i,'id':item['id'],**{k:result.get(k) for k in ('status','source','wall_seconds','sampled_peak_tree_mib')}}),flush=True)
    after=baseline(selected[:26],'after')
    probes={
        'blank':old.measured(command({'path':'/previous/samples/control.pdf','page':3}),timeout=75),
        'damaged':old.measured(command({'path':'/previous/samples/damaged.pdf','page':1}),timeout=10),
        'adapter_timeout':old.measured(command(selected[2],['--probe-timeout']),timeout=10),
        'outer_timeout':old.measured(command(selected[2]),timeout=.25)}
    import psutil
    remaining=[p.pid for p in psutil.process_iter(['cmdline']) if p.pid!=os.getpid()
               and 'worker' in (p.info['cmdline'] or [])]
    checks={'baseline_cases':len(before),'baseline_equal':before==after,
            'inputs_unchanged':hashes=={p:old.digest(p) for p in hashes},
            'reference_unchanged':frozen==old.digest(ROOT/'heldout-reference.json'),
            'workers_remaining':remaining,'probes':probes,
            'all_pages_completed':all(r['result']['status'] in ('ok','needs_review') for r in records),
            'native_exact':all(r['result']['text']==r['result']['native_text'] for r in records if r['result'].get('source')=='native'),
            'ocr_lines_once':all(sorted(x['id'] for x in r['result']['lines'])==list(range(len(r['result']['ocr_original']['lines'])))
                                 for r in records if r['result'].get('source')=='ocr')}
    write('checks.json',checks)
    assert all(checks[k] for k in ('baseline_equal','inputs_unchanged','reference_unchanged','all_pages_completed','native_exact','ocr_lines_once'))
    assert not remaining
    assert [probes[k]['status'] for k in probes]==['empty','error','timeout','timeout']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run','worker'])
    p.add_argument('--pdf');p.add_argument('--page',type=int,default=1);p.add_argument('--probe-timeout',action='store_true')
    args=p.parse_args()
    if args.action=='prepare':prepare()
    elif args.action=='run':run()
    else:
        adapter=ocr_reader
        if args.probe_timeout:
            def adapter(*_):
                try: subprocess.run([sys.executable,'-c','import time; time.sleep(30)'],timeout=.05,capture_output=True)
                except subprocess.TimeoutExpired as exc: raise TimeoutError('forced bounded adapter timeout') from exc
        print(json.dumps(read_page(args.pdf,args.page,enabled=True,native_reader=native_reader,ocr_reader=adapter),ensure_ascii=False))
