# 06 负例误报 6→0（M6 硬判据）

Status: completed（2026-09-21，U 二次复核立项 + `audits/20260921-f1-negative/` 交付）
Type: task
Depends: 无（独立，可并行启动、第一资源）
Layer: 判定层（scoring/拒检）> 检索词元
Bound-byte impact: **待定**（若只沉淀判定层，不触 `scoring.py` 字节则否；若改检索词元路径则涉及 `search_pg.py`）
Reingest: 否（纯消费侧判定，不需重摄入）

## 问题

M6 判据 `max_false_positives = 0`（`plugins/corpus/scoring.py:279`）为硬阻断。6 条 **no-answer** 题（`company/industry/macro-009/-010`）历轮（i33→i42 五轮）均为误报，是唯一零进展项（spec §6.0/§10.5/§14.4 判断 4）。

6 条走同一 OR 词元检索路径，各命中 5 篇候选文档，但命题为"是否给出 X"，预期应 0 命中。证据：`i41/negative-cases.json`（`retrieved_documents: 5`）。

## 根因

no-answer 题**单 token 命中即拉回候选文档**，而 FP 判定只取决于"是否有文档被检索"。例：
- "2027 年全年的氩气实际成交均价" → 命中任意含"2027/均价"的文档；
- "美联储 2026 年 9 月议息会议最终利率决定" → 命中非农点评等无关宏观。

判定侧看不到"命中的 token 是否构成实质答案"，只看"有文档"即计误报。

## 改动面（候选，二选一为主导）

1. **判定层拒检兜底（优先）**：在 `score()`/观测构造处，对 `answer_existence = none` 的题，要求命中须满足"多词元共现 / key 实体 + 限定词组合命中阈值"才构成候选；不满足即判 `NO_MATCH`/拒检。**优先于此项**——只动消费侧，不扰动有答案题 S1_candidates=66。
2. 检索词元路径收紧：对 no-answer 句收窄 OR 词元（短语化 / 提高命中阈值）。**仅当①无法完整兜住 6 题时补做**，且须回测有答案题 79 目标漏斗逐字节不回退。

## 不变量与反例

- **I-M6-1**：任一被裁 `answer_existence = none` 的题，`retrieved_documents == 0`。
- **I-M6-2（不扰动）**：有答案题 79 目标漏斗（spec §13.1）`S1_candidates` 恒 66 不降。
- 反例：构造"expected=0 但单个低频 token 命中"的伪负例，断言拒检生效。

## 验收

1. 6 题 `retrieved_documents` 0 且历轮（含后续 band/cell）不回升。
2. **每题固化 FP 归因表**（token → 命中块）入 `audits/<日期>-f1-negative/`，作为独立证据。
3. `max_false_positives = 0` 通过。
4. 有答案题 79 目标漏斗逐字节不回退。

## 冻结影响

若判定层为纯消费侧新增，不触 `scoring.py` 现有字节 → 不新增冻结修订；若动检索词元路径则随相关能力改动合并冻结（不单独立修订）。

## 不做

- 不改 6 题的金标与"期望 0"语义（它们本就该 0）。
- 不降低 `max_false_positives` 门槛。
- 不在本票提升任何有答案题 EvidencePass（那是 F2 的事）。