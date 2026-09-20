# P1 材料化逐题校验报告（草稿，未落正式）

- 输入：`query-gold-frozen.jsonl` `6f6c5a25d55b…`、投影 `5b89d981e871…`、`source-gold-frozen.jsonl` `37662c77a76c…`
- 汇总：有答案 24 题 / 负例 6 题；必需 79 条 + 补充 20 条
- 评分器 `gold_from_records` 干跑：**ok**
- **逐条回验全过**（quote/source_id/locator 与 source-gold 一致、题内 target_id 唯一）

| query_id | 存在性 | 必需 | 补充 | 逐条回验 |
|---|---|---|---|---|
| company-001 | answerable | 2 | 4 | 全过 |
| company-002 | answerable | 3 | 0 | 全过 |
| company-003 | answerable | 6 | 1 | 全过 |
| company-004 | answerable | 3 | 1 | 全过 |
| company-005 | answerable | 2 | 3 | 全过 |
| company-006 | answerable | 3 | 0 | 全过 |
| company-007 | answerable | 1 | 1 | 全过 |
| company-008 | answerable | 5 | 0 | 全过 |
| company-009 | no_answer | 0 | 0 | — |
| company-010 | no_answer | 0 | 0 | — |
| industry-001 | answerable | 5 | 2 | 全过 |
| industry-002 | answerable | 4 | 0 | 全过 |
| industry-003 | answerable | 3 | 1 | 全过 |
| industry-004 | answerable | 2 | 0 | 全过 |
| industry-005 | answerable | 2 | 0 | 全过 |
| industry-006 | answerable | 3 | 0 | 全过 |
| industry-007 | answerable | 3 | 1 | 全过 |
| industry-008 | answerable | 5 | 1 | 全过 |
| industry-009 | no_answer | 0 | 0 | — |
| industry-010 | no_answer | 0 | 0 | — |
| macro-001 | answerable | 3 | 1 | 全过 |
| macro-002 | answerable | 3 | 2 | 全过 |
| macro-003 | answerable | 4 | 1 | 全过 |
| macro-004 | answerable | 6 | 0 | 全过 |
| macro-005 | answerable | 2 | 1 | 全过 |
| macro-006 | answerable | 3 | 0 | 全过 |
| macro-007 | answerable | 3 | 0 | 全过 |
| macro-008 | answerable | 3 | 0 | 全过 |
| macro-009 | no_answer | 0 | 0 | — |
| macro-010 | no_answer | 0 | 0 | — |

> 目标明细（target_id / role / source-gold 引用 / 是否一致）见 `materialization-report.json`。
