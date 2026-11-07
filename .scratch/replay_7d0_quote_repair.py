import json
from pathlib import Path
from plugins.tools._quote_verification import QuoteCheck, compare_quotes, validate_quotes

root=Path('/home/administrator/.local/share/frontier-agent/web/runs/7d0cecf846254f4895d318299136a688/run/agent')
job=json.loads(next((root/'team-results').rglob('*.job.5.json')).read_text())
subject=job['assignment_metadata']['verification_checks'][0]['subject']['text']
rows=[json.loads(l) for l in (root/'trajectories/subagents/today_doc_verifier.t03.jsonl').read_text().splitlines()]
payload=json.loads(next(r['result'] for r in rows if r['t']=='result' and r.get('name')=='corpus_fetch'))
sources={'original':[{'locator':i['locator'],'text':i['text']} for i in payload['items']]}
results=[]
for item in payload['items']:
    label='标题块原文' if item['kind']=='heading' else '正文首段'
    after=subject.split(label,1)[1].split('\n',1)[1]
    quote=after.split('\n正文首段',1)[0] if item['kind']=='heading' else after
    for mode in ('exact','nbsp_space'):
        comparisons=compare_quotes([QuoteCheck(source_key='original',locator=item['locator'],quote=quote,mode=mode)],subject,sources)
        try:
            validate_quotes({'quote_comparisons':comparisons})
            accepted=True
        except ValueError:
            accepted=False
        assert accepted == (mode=='nbsp_space')
        assert not comparisons[0]['raw_match']
        results.append({'kind':item['kind'],'mode':mode,'accepted':accepted,'raw_match':False,'normalized_match':comparisons[0]['normalized_match']})
out=Path(__file__).parent/'team-7d0-quote-replay.json'
out.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(results,ensure_ascii=False))
