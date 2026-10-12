# 全链路重规划（含遗漏自检）

- 遗漏自检：**complete = True**（§7 未映射 0、§9 未映射 0、缺陷未映射 0、扫描命中未映射 0）
- 关键路径：`P10 → P11 → P01 → P02 → P03 → P04 → P27 → P29 → P30`

> 链路末端有两个无代码实现的缺环（P01 装配器、P02 匹配机制）：不修则『v4.1 补全 + 222 条裁定做完』仍然 0 分，并会把 0 分误归因为抽取质量。这两项零裁定、可立刻做，是本次重规划的起点。

## 遗漏自检机制

① 清单只在本文件声明一处，所有其它视图由它派生；② coverage_check 逐源核对（§7 全 14 行、§9 全 16 项、D1–D12、扫描命中），任何未映射即 complete=false；③ not_scanned 显式声明未覆盖范围，未核项不得被当作已闭合。

## 未覆盖范围（不得当作已闭合）

- U01 evidence/01–31 的内容未逐一核（仅按引用触及 10/28/32/33/34/35）
- U02 issues/01–31 的开放项未逐一核
- U03 benchmarks/ workflows/ plugins/ 全量未核（仅核评分器与契约相关文件）
- U04 并行会话在 44 号之后的产出未纳入（滚动纳入，不声称穷尽）
- U05 未核 holdout 与生产库（范围内禁止）

## Wave 0 · 零裁定·纯工程（可现在开始）

- 退出判据：P01/P02/P06/P08 全部产出且回归通过；P07 由 U 一句话决定

| ID | 事项 | 性质 | 责任 | 成本 | 依赖 | 来源 |
|---|---|---|---|---|---|---|
| P01 | 裁定→评分输入装配器（adjudications + 工作台 → raw/validated CandidateRecord） | code | agent | 零模型调用 | — | D3, §9-Stage2阻塞条款 |
| P02 | 评分器匹配机制改造（消费裁定映射，不再以 identity 相等为前提） | code | agent | 零模型调用 | P10 | D2, D12 |
| P06 | 签认护栏推广到其它生成脚本（默认拒绝覆盖已签认产物） | process | agent | 零调用 | — | D9 |
| P07 | 消编号歧义（两个 41：contract-v4-draft 与 items-chain-accounting） | process | U | 零调用 | — | D10 |
| P08 | 补齐或声明不补 MANIFEST（32/33/34/35 与 41-items-chain-accounting 的 r0） | audit | agent | 零调用 | — | scan-MANIFEST-missing |

## Wave 1 · 契约补全（需 U 签）

- 退出判据：v4.1 草案 diff 可核 + U 签认；并行那份标 superseded

| ID | 事项 | 性质 | 责任 | 成本 | 依赖 | 来源 |
|---|---|---|---|---|---|---|
| P10 | v4.1 合并草案：并入并行草案 18 条独有叶子（含 3 条核心读路径条款） | contract | agent | 零调用 | — | §9-v4.1, §5.13.1, D1, D4, D6 |
| P11 | v4.1 签认（取代两份 v4 并存的局面） | signoff | U | 人工 | P10 | §9-v4.1, D6 |

## Wave 2 · 记账与绑定（依赖 v4.1 哈希）

- 退出判据：绑定再绑定记录 + 门 28 基准推进 + 校验器落地

| ID | 事项 | 性质 | 责任 | 成本 | 依赖 | 来源 |
|---|---|---|---|---|---|---|
| P03 | 阈值单源落地：评分器读契约（OPEN-1=A 的兑现） | code | agent | 零模型调用 | P11 | D5, §7-6 |
| P04 | 口径归一化 + 读路径实现（caliber_rules / read_path） | code | agent | 零模型调用 | P11 | §7-7, §7-11 |
| P05 | 口径映射回归测试（防映射随数据/模型漂移） | code | agent | 零模型调用 | P04 | §7-7 A2 |
| P12 | 契约绑定再绑定 v2→v3→v4.1（金标 freeze-manifest） | audit | agent | 零调用 | P11 | D8, §5.3-记账4条, scan-parallel-freeze-rebinding-record |
| P13 | 门 28 metric_basis 推进至 v4.1，消除「权威源基准过期 + 阈值循环引用」 | contract | U | 零调用，须具名签认 | P11 | D7 |
| P14 | validation-report.human_accepted_counts 与 48/48 对齐 | audit | agent | 零调用 | P11 | §5.3-记账4条, scan-parallel-gold-acceptance-record |
| P15 | 采纳/否决并行提案 gate-32-v2-criteria.proposed.json（门 32 判据拆 G1/G2） | contract | U | 零调用 | — | §5.3-门32判据不同轴, scan-parallel-gate32-criteria |
| P16 | 冻结链校验器（任何契约/金标/manifest 修订须校验绑定一致） | code | agent | 零模型调用 | P11 | v4 bookkeeping_requirements |

## Wave 3 · 人工/授权（可并行）

- 退出判据：缺口 1 与缺口 2 各有数据；路线 a/b 可裁

| ID | 事项 | 性质 | 责任 | 成本 | 依赖 | 来源 |
|---|---|---|---|---|---|---|
| P18 | 缺口1：32 条区间「可救性」粗判抽样（不依赖 v4.1 细节） | human | xyl | 人工 | — | §9-32条抽样, §7-14, gap1 |
| P19 | 缺口2：route b 受控双臂实验（试跑 4 次 → 视结论决定全量 48） | authorized-call | U | 4~48 次模型调用 | — | §9-routeb实验授权, §7-13, gap2 |
| P20 | 补跑被传输事件丢掉的 1 个包（7 条 critical），含重试/幂等策略 | authorized-call | U | 1 次模型调用 + 新门 | — | §9-补跑授权, §7-2, I1 |
| P21 | 裁定 L6 两个我方信号槽（forecast / evidence） | contract | U | 零调用 | — | §9-L6两槽, §7-4 |
| P22 | 裁定 B-1 两条（NT-I06 / NT-I41）性质 | human | U | 零调用 | — | §9-B1两条, backlog B-1 |
| P23 | 跨角色范围裁定（claims 是否建读路径） | contract | U | 零调用 | — | §9-跨角色范围, §5.11 |
| P24 | 读路径普遍性三条硬要求：接受与否 | contract | U | 零调用 | — | §9-普遍性三条, §5.7 |
| P25 | Stage-1 助手 v2 是否采用为新裁定基线（取代 v1/v2 建议） | tool | U | 零调用 | — | §9-Stage1助手, §5.14 |
| P26 | 路线 a/b 最终裁定（凭缺口 1+2 的数据） | contract | U | 零调用 | P18, P19 | §9-接缝路线, §9-路线ab最终裁定 |

## Wave 4 · 执行出分

- 退出判据：Stage 2 全量裁定完成 → Stage 3 评分 → 门 33 判定

| ID | 事项 | 性质 | 责任 | 成本 | 依赖 | 来源 |
|---|---|---|---|---|---|---|
| P27 | Stage 2 全量 222 条裁定（含 source_stance 逐条按原文判定） | human | xyl | 222 条人工 | P11, P25 | §9-Stage2阻塞条款, unresolved_candidates_max=0 |
| P29 | Stage 3 严格评分（依赖装配器 + 匹配改造 + 阈值单源） | code | agent | 零模型调用 | P01, P02, P03, P04, P27 | D2, D3, D5 |
| P30 | 门 33 判定（出分或明确失败归因） | gate | U | 零调用 | P29, P20 | §6, §7-2 |

## Wave 5 · 收口

- 退出判据：报告 r9 闭项回填且签认

| ID | 事项 | 性质 | 责任 | 成本 | 依赖 | 来源 |
|---|---|---|---|---|---|---|
| P31 | 报告 r9 收口：闭项回填、§7/§9 去重与重排、签认栏 | doc | U | 零调用 | P30 | §7-编号乱序, §9-接缝路线重复两行 |

## Wave -1 · 已闭合（仅为审计保留）

- 退出判据：—

- `C01`、`C02`、`C03`、`C04`、`C05`、`C06`、`C07`、`C08`、`C09`、`C10`、`C11`

## 缺陷 → 计划项 映射（D1–D12）

| 缺陷 | 内容 |
|---|---|
| D1 | 已签 v4 缺 absent_required_fields.rule（缺字段不得直接判不匹配）→ P10 |
| D2 | 评分器只认字段逐字相等，不消费裁定 → P02 |
| D3 | 裁定→评分输入装配器不存在 → P01 |
| D4 | 已签 v4 缺 carrier_mapping.rule（只改字段名）→ P10 |
| D5 | OPEN-1=A 已签但评分器未改（阈值双源）→ P03 |
| D6 | 两份 v4 并存 → P10/P11 |
| D7 | 门 28 基准过期 + 阈值循环引用 → P13 |
| D8 | 金标冻结链契约绑定未再绑定 → P12 |
| D9 | 护栏只在单个脚本（部分闭合）→ P06 |
| D10 | 编号冲突（两个 41）→ P07 |
| D11 | 32/33/34/35 与 41-items-chain-accounting 的 r0 无 MANIFEST → P08 |
| D12 | 评分器 identity 匹配与契约 matching.mode 不相容（D2 的契约侧）→ P02/P10 |

## 与并行会话的关系

- 并行提案 `gate-32-v2-criteria.proposed.json`（门 32 判据拆 G1/G2）与`freeze-rebinding-record.json` / `gold-acceptance-record.json` 已纳入 P15/P12/P14，**须采纳或明确否决**，不得静默并存。
- 并行 `scoring-contract-v4.proposed.json` 由 P10 并入后标 `superseded_by`。
