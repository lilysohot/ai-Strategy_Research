"""Render paired captured evidence only; never call a model or search again."""
from common import ROOT, HERE, read, save
import json

cases = json.loads((ROOT / '.scratch/corpus-vector-acceptance-20261020/manifest.json').read_text())['cases']
metrics = {(r['case'], r['tag']): r for r in read('metrics.json') if r['mode'] == 'hybrid'}
authority = {tag: read(f'{tag}-authority.json') for tag in ('old', 'new')}
published = {r['source_id'] for r in read('build-results.json') if r['status'] == 'published'}
output = ['# 隔离库重建：32 题实际召回证据', '',
          '每题列出首条锚点原文及返回范围中已覆盖的旧标注证据。正文直接来自权威取证结果，未生成答案；首条并不自动代表相关或足够回答。完整池、排序和上下文 ID 保存在链接的 JSON。', '',
          '完整证据覆盖以来源匹配及旧标注块全部非模板文本为准；只命中部分文本不计完整覆盖。8 道压力题未穷尽标注，不据其返回条数推算准确率。', '']
for c in cases:
    output += [f"## {c['id']}：{c['question']}", '']
    if c.get('source_id'):
        output += ['目标来源版本：' + ('已发布 clean-7。' if c['source_id'] in published else '保留旧活动版本；不计为 clean-7 发布验证。'), '']
    for tag, label in [('old', '旧库'), ('new', '新隔离库')]:
        data = read(f"retrieval/{c['id']}-{tag}-hybrid.json")
        selected = data['trace']['selected']
        metric = metrics[c['id'], tag]
        output += [f"### {label}", '', f"[完整检索记录](retrieval/{c['id']}-{tag}-hybrid.json)；锚点 {len(selected)} 条，已审模板主导 {metric['reviewed_template_anchors']} 条。", '']
        if selected:
            ev = authority[tag][selected[0]['chunk_id']]
            output += [f"首条 `{ev['chunk_id']}`，来源 `{ev['source_id']}`：", '', '```text', ev['text'], '```', '']
        if c.get('gold_chunks'):
            output += [f"返回范围完整覆盖旧标注块：{len(metric['context_complete'])}/{metric['gold_blocks']}；正文首条覆盖：{'有' if metric['body_first_complete'] else '无'}。", '']
            # Display a real current returned chunk containing a non-heading gold fragment.
            definitions = read('metric-definition.json')['body_gold_parts'][c['id']]
            context_ids = list(dict.fromkeys(cid for h in selected for cid in (h['context_chunk_ids'] or [h['chunk_id']])))
            for gold_id in metric['context_complete'][:1]:
                fragments = definitions[gold_id]
                marker = max(fragments, key=len)
                for cid in context_ids:
                    ev = authority[tag][cid]
                    if ev['source_id'] == c['source_id'] and marker in ''.join(ev['text'].split()):
                        if not selected or cid != selected[0]['chunk_id']:
                            output += [f"返回范围中的标注证据原文 `{cid}`：", '', '```text', ev['text'], '```', '']
                        break
(HERE / 'evidence-report.md').write_text('\n'.join(output))
subset = {}
for tag in ('old', 'new'):
    rows = [metrics[c['id'], tag] for c in cases if c.get('source_id') in published and c['kind'] == 'positive']
    subset[tag] = {'positive_questions': len(rows), 'gold_blocks': sum(r['gold_blocks'] for r in rows),
                   'context_complete_blocks': sum(len(r['context_complete']) for r in rows),
                   'body_first_complete_cases': sum(bool(r['body_first_complete']) for r in rows)}
save('updated-source-metrics.json', subset)
print(json.dumps(subset, ensure_ascii=False))
for c in cases:
    if c['id'] in ('p13', 'p16', 'p20', 'n01'):
        print(c['id'], c['question'])
