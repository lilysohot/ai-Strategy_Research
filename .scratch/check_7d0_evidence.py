"""Deterministically audit captured subject against captured authoritative text."""
import hashlib
import json
from pathlib import Path

root=Path('/home/administrator/.local/share/frontier-agent/web/runs/7d0cecf846254f4895d318299136a688')
tr=root/'run/agent/trajectories'
main=json.loads((tr/'main_agent.json').read_text())
for m in main['messages']:
    if m.get('role')=='user' and m.get('content')=='从资料库中，检索出随意一份今天的研报':
        print('USER',m['content'])
job=json.loads(next((root/'run/agent/team-results').rglob('*.job.5.json')).read_text())
subject=job['assignment_metadata']['verification_checks'][0]['subject']['text']
rows=[json.loads(x) for x in (tr/'subagents/today_doc_verifier.t03.jsonl').read_text().splitlines()]
fetched=next(r for r in rows if r['t']=='result' and r.get('name')=='corpus_fetch')
payload=fetched['result']
if isinstance(payload,str): payload=json.loads(payload)
findings=[]
for item in payload['items']:
    original=item['text']
    label='标题块原文' if item['kind']=='heading' else '正文首段'
    after=subject.split(label,1)[1].split('\n',1)[1]
    quote=after.split('\n正文首段',1)[0] if item['kind']=='heading' else after
    record={
        'kind':item['kind'], 'raw_chars':len(original),'quote_chars':len(quote),
        'raw_sha_matches_declared':hashlib.sha256(original.encode()).hexdigest()==item['text_sha256'],
        'raw_equals_subject_quote':original==quote,
        'nbsp_normalized_equals':original.replace('\u00a0',' ')==quote.replace('\u00a0',' '),
        'diffs':[{'position':i,'raw':f'U+{ord(a):04X}','quote':f'U+{ord(b):04X}'} for i,(a,b) in enumerate(zip(original,quote)) if a!=b],
    }
    findings.append(record)
print('SOURCE_VS_SUBJECT',json.dumps(findings,ensure_ascii=False,indent=2))
for r in rows:
    if r['t']=='result' and r.get('name')=='bash': print('SCRIPT_RESULT',str(r['result'])[:4500])
(Path(__file__).parent/'audit_7d0_characters.json').write_text(json.dumps(findings,ensure_ascii=False,indent=2)+'\n')
assert all(f['raw_sha_matches_declared'] for f in findings), 'Tool bytes do not match declared hash'
assert all(f['raw_equals_subject_quote'] for f in findings), 'Claimed verbatim subject differs from captured authoritative source'
