"""Batch-two shadow experiment; frozen annotations, no production writes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open('x', encoding='utf8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def unrotate(point, rotation):
    x, y = point
    if rotation == 0:
        return x, y
    if rotation == 90:
        return y, 1-x
    if rotation == 180:
        return 1-x, 1-y
    raise ValueError('Only frozen 0/90/180 clockwise controls are allowed')


def evaluate(raw, checks):
    rows = []
    for check in checks:
        x0, y0, x1, y1 = check['rect']
        hits = []
        for i, (text, box) in enumerate(zip(raw['lines'], raw['boxes_normalized_original'])):
            cx = sum(p[0] for p in box)/4
            cy = sum(p[1] for p in box)/4
            if x0 <= cx < x1 and y0 <= cy < y1:
                hits.append((round(cy, 3), cx, i, text))
        hits.sort()
        actual = ''.join(re.sub(r'\s+', '', h[3]) for h in hits)
        expected = re.sub(r'\s+', '', check['expected'])
        match = actual == expected if check['kind'] == 'exact' else expected in actual
        rows.append({'id': check['id'], 'expected': check['expected'], 'actual': actual,
                     'matched': match, 'line_indices': [h[2] for h in hits]})
    return {'matched': sum(r['matched'] for r in rows), 'total': len(rows), 'checks': rows}


def worker(args):
    import numpy as np
    import pymupdf
    from rapidocr import RapidOCR
    sys.path.insert(0, '/modelconfig')
    from config import params
    start = time.perf_counter()
    with pymupdf.open(args.pdf) as doc:
        pg = doc[args.page-1]
        if pg.rect.width*pg.rect.height*(300/72)**2 > 25_000_000:
            raise ValueError('Pixel budget exceeded')
        pix = pg.get_pixmap(dpi=300, alpha=False, colorspace=pymupdf.csRGB)
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    rgb = np.rot90(rgb, k=-(args.rotation//90)).copy()
    h, w = rgb.shape[:2]
    engine = RapidOCR(params=params('small'))
    result = engine(rgb[:, :, ::-1].copy(), use_det=True, use_cls=args.mode=='cls', use_rec=True)
    boxes = result.boxes.tolist() if result.boxes is not None else []
    raw = {'lines': list(result.txts) if result.txts is not None else [],
           'scores': [float(s) for s in result.scores] if result.scores is not None else [],
           'boxes': boxes, 'render_pixels_rotated': [w,h],
           'boxes_normalized_original': [[unrotate((x/w,y/h),args.rotation) for x,y in box] for box in boxes]}
    print(json.dumps({'status': 'ok' if raw['lines'] else 'empty', 'raw': raw,
                      'worker_seconds': time.perf_counter()-start}, ensure_ascii=False))


def run():
    sys.path[:0] = ['/helpers', '/shadow']
    from lab import measured
    inputs, out = Path('/inputs'), Path('/out')
    manifest = json.loads((inputs/'manifest.json').read_text())
    fixture = json.loads((inputs/'checks.json').read_text())
    if digest(inputs/'checks.json') != manifest['checks_sha256']:
        raise ValueError('Checks were modified after freeze')
    for d in manifest['documents']:
        if digest(inputs/d['input']) != d['sha256']:
            raise ValueError('Input hash changed')
    write(out/'manifest.json', manifest)
    write(out/'checks.json', fixture)
    records = []
    baseline_cases = 0
    baseline_equal = True
    for d in manifest['documents']:
        pdf = inputs/d['input']
        before = {}
        if not d.get('synthetic',False):
            for mode in ('auto','text','image'):
                command = [sys.executable,'/reference/_doc_reader.py',str(pdf),'200000','-','0',mode,str(d['page'])]
                p = subprocess.run(command,capture_output=True,text=True,check=True,timeout=90)
                (out/f'{d["id"]}-baseline-{mode}.txt').write_text(p.stdout,encoding='utf8')
                before[mode] = hashlib.sha256(p.stdout.encode()).hexdigest()
            normal = measured([sys.executable,'/shadow/trial.py','page','--pdf',str(pdf),'--page',str(d['page'])], timeout=90)
            write(out/f'{d["id"]}-normal-route.json',normal)
            print(json.dumps({'normal_route': d['id'], 'status':normal.get('status'),
                              'source':normal.get('candidate',{}).get('source') }),flush=True)
        for rotation in manifest['rotations_clockwise']:
            for mode in manifest['modes']:
                key = f'{d["id"]}-r{rotation}-{mode}'
                result = measured([sys.executable,__file__,'worker','--pdf',str(pdf),'--page',str(d['page']),
                                   '--rotation',str(rotation),'--mode',mode],timeout=90)
                write(out/(key+'.json'),result)
                score = evaluate(result['raw'], fixture[d['id']]) if 'raw' in result else {'matched':0,'total':len(fixture[d['id']]),'checks':[]}
                record = {'id':key,'document':d['id'],'synthetic':d.get('synthetic',False),
                          'rotation':rotation,'mode':mode,'score':score,'status':result.get('status'),
                          'seconds':result['wall_seconds'],'peak_tree_mib':result['sampled_peak_tree_mib'],
                          'human_review':'pending','output_sha256':digest(out/(key+'.json'))}
                records.append(record)
                print(json.dumps({k:record[k] for k in ('id','status','seconds')}|{'matched':score['matched'],'total':score['total']}),flush=True)
        for mode, old_sha in before.items():
            p = subprocess.run([sys.executable,'/reference/_doc_reader.py',str(pdf),'200000','-','0',mode,str(d['page'])],
                               capture_output=True,text=True,check=True,timeout=90)
            baseline_equal &= hashlib.sha256(p.stdout.encode()).hexdigest() == old_sha
            baseline_cases += 1
    write(out/'records.json', records)
    write(out/'summary.json',{'baseline_cases':baseline_cases,'baseline_outputs_unchanged':baseline_equal,
                              'real_documents':3,'real_pages':3,'synthetic_pages':1,'ocr_runs':len(records),
                              'production_ingestion':False,'human_review':'pending',
                              'default_settings_changed':False,'checks_sha256':manifest['checks_sha256']})
    assert baseline_equal


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=['worker','run'])
    parser.add_argument('--pdf');parser.add_argument('--page',type=int)
    parser.add_argument('--rotation',type=int,choices=[0,90,180]);parser.add_argument('--mode',choices=['cls','no-cls'])
    args=parser.parse_args()
    if args.action=='worker':worker(args)
    else:run()
