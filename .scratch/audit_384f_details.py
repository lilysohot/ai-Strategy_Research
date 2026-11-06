import json, re, difflib
from pathlib import Path
root=Path('/home/administrator/.local/share/frontier-agent/web/runs/384fd87e9b974c678eacb28e083c9807')
base=root/'run/agent/trajectories'
start=json.loads((base/'main_agent.jsonl').read_text().splitlines()[0])['ts']
subjects=[]
for p in sorted(base.rglob('*.jsonl')):
 print('\nAGENT',p.name)
 for r in map(json.loads,p.read_text().splitlines()):
  tm=round(r.get('ts',start)-start,2)
  if r['t']=='llm':
   for c in r.get('tool_calls',[]):
    name=c['name']; a=c.get('args',{})
    if name=='corpus_submit_manifest': print('MANIFEST_ARGS',tm,json.dumps(a,ensure_ascii=False))
    if name=='submit_report' and 'verifier' in p.name: print('VERDICT',tm,json.dumps(a,ensure_ascii=False))
    if name=='assign_task':
     for t in a.get('tasks',[]):
      for ch in t.get('verification_checks',[]):
       print('BOUND',tm,json.dumps(ch,ensure_ascii=False))
       if ch.get('check_id')=='impact_attribution':subjects.append(ch.get('subject',{}).get('text',''))
    if name=='deliver_answer':
     for m in re.finditer('资料库没有|整个资料库只有',a.get('content','')):
      txt=a['content']; print('GUARD_CONTEXT',tm,txt[max(0,m.start()-150):m.end()+150])
  elif r['t']=='result' and r.get('name')=='corpus_submit_manifest': print('MANIFEST_RESULT',tm,r['result'])
  elif r['t']=='result' and r.get('name')=='assign_task':print('ASSIGN_RESULT',tm,r['result'])
if len(subjects)>=2:print('\nSUBJECT_DIFF\n','\n'.join(difflib.unified_diff(subjects[0].splitlines(),subjects[1].splitlines())))
