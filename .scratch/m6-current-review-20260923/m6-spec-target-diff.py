import json
from pathlib import Path
root=Path('/home/administrator/FrontierAgent')
records={q['query_id']:q for q in [json.loads(x) for x in (root/'.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl').read_text().splitlines()]}
norm=lambda x: ''.join(x.split())
for r in json.loads((Path(__file__).resolve().parent / 'm6-spec-fetch-probe-results.json').read_text()):
 for t in records[r['query_id']]['evidence_targets']:
  sid=t['source_id'].rsplit('_',1)[-1]
  matches=[d for d in r['diffs'] if d['source'].startswith(sid) and norm(t['quote']) in norm(d['band_text']) and norm(t['quote']) not in norm(d['fetch_text'])]
  if matches:
   d=matches[0]
   print(json.dumps({'qid':r['query_id'],'target':t['target_id'],'quote':t['quote'],'handle':'cv2:'+d['build'],'locator':'chunk:'+d['chunk'],'band_chars':d['band_chars'],'fetch_chars':d['fetch_chars']},ensure_ascii=False))
