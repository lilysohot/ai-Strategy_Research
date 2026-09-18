"""Read-only validation of annotation input; no gold emission or freeze."""
import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

import pymupdf

IR = Path(__file__).resolve().parent
ROOT = IR.parents[2]
working = IR / 'i0a4-labeling-working.json'
data = json.loads(working.read_text())
original = json.loads((ROOT / data['annotation_provenance']['original_backup']).read_text())
package_path = IR / data['package_ref']['artifact']
package = json.loads(package_path.read_text())
assert hashlib.sha256(package_path.read_bytes()).hexdigest() == data['package_ref']['sha256']
spec = importlib.util.spec_from_file_location('annotation_schema', IR / 'i0a4_freeze_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
# Only pure record validators are reused. check()/main()/emit are never called.
pkg_slots = {s['gold_slot']: s for s in package['source_gold_candidates']['slots']}
pkg_queries = {q['query_id']: q for q in package['query_gold_slots']}
adj = json.loads((IR / 'i0a2-adjudicated-20260915.json').read_text())
dev_docs = {s['db_doc_id'] for s in adj['sources'] if s.get('dev_selection') == 'approved'}
assert len(dev_docs) == 6
errors = []
pdfs = {}
source_quote_checks = []
for section, identity in [('label_slots', 'gold_slot'), ('query_slots', 'query_id')]:
    assert len(data[section]) == len(original[section])
    assert len({s[identity] for s in data[section]}) == len(data[section])
    assert {s[identity] for s in data[section]} == {s[identity] for s in original[section]}
for before, s in zip(original['label_slots'], data['label_slots']):
    for key in ['gold_slot', 'doc_id', 'scope', 'source_path', 'source_sha256', 'locator_page', 'header_markers', 'full_text']:
        assert s[key] == before[key], (s['gold_slot'], key)
    gate._check_slot(s, pkg_slots[s['gold_slot']], {}, errors)
    assert isinstance(s['must_preserve'], bool)
    assert s['human_review_status'] == 'pending'
    path = ROOT / s['source_path']
    pdfs.setdefault(s['doc_id'], pymupdf.open(path))
    raw = pdfs[s['doc_id']][int(s['locator_page']) - 1].get_text()
    for i, it in enumerate(s['expected_items']):
        assert it['quote'] in s['full_text']
        assert set(it) == {'kind', 'unit', 'period', 'row', 'col', 'cell', 'quote', 'text'}
        if it['kind'] == 'table_cell':
            assert all(it[k] for k in ['row', 'col', 'cell', 'unit', 'period'])
        if gate.norm_ws(it['quote']) not in gate.norm_ws(raw):
            source_quote_checks.append({'slot': s['gold_slot'], 'item': i, 'quote': it['quote']})
for q in data['query_slots']:
    gate._check_query(q, pkg_queries[q['query_id']], dev_docs, errors)
    if q['query_kind'] == 'negative':
        assert q['relevant_sources'] == [] and q['satisfy_rule'] is None
    assert q['human_review_status'] == 'pending'
assert not errors, errors
assert not source_quote_checks, source_quote_checks
counts = Counter((q['domain'], q['query_kind']) for q in data['query_slots'])
assert all(counts[(dom, kind)] == count for dom in ['company', 'industry', 'macro']
           for kind, count in [('answerable', 8), ('negative', 2)])
report = {
    'validation_kind': 'annotation_schema_and_source_integrity_only_not_human_gold_freeze',
    'working_sha256': hashlib.sha256(working.read_bytes()).hexdigest(),
    'label_slots': len(data['label_slots']), 'expected_items': sum(len(s['expected_items']) for s in data['label_slots']),
    'query_slots': len(data['query_slots']), 'role_counts': dict(Counter(s['annotation_role'] for s in data['label_slots'])),
    'checks': {'package_hash': 'passed', 'original_pdf_hashes': '6/6 passed',
               'immutable_slot_fields': 'passed', 'quote_exact_substrings': '87/87 passed',
               'quotes_in_original_pdf_normalized': '87/87 passed', 'existing_record_validators': 'passed',
               'domain_8_plus_2': 'passed', 'source_allowlist': 'passed'},
    'errors': errors, 'human_review_status': 'pending', 'frozen': False,
    'important': '结构和引文校验通过不等于独立人工金标；6个负例仍需真人复核证据覆盖。',
}
(IR / 'audits/i0a4-annotation-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
lines = [
    '# I0A-4 标注复核清单', '',
    '状态：AI辅助标注已填写；真人独立复核待完成。此文件不是冻结报告。', '',
    '## 完成范围', '',
    '- 23个证据槽：20个正文证据、3个通用说明；共87条预期。',
    '- 30道题：公司/行业/宏观各8道可回答题、2道负例。',
    '- 6份PDF哈希一致；87条引文是槽文本的精确子串，且可在对应原PDF页文本中匹配。',
    '- 三张数值表的行列已目视核对；表格标签包含单位、期间、行、列与单元格定位。',
    '- 原工作文件已备份，v3候选包未改动；未生成冻结件。', '',
    '## 优先复核事项', '',
    '1. 全部记录的reviewer是Codex，human_basis字段保留兼容名称，但不宣称真人审核。真人接受后应自行填写身份和复核时间。',
    '2. company-013：评级声明页含“茅台集团持有华创云信4.06%”的特定披露，按混合页保留；其余评级定义不作个股收益预测。',
    '3. company-003：原PDF有2024/2025历史列；槽抽取丢失列头。EPS 0.36应对应2026E；现金流括号为负数。',
    '4. industry-009：R32 99.6%为价格历史分位，28.5万吨/年为2026E配额；开工率脚注有两种时间窗口，未自行分配到产品。',
    '5. company-060：3.51亿元在末段写为国内收入、其他段落写为半导体装备总收入；不把国内3.51亿元纳入预期。',
    '6. company-008：原文“二季度”与“3月底和7月”有时间冲突，未据其拟精确提价次数题。',
    '7. industry-057：PTFE损耗参数符号原文也写Dk，未静默纠正；选材是供应链消息/计划。',
    '8. macro-038：PDF印刷日期为2026-09-05，与文件日期09-06不同。经济数据仅按报告内容标注，不作现实真实性核验。',
    '9. 负例要求语料没有支持答案的证据。未来已实现数据、唯一序列号、已签采购量、逐户明细均不能由现有概述/预测推出；其中细粒度缺失类仍须真人通读确认。',
    '10. 通用说明分类不等于永久删除：两页宏观评级说明与行业导读无当前问题所需的正文断言，仍可保留为文档元数据。', '',
    '## 证据槽', '', '| 槽位 | 页码 | 分类 | 预期数 |', '|---|---:|---|---:|',
]
for s in data['label_slots']:
    lines.append(f'| {s["gold_slot"]} | {s["locator_page"]} | {s["annotation_role"]} | {len(s["expected_items"])} |')
lines.extend(['', '## 题目与判分依据', ''])
for q in data['query_slots']:
    lines.extend([f'### {q["query_id"]} · {q["query_kind"]}', '', q['question'], '',
                  '**证据要求：** ' + q['evidence_requirement'], '',
                  '**来源：** ' + (', '.join(q['relevant_sources']) or '[]（无支持来源，待人工复核）'), ''])
(IR / 'i0a4-annotation-review.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
