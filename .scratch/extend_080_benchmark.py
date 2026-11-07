import json
from pathlib import Path

p = Path('benchmarks/team_workflow/cases.json')
cases = json.loads(p.read_text())
new = [
    ('P30', 'verification', '计算标注不能豁免基准、来源引用与算术复算；持久化判定一致',
     'tests/test_team_080_regressions.py -k calculation'),
    ('P31', 'context', '重复背景之后的结果表与分离的结果段完整送达，保留表头及精确片段位置',
     'tests/test_team_080_regressions.py -k "table or narrative"'),
    ('P32', 'orchestration', '同证据仅一次措辞修正，已有判定不得原样重投，新工具证据可解锁复核',
     'tests/test_team_080_regressions.py -k "recheck or retry"'),
    ('P33', 'orchestration', '独立核验真实并行启动；忙碌核验会话不能串行堆积新检查',
     'tests/test_team_080_regressions.py::test_independent_checks_run_concurrently_without_queueing'),
]
for id_, dimension, goal, selector in new:
    assert not any(c['id'] == id_ for c in cases)
    cases.append(dict(id=id_, layer='protocol', dimension=dimension, split='development',
        origin='080ad8521962429a814171f48ffc7f60 / bf9d5de507b54b519173c08c1746cb71',
        goal=goal, selector=selector))
cases.append({
    'id': 'F07', 'layer': 'frozen', 'dimension': 'verification', 'split': 'development',
    'origin': '080ad8521962429a814171f48ffc7f60 (synthetic adaptation)',
    'goal': '有输入的前一日收盘可计算，缺少基准的前一日涨幅必须保持未知；独立检查可并行',
    'question': '请团队分别核查虚构 Lumen 指数的行情和议会席位，独立核验后给出简短结论。草稿称：11月4日收盘100点且单日上涨2.16%，两者标为[计算]；选后Lyra有52席、Orion有44席。只用给定资料，不补做历史统计；缺失的输入请明确指出。',
    'sources': [
        {'url': 'https://fixtures.invalid/lumen/market', 'title': 'Lumen 行情表',
         'content': '2026-11-05 收盘110点，当日上涨10点。没有提供2026-11-03收盘或2026-11-04涨幅。'},
        {'url': 'https://fixtures.invalid/lumen/results', 'title': 'Lumen 席位结果',
         'content': '更新2026-11-05。本次选后结果已公布。\n' +
             '选前背景：Lyra 45席、Orion 53席、独立议员2席。\n' * 55 +
             '\n| 党派 | 选前 | 选后 |\n| Lyra | 45 | 52 |\n| Orion | 53 | 44 |\n| 独立 | 2 | 2 |\n| 未确定 | 0 | 2 |\n'},
    ],
    'rubric': [
        '11月4日收盘=110-10=100点，可保留明确计算过程；不得因缺涨幅基准而丢弃这个有效结论。',
        '11月4日涨幅需要11月3日收盘，资料没有提供。不得保留2.16%为可验证计算值，或倒推一个基准证明2.16%。',
        '选后Lyra52、Orion44，另2名独立及2席未确定；核验须看到结果表而非只复述研究报告或检查总数100。',
        '实际完成团队研究与独立核验；独立检查可并行，不能靠反复改标签取得PASS；保留缺失项并给出有效局部结论。',
    ],
    'budgets': {'wall_s': 600, 'max_prompt_tokens': 600000, 'max_research_jobs': 3},
})
p.write_text(json.dumps(cases, ensure_ascii=False, indent=4) + '\n')
