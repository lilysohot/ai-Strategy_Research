"""Version-independent exact-text evidence coverage; no answer generation."""
import hashlib
import statistics
from collections import defaultdict,Counter
from common import *

def norm(s):
    return ''.join(s.split())

cases=json.loads((ROOT/'.scratch/corpus-vector-acceptance-20261020/manifest.json').read_text())['cases']
authorities={tag:read(f'{tag}-authority.json') for tag in ('old','new')}
corpora={tag:{s['source_id']:s for s in read(f'{tag}-corpus.json')} for tag in ('old','new')}
noise=set()
review=json.loads((ROOT/'.scratch/corpus-clean-review-20261021/review-labels.json').read_text())
for row in review['units']:
    noise.add((row['source_id'],row['raw_hash']))
for row in json.loads((ROOT/'.scratch/corpus-clean-boundary-20261021/changes.json').read_text()):
    noise.add((row['source_id'],row['raw_hash']))
for sid,s in corpora['old'].items():
    for u in s['units']:
        if u['status']!='kept':
            noise.add((sid,u['content_hash']))

def parts(ev,drop_noise=False,body_only=False):
    units={u['unit_id']:u for u in ev['units']}
    result=[]
    for uid,start,end in ev['spans']:
        raw=units[uid]['raw_text']
        if body_only:
            source=corpora['old'][ev['source_id']]
            unit=next(u for u in source['units'] if u['unit_id']==uid)
            chunk=next(c for c in source['chunks'] if c['chunk_id']==ev['chunk_id'])
            if unit['kind'] in ('heading','title') or uid in chunk['context_refs']:
                continue
        if drop_noise and (ev['source_id'],hashlib.sha256(raw.encode()).hexdigest()) in noise:
            continue
        fragment=norm(ev['text'][start:end])
        if len(fragment)>=3:
            result.append(fragment)
    return result

gold={c['id']:{chunk:parts(authorities['old'][chunk],True) for chunk in c.get('gold_chunks',[])} for c in cases}
body_gold={c['id']:{chunk:parts(authorities['old'][chunk],True,True) for chunk in c.get('gold_chunks',[])} for c in cases}
assert all(fragments for blocks in body_gold.values() for fragments in blocks.values())
assert all(parts for blocks in gold.values() for parts in blocks.values())
save('metric-definition.json',{'scope':'exact full text fragments of original gold evidence, excluding previously reviewed templates; unchanged 32 questions; not universal semantic recall or precision',
 'gold_parts':gold,'body_gold_parts':body_gold,
 'body_metric_provenance':'Supplemental diagnostic added after p24 heading-reference change was observed; original full-block metric is retained. Excludes old heading/title units and context_refs, without changing questions or body evidence.',
 'notes':'Source identity required. Whole gold block requires all retained fragments. Candidate, anchor and expanded scopes measured separately. Unlabelled chunks are not automatically irrelevant.'})

def scopes(tag,chunks):
    out=defaultdict(list)
    for cid in dict.fromkeys(chunks):
        ev=authorities[tag][cid]
        out[ev['source_id']].append(norm(ev['text']))
    return {sid:'\n'.join(texts) for sid,texts in out.items()}

def complete(case,tag,chunks,body_only=False):
    text=scopes(tag,chunks).get(case.get('source_id'),'')
    expected=body_gold if body_only else gold
    return [cid for cid,fragments in expected[case['id']].items() if all(f in text for f in fragments)]

def noise_fraction(ev):
    den=num=0
    units={u['unit_id']:u for u in ev['units']}
    for uid,start,end in ev['spans']:
        size=len(norm(ev['text'][start:end]))
        den+=size
        if (ev['source_id'],hashlib.sha256(units[uid]['raw_text'].encode()).hexdigest()) in noise:
            num+=size
    return num/den if den else 0

records=[]
reports=[]
for case in cases:
    for tag in ('old','new'):
        for mode in ('lexical','hybrid'):
            data=read(f'retrieval/{case["id"]}-{tag}-{mode}.json')
            trace=data['trace']
            selected=trace['selected']
            anchor=[h['chunk_id'] for h in selected]
            contexts=[cid for h in selected for cid in (h['context_chunk_ids'] or [h['chunk_id']])]
            row={'case':case['id'],'kind':case['kind'],'tag':tag,'mode':mode,'status':trace['status'],
                'rows':len(selected),'elapsed_ms':data['elapsed_ms'],'gold_blocks':len(gold[case['id']]),
                'first_complete':complete(case,tag,anchor[:1]),
                'anchor_complete':complete(case,tag,anchor),
                'context_complete':complete(case,tag,contexts),
                'candidate_complete':complete(case,tag,[h['chunk_id'] for h in trace['fused']]),
                'body_first_complete':complete(case,tag,anchor[:1],True),
                'body_anchor_complete':complete(case,tag,anchor,True),
                'body_context_complete':complete(case,tag,contexts,True),
                'reviewed_template_anchors':sum(noise_fraction(authorities[tag][cid])>=0.8 for cid in anchor),
                'reviewed_template_contexts':sum(noise_fraction(authorities[tag][cid])>=0.8 for cid in set(contexts)),
                'unique_contexts':len(set(contexts))}
            if case.get('source_id'):
                row['gold_term_in_context']=norm(case['gold_term']) in scopes(tag,contexts).get(case['source_id'],'')
            records.append(row)
            if case['id'] in ('p01','p13','p16','n01') and mode=='hybrid':
                reports += [f"## {case['id']} {tag}: {case['question']}",'']
                for rank,h in enumerate(selected,1):
                    ev=authorities[tag][h['chunk_id']]
                    reports += [f"### {rank}. {h['chunk_id']} ({ev['source_id'][:8]})",ev['text'],'']

summary={}
for mode in ('lexical','hybrid'):
    for tag in ('old','new'):
        rows=[r for r in records if r['tag']==tag and r['mode']==mode]
        pos=[r for r in rows if r['kind']=='positive']
        summary[f'{tag}-{mode}']={'queries':len(rows),'statuses':dict(Counter(r['status'] for r in rows)),
            'positive_questions':len(pos),'gold_blocks':sum(r['gold_blocks'] for r in pos),
            'first_complete_cases':sum(bool(r['first_complete']) for r in pos),
            'anchor_complete_cases':sum(bool(r['anchor_complete']) for r in pos),
            'context_complete_cases':sum(bool(r['context_complete']) for r in pos),
            'context_complete_blocks':sum(len(r['context_complete']) for r in pos),
            'body_first_complete_cases':sum(bool(r['body_first_complete']) for r in pos),
            'body_anchor_complete_cases':sum(bool(r['body_anchor_complete']) for r in pos),
            'body_context_complete_blocks':sum(len(r['body_context_complete']) for r in pos),
            'candidate_complete_blocks':sum(len(r['candidate_complete']) for r in pos),
            'gold_term_context_cases':sum(r['gold_term_in_context'] for r in pos),
            'reviewed_template_anchors':sum(r['reviewed_template_anchors'] for r in rows),
            'total_anchors':sum(r['rows'] for r in rows),
            'reviewed_template_contexts':sum(r['reviewed_template_contexts'] for r in rows)}
save('metrics.json',records)
save('metrics-summary.json',summary)
(HERE/'focused-evidence.md').write_text('\n'.join(reports))
print(json.dumps(summary,ensure_ascii=False,indent=2))
