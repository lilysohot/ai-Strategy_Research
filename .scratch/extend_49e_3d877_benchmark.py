import json
from pathlib import Path

p = Path('benchmarks/team_workflow/cases.json')
cases = json.loads(p.read_text())
assert len(cases) == 40
origin = '49e4f04b05ca46fda0ae4e4b71d1636a / 3d87700083864a1dbb41acfa74f46136 (minimal synthetic replay)'
probe = 'benchmarks/team_workflow/regression_probes.py::'
groups = [
    ('P34', 'verification', '无计算标记也必须校验已提交凭据；有效凭据与直接事实保持可通过', [
        'test_unmarked_calculation_receipt_is_still_validated',
        'test_valid_unmarked_receipt_and_direct_fact_remain_acceptable']),
    ('P35', 'verification', '必核事实在detail中承认为未知时不得整段PASS；完整覆盖和诚实未知为对照', [
        'test_admitted_required_unknown_cannot_hide_inside_pass_detail',
        'test_complete_coverage_and_honest_unknown_are_accepted']),
    ('P36', 'evidence', '另一文档的交易周不能填补表格缺失期间；同表完整期间为正向对照', [
        'test_cross_document_week_cannot_complete_unknown_table_period',
        'test_same_table_period_and_unknown_period_controls']),
    ('P37', 'recovery', '真实交付入口按替代检查结算义务；未替代、部分替代和未通过仍阻断', [
        'test_replacement_settles_obligations_not_historical_attempts']),
]
for key, dimension, goal, tests in groups:
    cases.append(dict(id=key, layer='protocol', dimension=dimension, split='development',
                      origin=origin, goal=goal, selectors=[probe+t for t in tests]))
cases.append(dict(id='P38', layer='protocol', dimension='observability', split='transfer',
                  origin=origin, goal='诊断区分并行耗时、未知遥测、单次上下文和调用预算；旧基线不变',
                  selectors=[
                      'tests/test_team_eval_regression_expansion.py::test_tool_timings_preserve_missing_and_parallel_durations',
                      'tests/test_team_eval_regression_expansion.py::test_optional_efficiency_budgets_fail_closed_without_changing_old_cases']))
budgets = dict(wall_s=600, max_prompt_tokens=600000, max_research_jobs=3,
               max_model_attempts=50, max_single_prompt_tokens=80000,
               max_exact_repeated_requests=6)
for key, complete in [('F08', False), ('F09', True)]:
    table = ('统计期间：2026-08-31至2026-09-04。\n' if complete else
             '残片未保留统计期间，不知道是哪一周。\n') + '| 指标 | 数值 | 单位 |\n| 日均成交额 | 120 | 亿元 |\n| 融资余额 | 240 | 亿元 |'
    quote = '2026-11-06：Lumen收盘110点。' + ('开盘105点。' if complete else '没有提供开盘价。')
    cases.append(dict(
        id=key, layer='frozen', dimension='verification', split='transfer' if complete else 'development',
        origin=origin, pair='F08' if complete else 'F09',
        goal='同一核验任务的完整证据正向对照' if complete else '缺表格期间及开盘价时不得认证整段；不得借其他报告补期间',
        question='请团队核查这段虚构行情草稿，独立核验后简短说明可保留与需修正的内容：2026-08-31至09-04交易周日均成交额120亿元、融资余额240亿元；2026-11-06 Lumen指数收盘110点、开盘105点。只使用给定材料，不开展额外行业研究。',
        sources=[dict(url='https://fixtures.invalid/period/table', title='资金表原文', content=table),
                 dict(url='https://fixtures.invalid/period/other', title='另一份指数周报', content='另一份报告：2026-08-31至2026-09-04交易周，Lumen指数收于100点。没有引用资金表。'),
                 dict(url='https://fixtures.invalid/period/quote', title='Lumen当日收盘记录', content=quote)],
        rubric=(
            ['资金表自身给出08-31至09-04期间，120亿元和240亿元均可确认，不得机械拒绝有充分证据的数字。',
             '11-06收盘110和开盘105均有来源，应明确确认两者。'] if complete else
            ['120和240虽在表体出现，期间未知，不得借另一报告的交易周认证资金数据；明确缺少什么。',
             '保留有证据的11-06收盘110，开盘105保持未知，不能说无冲突所以通过。']
        ) + ['实际进行独立核验；最终摘要、正文、核验标签对每个已知和未知项一致，不把局部PASS扩大成全段通过。',
             '完成有用的简短回答，不以反复修改措辞获取PASS，不扩展成产业研究或精确字数整理任务。'],
        budgets=dict(budgets)))
cases.append(dict(
    id='F10', layer='frozen', dimension='delivery', split='development', origin=origin,
    goal='证据缺口必须传到综合结论；有界检索与旧日期限制不得只留在附录',
    question='今天是2026-11-06。请团队仅用给定档案判断虚构Arbor与Birch两家工厂是否都已完成量产验证，独立核验后给简短结论。草稿写：两家全部通过，可确认整个扩产计划已经兑现；档案中没有11月资料。请核查并修正，不要另找行业资料。',
    sources=[
        dict(url='https://fixtures.invalid/factory/catalog', title='本次档案查询回执', content='这次查询只返回部分档案，不是全量目录。21份材料日期未知。检索截止2026-11-06。本次找到的具名验收文件日期为2026-09-06，未命中11月材料；不能推出所有档案或外部世界都没有11月材料。'),
        dict(url='https://fixtures.invalid/factory/arbor', title='Arbor验收记录', content='2026-09-06验收：Arbor日产100件、合格率99.8%，满足日产至少90件及合格率至少99.5%的门槛。未评估此后的持续生产。'),
        dict(url='https://fixtures.invalid/factory/birch-note', title='Birch研究笔记', content='研究笔记称Birch日产120件、合格率99.9%，但未附验收记录，数值未独立确认。'),
        dict(url='https://fixtures.invalid/factory/birch', title='Birch原始验收记录', status='unavailable', content='')],
    rubric=[
        '明确Arbor在9月6日达到给定门槛，但不扩大为11月持续达标。',
        'Birch没有可取得的原始验收记录，研究笔记不能代替独立核验；不得认定两家全部通过或整个计划已兑现。',
        '只能说本次未命中11月材料，不能说全库或外部世界没有；摘要与正文均保留此范围。',
        '团队独立核验后保留有用局部结论；免责声明不能为正文的无保留结论兜底。'],
    budgets=dict(budgets)))
p.write_text(json.dumps(cases,ensure_ascii=False,indent=4)+'\n')
