"""Local OCR derivatives, page images preserved and parent hashes recorded."""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import fitz

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
RUNTIME=HERE/'ocr-runtime/root'
for package in (HERE/'ocr-runtime/packages').glob('*.deb'):
    subprocess.run(['dpkg-deb','-x',str(package),str(RUNTIME)],check=True)
env={**os.environ,'LD_LIBRARY_PATH':str(RUNTIME/'usr/lib/x86_64-linux-gnu'),
     'TESSDATA_PREFIX':str(RUNTIME/'usr/share/tesseract-ocr/5/tessdata'),'OMP_THREAD_LIMIT':'2'}
exe=str(RUNTIME/'usr/bin/tesseract')
parser=argparse.ArgumentParser();parser.add_argument('--setup-only',action='store_true');args=parser.parse_args()
version=subprocess.run([exe,'--version'],env=env,text=True,capture_output=True)
print(version.stdout or version.stderr,flush=True)
version.check_returncode()
if args.setup_only: raise SystemExit(0)
output=ROOT/'data/vector-pilot-clean7-20261021/ocr-derivatives'
output.mkdir(parents=True,exist_ok=True)
inventory=json.loads((HERE/'inventory.json').read_text())
records=[]
for row in inventory:
    if sum(row['page_text_chars'])>=200: continue
    sid=row['source_id']; language='eng' if sid.startswith('8935e529') else 'chi_sim+eng'
    path=Path(row['path']); assert hashlib.sha256(path.read_bytes()).hexdigest()==sid
    target=output/(path.stem+'.local-ocr.pdf')
    if target.exists(): raise RuntimeError('Refusing to overwrite OCR derivative: '+str(target))
    page_info=[]; merged=fitz.open()
    with fitz.open(path) as original:
        for idx,page in enumerate(original):
            prefix=HERE/'ocr-pages'/f'{sid[:8]}-{idx+1}'
            prefix.parent.mkdir(parents=True,exist_ok=True)
            image=Path(str(prefix)+'.png')
            pix=page.get_pixmap(dpi=300,colorspace=fitz.csRGB,alpha=False)
            pix.save(image)
            subprocess.run([exe,str(image),str(prefix),'-l',language,'--dpi','300',
                            'pdf','txt','tsv'],env=env,check=True,capture_output=True)
            with fitz.open(str(prefix)+'.pdf') as rendered:
                # Preserve original page dimensions when importing the OCR page.
                newpage=merged.new_page(width=page.rect.width,height=page.rect.height)
                newpage.show_pdf_page(newpage.rect,rendered,0)
            text=Path(str(prefix)+'.txt').read_text()
            page_info.append({'page':idx+1,'text_chars':len(text.strip()),'language':language,
                              'text_path':str(prefix)+'.txt','tsv_path':str(prefix)+'.tsv'})
            print(json.dumps({'source':sid[:8],'page':idx+1,'text_chars':len(text.strip())}),flush=True)
    merged.set_metadata({'title':path.stem+' [local OCR derivative]',
        'subject':'OCR-derived text, not verified transcription; parent_sha256='+sid,
        'producer':version.stdout.splitlines()[0]})
    merged.save(target,garbage=4,deflate=True);merged.close()
    with fitz.open(target) as derivative:
        assert len(derivative)==row['pages']
        assert all(len(p.get_text().strip())>100 for p in derivative)
        derivative[0].get_pixmap().save(str(HERE/f'{sid[:8]}-ocr-first.png'))
    records.append({'parent_source_id':sid,'parent_path':str(path),'derived_path':str(target),
        'derived_source_id':hashlib.sha256(target.read_bytes()).hexdigest(),
        'method':'local-tesseract-300dpi','version':version.stdout.splitlines()[0],
        'language':language,'pages':page_info,'coverage_claim':'ocr_text_not_verified_transcription'})
    (HERE/'ocr-provenance.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
