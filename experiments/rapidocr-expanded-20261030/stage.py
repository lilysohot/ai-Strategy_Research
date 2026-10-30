import hashlib,json,shutil
from pathlib import Path
from pypdf import PdfReader
root=Path(__file__).parent
inventory=json.loads((root/'outputs/inventory.json').read_text(encoding='utf8'))
selection={'d001':[1,3],'d002':[1,2,3,4],'d005':[1],'d021':[2,3],
           'd035':[2,5,13],'d039':[1],'d054':[1],'d061':[1,2,3,4],
           'd062':[2],'d064':[1],'d065':[3],'d066':[1],'d067':[1],'d068':[1,2,3]}
(root/'samples').mkdir(exist_ok=True)
manifest=[]
for doc in inventory:
    if doc['id'] not in selection:continue
    dest=root/'samples'/f"{doc['id']}.pdf"
    shutil.copyfile(doc['path'],dest)
    assert hashlib.sha256(dest.read_bytes()).hexdigest()==doc['sha256']
    for page in selection[doc['id']]:
        meta=next((c for c in doc['candidates'] if c['page']==page),None)
        if meta is None:
            p=PdfReader(dest).pages[page-1]
            text=p.extract_text() or ''
            meta={'page':page,'chars':len(text.strip()),'width':float(p.mediabox.width),
                  'height':float(p.mediabox.height),'excerpt':text[:200]}
        manifest.append({'id':f"{doc['id']}-p{page:02d}",'doc_id':doc['id'],
             'name':doc['name'],'original_path':doc['path'],'sha256':doc['sha256'],
             'path':f"/samples/{doc['id']}.pdf",'page':page,'inventory_page':meta})
assert len(manifest)==26
(root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
print(f'Staged {len(selection)} documents, {len(manifest)} pages')
