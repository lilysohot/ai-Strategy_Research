import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
root=Path(__file__).parent
data=json.loads((root/'reference-data.json').read_text(encoding='utf8'))
prior=json.loads((root.parent/'ocr-smoke-20261019/manual-checks.json').read_text(encoding='utf8'))
for page,old,omit in [('d066-p01','user2',0),('d067-p01','user1',1)]:
    data[page]={'language':'zh','source_type':'scan','previous_sample':True,
                'excerpts':[t for i,t in enumerate(prior[old]['excerpts']) if i!=omit],
                'keys':[t for t in prior[old]['key_tokens'] if t!='+4.80%']}
manifest=json.loads((root/'manifest.json').read_text(encoding='utf8'))
assert set(data)=={m['id'] for m in manifest}
payload={'method':'Manually transcribed from complete rendered source pages before OCR; prior two pages reuse pre-existing fixed body references. Whitespace ignored; punctuation and case remain significant. 2 excerpts per new body page, 3 per prior page. No full-document truth or recall claim.',
         'created_utc':datetime.now(timezone.utc).isoformat(),
         'predeclared_gates':{'success_rate':1.0,'median_wall_seconds_max':15,'p95_wall_seconds_max':30,
           'peak_worker_mib_max':2048,'weighted_body_cer_zh_max':0.02,'weighted_body_cer_en_max':0.03,
           'exact_key_presence_min':0.98,'max_missing_excerpt_count':0,
           'missing_excerpt_definition':'best-span edit distance / reference length >= 0.5'},
         'pages':data}
target=root/'reference-frozen.json'
if target.exists():raise SystemExit('Reference already frozen; do not overwrite')
target.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
digest=hashlib.sha256(target.read_bytes()).hexdigest()
(root/'outputs/reference-sha256.txt').write_text(digest,encoding='ascii')
print('Frozen reference',digest,'body pages',sum(bool(r['excerpts']) for r in data.values()))
