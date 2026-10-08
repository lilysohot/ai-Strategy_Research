# 15 · 同范围 r4 校验器修复复验

Status: blocked
Execution: 工业富联来源完成 26 次真实调用；Claims 出现一次 outcome_unknown，items 因一个错误槽位 ID 的全批拒绝及三个否定信号缺失而 failed；relations 未派生；按冻结停止条件未启动光模块，未形成可供三角色逐条裁定的完整候选名册
Type: task
Parent: [13 · 同范围 r3 有界真实复验](13-bounded-r3-trial.md)
Model calls: 26
Automatic retries: 0
Concurrency: 1
Production database access: 0

## 运行终态

- snapshot 与 24 单元范围未变；r4 使用 `material-semantics-21`、
  `material-items-validation-v4`。
- 工业富联 attempt 上限 37，实际 26；所有 items HTTP 请求返回，Claims 第 3 次请求为
  `outcome_unknown`，未自动或手工重发。
- Claims：`outcome_unknown / not_checked / review_required`。
- material items：`failed / not_checked / review_required`；生成 91 个已通过单条校验的 items，
  coverage 为 74 extracted、3 partial、1 failed。
- material relations：未派生，`CS_DEPENDENCY_NOT_READY`。
- 光模块：0 次调用，保持 prepared 状态。

## 失败根因

唯一 failed 槽的原文为 `**持有 + 观望。**`。模型返回的逐字引文正确，但把系统提供的
`candidate_slot_id` 抄成不存在的截断 ID；由于当前协议只对“省略 ID”做唯一引文回绑，对“错误
ID”保持 fail closed，因此该批触发 `all atomic items failed evidence validation`。

三个 partial 槽均为模型未保留必要否定 polarity：

- `不是 8 月能兑现的地板。`
- `高盛 121 是 IMA 标题，更不能当明天的价格。`
- `双供一旦发生，伤口不是……`

这是本轮真实输出，不通过修改工件或降低信号要求消除。Claims 的 outcome_unknown 也不能在没有
幂等恢复证据时补发同一请求。

## 为什么没有逐条裁定三角色

用户要求的裁定范围是相同 24 单元的 Claims/items/relations 完整候选。当前只有工业富联的部分
Claims/items；relations 没有候选，光模块没有执行。此时对可见子集做终态 precision/recall 会改变
分母并掩盖协议阻断，不能冒充完整逐条裁定。

r3 与 r4 原始响应、执行账和部分候选均完整保留，可作为失败诊断材料；没有发布、query、delivery
或 context_use。后续若继续，需要一个新版本同时解决：错误但可由唯一逐字引文无歧义回绑的槽位
ID、partial items 的合格端点子集 relations 派生，以及 provider outcome_unknown 的幂等恢复策略。
在这些规则冻结前，不再进行第三次真实重跑。
