import json
from pathlib import Path
from types import SimpleNamespace
from plugins.tools._web_handoff import web_records
from plugins.tools.web_fetch import _normalise_inputs
p=Path('/home/administrator/.local/share/frontier-agent/web/runs/18937dbdabb1401296a685aeaa747c0b/run/agent/trajectories/subagents/ai_video_capability_research.t01.jsonl')
rows=[json.loads(s) for s in p.read_text().splitlines()]
call=next(c for r in rows if r['t']=='llm' for c in r.get('tool_calls',[]) if c['name']=='web_fetch')
r=next(r for r in rows if r['t']=='result' and r.get('name')=='web_fetch')
args=call['args']; result=SimpleNamespace(args=args,result=r['result'],is_error=False)
records=web_records(result,None)
urls,_=_normalise_inputs(args['url'],args['info_to_extract'])
print(json.dumps({'fetch_normalized_urls':len(urls),'handoff_records':len(records),'handoff_source':records[0]['source'],'single_record_contains_two_pages':all(u in records[0]['content'] for u in urls)},ensure_ascii=False))
assert len(urls)==2 and len(records)==1
assert records[0]['source']==args['url']
print('Confirmed: runtime normalizes JSON URL list but handoff records it as a single source.')
