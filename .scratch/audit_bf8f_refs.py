import json
import os
import re
import sys
from pathlib import Path

ROOT=Path('/home/administrator/FrontierAgent')
sys.path.insert(0,str(ROOT))
from plugins.corpus.search_refs import canonical_locator

run=Path('/home/administrator/.local/share/frontier-agent/web/runs/bf8f51c91e594a49b9e77a64c5915afe')
refs=run/'run/corpus/search-refs'
os.environ['CORPUS_SEARCH_REF_ROOT']=str(refs)
os.environ['CORPUS_TARGET_DB']=json.loads(next(refs.glob('*.json')).read_text())['target']
base=run/'run/agent/trajectories'
seen=set()
for p in base.rglob('*.jsonl'):
    rows=[json.loads(x) for x in p.read_text().splitlines()]
    if 'verifier' in p.stem:
        snap=json.loads(p.with_suffix('.json').read_text())
        for i,m in enumerate(snap['messages']):
            c=m.get('content') or ''
            if not isinstance(c,str) or '# Tool-delivered corpus evidence' not in c:continue
            packet=c.split('# Tool-delivered corpus evidence',1)[1]
            parsed=[]
            for line in packet.splitlines():
                if line.startswith('{'):
                    try:parsed.append(json.loads(line))
                    except ValueError:pass
                elif line.startswith('Additional exact references'):
                    parsed.extend(json.loads(line.split(': ',1)[1]))
            ok=bad=0
            for rec in parsed:
                try:canonical_locator(rec['doc_id'],rec['locator']);ok+=1
                except (ValueError,KeyError):bad+=1
            print('PACKET_REFS',p.stem,i,'ok',ok,'bad',bad,'chars',len(packet))
        for row in rows:
            if row['t']=='llm':
                for call in row.get('tool_calls',[]):
                    a=call.get('args',{})
                    if call['name']=='corpus_fetch':
                        for ref in a.get('locators',[a.get('locator')]):
                            if not ref or not ref.startswith('eref:'):continue
                            try:canonical_locator(a['doc_id'],ref);out='ok'
                            except ValueError as e:out=str(e)
                            print('FETCH_REF',ref,out)
                    elif call['name']=='submit_report':
                        print('SUBMIT_KEYS',p.stem,[v.get('evidence_keys') for v in a.get('verification_results',[])])
        print('FIRST_LLM',p.stem,next(r['usage']['prompt_tokens'] for r in rows if r['t']=='llm'))
    for r in rows:
        if r['t']!='result' or r.get('name') not in {'corpus_search','corpus_fetch'}:continue
        try:d=json.loads(r['result'])
        except (ValueError,TypeError):continue
        texts=[(h.get('doc_id'),e.get('text','')) for h in d.get('hits',[]) for e in h.get('excerpts',[])]
        texts += [(it.get('doc_id',d.get('doc_id')),it.get('text','')) for it in d.get('items',[d])]
        for doc,t in texts:
            if ('保留时长' in t or '20–25' in t or '20-25' in t) and t not in seen:
                seen.add(t)
                print('STORAGE_SOURCE',doc,t[:2200])
summary=json.loads((run/'summary.json').read_text())
answer=summary['final_answer']
for c in summary['report_contract']['verification_checks']:
    print('EXACT_CHECKED_PASSAGE',c['check_id'],c['subject']['text'] in answer,
          'STORAGE_IN_CHECK', '20–25' in c['subject']['text'])
print('FINAL_CHARS',len(answer))
print('EVIDENCE_BOUNDARY',json.dumps(summary.get('evidence_boundary'),ensure_ascii=False)[:1800])
for rid in ['8eda75f47314494ea7a03c020dd219bb',run.name]:
    allrows=[json.loads(x) for p in (run.parent/rid/'run/agent/trajectories').rglob('*.jsonl') for x in p.read_text().splitlines()]
    mainrows=[json.loads(x) for x in (run.parent/rid/'run/agent/trajectories/main_agent.jsonl').read_text().splitlines()]
    print('COUNTS',rid,'tools',sum(r['t']=='result' for r in allrows),'main_max_input',max(r['usage']['prompt_tokens'] for r in mainrows if r['t']=='llm'))
