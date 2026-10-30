"""Isolated research harness only; no production integration."""
import argparse,ast,hashlib,importlib.metadata,json,os,re,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path('/lab');OUT=ROOT/'outputs'
sys.path.insert(0,'/previous')
import lab as old
old.OUT=OUT;old.PYTHON='/opt/rapid/bin/python'
sys.path.insert(0,'/prior')
from test_ocr import worker

def write(name,value):
    target=OUT/name
    target.parent.mkdir(exist_ok=True,parents=True)
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

def command(item):
    return [sys.executable,'/lab/experiment.py','worker','--pdf',item['path'],'--page',str(item['page'])]

def baseline(items,phase):
    results={}
    for i,item in enumerate(items,1):
        results.update(old.baseline([{'id':item['id'],'path':item['path'],'pages':[item['page']]}],phase))
        if i%6==0:print(f'baseline {phase}: {i}/{len(items)} pages',flush=True)
    write(f'baseline-{phase}.json',results)
    return results

def run():
    items=json.loads((ROOT/'manifest.json').read_text())
    reference_hash=old.digest(ROOT/'reference-frozen.json')
    assert reference_hash==(OUT/'reference-sha256.txt').read_text().strip()
    hashes={i['path']:old.digest(i['path']) for i in items}
    before=baseline(items,'before')
    write('environment.json',{'python':sys.version,'platform':sys.platform,
        'packages':{p:importlib.metadata.version(p) for p in ('rapidocr','onnxruntime','pymupdf','pypdf','numpy','pillow')},
        'cpu_max':Path('/sys/fs/cgroup/cpu.max').read_text(),'memory_max':Path('/sys/fs/cgroup/memory.max').read_text(),
        'models':json.loads(Path('/opt/model-manifest.json').read_text()),'input_sha256':hashes,
        'reference_sha256':reference_hash,'network':'docker --network none; PDF copies read-only; no original directory mounted',
        'rendering':'300dpi RGB to BGR, 25 megapixel pre-render cap',
        'preprocessing':'RapidOCR default max_side_len=2000, detector min side736, text_score=0.5, small det+rec, v4 cls, ONNX intra/inter1',
        'measurement':'Each page in fresh process. Wall includes imports/render/model/OCR. RSS tree sampled20ms. Serial 2CPU/4GiB. 90-second deadline. Primary26 pages once; 5 sentinel pages twice more.'})
    (OUT/'requirements-resolved.txt').write_text(subprocess.check_output([sys.executable,'-m','pip','freeze']).decode())
    (OUT/'rapidocr-default.yaml').write_text(Path('/opt/rapid/lib/python3.12/site-packages/rapidocr/config.yaml').read_text())
    records=[]
    for index,item in enumerate(items,1):
        saved=OUT/'runs'/f"{item['id']}-r1.json"
        result=json.loads(saved.read_text()) if saved.exists() else old.measured(command(item),timeout=90)
        write(f"runs/{item['id']}-r1.json",result)
        (OUT/f"{item['id']}.txt").write_text(result.get('text',''),encoding='utf8')
        records.append({'id':item['id'],'result':result})
        write('results.json',records)
        print(json.dumps({'page':index,'id':item['id'],**{k:result.get(k) for k in ('status','wall_seconds','sampled_peak_tree_mib')} }),flush=True)
    repeats={}
    sentinels={'d001-p01','d002-p01','d061-p02','d066-p01','d067-p01'}
    for item in items:
        if item['id'] not in sentinels:continue
        runs=[next(x['result'] for x in records if x['id']==item['id'])]
        for repeat in (2,3):
            saved=OUT/'runs'/f"{item['id']}-r{repeat}.json"
            result=json.loads(saved.read_text()) if saved.exists() else old.measured(command(item),timeout=90)
            write(f"runs/{item['id']}-r{repeat}.json",result);runs.append(result)
            print(f"repeat {item['id']} r{repeat}: {result['status']} {result['wall_seconds']}s",flush=True)
        repeats[item['id']]={'text_identical':len({r.get('text') for r in runs})==1,
            'statuses':[r['status'] for r in runs],'wall_seconds':[r['wall_seconds'] for r in runs]}
    write('repeat-checks.json',repeats)
    after=baseline(items,'after')
    blank={'path':'/previous/samples/control.pdf','page':3}
    damaged={'path':'/previous/samples/damaged.pdf','page':1}
    probes={'blank':old.measured(command(blank),timeout=30),'damaged':old.measured(command(damaged),timeout=30),
            'forced_timeout':old.measured(command(items[0]),timeout=0.25)}
    import psutil
    remaining=[p.pid for p in psutil.process_iter(['cmdline']) if p.pid!=os.getpid()
               and 'worker' in (p.info['cmdline'] or []) and '/lab/experiment.py' in (p.info['cmdline'] or [])]
    checks={'baseline_case_count':len(before),'baseline_outputs_equal':before==after,
        'inputs_unchanged':hashes=={i['path']:old.digest(i['path']) for i in items},
        'reference_unchanged':reference_hash==old.digest(ROOT/'reference-frozen.json'),
        'worker_processes_remaining':remaining,'probes':probes}
    write('checks.json',checks)
    assert checks['baseline_outputs_equal'] and checks['inputs_unchanged'] and checks['reference_unchanged'] and not remaining
    assert probes['blank']['status']=='empty' and probes['damaged']['status']=='error' and probes['forced_timeout']['status']=='timeout'

def evaluate():
    ref=json.loads((ROOT/'reference-frozen.json').read_text())
    errata=json.loads((ROOT/'reference-errata.json').read_text())
    for correction in errata['corrections']:
        values=ref['pages'][correction['id']][correction['field']]
        assert values[correction['index']]==correction['old']
        values[correction['index']]=correction['new']
    write('reference-effective.json',ref)
    source=ast.parse(Path('/previous/evaluate_real.py').read_text())
    namespace={'re':re}
    exec(compile(ast.Module(body=[n for n in source.body if isinstance(n,ast.FunctionDef)],type_ignores=[]),'prior_metric','exec'),namespace)
    norm,distance=namespace['norm'],namespace['excerpt_distance']
    rows=[]
    for record in json.loads((OUT/'results.json').read_text()):
        key=record['id'];spec=ref['pages'][key];r=record['result']
        text=norm(r.get('text',''))
        native=norm((OUT/f'baseline-before-{key}-text.txt').read_text())
        excerpts=[]
        for target in spec['excerpts']:
            error,match=distance(norm(target),text)
            native_error,native_match=distance(norm(target),native)
            excerpts.append({'reference':target,'matched':match,'edits':error,'chars':len(norm(target)),
                             'native_edits':native_error,'native_match':native_match,'missing':error/len(norm(target))>=0.5})
        missing_keys=[t for t in spec['keys'] if norm(t) not in text]
        rows.append({'id':key,'language':spec['language'],'source_type':spec['source_type'],
            'control':spec.get('control'),'previous_sample':spec.get('previous_sample',False),
            'status':r['status'],'wall_seconds':r['wall_seconds'],'peak_mib':r['sampled_peak_tree_mib'],
            'text_chars':len(text),'line_count':len(r.get('lines',[])),
            'reference_chars':sum(e['chars'] for e in excerpts),'edits':sum(e['edits'] for e in excerpts),
            'native_edits':sum(e['native_edits'] for e in excerpts),
            'missing_excerpts':sum(e['missing'] for e in excerpts),'excerpts':excerpts,
            'keys_total':len(spec['keys']),'missing_keys':missing_keys,
            'native_missing_keys':[t for t in spec['keys'] if norm(t) not in native]})
    write('evaluation.json',rows)
    def aggregate(group):
        chars=sum(r['reference_chars'] for r in group)
        keys=sum(r['keys_total'] for r in group)
        return {'pages':len(group),'body_pages':sum(r['reference_chars']>0 for r in group),'chars':chars,
            'edits':sum(r['edits'] for r in group),'cer':sum(r['edits'] for r in group)/chars if chars else None,
            'native_cer':sum(r['native_edits'] for r in group)/chars if chars else None,
            'keys_total':keys,'keys_present':keys-sum(len(r['missing_keys']) for r in group),
            'missing_excerpts':sum(r['missing_excerpts'] for r in group)}
    times=sorted(r['wall_seconds'] for r in rows)
    groups={'all':aggregate(rows),'new_only':aggregate([r for r in rows if not r['previous_sample']])}
    for field in ('source_type','language'):
        for value in sorted({r[field] for r in rows}):groups[f'{field}:{value}']=aggregate([r for r in rows if r[field]==value])
    for st in ('scan','native'):
        for lang in ('zh','en','mixed'):
            group=[r for r in rows if r['source_type']==st and r['language']==lang]
            if group:groups[f'{st}:{lang}']=aggregate(group)
    gates=ref['predeclared_gates'];whole=groups['all']
    summary={'pages':len(rows),'ok':sum(r['status']=='ok' for r in rows),'groups':groups,
        'timing':{'total_wall_seconds':sum(times),'median':statistics.median(times),
                  'p95_nearest_rank':times[__import__('math').ceil(len(times)*0.95)-1],'max':max(times)},
        'max_sampled_worker_mib':max(r['peak_mib'] for r in rows),
        'gate_results':{'success':all(r['status']=='ok' for r in rows),
            'median_time':statistics.median(times)<=gates['median_wall_seconds_max'],
            'p95_time':times[__import__('math').ceil(len(times)*0.95)-1]<=gates['p95_wall_seconds_max'],
            'memory':max(r['peak_mib'] for r in rows)<=gates['peak_worker_mib_max'],
            'zh_cer':groups['language:zh']['cer']<=gates['weighted_body_cer_zh_max'],
            'en_cer':groups['language:en']['cer']<=gates['weighted_body_cer_en_max'],
            'exact_key_presence':whole['keys_present']/whole['keys_total']>=gates['exact_key_presence_min'],
            'no_missing_excerpts':whole['missing_excerpts']==0}}
    write('summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['run','evaluate','worker'])
    parser.add_argument('--pdf');parser.add_argument('--page',type=int,default=1)
    args=parser.parse_args()
    if args.action=='worker':worker(args.pdf,'small',args.page)
    elif args.action=='run':run()
    else:evaluate()
