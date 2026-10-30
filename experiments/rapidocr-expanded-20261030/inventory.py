"""Read-only local inventory; no OCR and no network."""
import hashlib
import json
import sys
from pathlib import Path
from pypdf import PdfReader

root = Path(__file__).parent
corpus = Path(r'\\wsl.localhost\Ubuntu\home\administrator\FrontierAgent\data\corpus')
records=[]
for i,p in enumerate(sorted(corpus.glob('*.pdf')),1):
    item={'id':f'd{i:03d}','name':p.name,'path':str(p),'bytes':p.stat().st_size,
          'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    try:
        reader=PdfReader(p)
        n=len(reader.pages)
        item['pages']=n
        candidates=sorted(set([*range(min(n,4)),n//2,max(0,n-3)]))
        item['candidates']=[]
        for index in candidates:
            page=reader.pages[index]
            text=page.extract_text() or ''
            images=[]
            resources=page.get('/Resources',{})
            resources=resources.get_object() if hasattr(resources,'get_object') else resources
            xobjects=resources.get('/XObject',{})
            xobjects=xobjects.get_object() if hasattr(xobjects,'get_object') else xobjects
            for ref in xobjects.values():
                obj=ref.get_object()
                if obj.get('/Subtype')=='/Image':
                    images.append([obj.get('/Width'),obj.get('/Height')])
            item['candidates'].append({'page':index+1,'chars':len(text.strip()),
                'width':float(page.mediabox.width),'height':float(page.mediabox.height),
                'images':images,'excerpt':text[:200]})
    except Exception as e: item['error']=repr(e)
    records.append(item)
    print(json.dumps({k:v for k,v in item.items() if k in ('id','name','pages','error')},ensure_ascii=False),flush=True)
(root/'outputs/inventory.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
