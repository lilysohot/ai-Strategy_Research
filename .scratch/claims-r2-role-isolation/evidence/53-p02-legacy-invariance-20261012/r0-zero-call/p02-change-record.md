# P02 · 评分器匹配机制改造（Wave 0，零调用）

- 依据契约：`non-table-selected-target-scoring-contract-v4.1`（`sha256:c76ac13e…`，已签 2026-10-12）
- 授权：U 2026-10-12（默认 `ADJUDICATED`；同意改既有测试 14 处调用点）
- 设计说明（先于代码）：`evidence/50-p02-matcher-design-20261012/r0-zero-call/matcher-design.md`
- 落实的契约条款：`read_path.equivalence_judgement.scorer_contract`
  ——「评分器只消费裁定完成的映射，并校验其 role/source_id 合法性与 canonical_observed_fields 是否齐备；**身份相等不得作为匹配前提**」

## 一、改了什么

| 位置 | 改动 |
|---|---|
| `plugins/corpus/structured_scoring.py` | 新增 `MatchingMode`（`ADJUDICATED` 默认／`LEGACY_IDENTITY` 须显式）、`AdjudicatedMappingLike` 协议、`AdjudicationJudgement` 枚举；新增 `raw_mappings`／`validated_mappings` 参数 |
| 同上 | 匹配拆成 `_match_by_identity`（legacy，仅诊断/对照）与 `_match_by_adjudication`（只校验裁定，不二次判定） |
| 同上 | `RoleMetrics`/`OriginMetrics` 增 `correct_extra`；`precision = (tp + correct_extra) / (tp + correct_extra + fp)`（默认 0 时与原式 `tp/(tp+fp)` **恒等**）；`recall` 分母**不含** `correct_extra` |
| `plugins/corpus/adjudication_assembly.py` | `Judgement` 改为 `AdjudicationJudgement` 的别名 ⇒ 裁定词汇表**单一来源** |
| `tests/test_corpus_structured_scoring.py` | 既有 **14 处**调用点显式加 `matching_mode=MatchingMode.LEGACY_IDENTITY`（**只改调用点，断言一字未动**） |
| `tests/test_corpus_structured_scoring_adjudicated.py` | **新增** 20 项，覆盖 P02 退出判据 |

哈希：评分器 `172ce465…` → `50d1553e…`；装配器 `b7e426f3…` → `efd93be3…`；新增测试 `3b6fafc2…`。

## 二、裁定驱动路径的语义（`_match_by_adjudication`）

| judgement | 匹配 | 账本 |
|---|---|---|
| `matched` | 按 `gold_record_id`，**不比字段** | TP |
| `correct_extra` | 不匹配 | 计入 precision 分子；**不入** recall 分母 |
| `incorrect` | 不匹配 | FP |
| `duplicate` | 不匹配 | FP（并单记 `duplicate_fp`） |
| `unresolved` | — | **报错**（`unresolved_candidates_max = 0`） |
| `out_of_scope` | — | **报错**（须由装配器先滤掉） |
| 无 mapping | — | **报错**（不得回落身份相等） |

fail-closed 校验：mapped gold 必须存在；其 role/source 必须与候选一致；一个 gold 只能被匹配一次；mapping 行不得重复；`ADJUDICATED` 下 `mappings=None` 直接报错；`LEGACY_IDENTITY` 下不得传 mappings（两路不混用）。

## 三、退出判据结果

| 判据 | 结果 |
|---|---|
| 字段**完全不同**但映射正确 ⇒ TP（证明身份相等不是前提） | ✅ |
| 字段**完全相同**但判 `incorrect` ⇒ FP（证明字段相等不能自动匹配） | ✅ |
| `correct_extra` 进 precision 分子、不入 recall 分母 | ✅ |
| `duplicate` 计 FP；origin 切片同口径 | ✅ |
| 缺 mapping／gold 不存在／跨 role／跨 source／重复匹配／重复 mapping 行 ⇒ 全部报错 | ✅ |
| `ADJUDICATED` 无 mappings ⇒ 报错，不回落 | ✅ |
| **legacy（控制臂）四臂逐字段不变** | ✅ 见 `legacy-invariance.json` |
| P02 不动阈值（`PILOT_CANDIDATE_POLICY` 仍 0.95/0.90，属 P03） | ✅ |

**legacy 不变性**（复跑 `evidence/36` 四臂，不改历史脚本、`in_place_edits = 0`）：
A 原生 `tp 0 / fp 222 / fn 48`；B 金标注入 `tp 19`；C 路线 a 投影 `tp 0`；D/D2 `tp 0`；
比对 **12 个字段区**，`differing_sections = []`，`36/l9-redo.json` 字节未变（`acd268f2…`）。

## 四、向后兼容影响（**已声明，未处置**）

全仓另有 **3 个非测试脚本**调用 `score_structured_quality` 且未传 `matching_mode`，改造后**再跑会报错**（这是刻意的：身份相等不得是缺省）：

| 脚本 | 处置 |
|---|---|
| `evidence/10-quality-freeze-20261008-r1/run_quality_score.py:246` | 历史已执行脚本，**不改**；若需重跑，须在新目录/新版本中显式传 `LEGACY_IDENTITY` |
| `evidence/34-chain-root-cause-audit-20261011/r0-zero-call/audit_chain.py:327` | 同上 |
| `evidence/36-l9-redo-and-baseline-20261011/r0-zero-call/l9_redo.py:208` | 同上（本次不变性验证即通过"包装注入"完成，未改其字节） |

判为**可接受的破面**：三者都是已执行的历史证据脚本，其产物已冻结；P02 的默认值由 U 裁定，不能为了它们的可重跑性而把"身份相等"设回缺省（那正是契约禁止的）。

## 五、不宣称

- P02 **不产生任何门分数**。真实裁定数仍为 0（Stage 2 阻塞），裁定驱动路径在真实数据上尚无输入。
- P02 **不改阈值**（0.95/0.90 的硬编码仍在，属 P03）。
- P02 **不实现口径归一化**（属 P04/P05）；装配器只做契约 `caliber_rules` 已声明的 `auto_normalize` 两项。
- 本记录不改动任何既有产物；`evidence/36`、`evidence/10`、`evidence/34` 的字节一律未动。
