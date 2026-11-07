import json
from pathlib import Path
from benchmarks.team_workflow.run import digest

folder = Path('benchmarks/team_workflow')
cases = json.loads((folder/'cases.json').read_text())
assert len(cases) == 53
(folder/'baseline-53.lock.json').write_text(json.dumps({'cases': {c['id']: digest(c) for c in cases}}, indent=2)+'\n')
prefix = 'tests/test_team_requirement_scope.py::'
for name, goal, tests in [
    ('P43', '可选边界保留但不阻塞已支持的用户结果；矛盾完成提交原子拒绝', [
        'test_nonblocking_boundaries_survive_delivery_without_partial_status',
        'test_resolved_with_blocking_gap_rejected_atomically']),
    ('P44', '可选边界不能豁免失败核验或缺失必要证据', [
        'test_limitations_cannot_waive_required_verification',
        'test_required_missing_evidence_stays_partial_with_optional_boundary']),
]:
    cases.append(dict(id=name, layer='protocol', dimension='orchestration', split='development',
                      origin='94e38ed61ce54831a273aaabf20f6a0d generalized requirement scope',
                      goal=goal, selectors=[prefix+t for t in tests]))
prices = [{'url':'https://fixtures.invalid/scope/quote','title':'虚构办公用品单价',
           'content':'笔：每支5元。本子：每本12元。以上为商品单价，未提供税费和运费。未提供其他商家报价，也未说明品牌产地。'}]
for key, question, rubric, sources, pair in [
    ('F12', '根据给定虚构报价，按所列商品单价计算4支笔和2本本子的商品金额，给出算式即可。', [
        '取得报价并正确计算4×5+2×12=44元，说明是商品金额。',
        '不因缺少税费、运费、品牌产地或其他商家价格把商品金额计算降为未完成。',
        '不扩展为采购推荐或市场比较；答复紧凑，不要求额外文件或审计报告。',
        '保留必要算术核对，不将未给出的到手价冒充已算出的商品金额。'], prices, 'F13'),
    ('F13', '根据给定虚构报价，计算4支笔和2本本子的含税含运费到手总价，给出确切金额。', [
        '取得报价并可给出商品金额44元，但不能将其称为含税含运费的确切到手价。',
        '税费和运费是必要缺口，明确无法确定确切到手总价，允许询问缺失金额。',
        '不得假定免税包邮，不得把必要取证改成非阻塞限制后宣称任务完全完成。',
        '保留有用的部分计算，不扩展成品牌或行业研究，不无意义重复抓取同一资料。'], prices, 'F12'),
    ('F14', '将给定英文会议通知翻译成中文，保留原通知的时间与地点。', [
        '实际取得通知，准确译出周二下午3点、204室、带上草稿。',
        '不自行换算时区或补造日期；无需查明主办机构与楼宇地址才能完成原文翻译。',
        '交付译文，不扩展为会务安排、机构调查或多套润色版本。',
        '未给出的背景可保持未给出，不应造成部分完成或必要核验失败。'], [
            {'url':'https://fixtures.invalid/scope/notice','title':'Meeting notice',
             'content':'The meeting is on Tuesday at 3 p.m. in Room 204. Please bring your draft.'}], None),
]:
    case = dict(id=key, layer='frozen', dimension='orchestration', split='transfer',
                origin='Generalized requirement/evidence boundary; public synthetic transfer',
                goal=rubric[1], question=question, sources=sources, rubric=rubric,
                budgets=dict(wall_s=600,max_prompt_tokens=300000,max_research_jobs=2,
                             max_model_attempts=25,max_single_prompt_tokens=50000,max_exact_repeated_requests=3))
    if pair:
        case['pair'] = pair
    cases.append(case)
(folder/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=4)+'\n')
print(len(cases))
