import hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent
prior=ROOT.parent/'rapidocr-expanded-20261030'
inventory=json.loads((prior/'outputs/inventory.json').read_text(encoding='utf8'))
selected=[('d004',1),('d006',1),('d007',1),('d024',1),('d028',1),('d003',4),('d017',1),('d050',1)]
manifest=[]
for doc,page in selected:
    d=next(x for x in inventory if x['id']==doc)
    data=Path(d['path']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==d['sha256']
    (ROOT/'samples'/f'{doc}.pdf').write_bytes(data)
    manifest.append({'id':f'{doc}-p{page:02d}','doc_id':doc,'page':page,'path':f'/samples/{doc}.pdf',
                     'original_path':d['path'],'name':d['name'],'sha256':d['sha256']})
(ROOT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
print('Staged',len(manifest),'new source pages in isolated PDF copies')
