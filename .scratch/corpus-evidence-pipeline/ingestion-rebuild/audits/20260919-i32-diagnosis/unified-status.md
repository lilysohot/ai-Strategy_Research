# I3-2 统一状态表（步骤 1，2026-09-19）

| # | 冻结项 | 状态 | 证据 | 缺口/下一步 |
|---|---|---|---|---|
| 1 | source gold | ✅ 冻结（r26） | `source-gold-frozen.jsonl` `37662c77…`；负例库 `0fc9dac3…` | — |
| 2 | query gold（审批原件） | ✅ 冻结（r26） | `query-gold-frozen.jsonl` `6f6c5a25…`；门 ready=true | 不改动（保留审批证据） |
| 2b | **正式评分输入** | ✅ 已派生（待冻结 r27） | `i3-2/query-gold-scoring-v1.jsonl` `1b018ceb…` + `i3-2/scoring-input-manifest.json`；自校验 0 错、6 条变异反例各自失败、与 P1 逐字节一致、评分器接受 | 随 r27 绑定 + U 签认 |
| 3 | 阈值（policy） | ✅ 已确认（记于 P2） | 默认 5 项；`p2/policy-and-lists-confirmation.json` | 随 r27 记录；运行时显式构造 policy |
| 4 | 关键题 | ✅ 已确认（记于 P2） | 28/30；清单哈希已记 | 同 I3-2-4 的语义风险保留 |
| 5 | 负例 | ✅ 已确认（记于 P2） | 6 道全 critical；误报上限 0 | — |
| 6 | 旧基线映射 | ✅ 范围已确认（U 2026-09-19） | `baseline-case-manifest.json`（19 旧检索题含 O6 排除 + 57 字段 + 7 公式已枚举） | 见清单 blocked_items（tout 12 格材料、第 3 条正文用例、宏观身份） |
| 7 | 评分器冻结 | ✅ 无缺口 | `plugins/corpus/scoring.py` `bf9c8b80…`（r19/r21） | — |
| 8 | 试验初始版本 | ⚠️ 草稿（待唯一化） | `p4/experiment-initial-version.json`；本轮已把评分输入唯一化 | 待步骤 4：唯一 manifest + 阶段完成门 |

## 两处旧记录的更正（诊断文档第 29—32 行）

- **更正 1**：`inventory.md/json` 里『阈值未确认、试验初始版本无产物』已落后——P2 已确认阈值/清单，P4 已建清单草稿；本轮状态表以 P2/P4 为准。
- **更正 2**：『30 题全部因缺 targets 不能评分』不准确——缺 targets 阻断的是 **24 道有答案题**；6 道负例按 `_evidence_required(no_answer)=False` 本就不需要 targets。

## 本轮新增/变更文件

| 文件 | 性质 |
|---|---|
| `i3s2_scoring_input.py`（新） | 正式评分输入派生器 + 自校验 + 变异反例 + 唯一读入口 |
| `i3-2/query-gold-scoring-v1.jsonl`（新） | 正式派生评分输入（不改审批原件） |
| `i3-2/scoring-input-manifest.json`（新） | 派生 lineage 清单 |
| `audits/20260919-i32-diagnosis/baseline-case-manifest.{json,md}`（新） | 步骤 3 用例清单 |
| `audits/20260918-i32-remaining-inventory/inventory.{md,json}` | 更正两处旧表述 |

