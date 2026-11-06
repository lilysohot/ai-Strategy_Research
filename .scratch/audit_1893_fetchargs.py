import json
from pathlib import Path
base=Path('/home/administrator/.local/share/frontier-agent/web/runs/18937dbdabb1401296a685aeaa747c0b/run/agent/trajectories')
for p in base.rglob('*.jsonl'):
 for line in p.read_text().splitlines():
  r=json.loads(line)
  if r['t']=='llm':
   for c in r.get('tool_calls',[]):
    if c['name']=='web_fetch': print(p.stem,json.dumps(c['args'],ensure_ascii=False)[:750])
