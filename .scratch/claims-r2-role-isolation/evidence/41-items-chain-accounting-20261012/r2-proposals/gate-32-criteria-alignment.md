# 门 32 判据同轴化提案（待人工签认）

- 日期：2026-10-12
- 状态：**提案**。不修改门 32 既有冻结件与判定文件；签认后以新门版本记录，旧判据与判定留存可追溯。
- 依据：Issue 41（原编 36 号）`../r0-zero-call/accounting-checks.json` AC-8；`32-…/live/gate-decision.json`

## 1. 问题（机读事实）

同一份判定文件给出两个并列结论，且没有规定哪个代表本次执行结论：

```
verdict                          = structural_fail
root_cause_status                = eliminated（v6 0 次协议违规 vs v5 control 11 次）
criteria_unmet                   = [protocol_status_valid,
                                    failed_partial_invalid_duplicate_batches_max_0,
                                    completed_min, execution_status_succeeded]
protocol_status_valid.observed   = not_checked
protocol_status_valid.reason     = "the items task did not succeed, so protocol adjudication
                                    was not reached"
```

未满足的 4 项**都不是被测对象**：1 次与协议无关的 `TransportOutcomeUnknown`（md 7 槽）与
2 个我方信号过强槽（docx）即可让「协议修复」无法被确认。判据与被测对象不同轴。

## 2. 建议：把退出判据拆成两组，分别出结论

| 组 | 判据 | 归因对象 |
|---|---|---|
| **G1 · 被测对象确认（协议修复）** | ① control 臂 `unsupported JSONL record` 批次数 > 0（对照成立）；② treatment 臂同项 == 0；③ 校验器/匹配器未放宽（fail-closed 保持） | 仅协议与契约 |
| **G2 · 结构完备性** | attempts 实际==计划；无 429；无自动重试；failed+partial+invalid+duplicate == 0；每源 `completed_min`；`execution_status=succeeded`；`context_status=complete`；关闭思考的 `reasoning_tokens` 为 0 或缺失 | 基础设施 + 我方规则 + 协议 |

结论规则：

- **G1 的结论独立成立**，不因 G2 未满足而被否决；G1 通过即记 `protocol_fix_confirmed`（附两臂数字）。
- G2 未满足时记 `structural_incomplete`，并**逐项归因**：`infrastructure` / `our_rule` / `model`。
  归属按根因层判定（模型看不到或无接口=我方契约缺陷）。
- 最终放行仍要求 G1+G2 同时满足；但"协议是否修好"这一问必须能单独回答。

## 3. 附带的记法约束

- 判定文件不得只留一个 `verdict` 字段承载两个不同问题；至少分别给出 `gate_verdict`、
  `protocol_fix_confirmed`、`criteria_unmet`、`attribution`（本门已具备后两者，仅需拆结论）。
- `not_checked` 必须与其原因绑定出现（本门已具备），且不得被计入"未通过"而不加区分。

## 4. 不做

- 不改门 32 的阈值、授权四项、终态判定文本与既有哈希；
- 不因此放宽任何执行要求（G1+G2 同时满足才能放行，规则不变）；
- 不发布、不发起模型调用。

## 5. 待签认

- 签名人：　xyl　　　日期：20260-10-12
- 选项：☐ 采纳拆分判据并出 v2 门　☐ 维持现状（则协议修复无法单独确认）　☐ 退回修改
