# 13 · 同范围 r3 有界真实复验

Status: stopped
Execution: 已冻结并启动同一 24 单元 r3；工业富联来源完成 26 次真实调用后，Claims 有效、items 因 5/78 槽位 partial 而协议无效，relations 正确阻断；按失败停止条件未启动光模块来源；原运行完整保留
Type: task
Parent: [12 · r3 抽取质量修复与冻结](12-r3-quality-remediation.md)
Model calls: 26
Automatic retries: 0
Concurrency: 1
Production database access: 0

## 冻结范围

- 与 r2 相同 snapshot：工业富联 `sha256:d654...c055`；光模块 `sha256:7d8f...a7195`。
- 同一 24 个非表格单元与同一签认金标；未把金标暴露给模型。
- r3 总 attempt 上限 86；工业富联上限 37，实际 26；光模块实际 0。
- 配置 `openai_compat / doubao-seed-2.0-mini`，并发 1，自动重试 0。

## 工业富联终态

- Claims：`succeeded / valid / review_required`，9 次调用。
- material items：`succeeded / invalid / review_required`，17 次调用；产出 92 个通过单条校验的
  items，78 个槽中 73 extracted、5 partial。
- relations：未派生，原因 `CS_DEPENDENCY_NOT_READY`。
- 全部 26 次 HTTP 调用成功，无重试；费用字段未返回，记 26 个 unknown-cost calls。

5 个 partial 的根因经只读审计确认：

1. 两槽是 evidence 信号假阳性：“不因为……”与句首“所以……”实际是 claim。
2. `quoted_other` 合法记录使用 `speaker_ref=null`，被过早字段校验拒绝。
3. Markdown 强调句的句号切槽漏掉闭合 `**`，使逐字引文跨槽。
4. 同槽已有两个合法 item 时，一个带多余句号的失败候选使整槽降为 partial。

上述均为确定性验证/边界规则，不是重发可解决的问题。r3 账本和工件不修改、不补发、不筛选。

## 后续修复

四个根因先各加一个红测，修复后均转绿；受影响测试现为 `122 passed`，Ruff 与 Pyright 通过。
新实现版本为 `material-semantics-21`、`material-items-validation-v4`，冻结在
[14-r4-validator-remediation-freeze-20261008](../evidence/14-r4-validator-remediation-freeze-20261008/freeze-manifest.json)。
下一次真实执行必须使用新 run ID，不得冒充 r3 续跑。
