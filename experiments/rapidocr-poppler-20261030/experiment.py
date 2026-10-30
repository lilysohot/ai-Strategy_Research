"""Read-only production comparison; eight new source pages; injected native holes.

Only forced OCR is freshly timed. Hybrid routes reuse raw OCR and are not timed
as end-to-end OCR. No production imports of this module or network requests.
"""
import argparse,hashlib,json,os,re,runpy,shutil,subprocess,sys
from pathlib import Path
ROOT=Path('/lab');OUT=ROOT/'outputs'
sys.path.insert(0,'/previous');import lab as old
sys.path.insert(0,'/body');from body_reader import read_page
old.OUT=OUT;old.PYTHON=sys.executable
pdf=runpy.run_path('/reference/_reader_pdf.py')

def write(name,value):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

def selected():
    original=json.loads(Path('/expanded/manifest.json').read_text())
    for x in original:x['path']=x['path'].replace('/samples/','/expanded/samples/')
    return original+json.loads((ROOT/'manifest.json').read_text())

def native(path,page):
    # Require the CLI to succeed so this test cannot silently fall back to pypdf.
    out=subprocess.run(['pdftotext','-layout','-f',str(page),'-l',str(page),path,'-'],capture_output=True,text=True,timeout=60)
    if out.returncode:raise RuntimeError(out.stderr)
    actual=pdf['_pdf_page_text'](path,page)
    assert actual==out.stdout
    return actual

def prepare():
    from PIL import Image,ImageDraw
    items=selected()[26:]
    for item in items:
        key=item['id']
        subprocess.run(['pdftoppm','-png','-r','110','-f',str(item['page']),'-l',str(item['page']),'-singlefile',item['path'],str(OUT/key)],check=True,capture_output=True,timeout=60)
        (OUT/f'{key}-native.txt').write_text(native(item['path'],item['page']),encoding='utf8')
    for start in (0,4):
        sheet=Image.new('RGB',(1400,1900),'#ddd');draw=ImageDraw.Draw(sheet)
        for j,item in enumerate(items[start:start+4]):
            im=Image.open(OUT/f"{item['id']}.png");im.thumbnail((690,910))
            x=(j%2)*700;y=(j//2)*950
            sheet.paste(im,(x,y+30));draw.text((x+10,y+8),item['id'],fill='black')
        sheet.save(OUT/f'contact-{start//4}.jpg')
    write('environment.json',{'poppler':subprocess.check_output(['pdftotext','-v'],stderr=subprocess.STDOUT).decode(),
        'packages':Path('/opt/poppler-packages.txt').read_text(),'python':sys.version,
        'cpu_max':Path('/sys/fs/cgroup/cpu.max').read_text(),'memory_max':Path('/sys/fs/cgroup/memory.max').read_text(),
        'network':'none','runtime_scope':'Isolated reproduction of production Poppler code path; not an observed live deployment sandbox.',
        'ocr_settings':'Same immutable base as prior small model, 300dpi, ONNX threads1, fresh process per new page; 90s outer limit.'})

def baseline(items,phase):
    # Only this experiment's disposable tmpfs, never a host directory.
    cache=Path('/workspace/.readdoc_pdf_img')
    assert cache.resolve()==Path('/workspace/.readdoc_pdf_img')
    if cache.exists():shutil.rmtree(cache)
    results={}
    for i,item in enumerate(items,1):
        results.update(old.baseline([{'id':item['id'],'path':item['path'],'pages':[item['page']]}],phase))
        rendered=pdf['_pdf_to_images'](item['path'],[item['page']])
        assert len(rendered)==1 and Path(rendered[0][1]).is_file()
        if i%8==0:print(f'Poppler baseline {phase}: {i}/{len(items)}',flush=True)
    write(f'baseline-{phase}.json',results)
    pngs={str(p.relative_to(cache)):old.digest(p) for p in cache.rglob('*.png')}
    write(f'baseline-images-{phase}.json',pngs)
    return results,pngs

def regression():
    # image mode with no vision endpoint does not itself render. Exercise the
    # existing render helper explicitly, with fresh tmpfs images in each phase.
    items=selected()
    before,bpng=baseline(items,'render-before')
    after,apng=baseline(items,'render-after')
    result={'cases':len(before),'outputs_equal':before==after,'rendered_pages':len(bpng),
            'image_hashes_equal':bpng==apng,'all_commands_succeeded':all(x['exit_code']==0 for x in before.values())}
    write('render-regression.json',result)
    assert result['outputs_equal'] and result['image_hashes_equal'] and result['all_commands_succeeded'] and len(bpng)==len(items)
    print(json.dumps(result),flush=True)

def run():
    items=selected(); inputs={x['path']:old.digest(x['path']) for x in items}
    reference_hash=old.digest(ROOT/'reference.json')
    code_hash=old.digest('/body/body_reader.py')
    before,images_before=baseline(items,'before')
    raw={r['id']:r['result'] for r in json.loads(Path('/expanded/outputs/results.json').read_text())}
    actual=[]
    for i,item in enumerate(items[26:],1):
        result=old.measured([sys.executable,'/prior/test_ocr.py','worker','--pdf',item['path'],'--page',str(item['page']),'--size','small'],timeout=90)
        write(f"raw/{item['id']}.json",result);raw[item['id']]=result
        actual.append({'id':item['id'],'result':result});write('fresh-ocr.json',actual)
        print(f"New OCR {i}/8 {item['id']}: {result['status']} {result['wall_seconds']}s",flush=True)
    records=[]
    for item in items:
        key=item['id'];text=native(item['path'],item['page'])
        adapter=lambda *_:raw[key]
        hybrid=read_page(item['path'],item['page'],enabled=True,native_reader=lambda *_:text,ocr_reader=adapter)
        ordered=read_page(item['path'],item['page'],enabled=True,native_reader=lambda *_:'',ocr_reader=adapter)
        records.append({'id':key,'new_page':item in items[26:],'hybrid':hybrid,'ordered_ocr':ordered})
        write(f'pages/{key}.json',records[-1])
        (OUT/f'{key}-hybrid.txt').write_text(hybrid['text'],encoding='utf8')
    write('results.json',records)
    probes=[]
    for item in items[26:]:
        if item['id']=='d003-p04':continue  # TOC control is not a body-loss probe.
        key=item['id'];native_text=next(x['hybrid']['native_text'] for x in records if x['id']==key)
        lines=native_text.splitlines(keepends=True)
        eligible=[i for i,l in enumerate(lines) if len(re.sub(r'\s+','',l))>=35 and sum(c.isalpha() for c in l)>20]
        if len(eligible)<4:continue
        for fraction in (.25,.5):
            count=max(1,round(len(eligible)*fraction)); start=(len(eligible)-count)//2
            dropped=set(eligible[start:start+count]);missing=''.join(l for i,l in enumerate(lines) if i in dropped)
            damaged=''.join(l for i,l in enumerate(lines) if i not in dropped)
            calls=[]
            def adapter(*_):calls.append(True);return raw[key]
            result=read_page(item['path'],item['page'],enabled=True,native_reader=lambda *_:damaged,ocr_reader=adapter)
            probes.append({'id':key,'fraction_of_dense_lines_removed':fraction,'removed_text':missing,
                'removed_characters':len(re.sub(r'\s+','',missing)),'remaining_characters':len(re.sub(r'\s+','',damaged)),
                'ocr_triggered':bool(calls),'status':result['status'],'route_reason':result['route_reason'],
                'needs_review':result['needs_review'],'retained_damaged_text_unchanged':result['text']==damaged})
    write('partial-native-probes.json',probes)
    after,images_after=baseline(items,'after')
    checks={'baseline_cases':len(before),'baseline_outputs_equal':before==after,
            'rendered_pages':len(images_before),'image_hashes_equal':images_before==images_after,
            'inputs_unchanged':inputs=={p:old.digest(p) for p in inputs},
            'reference_unchanged':reference_hash==old.digest(ROOT/'reference.json'),
            'module_unchanged':code_hash==old.digest('/body/body_reader.py'),
            'fresh_ocr_completed':all(x['result']['status']=='ok' for x in actual),
            'native_preserved':all(x['hybrid']['text']==x['hybrid']['native_text'] for x in records if x['hybrid']['source']=='native'),
            'ocr_lines_preserved':all(sorted(l['id'] for l in x['ordered_ocr']['lines'])==list(range(len(raw[x['id']]['lines']))) for x in records)}
    write('checks.json',checks)
    assert all(checks[k] for k in checks if k not in ('baseline_cases','rendered_pages'))
    print(json.dumps(checks),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run','regression']);args=p.parse_args()
    {'prepare':prepare,'run':run,'regression':regression}[args.action]()
