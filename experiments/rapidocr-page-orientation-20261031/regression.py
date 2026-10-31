"""Harness owns synthetic rotations and annotations; orientation code sees pixels only."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path,value):
    with path.open('x',encoding='utf8') as handle:json.dump(value,handle,ensure_ascii=False,indent=2)


def worker(args):
    import numpy as np
    import pymupdf
    from rapidocr import RapidOCR
    from page_orientation import orient_image
    sys.path.insert(0,'/modelconfig')
    from config import params
    with pymupdf.open(args.pdf) as doc:
        pg=doc[args.page-1]
        if pg.rect.width*pg.rect.height*(300/72)**2>25_000_000:raise ValueError('Pixel budget exceeded')
        pix=pg.get_pixmap(dpi=300,alpha=False,colorspace=pymupdf.csRGB)
    rgb=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,3)
    image=np.rot90(rgb,k=-(args.rotation//90)).copy()
    decision=orient_image(image,RapidOCR(params=params('small')))
    print(json.dumps({'status':decision['status'],'decision':decision},ensure_ascii=False))


def run():
    sys.path[:0]=['/helpers','/eval']
    from lab import measured
    from experiment import evaluate
    from page_orientation import inverse_point
    inputs,out=Path('/inputs'),Path('/out')
    manifest=json.loads((inputs/'manifest.json').read_text());checks=json.loads((inputs/'checks.json').read_text())
    assert digest(inputs/'checks.json')==manifest['checks_sha256']
    write(out/'manifest.json',manifest);write(out/'checks.json',checks)
    records=[]
    for d in manifest['documents']:
        assert digest(inputs/d['input'])==d['sha256']
        for rotation in d['rotations']:
            key=f'{d["id"]}-r{rotation}'
            result=measured([sys.executable,__file__,'worker','--pdf',str(inputs/d['input']),
                             '--page',str(d['page']),'--rotation',str(rotation)],timeout=90)
            write(out/(key+'.json'),result)
            decision=result.get('decision',{})
            correction=decision.get('correction_clockwise')
            direction_ok=(decision.get('status')=='unknown' if d['expected']=='unknown' else
                          decision.get('status')=='oriented' and (rotation+correction)%360==0)
            score={'matched':0,'total':len(checks[d['id']]),'checks':[]}
            if 'raw' in decision:
                raw={**decision['raw'],'boxes_normalized_original':[[inverse_point(p,rotation) for p in box]
                      for box in decision['boxes_normalized_input']]}
                score=evaluate(raw,checks[d['id']])
            record={'id':key,'document':d['id'],'rotation':rotation,'expected_status':d['expected'],
                    'status':decision.get('status',result['status']),'correction_clockwise':correction,
                    'direction_ok':direction_ok,'score':score,'seconds':result['wall_seconds'],
                    'peak_tree_mib':result['sampled_peak_tree_mib'],'human_review':'pending',
                    'passed':direction_ok and score['matched']==score['total'],'sha256':digest(out/(key+'.json'))}
            records.append(record)
            print(json.dumps({k:record[k] for k in ('id','status','correction_clockwise','direction_ok','passed','seconds')}|
                             {'matched':score['matched'],'total':score['total']}),flush=True)
    write(out/'records.json',records)
    write(out/'summary.json',{'cases':len(records),'passed':sum(r['passed'] for r in records),
                              'all_passed':all(r['passed'] for r in records),'production_ingestion':False,
                              'worker_seconds':sum(r['seconds'] for r in records),
                              'max_sampled_worker_tree_mib':max(r['peak_tree_mib'] for r in records),
                              'human_review':'pending'})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['worker','run'])
    parser.add_argument('--pdf');parser.add_argument('--page',type=int)
    parser.add_argument('--rotation',type=int,choices=[0,90,180]);args=parser.parse_args()
    if args.action=='worker':worker(args)
    else:run()
