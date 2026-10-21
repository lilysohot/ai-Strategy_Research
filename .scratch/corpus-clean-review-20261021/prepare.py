"""Read-only offline review packets: all state changes, boundaries and evidence."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE = ROOT/'.scratch/corpus-clean-disclaimer-20261021'
sys.path[:0] = [str(ROOT), str(BASE)]
from common import restore
from plugins.corpus.preparation.clean import clean_reader_result
from plugins.corpus.preparation.chunk import chunk_clean_result
from plugins.corpus.preparation.contract import UnitStatus


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


base = read(BASE/'baseline.json')
previous = read(BASE/'evaluation.json')
assert previous['baseline_sha256'] == sha(BASE/'baseline.json')
assert len(base) == 18
sources = {s['source_id']:s for s in read(ROOT/'.scratch/corpus-vector-acceptance-20261020/corpus.json')}
authority = read(ROOT/'.scratch/corpus-relevance-audit-20261021/authority.json')
manifest = read(ROOT/'.scratch/corpus-vector-acceptance-20261020/manifest.json')
packets=[]
all_changes=[]
readers={}
new_regions={}
new_chunks={}
source_checks=[]
for source in base:
    sid=source['source_id']
    reader=restore(source['checkpoint'],sid)
    readers[sid]=reader
    old={r['ordinal']:r for r in source['clean']['regions'] if r['ordinal'] is not None}
    new=clean_reader_result(reader)
    assert new.clean_rev == 'clean-6'
    regions={r.ordinal:r for r in new.regions if r.ordinal is not None}
    assert set(old)==set(regions)
    for ordinal,region in regions.items():
        if old[ordinal]['status']=='kept' and region.status is UnitStatus.KEPT:
            assert old[ordinal]['clean_view']==region.clean_view
    new_regions[sid]=regions
    chunks=chunk_clean_result(reader,new).chunks
    new_chunks[sid]=chunks
    old_clean=SimpleNamespace(regions=tuple(SimpleNamespace(**{**r,'status':UnitStatus(r['status'])}) for r in source['clean']['regions']))
    old_chunks=chunk_clean_result(reader,old_clean).chunks
    old_refs={i for c in old_chunks for i in (*c.unit_ordinals,*c.context_refs)}
    new_refs={i for c in chunks for i in (*c.unit_ordinals,*c.context_refs)}
    removed={i for i,r in regions.items() if old[i]['status']=='kept' and r.status is UnitStatus.NOISE}
    expected={r['ordinal'] for s in previous['sources'] if s['source_id']==sid for r in s['removed']}
    assert removed==expected
    changes=[{'source_id':sid,'ordinal':i,'before':old[i]['status'],'after':r.status.value}
             for i,r in regions.items() if old[i]['status']!=r.status.value]
    all_changes.extend(changes)
    source_checks.append({'source_id':sid,'title':sources[sid]['title'],
        'old_chunks':len(old_chunks),'new_chunks':len(chunks),
        'kept_units_lost_from_chunks':sorted((old_refs-new_refs)-removed),
        'new_noise_referenced':sorted(removed & new_refs),
        'removed_table_rows':[u.ordinal for u in reader.units if u.ordinal in removed and u.kind=='table_row'],
        'schema':json.loads(source['checkpoint'])['checkpoint_schema_rev']})
    ordered=sorted(reader.units,key=lambda u:u.ordinal)
    groups=[]
    for pos,u in enumerate(ordered):
        if u.ordinal not in removed:
            continue
        if groups and pos==groups[-1][-1]+1:
            groups[-1].append(pos)
        else:
            groups.append([pos])
    for positions in groups:
        packet_id=f'{sid[:8]}-{ordered[positions[0]].ordinal:04d}-{ordered[positions[-1]].ordinal:04d}'
        indices=range(max(0,positions[0]-2),min(len(ordered),positions[-1]+3))
        units=[]
        for pos in indices:
            u=ordered[pos]
            r=regions[u.ordinal]
            units.append({'ordinal':u.ordinal,'removed':u.ordinal in removed,'kind':u.kind,
                'page':u.location.page,'text':u.raw_text,'hash':u.content_hash,
                'before':old[u.ordinal]['status'],'after':r.status.value,
                'reasons':list(r.reasons),'label_path':list(u.location.label_path),
                'cells':[list(c) for c in u.location.cells]})
        packets.append({'id':packet_id,'source_id':sid,'title':sources[sid]['title'],'units':units})

# Bind historical evidence to the SAME source and unit raw text, not chunk IDs.
alignment=[]
for chunk,ev in authority.items():
    units={u.ordinal:u for u in readers[ev['source_id']].units}
    for unit in ev['units']:
        ordinal=int(unit['unit_id'].split(':')[-1])
        assert unit['raw_text']==units[ordinal].raw_text,(chunk,unit['unit_id'])
    alignment.append(chunk)

gold=[]
for case in manifest['cases']:
    if case['kind']!='positive':
        continue
    blocks=[]
    sid=case['source_id']
    regions=new_regions[sid]
    referenced={i for c in new_chunks[sid] for i in (*c.unit_ordinals,*c.context_refs)}
    for chunk in case['gold_chunks']:
        ev=authority[chunk]
        assert ev['source_id']==sid
        block_units=[]
        for unit in ev['units']:
            ordinal=int(unit['unit_id'].split(':')[-1])
            block_units.append({**unit,'ordinal':ordinal,'new_status':regions[ordinal].status.value,
                'in_new_chunk':ordinal in referenced})
        blocks.append({'old_chunk':chunk,'units':block_units,'text':ev['text']})
    gold.append({'id':case['id'],'question':case['question'],'expected':case['expected'],
                 'source_id':sid,'blocks':blocks})

plan={'hashes':{str(p.relative_to(ROOT)):sha(p) for p in
    (BASE/'baseline.json',BASE/'evaluation.json',ROOT/'plugins/corpus/preparation/clean.py',
     ROOT/'.scratch/corpus-relevance-audit-20261021/authority.json',
     ROOT/'.scratch/corpus-vector-acceptance-20261020/manifest.json')},
    'scope':'All 301 newly excluded units, surrounding boundaries, 24 positive full evidence packages. Agent review, not human/blind adjudication. No DB/index/model calls.',
    'rules':{'safe_noise':'legal boilerplate, rating definitions, contact details, standalone reminder',
             'unsafe':'research prose, actual rating/recommendation, financial facts or necessary table header/period/unit/footnote',
             'uncertain':'ambiguous role or lost dependency; must not pass as safe'},
    'authority_chunks_raw_aligned':len(alignment)}
save(HERE/'plan.json',plan)
save(HERE/'packets.json',packets)
save(HERE/'gold-evidence.json',gold)
save(HERE/'state-checks.json',{'changes':all_changes,'sources':source_checks})
for n in range(0,len(packets),8):
    lines=['# 排除单元与边界原文核验', '']
    for p in packets[n:n+8]:
        lines += [f'## {p["id"]} {p["title"]}', '']
        for u in p['units']:
            lines += [f'### {u["ordinal"]} {"EXCLUDED" if u["removed"] else "CONTEXT"} {u["kind"]} page={u["page"]} {u["before"]}->{u["after"]}',u['text'],'']
    (HERE/f'packet-{n//8+1:02d}.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'packets':len(packets),'removed':sum(u['removed'] for p in packets for u in p['units']),
    'changes':dict(Counter(f'{r["before"]}->{r["after"]}' for r in all_changes)),
    'source_checks':source_checks,'gold_blocks':sum(len(c['blocks']) for c in gold)},ensure_ascii=False,indent=2))
