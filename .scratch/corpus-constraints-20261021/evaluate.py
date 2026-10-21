"""Score frozen rankings against unchanged evidence; not used by ranking code."""
import json,hashlib,sys
from pathlib import Path
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[2]; HERE=Path(__file__).resolve().parent
PRIOR=ROOT/'.scratch/corpus-clean7-rebuild-20261021'
sys.path.insert(0,str(ROOT))
from signals import Signals

def read(p): return json.loads(p.read_text())
def save(name,obj): (HERE/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2))
def norm(s): return ''.join(s.split())
rank=read(HERE/'rankings.json'); authority=read(PRIOR/'new-authority.json')
definitions=read(PRIOR/'metric-definition.json')
manifest=read(ROOT/'.scratch/corpus-vector-acceptance-20261020/manifest.json')
cases={c['id']:c for c in manifest['cases']}
labels=read(ROOT/'.scratch/corpus-relevance-audit-20261021/labels.json')['cases']
corpus=read(PRIOR/'new-corpus.json')
signals=Signals(corpus,authority,read(HERE/'prepared.json')['metadata'])
updated={r['source_id'] for r in read(PRIOR/'build-results.json') if r['status']=='published'}
noise={(r['source_id'],r['raw_hash']) for r in read(ROOT/'.scratch/corpus-clean-review-20261021/review-labels.json')['units']}
noise.update((r['source_id'],r['raw_hash']) for r in read(ROOT/'.scratch/corpus-clean-boundary-20261021/changes.json'))
for s in read(PRIOR/'old-corpus.json'):
 noise.update((s['source_id'],u['content_hash']) for u in s['units'] if u['status']!='kept')
def noisy(cid):
 ev=authority[cid]; units={u['unit_id']:u for u in ev['units']}; num=den=0
 for uid,a,b in ev['spans']:
  n=len(norm(ev['text'][a:b]));den+=n
  if (ev['source_id'],hashlib.sha256(units[uid]['raw_text'].encode()).hexdigest()) in noise:num+=n
 return den>0 and num/den>=.8
def text_scope(ids):
 groups=defaultdict(list)
 for cid in set(ids):groups[authority[cid]['source_id']].append(norm(authority[cid]['text']))
 return {s:'\n'.join(v) for s,v in groups.items()}
def complete(cid,ids,body=False):
 text=text_scope(ids).get(cases[cid].get('source_id'),'')
 parts=definitions['body_gold_parts' if body else 'gold_parts'][cid]
 return [g for g,fragments in parts.items() if all(f in text for f in fragments)]
def context(hits):return {cid for h in hits for cid in (h['context_chunk_ids'] or [h['chunk_id']])}
def detail(cid,ids):
 if cid not in ('p01','p13','p16'):return None
 matches=[]
 for chunk in ids:
  ev=authority[chunk];text=signals.body[chunk]
  for old,g in labels[cid]['labels'].items():
   if g['grade'] in ('full','partial') and ev['source_id']==g['source_id'] and all(''.join(m.casefold().split()) in text for m in g['support_markers']):
    matches.append({'chunk':chunk,'old_label':old,'grade':g['grade'],'facets':g['facets']})
 return {'full_support_marker_match':any(m['grade']=='full' for m in matches),'facets':sorted({f for m in matches for f in m['facets']}),'matches':matches}
rows=[]; losses=[]
for cid,r in rank['cases'].items():
 base=context(r['methods']['baseline']['selected'])
 for method,data in r['methods'].items():
  hits=data['selected'];ids=[h['chunk_id'] for h in hits];ctx=context(hits)
  good=complete(cid,ctx)
  row={'case':cid,'method':method,'kind':cases[cid]['kind'],'rows':len(hits),'contexts':len(ctx),
   'all_baseline_context_preserved':base<=ctx,'context_added':len(ctx-base),'context_lost':len(base-ctx),
   'gold_context':good,'body_first':complete(cid,ids[:1],True),'gold_first':complete(cid,ids[:1]),
   'lost_gold':sorted(set(complete(cid,base))-set(good)),'template_anchors':sum(noisy(c) for c in ids),
   'first':ids[0] if ids else None,'detail_first':detail(cid,ids[:1]),'detail_context':detail(cid,ctx),
   'target_source_first':bool(hits and hits[0]['source_id']==cases[cid].get('source_id'))}
  rows.append(row)
  if method=='baseline':
   for gid,fragments in definitions['gold_parts'][cid].items():
    if gid in good:continue
    matching=[f for f in data['fates'] if f['source_id']==cases[cid].get('source_id') and all(p in norm(authority[f['chunk_id']]['text']) for p in fragments)]
    losses.append({'case':cid,'old_gold':gid,'candidate_matches':matching})
summary={}
for method in next(iter(rank['cases'].values()))['methods']:
 rs=[r for r in rows if r['method']==method];ps=[r for r in rs if r['kind']=='positive']
 summary[method]={'body_first_cases':sum(bool(r['body_first']) for r in ps),'full_block_first_cases':sum(bool(r['gold_first']) for r in ps),
  'gold_context_blocks':sum(len(r['gold_context']) for r in ps),'new_source_gold_context_blocks':sum(len(r['gold_context']) for r in ps if cases[r['case']].get('source_id') in updated),
  'baseline_scope_preserved_cases':sum(r['all_baseline_context_preserved'] for r in rs),'contexts_all32':sum(r['contexts'] for r in rs),
  'template_anchors':sum(r['template_anchors'] for r in rs),'rows_all32':sum(r['rows'] for r in rs),
  'lost_gold':{r['case']:r['lost_gold'] for r in rs if r['lost_gold']},
  'detailed_top1':{r['case']:{'full':r['detail_first']['full_support_marker_match'],'facets':r['detail_first']['facets']} for r in rs if r['detail_first'] is not None}}
save('metrics.json',rows);save('summary.json',summary);save('omissions.json',losses)
save('evaluation-definition.json',{'rankings_sha256':hashlib.sha256((HERE/'rankings.json').read_bytes()).hexdigest(),
 'gold_definition_sha256':hashlib.sha256((PRIOR/'metric-definition.json').read_bytes()).hexdigest(),
 'scope':'Same 24 positive / 8 stress development questions. Exact old evidence fragments, same source. Detailed checks use old support markers in role-cleaned body; require manual review before semantic claims. No unjudged precision or global recall claims.'})
print(json.dumps(summary,ensure_ascii=False,indent=2))
print('OMISSIONS',json.dumps(losses,ensure_ascii=False))
lines=['# 正文排序实验：原文对照','', '基线与变体均来自同一已发布快照和冻结候选。以下是原文，不是生成答案。','']
changed=[cid for cid in cases if any(m['selected'][0]['chunk_id']!=rank['cases'][cid]['methods']['baseline']['selected'][0]['chunk_id'] for m in rank['cases'][cid]['methods'].values() if m['selected'])]
for cid in dict.fromkeys(['p01','p13','p16','p20','n01',*changed]):
 r=rank['cases'][cid];lines += [f"## {cid} {r['question']}",'',f"自动提取：{r['intent']}；候选中无实体支持：{r['entity_no_candidate_support']}",'']
 seen={}
 for method,m in r['methods'].items():
  if m['selected']:
   cid2=m['selected'][0]['chunk_id'];seen.setdefault(cid2,[]).append(method)
 for chunk,methods in seen.items():
  lines += [f"### {', '.join(methods)}：{chunk}",'',f"信号：{r['features'][chunk]}",'','```text',authority[chunk]['text'],'```','']
(HERE/'evidence-report.md').write_text('\n'.join(lines))
