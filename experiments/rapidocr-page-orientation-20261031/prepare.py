"""Freeze known regressions and explicit abstention controls before inference."""
import hashlib
import json
from pathlib import Path
import shutil
import pymupdf

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1]


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    run=ROOT/'outputs/v1';inputs=run/'inputs'
    inputs.mkdir(parents=True,exist_ok=False)
    second=REPO/'experiments/rapidocr-orientation-20261031/outputs/batch2/inputs'
    first=REPO/'experiments/rapidocr-shadow-20261031'
    manifest=json.loads((second/'manifest.json').read_text())
    checks=json.loads((second/'checks.json').read_text())
    docs=[]
    for d in manifest['documents']:
        source=second/d['input'];shutil.copyfile(source,inputs/d['input'])
        shutil.copyfile(second/(d['id']+'.png'),inputs/(d['id']+'.png'))
        assert digest(inputs/d['input'])==d['sha256']
        docs.append({**d,'expected':'oriented','rotations':[0,90,180]})
    prior=json.loads((first/'outputs/20261030T165838Z/inputs/manifest.json').read_text())
    ddog=next(d for d in prior['documents'] if d['id']=='ddog')
    shutil.copyfile(first/'outputs/20261030T165838Z/inputs/ddog.pdf',inputs/'ddog.pdf')
    shutil.copyfile(first/'outputs/20261030T165838Z/results/pages/ddog-p07/source.png',inputs/'ddog.png')
    truth=json.loads((first/'number-cells.json').read_text())
    checks['ddog']=[{**c,'kind':'exact'} for c in truth['cells']]
    docs.append({'id':'ddog','name':ddog['name'],'input':'ddog.pdf','sha256':ddog['sha256'],
                 'page':7,'expected':'oriented','rotations':[0,90,180]})
    for key in ('blank','numeric','mixed'):
        with pymupdf.open() as doc:
            pg=doc.new_page(width=595,height=842)
            if key=='numeric':
                for i,text in enumerate(['990.0','17.5%','-3.1%','+7.3%','1234.50','2026']):
                    pg.insert_text((60,110+i*80),text,fontsize=22)
            if key=='mixed':
                texts=['A reliable direction needs multiple lines',
                       'Company revenue and operating performance',
                       'Source evidence must remain available']
                for i,text in enumerate(texts):
                    pg.insert_text((45,110+i*70),text,fontsize=16)
                    pg.insert_text((550,600+i*70),text,fontsize=16,rotate=180)
            doc.save(inputs/(key+'.pdf'));pg.get_pixmap(dpi=140,alpha=False).save(inputs/(key+'.png'))
        docs.append({'id':key,'name':'Synthetic abstention control: '+key,'synthetic':True,
                     'input':key+'.pdf','page':1,'sha256':digest(inputs/(key+'.pdf')),
                     'expected':'unknown','rotations':[0]})
        checks[key]=[]
    (inputs/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf8')
    files=list((REPO/'plugins/tools').glob('*.py'))+[ROOT/'page_orientation.py',ROOT/'regression.py',
          REPO/'experiments/rapidocr-orientation-20261031/experiment.py',REPO/'experiments/rapidocr-smoke-20261019/config.py']
    record={'documents':docs,'checks_sha256':digest(inputs/'checks.json'),
            'code_sha256':{str(p.relative_to(REPO)):digest(p) for p in files},
            'thresholds':{'min_axis_boxes':3,'axis_majority':.8,'min_letters':6,'min_letter_fraction':.5,
                          'min_line_confidence':.85,'min_anchor_count':3,'min_y_bands':2,'min_relative_margin':.25},
            'production_ingestion':False,'human_review':'pending',
            'scope':'Known regression set, not unseen generalization. No expected value or angle passed to orient_image.'}
    (inputs/'manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'cases':sum(len(d['rotations']) for d in docs),'oriented_expected':15,'abstention_expected':3}))


if __name__=='__main__':main()
