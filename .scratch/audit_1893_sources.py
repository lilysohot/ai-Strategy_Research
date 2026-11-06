import json
from pathlib import Path
base=Path('/home/administrator/.local/share/frontier-agent/web/runs/18937dbdabb1401296a685aeaa747c0b/run/agent/trajectories/subagents')
for p in base.glob('*research.t01.jsonl'):
 for line in p.read_text().splitlines():
  r=json.loads(line)
  if r['t']=='result' and r.get('name')=='web_fetch':
   txt=str(r.get('result',''))
   try:
    obj=json.loads(txt)
    parts=[(v.get('source'),v.get('content','')) for v in obj.get('items',[])]
   except (ValueError,AttributeError): parts=[('',txt)]
   for source,body in parts:
    if any(x in body for x in ['11.82','调研预测','6.5亿','6.5 亿']):
     print('SOURCE',source)
     for token in ['11.82','调研预测','6.5亿','6.5 亿']:
      at=body.find(token)
      if at>=0: print('MATCH',token,body[max(0,at-130):at+240].replace('\n',' '))
