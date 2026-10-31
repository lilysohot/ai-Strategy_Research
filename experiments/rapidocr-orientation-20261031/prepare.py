"""Freeze batch two before any OCR. Requires local PDFs and historical inventory."""
import hashlib
import json
from pathlib import Path
import shutil

import pymupdf

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SELECTION = [('saas','66977e5cea1fe501ea7a0f53398de1a606458dfb10de3ab9a24bb5860b217054',16),
             ('pltr','159dafdebdebd834d3317aac90a0a6405653ab17683ce81902eb975bce181aad',9),
             ('copilot','98fbd740eea78deb7c522077789b9af3ef9a57ba42d9e37621edfb5a2f405a05',2)]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    run = ROOT/'outputs/batch2'
    if (run/'results').exists():
        raise ValueError('Refuse to restage after inference or overwrite results')
    inputs = run/'inputs'
    inputs.mkdir(parents=True,exist_ok=True)
    archive=Path('/mnt/c/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments')
    known=json.loads((archive/'rapidocr-expanded-20261030/outputs/inventory.json').read_text())
    first=json.loads((REPO/'experiments/rapidocr-shadow-20261031/outputs/20261030T165838Z/inputs/manifest.json').read_text())
    previous={d['sha256'] for d in known}|{d['sha256'] for d in first['documents']}
    sources={digest(p):p for p in (REPO/'data/corpus-incoming/20261026').glob('*.pdf')}
    documents=[]
    for key,sha,page in SELECTION:
        if sha in previous:raise ValueError('Document is not unseen by these prior inventories')
        source=sources[sha];target=inputs/(key+'.pdf')
        if target.exists():
            if digest(target)!=sha:raise ValueError('Existing staged input differs')
        else:shutil.copyfile(source,target)
        with pymupdf.open(target) as doc:
            doc[page-1].get_pixmap(dpi=140,alpha=False).save(inputs/(key+'.png'))
            documents.append({'id':key,'name':source.name,'source_path':str(source),'sha256':sha,
                              'input':target.name,'page':page,'total_pages':len(doc),
                              'unprocessed_pages':[n for n in range(1,len(doc)+1) if n!=page],
                              'novelty':'Absent from historical 68-document inventory and first 3-report trial; database state not queried.'})
    checks=json.loads((ROOT/'checks.json').read_text())
    with pymupdf.open() as doc:
        pg=doc.new_page(width=595,height=842)
        pg.insert_text((40,50),'SYNTHETIC SIGN / UNIT CONTROL',fontsize=16)
        for i,c in enumerate(checks['signs']):pg.insert_text((40,110+i*65),c['expected'],fontsize=16)
        doc.save(inputs/'signs.pdf')
        pg.get_pixmap(dpi=140,alpha=False).save(inputs/'signs.png')
    documents.append({'id':'signs','name':'Synthetic sign / unit control','synthetic':True,
                      'input':'signs.pdf','page':1,'total_pages':1,'sha256':digest(inputs/'signs.pdf')})
    shutil.copyfile(ROOT/'checks.json',inputs/'checks.json')
    manifest={'documents':documents,'rotations_clockwise':[0,90,180],'modes':['cls','no-cls'],
              'checks_sha256':digest(inputs/'checks.json'),'annotation':'Assistant transcription frozen before inference; not human acceptance.',
              'gate':'All frozen checks pass; no newly wrong upright values; rotated controls pass. Table association still requires human review.',
              'human_review':'pending','production_ingestion':False}
    (inputs/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    paths=list((REPO/'plugins/tools').glob('*.py'))+list((REPO/'experiments/rapidocr-body-20261030').glob('*.py'))+[REPO/'experiments/rapidocr-smoke-20261019/config.py',ROOT/'experiment.py',ROOT/'checks.json']
    (run/'code-before.json').write_text(json.dumps({str(p.relative_to(REPO)):digest(p) for p in paths},indent=2))
    print(json.dumps({'real_documents':3,'real_pages':3,'synthetic_pages':1,'checks':{k:len(v) for k,v in checks.items()},'ocr_runs':24}))


if __name__=='__main__':main()
