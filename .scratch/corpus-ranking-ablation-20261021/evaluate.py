"""Offline isolated ablations; signals are computed before loading labels."""
import hashlib
import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from signals import INTENTS, features, rerank_within_source
from signals_v2 import features as features_v2
from plugins.corpus.preparation.search_pg import SearchHit
from plugins.corpus.retrieval.dedup import dedupe_contained_hits
from plugins.corpus.retrieval.hybrid import fuse
from plugins.corpus.service import CorpusService


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


spec = importlib.util.spec_from_file_location('capture_replay', ROOT / '.scratch/corpus-selection-audit-20261021/run.py')
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
authority_path = ROOT / '.scratch/corpus-relevance-audit-20261021/authority.json'
authority = read(authority_path)
source_titles = {s['source_id']: s['title'] for s in read(ROOT / '.scratch/corpus-vector-acceptance-20261020/corpus.json')}
prepared = read(HERE / 'prepared.json')
manifest_path = ROOT / '.scratch/corpus-vector-acceptance-20261020/manifest.json'
assert prepared['manifest_sha256'] == sha(manifest_path)
questions = [{k: c[k] for k in ('id', 'question')} for c in read(manifest_path)['cases']]
assert set(INTENTS) == {c['id'] for c in questions}
structures = {s: {c: SimpleNamespace(**{**v, 'units': tuple(SimpleNamespace(**u) for u in v['units'])})
                 for c,v in rows.items()} for s,rows in read(HERE / 'structures.json').items()}
service = CorpusService.__new__(CorpusService)


def restore_hits(rows):
    fields = ('section_path', 'unit_refs', 'cells', 'label_path', 'context_chunk_ids')
    return tuple(SearchHit(**{**r, **{k: tuple(tuple(v) if isinstance(v, list) else v for v in r[k]) for k in fields}}) for r in rows)


def select(trace, fused, lexical, lexemes):
    selected = service._selected_context_hits(fused, trace.chunk_order, 10,
        lexemes=tuple(lexemes), lexical_fallback_hits=lexical if trace.status == 'hybrid' else None)
    selected = service._attach_table_header_context(selected, trace.chunk_order, structures)
    return dedupe_contained_hits(selected)


def scope(hits):
    return {(h.build_id,c) for h in hits for c in (h.context_chunk_ids or (h.chunk_id,))}


runs = {}
for case in questions:
    cid = case['id']
    path = ROOT / f'.scratch/corpus-selection-audit-20261021/captures/{cid}.json'
    data = prepared['cases'][cid]
    assert data['capture_sha256'] == sha(path)
    trace = prior.restore(read(path)['trace'])
    feature_map = {chunk: features(cid, case['question'], ev) for chunk,ev in authority.items()}
    revised_features = {chunk: features_v2(cid, case['question'], ev, source_titles[ev['source_id']]) for chunk,ev in authority.items()}
    baseline = dedupe_contained_hits(trace.selected)
    assert scope(baseline) == scope(trace.selected)
    assert select(trace, trace.fused, trace.lexical, data['lexemes']) == baseline, cid
    methods = {'dedup_baseline': (trace.fused, baseline)}
    for name in ('filename_zero', 'institution_zero'):
        lexical = restore_hits(data[name])
        fused = fuse(lexical, trace.dense) if trace.status == 'hybrid' else lexical
        methods[name] = (fused, select(trace, fused, lexical, data['lexemes']))
    for signal in ('template', 'entity', 'aspects'):
        fused = rerank_within_source(trace.fused, feature_map, signal)
        lexical = rerank_within_source(trace.lexical, feature_map, signal)
        assert {(h.build_id,h.chunk_id) for h in fused} == {(h.build_id,h.chunk_id) for h in trace.fused}
        methods[signal] = (fused, select(trace, fused, lexical, data['lexemes']))
        fused_v2 = rerank_within_source(trace.fused, revised_features, signal)
        lexical_v2 = rerank_within_source(trace.lexical, revised_features, signal)
        methods[signal + '_v2'] = (fused_v2, select(trace, fused_v2, lexical_v2, data['lexemes']))
    runs[cid] = {'question': case['question'], 'trace': trace, 'features': feature_map,
                 'features_v2': revised_features, 'methods': methods}

# Freeze actual rankings and rule hashes BEFORE reading any relevance labels.
save(HERE / 'rankings.json', {'signal_sha256': sha(HERE / 'signals.py'), 'signal_v2_sha256': sha(HERE / 'signals_v2.py'), 'prepared_sha256': sha(HERE / 'prepared.json'),
     'cases': {cid: {'question': row['question'], 'features': row['features'], 'features_v2': row['features_v2'],
         'methods': {name: {'candidates': [h.chunk_id for h in pool], 'selected': [asdict(h) for h in hits]}
                     for name,(pool,hits) in row['methods'].items()}} for cid,row in runs.items()}})

labels_path = ROOT / '.scratch/corpus-relevance-audit-20261021/labels.json'
labels = read(labels_path)
assert labels['authority_sha256'] == sha(authority_path)
gold = {c['id']: c for c in read(manifest_path)['cases']}


def detailed(cid, hits, k):
    case = labels['cases'][cid]
    selected = hits[:k]
    positives = set(case['positive_chunks'])
    judgments = []
    for h in selected:
        grade = case['labels'].get(h.chunk_id)
        if grade is None and case['build_id'] and h.build_id != case['build_id']:
            grade = {'grade': 'source_scope_mismatch', 'facets': []}
        judgments.append(grade)
    unknown = sum(g is None for g in judgments)
    relevant = sum(h.chunk_id in positives for h in selected)
    observed = {c for b,c in scope(selected)}
    facets = {f for g in judgments if g for f in g['facets']}
    return {'returned': len(selected), 'unjudged': unknown,
        'precision_at_k': relevant/k if not unknown else None,
        'precision_returned': relevant/len(selected) if selected and not unknown else None,
        'full_count': sum(g and g['grade'] == 'full' for g in judgments) if not unknown else None,
        'context_recall': len(observed & positives)/len(positives) if positives else None,
        'anchor_facet_coverage': len(facets)/len(case['facets']) if case['facets'] else None,
        'anchors': [{'chunk': h.chunk_id, 'grade': g['grade'] if g else 'unjudged'} for h,g in zip(selected,judgments)]}


out = {'hashes': {p.name: sha(p) for p in (manifest_path, labels_path, authority_path, HERE/'signals.py', HERE/'signals_v2.py', HERE/'rankings.json')},
       'cases': {}, 'summary': {}}
for cid,row in runs.items():
    baseline = row['methods']['dedup_baseline'][1]
    gold_set = set(gold[cid].get('gold_chunks', []))
    data = {'status': row['trace'].status, 'methods': {}}
    for name,(pool,hits) in row['methods'].items():
        scoring_features = row['features_v2'] if name.endswith('_v2') else row['features']
        anchors = [h.chunk_id for h in hits]
        context = {c for b,c in scope(hits)}
        metrics = {'rows': len(hits), 'context_chunks': len(scope(hits)),
            'old_gold_top1': bool(anchors and anchors[0] in gold_set),
            'old_gold_anchor_top10': sorted(set(anchors) & gold_set),
            'old_gold_context': sorted(context & gold_set),
            'old_gold_pool': sorted({h.chunk_id for h in pool} & gold_set),
            'lost_old_gold_context': sorted(({c for b,c in scope(baseline)} & gold_set) - context),
            'added_old_gold_context': sorted((context & gold_set) - {c for b,c in scope(baseline)}),
            'template_anchors': [h.chunk_id for h in hits if row['features'][h.chunk_id]['template']],
            'strong_template_anchors': [h.chunk_id for h in hits if row['features_v2'][h.chunk_id]['template']],
            'entity_top1': scoring_features[anchors[0]]['entity'] if anchors else None,
            'full_scope_preserved': scope(baseline) <= scope(hits)}
        if cid in labels['cases']:
            metrics['judged'] = {str(k): detailed(cid,hits,k) for k in (1,5,10)}
        data['methods'][name] = metrics
    out['cases'][cid] = data

for name in runs['p01']['methods']:
    successful = [(cid,row['methods'][name]) for cid,row in out['cases'].items()
                  if row['status']=='hybrid' and gold[cid]['kind']=='positive']
    out['summary'][name] = {'hybrid_positive_count': len(successful),
        'old_gold_top1_cases': sum(m['old_gold_top1'] for cid,m in successful),
        'old_gold_anchor_hit_cases': sum(bool(m['old_gold_anchor_top10']) for cid,m in successful),
        'old_gold_context_total': sum(len(m['old_gold_context']) for cid,m in successful),
        'lost_context_cases': {cid:m['lost_old_gold_context'] for cid,m in successful if m['lost_old_gold_context']},
        'added_context_cases': {cid:m['added_old_gold_context'] for cid,m in successful if m['added_old_gold_context']},
        'rows_all32': sum(row['methods'][name]['rows'] for row in out['cases'].values()),
        'all_baseline_context_preserved_cases': sum(row['methods'][name]['full_scope_preserved'] for row in out['cases'].values()),
        'template_anchors_all32': sum(len(row['methods'][name]['template_anchors']) for row in out['cases'].values()),
        'strong_template_anchors_all32': sum(len(row['methods'][name]['strong_template_anchors']) for row in out['cases'].values()),
        'contexts_all32': sum(row['methods'][name]['context_chunks'] for row in out['cases'].values())}
save(HERE / 'metrics.json', out)

lines = ['# 单信号排序对照：原文核验包', '', '规则预先冻结；无关来源按题目明确来源范围判定。n01 新候选未标注时记 unjudged。', '']
for cid in labels['cases']:
    row = runs[cid]
    lines += [f'## {cid} {row["question"]}', '']
    for name,(pool,hits) in row['methods'].items():
        lines += [f'### {name}', '']
        display_features = row['features_v2'] if name.endswith('_v2') else row['features']
        for rank,h in enumerate(hits,1):
            judgment = out['cases'][cid]['methods'][name]['judged']['10']['anchors'][rank-1]['grade']
            lines += [f'#### {rank}. {h.chunk_id}', f'标注：{judgment}；信号：{display_features[h.chunk_id]}；范围 {len(h.context_chunk_ids)} 块', '', authority[h.chunk_id]['text'], '']
(HERE / 'evidence-report.md').write_text('\n'.join(lines), encoding='utf-8')
print(json.dumps(out['summary'],ensure_ascii=False,indent=2))
for cid in labels['cases']:
    print(cid, {name: {'top1': m['judged']['1'], 'context_recall': m['judged']['10']['context_recall']} for name,m in out['cases'][cid]['methods'].items()})
