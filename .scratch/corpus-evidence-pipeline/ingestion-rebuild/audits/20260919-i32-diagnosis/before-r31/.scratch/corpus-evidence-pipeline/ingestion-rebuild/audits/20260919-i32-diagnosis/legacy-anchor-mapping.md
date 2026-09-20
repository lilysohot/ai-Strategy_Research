# 旧检索 golden：旧锚点 → 新 source 身份映射（首轮，待人工确认）

- **收口（2026-09-19T21:30:00+08:00，U 授权）**：19 题锚点按**确定性规则**复核关闭（归一化标题子串唯一命中 + 来源路径在磁盘 + 5 个 doc_id 与已标注 source-gold 同源）；复核 22 个锚点、失败 0 个。
- 生成：2026-09-19T17:58:23+08:00；状态：**first_pass_pending_human_confirm**
- 输入：`golden.py` `e983b3914be4…`；`i0a5-doclist-recount-20260915.json` `d98b0517ccbf…`
- 规则：旧锚点 (title_contains, doc_prefix) → 旧文档目录 i0a5-doclist 的 doc_id（`YYYY-MM-DD_<8hex>`，即新体系的 source 身份）；先做归一化标题子串匹配，失败退回最长 CJK/数字 token 命中；多候选/零候选一律标 ambiguous/unmatched 且 confirmed=false
- 计数：{"resolved_unique": 19, "excluded_holdout": 1}（O6 留出排除）

| 题 | kind | 锚点 | 匹配依据 | 结论 | 文档 |
|---|---|---|---|---|---|
| N1 | 数字 | `字节获296亿美元银团贷款`（prefix=—） | title_substring | resolved_unique | 2026-09-06_a91d95c7 |
| N2 | 数字 | `figure斥35亿美元加码helix算力`（prefix=—） | title_substring | resolved_unique | 2026-09-06_0c25f0e9 |
| N3 | 数字 | `3600亿增资银行保险`（prefix=—） | title_substring | resolved_unique | 2026-09-07_1e021a8c |
| N4 | 数字 | `电子特气涨幅超24`（prefix=—） | title_substring | resolved_unique | 2026-09-06_f8e31696 |
| N5 | 数字 | `焦煤期货收盘价周内下跌3-64`（prefix=—） | title_substring | resolved_unique | 2026-09-06_c1ddcd8a |
| N6 | 数字 | `长江证券-化工专题`（prefix=—） | title_substring | resolved_unique | 2026-08-13_174b6462 |
| N7 | 数字 | `国信证券`（prefix=2026-08-17） | title_substring | resolved_unique | 2026-08-17_c195233b |
| N8 | 数字 | `光力科技`（prefix=—） | title_substring | resolved_unique | 2026-09-06_dddc7cd0 |
| O1 | 观点 | `华创证券`（prefix=2026-08-16） | title_substring | resolved_unique | 2026-08-16_6f14cc14 |
| O2 | 观点 | `jpmorgan`（prefix=—） | title_substring | resolved_unique | 2026-08-16_7d3ca3b9 |
| O3 | 观点 | `ai-pcb及半导体设备迎来布局良机`（prefix=—） | title_substring | resolved_unique | 2026-09-06_00f08e66 |
| O4 | 观点 | `看好供给约束型周期品`（prefix=—） | title_substring | resolved_unique | 2026-09-06_d01c64bf |
| O5 | 观点 | `钽价有望启动上行`（prefix=—） | title_substring | resolved_unique | 2026-09-06_428e7222 |
| O6 | 观点 | — | — | **留出排除** | — |
| C1 | 对比 | `华创证券`（prefix=2026-08-16） | title_substring | resolved_unique | 2026-08-16_6f14cc14 |
| C1 | 对比 | `国信证券`（prefix=2026-08-17） | title_substring | resolved_unique | 2026-08-17_c195233b |
| C2 | 对比 | `gpt-6-astra-fable-5-1正式发布`（prefix=—） | title_substring | resolved_unique | 2026-09-06_987d9f69 |
| C2 | 对比 | `gpt-6-astra发布`（prefix=—） | title_substring | resolved_unique | 2026-09-07_acbf026c |
| C3 | 对比 | `2026年8月美国非农数据点评`（prefix=—） | title_substring | resolved_unique | 2026-09-06_793b3967 |
| C3 | 对比 | `非农大超预期`（prefix=—） | title_substring | resolved_unique | 2026-09-06_f7f65d7e |
| T1 | 时效 | `James-Bulltard_9826`（prefix=2026-09-08） | title_substring | resolved_unique | 2026-09-08_bc0309f3 |
| T2 | 时效 | `全球流动性观察`（prefix=2026-09-08） | title_substring | resolved_unique | 2026-09-08_77b352bf |
| T3 | 时效 | `白银矿股`（prefix=2026-09-07） | title_substring | resolved_unique | 2026-09-07_5c5fce92 |

## 公式输入字段（来自 `plugins/corpus/derivation.py`）

- `revenue_growth` ← revenue、revenue
- `parent_profit_growth` ← parent_net_profit、parent_net_profit
- `operating_cash_growth` ← operating_cash_flow、operating_cash_flow
- `cash_profit_ratio` ← operating_cash_flow、parent_net_profit
- `net_margin` ← net_profit、revenue
- `balance_residual` ← assets、liabilities、equity
- `profit_residual` ← net_profit、parent_net_profit、minority_profit

## 待人工确认

- 无（全部唯一命中）
