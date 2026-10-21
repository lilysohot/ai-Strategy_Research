"""Offline evidence conservation and structural boundary inspection."""
import contextlib
import io
from dataclasses import asdict

with contextlib.redirect_stdout(io.StringIO()):
    import prepare as p

from collections import Counter

gold_checks = []
for case in p.gold:
    excluded = []
    retained = []
    for block in case['blocks']:
        for u in block['units']:
            item = {'chunk':block['old_chunk'],'ordinal':u['ordinal'],'text':u['raw_text']}
            if not u['in_new_chunk']:
                excluded.append(item)
            else:
                assert u['new_status'] == 'kept'
                retained.append(item)
    gold_checks.append({'id':case['id'],'question':case['question'],
        'retained_unit_occurrences':len(retained),'excluded':excluded})

relations=[]
for sid,reader in p.readers.items():
    nodes={n.node_id:n for n in reader.structure.nodes}
    counts=Counter(r.kind.value for r in reader.structure.relations)
    crossing=[]
    for r in reader.structure.relations:
        a,b=nodes[r.source_id],nodes[r.target_id]
        if a.ordinal is None or b.ordinal is None:
            continue
        ar,br=p.new_regions[sid][a.ordinal],p.new_regions[sid][b.ordinal]
        if ar.status != br.status and r.kind.value not in ('contains','next_in_reading_order'):
            crossing.append({'relation':asdict(r),'a':a.ordinal,'b':b.ordinal,
                             'a_status':ar.status.value,'b_status':br.status.value})
    relations.append({'source_id':sid,'relation_counts':dict(counts),'crossing':crossing})

sid=next(s for s in p.readers if s.startswith('1e021a8c'))
reader=p.readers[sid]
boundary=[{'unit':asdict(u),'clean':asdict(p.new_regions[sid][u.ordinal])}
          for u in reader.units if 38 <= u.ordinal <= 56]
p.save(p.HERE/'evidence-conservation.json',gold_checks)
p.save(p.HERE/'structure-checks.json',relations)
p.save(p.HERE/'partial-table.json',boundary)
print('GOLD',p.json.dumps(gold_checks,ensure_ascii=False,indent=2))
print('RELATIONS',p.json.dumps(relations,ensure_ascii=False,indent=2))
print('TABLE',p.json.dumps(boundary,ensure_ascii=False,indent=2))
