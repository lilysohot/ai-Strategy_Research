import difflib
from common import *
old={s['source_id']:s for s in read('old-corpus.json')}
new={s['source_id']:s for s in read('new-corpus.json')}
sid=next(s for s in old if s.startswith('f8fa2208'))
a,b=old[sid],new[sid]
print('REVISIONS',json.dumps({tag:{k:s['build'][k] for k in ('parse_rev','clean_rev','chunk_rev','index_rev')} for tag,s in [('old',a),('new',b)]}))
for oc,nc in zip(a['chunks'],b['chunks']):
    diffs={k:[oc[k],nc[k]] for k in ('search_text','title_text','section_path','unit_refs') if oc[k]!=nc[k]}
    if diffs:
        print('CHUNK CHANGE',oc['chunk_id'],json.dumps(diffs,ensure_ascii=False))
for tag in ('old','new'):
    trace=read(f'retrieval/p24-{tag}-hybrid.json')['trace']
    print(tag,[(channel,[(i+1,h['chunk_id'],h['score']) for i,h in enumerate(trace[channel]) if h['source_id']==sid]) for channel in ('lexical','dense','fused','selected')])
    auth=read(f'{tag}-authority.json')
    print('FIRST',tag,auth[trace['selected'][0]['chunk_id']]['text'])
