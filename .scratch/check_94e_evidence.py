"""Read-only cross-run replay: test the new answer's document-absence claim."""
import json
from pathlib import Path

base = Path('/home/administrator/.local/share/frontier-agent/web/runs')
root = base/'94e38ed61ce54831a273aaabf20f6a0d'
summary = json.loads((root/'summary.json').read_text())
rows = [json.loads(s) for s in (root/'run/agent/trajectories/subagents/corpus_lookup_research.t01.jsonl').read_text().splitlines()]
inventory = next(json.loads(r['result']) for r in rows if r['t']=='result' and r.get('name')=='corpus_inventory')
heading = next(json.loads(r['result']) for r in rows if r['t']=='result' and r.get('name')=='corpus_fetch')
old = base/'7d0cecf846254f4895d318299136a688/run/agent/trajectories/subagents/today_doc_verifier.t03.jsonl'
old_items = []
for row in map(json.loads, old.read_text().splitlines()):
    if row['t']=='result' and row.get('name')=='corpus_fetch':
        data=json.loads(row['result'])
        for item in data.get('items', [data]):
            if item.get('kind')=='body' and (item.get('build_id') or data.get('build_id')) == heading['build_id']:
                old_items.append(item)
findings = {
    'inventory_unknown_members': inventory['unknown_members'],
    'inventory_requested_scope_count': inventory['total_chunks'],
    'same_build_historical_body_count': len(old_items),
    'same_build_historical_bodies': [{'locator':i['locator'],'chars':len(i['text']),'kind':i['kind']} for i in old_items],
    'source_soft_hyphens': heading['text'].count('\u00ad'),
    'answer_soft_hyphens': summary['final_answer'].count('\u00ad'),
    'answer_claims_verbatim': '逐字' in summary['final_answer'],
    'answer_claims_no_body': '正文 chunk 数为 0' in summary['final_answer'],
    'verification': summary['report_contract']['verification'],
}
Path('.scratch/audit_94e_evidence.json').write_text(json.dumps(findings,ensure_ascii=False,indent=2))
print(json.dumps(findings,ensure_ascii=False,indent=2))
assert not (findings['answer_claims_no_body'] and old_items), 'Same immutable build already has captured body: whole-document absence claim is contradicted'
