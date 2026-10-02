# 08 · 证据消费账、报告清单与 A4 校验适配

Status: needs-triage
Execution: 未开始
Type: task
Plan: W5 前置接线；R2-S2/S3
Blocked by: 07
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

把新查询实际送达的原文证据纳入现有 ConsumptionLedger、corpus_submit_manifest 和最终报告检查，不平行建设报告校验系统。

## 前置与外部门

07 已验收，01 的报告引用/依赖表示已冻结；复用现有 50 项消费账/清单测试作为回归，不把它们当本票新功能已通过的证据。

## 范围与预期文件

- plugins/corpus/ledger.py、plugins/tools/corpus_manifest.py、必要的 workflow 发布调用接缝。
- tests/test_corpus_structured_consumption.py；扩展 test_corpus_ledger.py、test_corpus_manifest_tool.py。
- 新查询活动登记、实际消息送达、语义记录/发布版本和原文范围桥接、伴随清单绑定；报告侧桥接遵守
  `contracts/v1/report-semantic-reference.schema.json`。
- 报告依赖作用 value/period/unit/header/footnote 等与 cite/compare/calculate 许可分开；条件/否定/归属按 01 的受控表示校验。

## 验收条件

- [ ] 不伪造 corpus_fetch 事件；只记录真实工具调用与原文范围，抽取成功、记录 ID 或后台 resolver 读取不等于 delivered。
- [ ] pending 经实际消息确认后才能变 delivered；裁剪/压缩/缺必要片段不能被已发布状态掩盖。
- [ ] 仅新查询活动也绑定清单工具并进入 A4 检查，不因 offered/fetched 旧条件而 skip。
- [ ] 报告清单绑定 report_quote、原文多段引用及语义版本；重复引文用精确区间，不按首次命中认定证据已送达。
- [ ] 后端仍核对权威原文、引用和报告锚点，并只读检查语义撤回/用途/依赖有效性；不要求 Agent 例行重读原文。
- [ ] semantic publication manifest 不能当 report evidence manifest，执行账不能替消费账；原文路径旧报告清单保持兼容。
- [ ] 正例 verified；错误句柄、未送达、依赖缺失、撤回和基础设施故障得到真实错误/降级，observe/skip 不冒充过门。
- [ ] 保持现有全局 A4 默认观测策略，分别测试 observe/enforce，不借适配修改全局产品阻断策略。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_consumption.py tests/test_corpus_ledger.py tests/test_corpus_manifest_tool.py -q
uv run ruff check plugins/corpus/ledger.py plugins/tools/corpus_manifest.py tests/test_corpus_structured_consumption.py
```

resolver 用明确的同版本合成原文 Adapter；不得为通过测试跳过逐字核验、消息送达或 report_quote 检查。

## 非目标

不新增模型裁判，不把确定性 A4 成功当报告语义绝对正确，不修订历史报告或放宽普通 search snippet 引用限制。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
