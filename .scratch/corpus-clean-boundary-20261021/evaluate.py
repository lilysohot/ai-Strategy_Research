"""Compare frozen clean-6 with clean-7, including table-cell dependencies."""
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / '.scratch/corpus-clean-disclaimer-20261021')]
from common import restore
from plugins.corpus.preparation.clean import CLEAN_REV, clean_reader_result, verify_clean_region
from plugins.corpus.preparation.chunk import chunk_clean_result
from plugins.corpus.preparation.contract import UnitStatus

def read(path):
    return json.loads(path.read_text())

def save(name, obj):
    (HERE/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2))

assert CLEAN_REV == 'clean-7'
base = read(HERE/'baseline.json')
authority = read(ROOT/'.scratch/corpus-relevance-audit-20261021/authority.json')
manifest = read(ROOT/'.scratch/corpus-vector-acceptance-20261020/manifest.json')
labels = read(ROOT/'.scratch/corpus-relevance-audit-20261021/labels.json')
changes=[]
sources=[]
evidence=[]
crossings=[]
readers={}
regions_by_source={}
refs_by_source={}
for source in base:
    sid=source['source_id']
    reader=restore(source['checkpoint'],sid)
    readers[sid]=reader
    units={u.ordinal:u for u in reader.units}
    old={r['ordinal']:r for r in source['clean']['regions'] if r['ordinal'] is not None}
    clean=clean_reader_result(reader)
    regions={r.ordinal:r for r in clean.regions if r.ordinal is not None}
    regions_by_source[sid]=regions
    assert set(old)==set(regions)==set(units)
    chunks=chunk_clean_result(reader,clean).chunks
    old_clean=SimpleNamespace(regions=tuple(SimpleNamespace(**{**r,'status':UnitStatus(r['status'])}) for r in source['clean']['regions']))
    old_chunks=chunk_clean_result(reader,old_clean).chunks
    old_refs={i for c in old_chunks for i in (*c.unit_ordinals,*c.context_refs)}
    refs={i for c in chunks for i in (*c.unit_ordinals,*c.context_refs)}
    refs_by_source[sid]=refs
    removed=set()
    for i,r in regions.items():
        if r.status is UnitStatus.KEPT:
            verify_clean_region(units[i].raw_text,r.clean_view,r.mapping)
            if old[i]['status']=='kept':
                assert old[i]['clean_view']==r.clean_view
        if old[i]['status']!=r.status.value:
            if old[i]['status']=='kept':
                removed.add(i)
            changes.append({'source_id':sid,'ordinal':i,'old':old[i]['status'],'new':r.status.value,
                'kind':units[i].kind,'page':units[i].location.page,'text':units[i].raw_text,
                'raw_hash':units[i].content_hash,'reasons':list(r.reasons)})
    assert not ((old_refs-refs)-removed)
    assert not (refs & {i for i,r in regions.items() if r.status is not UnitStatus.KEPT})
    sources.append({'source_id':sid,'old_chunks':len(old_chunks),'new_chunks':len(chunks),
        'removed':sorted(removed),'kept_reference_loss':[]})
    nodes={n.node_id:n for n in reader.structure.nodes}
    parents=defaultdict(set)
    for rel in reader.structure.relations:
        if rel.kind.value=='contains':
            parents[rel.target_id].add(rel.source_id)
    def owners(node_id, seen=frozenset()):
        if node_id in seen:
            return set()
        n=nodes[node_id]
        if n.ordinal is not None:
            return {n.ordinal}
        return set().union(*(owners(a,seen|{node_id}) for a in parents[node_id]))
    for rel in reader.structure.relations:
        if rel.kind.value in ('contains','next_in_reading_order'):
            continue
        for a in owners(rel.source_id):
            for b in owners(rel.target_id):
                if regions[a].status != regions[b].status:
                    crossings.append({'source_id':sid,'kind':rel.kind.value,'a':a,'b':b,
                        'newly_introduced':old[a]['status']==old[b]['status'],
                        'a_status':regions[a].status.value,'b_status':regions[b].status.value})

for chunk,ev in authority.items():
    units={u.ordinal:u for u in readers[ev['source_id']].units}
    for u in ev['units']:
        assert u['raw_text']==units[int(u['unit_id'].split(':')[-1])].raw_text

old_by_source={s['source_id']:{r['ordinal']:r for r in s['clean']['regions'] if r['ordinal'] is not None} for s in base}
cases=[(c['id'],c['gold_chunks']) for c in manifest['cases'] if c['kind']=='positive']
cases += [(cid+':detailed',case['positive_chunks']) for cid,case in labels['cases'].items() if case.get('positive_chunks')]
for cid,chunks in cases:
    lost=[]
    for chunk in chunks:
        ev=authority[chunk]
        sid=ev['source_id']
        for u in ev['units']:
            i=int(u['unit_id'].split(':')[-1])
            if old_by_source[sid][i]['status']=='kept' and i not in refs_by_source[sid]:
                lost.append({'chunk':chunk,'ordinal':i,'text':u['raw_text']})
    evidence.append({'case':cid,'chunks':chunks,'newly_lost':lost})
assert not any(c['newly_lost'] for c in evidence)
assert not any(c['newly_introduced'] for c in crossings)
sid=next(s for s in readers if s.startswith('1e021a8c'))
assert all(regions_by_source[sid][i].status is UnitStatus.NOISE for i in range(40,50))
assert not any(c['source_id']==sid for c in crossings)
save('changes.json',changes)
save('evidence.json',evidence)
save('dependencies.json',crossings)
save('sources.json',sources)
summary={'clean_rev':CLEAN_REV,'sources':len(sources),'changed_sources':len({c['source_id'] for c in changes}),
    'transitions':dict(Counter(c['old']+'->'+c['new'] for c in changes)),
    'old_chunks':sum(s['old_chunks'] for s in sources),'new_chunks':sum(s['new_chunks'] for s in sources),
    'newly_lost_evidence_units':0,'remaining_dependency_crossings':len(crossings),
    'fixed_table_units':list(range(40,50)),
    'hashes':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in
        (HERE/'baseline.json',ROOT/'plugins/corpus/preparation/clean.py',ROOT/'.scratch/corpus-vector-acceptance-20261020/manifest.json')}}
save('summary.json',summary)
lines=['# clean-6 → clean-7 全量状态变化','']
for c in changes:
    lines += [f"## {c['source_id'][:8]} unit:{c['ordinal']} {c['old']} → {c['new']} ({c['kind']}, p{c['page']})",c['text'],'']
(HERE/'changed-text.md').write_text('\n'.join(lines))
print(json.dumps(summary,ensure_ascii=False,indent=2))
