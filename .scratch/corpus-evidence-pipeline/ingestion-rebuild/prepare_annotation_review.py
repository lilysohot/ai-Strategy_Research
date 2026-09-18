import hashlib
import json
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[3]
IR = Path(__file__).resolve().parent
OUT = IR / 'audits' / 'annotation-review'
OUT.mkdir(parents=True, exist_ok=True)
data = json.loads((IR / 'i0a4-labeling-working.json').read_text())
docs = {}
for slot in data['label_slots']:
    path = ROOT / slot['source_path']
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == slot['source_sha256'], slot['doc_id']
    if slot['doc_id'] not in docs:
        docs[slot['doc_id']] = pymupdf.open(path)
        (OUT / (slot['doc_id'] + '.txt')).write_text('\n'.join(
            f'\n=== PDF page {n+1} ===\n' + p.get_text()
            for n, p in enumerate(docs[slot['doc_id']])
        ), encoding='utf-8')
    page = docs[slot['doc_id']][int(slot['locator_page']) - 1]
    page.get_pixmap(matrix=pymupdf.Matrix(1.8, 1.8)).save(OUT / (slot['gold_slot'] + '.png'))
print(json.dumps({key: len(doc) for key, doc in docs.items()}, indent=2))
