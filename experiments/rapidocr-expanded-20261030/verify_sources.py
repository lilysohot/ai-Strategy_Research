import hashlib,json
from pathlib import Path
root=Path(__file__).parent
inventory=json.loads((root/'outputs/inventory.json').read_text(encoding='utf8'))
changed=[]
for doc in inventory:
    if hashlib.sha256(Path(doc['path']).read_bytes()).hexdigest()!=doc['sha256']:
        changed.append(doc['name'])
result={'corpus_files_checked':len(inventory),'changed_files':changed}
(root/'outputs/source-isolation-after.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=False))
assert not changed
