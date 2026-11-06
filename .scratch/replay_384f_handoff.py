"""Offline replay of recorded source results; no model or corpus service calls."""
import json, unicodedata
from pathlib import Path
from plugins.tools._corpus_handoff import observed_corpus_evidence, evidence_identity, render_corpus_handoff

root=Path('/home/administrator/.local/share/frontier-agent/web/runs/384fd87e9b974c678eacb28e083c9807/run/agent/trajectories')
sources={}
reports=[]
for name in ['corpus_model_research','corpus_impact_research']:
 p=next(root.rglob(name+'.t01.jsonl')); records={}
 for r in map(json.loads,p.read_text().splitlines()):
  if r['t']=='result' and r.get('name') in ['corpus_search','corpus_fetch']:
   for item in observed_corpus_evidence(r['name'],json.loads(r['result'])):
    records[evidence_identity(item)]=item
  if r['t']=='llm':
   for call in r.get('tool_calls',[]):
    if call['name']=='submit_report':reports.append(call['args']['content'])
 sources[name]=list(records.values())
for r in map(json.loads,(root/'main_agent.jsonl').read_text().splitlines()):
 if r['t']!='llm':continue
 for call in r.get('tool_calls',[]):
  if call['name']!='assign_task':continue
  for task in call['args'].get('tasks',[]):
   for check in task.get('verification_checks',[]):
    if check['check_id']!='impact_attribution':continue
    subject=check['subject']['text']
    rendered=render_corpus_handoff(sources,reference_text='\n'.join([subject,*reports]),focus_text=subject)
    text=unicodedata.normalize('NFKC',rendered)
    checks={'H100': '2.90' in text, 'capex': 'CAPEX 将接近8000' in text,
            'distillation': '10 到 50 倍' in text}
    print(json.dumps({'revision':bool(check.get('replaces_job_id')),'chars':len(rendered),'evidence':checks},ensure_ascii=False))
    assert all(checks.values()),checks
