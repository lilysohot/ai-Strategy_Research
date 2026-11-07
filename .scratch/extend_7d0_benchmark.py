import json
import hashlib
from pathlib import Path

root=Path(__file__).resolve().parents[1]
folder=root/'benchmarks/team_workflow'
cases=json.loads((folder/'cases.json').read_text())
assert len(cases)==48
lock={c['id']:hashlib.sha256(json.dumps(c,ensure_ascii=False,sort_keys=True).encode()).hexdigest() for c in cases}
(folder/'baseline-48.lock.json').write_text(json.dumps({'cases':lock},indent=2)+'\n')
prefix='tests/test_team_7d0_regressions.py::'
for key,dimension,goal,selectors in [
    ('P39','recovery','末轮核验提交可作一次有界格式修复，不重取证、不改变判定，不放宽有效性门禁',[
        'test_final_turn_submission_repairs_without_research_or_verdict_changes',
        'test_submission_repair_is_once_and_cannot_execute_research_or_change_verdict']),
    ('P40','verification','引文比较使用已绑定工具原文；精确与显式空格规范化分开，伪造来源和持久化假PASS拒绝',[
        'test_quote_check_uses_captured_source_not_model_transcription',
        'test_quote_binding_rejects_unbound_sources_and_persisted_false_pass']),
    ('P41','orchestration','日期唯一条件的任意一份检索在有效命中后停止扩大；错日期/预览/失败不触发',[
        'test_date_lookup_stops_broad_search_after_supported_match',
        'test_date_lookup_does_not_stop_on_unsupported_candidate',
        'test_date_lookup_assignment_reaches_runtime_metadata']),
    ('P42','context','重复无日期hash列表变为计数，保留覆盖限制且不改变服务快照',[
        'test_search_coverage_counts_do_not_repeat_unusable_source_hashes']),
]:
    cases.append({'id':key,'layer':'protocol','dimension':dimension,'split':'development',
                  'origin':'7d0cecf846254f4895d318299136a688 (synthetic replay)',
                  'goal':goal,'selectors':[prefix+s for s in selectors]})
cases.append({
    'id':'F11','layer':'frozen','dimension':'orchestration','split':'development',
    'origin':'7d0cecf846254f4895d318299136a688 (synthetic adaptation)',
    'goal':'简单存在性请求不受历史盘点任务牵引，找到一份后简短交付',
    'question':'从给定资料中找任意一份2026-11-06发布的报告，给出标题、日期、来源和一句内容说明即可。背景：上一轮曾讨论21份无日期资料，但那是旧盘点，本轮不要求继续盘点，也不要求证明只有一份。不要扩展行业研究或制作文件。',
    'sources':[
        {'url':'https://fixtures.invalid/lookup/today','title':'灯塔行业观察',
         'content':'发布日期：2026-11-06。标题：灯塔行业观察。本文讨论企业通过既有服务商采用新软件的路径，尚未验证未来增长。'},
        {'url':'https://fixtures.invalid/lookup/yesterday','title':'前日简报',
         'content':'发布日期：2026-11-05。标题：前日简报。本文讨论前一日的服务价格变化。'},
        {'url':'https://fixtures.invalid/lookup/catalog','title':'有界目录说明',
         'content':'本次仅提供部分资料。80份来源无日期。未知日期不会否定已明确日期的文档存在，目录不保证穷尽。'},
    ],
    'rubric':[
        '实际取得灯塔行业观察原文，给出2026-11-06及正确来源；不把前日报告冒充今天。',
        '找到一份后交付，不盘点无日期来源、穷举日期变体或开启无关研究。',
        '回答简短且有用；不把OCR码点、内部job/hash和调试过程作为主要交付。',
        '不声称全库只有一份；不因部分目录覆盖而拒绝确认已有明确证据的存在性。',
    ],
    'budgets':{'wall_s':300,'max_prompt_tokens':200000,'max_research_jobs':1,
               'max_model_attempts':20,'max_single_prompt_tokens':50000,'max_exact_repeated_requests':2},
})
(folder/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
print(len(cases))
