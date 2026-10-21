"""Persist agent adjudication made after reading all 21 context packets."""
import contextlib
import io
from collections import Counter, defaultdict

with contextlib.redirect_stdout(io.StringIO()):
    import prepare as p

from plugins.corpus.preparation.clean import _STOCK_CODE

# Explicitly reviewed ranges; no keyword classifier is used as review ground truth.
ranges = {
 '00f08e66': [(1,1,'reminder'),(144,147,'rating_definition'),(153,177,'legal'),(178,195,'contact')],
 '11ea15ac': [(175,197,'rating_definition')],
 '174b6462': [(1282,1302,'rating_definition')],
 '1e021a8c': [(38,39,'legal'),(40,42,'rating_definition')],
 '1e141ab0': [(1,1,'reminder'),(150,174,'legal'),(175,194,'contact')],
 '3f634514': [(1,1,'reminder'),(266,267,'rating_definition'),(272,295,'legal'),(296,313,'contact')],
 '5525b384': [(44,50,'rating_definition'),(51,51,'layout')],
 '793b3967': [(1,1,'reminder'),(456,464,'legal')],
 '8158cbb9': [(207,209,'legal')],
 '987d9f69': [(1,1,'reminder'),(193,194,'rating_definition'),(200,224,'legal'),(225,242,'contact')],
 'd441478b': [(576,598,'rating_definition'),(599,607,'contact')],
 'dddc7cd0': [(1,1,'reminder')],
 'f8e31696': [(213,214,'legal'),(215,225,'rating_definition')],
}
rationales = {
 'reminder':'整单元只有阅读声明提醒，无正文事实。',
 'rating_definition':'评级定义及适用基准/期限，不是对某只股票或本行业的实际评级。',
 'legal':'末页法律、版权、分析师独立性或出具机构资质说明，无本报告研究对象的分析正文。',
 'contact':'出具机构研究所城市、电话、地址或推广入口，不是公司经营地点/经营数据。',
 'layout':'完整内部传播提示。',
}
annotations=[]
for packet in p.packets:
    for u in packet['units']:
        if not u['removed']:
            continue
        matches=[category for start,end,category in ranges[packet['source_id'][:8]] if start<=u['ordinal']<=end]
        assert len(matches)==1
        category=matches[0]
        annotations.append({'source_id':packet['source_id'],'ordinal':u['ordinal'],
            'raw_hash':u['hash'],'packet':packet['id'],'category':category,
            'content_decision':'non_research_template','reason':rationales[category],
            'dependency_issue':'partial_rating_table' if packet['source_id'].startswith('1e021a8c') and u['ordinal'] in (40,41,42) else None})
assert len(annotations)==len({(a['source_id'],a['ordinal']) for a in annotations})==301
assert {(a['source_id'],a['ordinal']) for a in annotations} == {(c['source_id'],c['ordinal']) for c in p.all_changes}
p.save(p.HERE/'review-labels.json',{'reviewer':'agent, full packet reading; not independent human or blind review','units':annotations})

old_regions={s['source_id']:{r['ordinal']:r for r in s['clean']['regions'] if r['ordinal'] is not None} for s in p.base}
conservation=[]
unique_gold=set()
for case in p.gold:
    lost=[]
    for b in case['blocks']:
        unique_gold.add(b['old_chunk'])
        for u in b['units']:
            if not u['in_new_chunk']:
                lost.append({'chunk':b['old_chunk'],'ordinal':u['ordinal'],'text':u['raw_text'],
                    'old_status':old_regions[case['source_id']][u['ordinal']]['status'],
                    'new_status':u['new_status']})
    newly_lost=[u for u in lost if u['old_status']=='kept']
    assert all(u['text'].strip()=='敬请参阅最后一页特别声明' for u in newly_lost)
    conservation.append({'case':case['id'],'old_chunks':[b['old_chunk'] for b in case['blocks']],
        'non_referenced_units':lost,'newly_excluded':newly_lost,
        'finding':'All old evidence units remain referenced except reviewed standalone templates; existing noise is separately identified.'})
p.save(p.HERE/'gold-review.json',conservation)

extra=[]
labels=p.read(p.ROOT/'.scratch/corpus-relevance-audit-20261021/labels.json')
for cid,case in labels['cases'].items():
    for chunk in case.get('positive_chunks',[]):
        ev=p.authority[chunk]
        sid=ev['source_id']
        refs={i for c in p.new_chunks[sid] for i in (*c.unit_ordinals,*c.context_refs)}
        newly_lost=[u for u in ev['units'] if (i:=int(u['unit_id'].split(':')[-1])) not in refs and old_regions[sid][i]['status']=='kept']
        assert not newly_lost
        extra.append({'case':cid,'chunk':chunk,'newly_lost_units':newly_lost})
p.save(p.HERE/'detailed-label-conservation.json',extra)

# Resolve cell endpoints through CONTAINS parents to projected row units. Direct
# ordinal-only checks miss header_for relations between unprojected cells.
crossings=[]
for sid,reader in p.readers.items():
    nodes={n.node_id:n for n in reader.structure.nodes}
    parents=defaultdict(set)
    for r in reader.structure.relations:
        if r.kind.value=='contains':
            parents[r.target_id].add(r.source_id)
    def owners(node_id, seen=frozenset()):
        if node_id in seen:
            return set()
        n=nodes[node_id]
        if n.ordinal is not None:
            return {n.ordinal}
        return set().union(*(owners(a,seen|{node_id}) for a in parents[node_id]))
    for r in reader.structure.relations:
        if r.kind.value in ('contains','next_in_reading_order'):
            continue
        aa,bb=owners(r.source_id),owners(r.target_id)
        for a in aa:
            for b in bb:
                if p.new_regions[sid][a].status != p.new_regions[sid][b].status and any(c['source_id']==sid and c['ordinal'] in (a,b) for c in p.all_changes):
                    crossings.append({'source_id':sid,'kind':r.kind.value,'source_node':r.source_id,
                        'target_node':r.target_id,'source_ordinal':a,'target_ordinal':b,
                        'source_status':p.new_regions[sid][a].status.value,'target_status':p.new_regions[sid][b].status.value})
p.save(p.HERE/'new-dependency-crossings.json',crossings)

sid=next(s for s in p.readers if s.startswith('1e021a8c'))
matches=[]
for u in p.readers[sid].units:
    if 43<=u.ordinal<=69:
        m=_STOCK_CODE.search(u.raw_text)
        if m:
            matches.append({'ordinal':u.ordinal,'text':u.raw_text,'matched_stock_code':m.group()})
p.save(p.HERE/'false-stock-code-matches.json',matches)
summary={'new_exclusions':301,'affected_sources':len(ranges),'reviewed_packets':len(p.packets),
 'categories':dict(Counter(a['category'] for a in annotations)),
 'old_offline_chunks':sum(s['old_chunks'] for s in p.source_checks),
 'new_offline_chunks':sum(s['new_chunks'] for s in p.source_checks),
 'published_authority_chunks':len(p.authority),'positive_cases':len(conservation),
 'old_gold_block_occurrences':sum(len(c['blocks']) for c in p.gold),'unique_old_gold_blocks':len(unique_gold),
 'newly_excluded_gold_occurrences':sum(len(c['newly_excluded']) for c in conservation),
 'detailed_positive_blocks':len(extra),'new_dependency_crossings':len(crossings),
 'false_stock_code_matches':matches,
 'decision':'Hold clean-6 rebuild until partial rating-table boundary is corrected; no research-prose deletion found in this reviewed delta.'}
p.save(p.HERE/'summary.json',summary)
print(p.json.dumps(summary,ensure_ascii=False,indent=2))
