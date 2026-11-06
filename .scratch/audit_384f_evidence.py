import json,re,unicodedata
from pathlib import Path
root=Path('/home/administrator/.local/share/frontier-agent/web/runs/384fd87e9b974c678eacb28e083c9807')
base=root/'run/agent/trajectories'
for p in sorted(base.rglob('*.json')):
 d=json.loads(p.read_text());print('AGENT',p.name,d.get('task_id'),d.get('role_id'))
 for i,m in enumerate(d.get('messages',[])):
  txt=m.get('content')or''
  if not isinstance(txt,str):continue
  norm=unicodedata.normalize('NFKC',txt)
  if m.get('role')=='user' and i>2:continue
  for term in ['2.90','8000','10 到 50','10到50','10 至 50','10~50','body%3A0008','3b24138d','a6eb9fdd']:
   for hit in list(re.finditer(re.escape(term),norm))[:2]: print('HIT',i,m.get('role'),term,norm[max(0,hit.start()-100):hit.end()+140].replace('\n',' '))
v=json.loads((root/'run/corpus/manifest_verification.json').read_text())
print('FINAL_MANIFEST', {k:v.get(k) for k in ['status','counts','publish_status','report_bound']})
for c in v.get('conclusions',[]):print('FINAL_CONCLUSION',c['id'],c['status'],c.get('problems'))
for p in sorted(base.rglob('evidence_verifier.t0[23].json')):
 d=json.loads(p.read_text());txt=next(m['content'] for m in d['messages'] if m['role']=='user')
 hand=unicodedata.normalize('NFKC',txt.split('# Tool-delivered corpus evidence',1)[-1])
 print('HANDOFF_ONLY',p.name,len(hand))
 for term in ['2.90','8000','10 到 50','3b24138d','a6eb9fdd','body%3A0005','Omitted excerpt bodies']:
  hits=list(re.finditer(re.escape(term),hand));print('HANDOFF_TERM',term,'count',len(hits))
  for h in hits[:3]: print(hand[max(0,h.start()-100):h.end()+140].replace('\n',' '))
