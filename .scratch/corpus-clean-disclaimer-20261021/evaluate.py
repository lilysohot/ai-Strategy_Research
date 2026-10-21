"""Compare clean-6 to frozen clean-5 reader inputs; no DB/model calls."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from common import restore
from plugins.corpus.preparation.clean import clean_reader_result, verify_clean_region, verify_noise_verdicts
from plugins.corpus.preparation.chunk import chunk_clean_result
from plugins.corpus.preparation.contract import UnitStatus


def norm(text):
    return ''.join(text.replace('%','').replace('％','').split()).casefold()


baseline=json.loads((HERE/'baseline.json').read_text())
authority=json.loads((ROOT/'.scratch/corpus-relevance-audit-20261021/authority.json').read_text())
manifest=json.loads((ROOT/'.scratch/corpus-vector-acceptance-20261020/manifest.json').read_text())
labels=json.loads((ROOT/'.scratch/corpus-relevance-audit-20261021/labels.json').read_text())
out={'baseline_sha256':hashlib.sha256((HERE/'baseline.json').read_bytes()).hexdigest(),'sources':[],'positive_checks':[]}
new_text={}
regions_by_source={}
lines=['# clean-6 新增排除单元复核', '', '此清单包含所有 kept → noise 单元。原文在读取单元及历史版本中保留。', '']
for row in baseline:
    reader=restore(row['checkpoint'], row['source_id'])
    raw_before=tuple(u.content_hash for u in reader.units)
    old={r['ordinal']:r for r in row['clean']['regions'] if r['ordinal'] is not None}
    clean=clean_reader_result(reader)
    verify_noise_verdicts(clean.regions)
    new={r.ordinal:r for r in clean.regions if r.ordinal is not None}
    assert set(new)==set(old)=={u.ordinal for u in reader.units}
    assert raw_before==tuple(u.content_hash for u in reader.units)
    units={u.ordinal:u for u in reader.units}
    removed=[]
    for ordinal,region in new.items():
        if region.status is UnitStatus.KEPT:
            verify_clean_region(units[ordinal].raw_text,region.clean_view,region.mapping)
            if old[ordinal]['status']=='kept':
                assert region.clean_view == old[ordinal]['clean_view']
        if old[ordinal]['status']=='kept' and region.status is UnitStatus.NOISE:
            u=units[ordinal]
            removed.append({'ordinal':ordinal,'kind':u.kind,'text':u.raw_text,'reasons':region.reasons})
    chunks=chunk_clean_result(reader,clean)
    assert not any(set(c.unit_ordinals)&{r['ordinal'] for r in removed} for c in chunks.chunks)
    new_text[row['source_id']]='\n'.join(c.search_text for c in chunks.chunks)
    regions_by_source[row['source_id']]=new
    out['sources'].append({'source_id':row['source_id'],'build_id':row['build_id'],
        'old_kept':sum(r['status']=='kept' for r in old.values()),
        'new_kept':sum(r.status is UnitStatus.KEPT for r in new.values()),
        'removed':removed,'new_chunks_before_admission':len(chunks.chunks)})
    lines += [f'## {row["source_id"]}', '']
    for r in removed:
        lines += [f'### unit:{r["ordinal"]:04d} ({r["kind"]})', ', '.join(r['reasons']), '', r['text'], '']
for case in manifest['cases']:
    if case['kind']!='positive':
        continue
    kept=norm(case['gold_term']) in norm(new_text[case['source_id']])
    out['positive_checks'].append({'id':case['id'],'gold_term_retained':kept})
    assert kept,case['id']
out['reviewed_support_checks']=[]
for cid,case in labels['cases'].items():
    for chunk in case['positive_chunks']:
        evidence=authority[chunk]
        markers=case['labels'][chunk]['support_markers']
        checks=[norm(marker) in norm(new_text[evidence['source_id']]) for marker in markers]
        assert all(checks),(cid,chunk,markers)
        out['reviewed_support_checks'].append({'case':cid,'chunk':chunk,'markers':markers,'all_retained':True})
# Locate the previously returned disclaimer anchors by original unit identities.
out['disclaimer_anchor_checks']=[]
for chunk in ('16a9a510ef9e405f:body:0016','16a9a510ef9e405f:body:0017'):
    ev=authority[chunk]
    regions=regions_by_source[ev['source_id']]
    kept=[u['unit_id'] for u in ev['units'] if regions[int(u['unit_id'].split(':')[-1])].status is UnitStatus.KEPT]
    out['disclaimer_anchor_checks'].append({'old_chunk':chunk,'retained_units':kept})
    assert not kept,(chunk,kept)
out['summary']={'source_count':len(baseline),'affected_sources':sum(bool(r['removed']) for r in out['sources']),
    'newly_excluded_units':sum(len(r['removed']) for r in out['sources']),
    'positive_gold_terms_retained':sum(r['gold_term_retained'] for r in out['positive_checks']),
    'reviewed_positive_chunks':len(out['reviewed_support_checks']),
    'removed_reasons':dict(Counter(reason for row in out['sources'] for r in row['removed'] for reason in r['reasons']))}
(HERE/'evaluation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
(HERE/'removed-review.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(out['summary'],ensure_ascii=False,indent=2))
