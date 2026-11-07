"""Read only: replay observed locators against the same immutable corpus build."""
import hashlib
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
from plugins.corpus.service import get_service

doc = 'cv2:3d10e850ae56226f927c508c3600beaff482b4efaf5550397f07218524fe299a'
svc = get_service()
wrong = svc.context_inventory(doc, ['chunk:0'])
body_locator = 'chunk:3d10e850ae56226f:body:0000'
correct = svc.context_inventory(doc, [body_locator])
body = svc.fetch_verbatim(doc, body_locator)
result = {
    'doc_id': doc,
    'invalid_locator_count': wrong['total_chunks'],
    'invalid_locator_unknown': wrong['unknown_members'],
    'actual_body_locator': body_locator,
    'actual_body_inventory_count': correct['total_chunks'],
    'actual_body_kinds': correct['by_kind'],
    'actual_body_chars': len(body.text),
    'actual_body_sha256': hashlib.sha256(body.text.encode()).hexdigest(),
}
Path('.scratch/audit_94e_live_body.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
assert wrong['total_chunks'] == 0 and correct['total_chunks'] == 1 and body.text
