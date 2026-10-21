import contextlib
import io
with contextlib.redirect_stdout(io.StringIO()):
    import metrics as m
from common import *
rows=m.records
for mode in ('lexical','hybrid'):
    for case in m.cases:
        pair={r['tag']:r for r in rows if r['case']==case['id'] and r['mode']==mode}
        fields=['first_complete','anchor_complete','context_complete']
        if any(pair['old'][f]!=pair['new'][f] for f in fields):
            print(json.dumps({'case':case['id'],'mode':mode,**{tag:{f:pair[tag][f] for f in fields} for tag in ('old','new')}}))
noise={}
for tag in ('old','new'):
    for case in m.cases:
        data=read(f'retrieval/{case["id"]}-{tag}-hybrid.json')
        for h in data['trace']['selected']:
            cid=h['chunk_id']
            ev=m.authorities[tag][cid]
            if m.noise_fraction(ev)>=0.8:
                noise.setdefault((tag,cid),{'tag':tag,'chunk':cid,'text':ev['text'],'cases':[]})['cases'].append(case['id'])
save('template-anchors.json',list(noise.values()))
print('UNIQUE TEMPLATE ANCHORS',len(noise))
for x in noise.values():
    print(x['tag'],x['chunk'],x['cases'],x['text'][:500])
for cid in ('p01','p13','p16','n01'):
    for tag in ('old','new'):
        data=read(f'retrieval/{cid}-{tag}-hybrid.json')
        print(cid,tag,[(h['source_id'][:8],h['chunk_id']) for h in data['trace']['selected']])
