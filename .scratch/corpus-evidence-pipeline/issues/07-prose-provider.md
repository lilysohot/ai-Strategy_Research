# 07 正文模型输出稳定性与真实抽取验收

Status: ready-for-agent
Execution: completed
Acceptance: targeted-prose-loop-passed — 未放行全库正文或宏观自动计算
Priority: P1
Blocked by: none

## Evidence

当前 glm-5.3-flash 端点在本轮正文调用中出现空内容、两次 60 秒超时，缩至 600 字证据包后仍未获得可接受完整响应，completion_tokens 达 4096。不能仅凭 token 用量断言都是 reasoning，现有适配器未保留 finish_reason/内容长度诊断。

## Acceptance

- 以不记录凭据/私密全文的方式保存 finish_reason、内容长度、reasoning token 用量（若供应商返回）、超时与响应 schema。
- 针对当前端点验证结构化输出能力和实际 thinking 参数，明确预算，不用无界增加 token 代替诊断。
- 不更改本轮冻结的 actual/consensus 目标，真实抽取达到 2/2 且引文、期间、主体可核验；再扩展未调参正文留出样本。
- 只有注册宏观指标与维度后才允许计算 surprise；实际/预期/前值分开，不能把不同 state 当成同一个事实。
- 修复通用 preflight 工作流 facade 失配并验证一次真实调用；不能用合成模型响应宣称供应商链路通过。

## Comments

2026-09-12：继续执行；已建立 SDK→抽取器的诊断回归，修复前 5 failed。先补诊断，固定原样本和预算，再对 reasoning_effort 做单变量验证。

本轮停止追加模型重试，保留失败版本；不更换账户或默认模型，不做全库重抽。

2026-09-12 后续执行完成：同模型/同输入/同 4096 输出预算，基线 4085 reasoning tokens、0 正文、length；单变量 low 后完整返回。再修复 raw 名称受控映射、空白引文精确回定位和无来源年份拒绝。原有两个目标修复后 4 次真实调用均 2/2；未调参天风留出 2/2（取值与缺年份负控，不是完整时间坐标的正例）。

新增 allowlist 诊断，无原文/推理内容/凭据日志；截断 `[]`、空响应、非法数组元素/记录不再成为空成功。GLM-5.3 系列仅在 corpus 批处理默认 low，未改全局模型或工作流推理配置。通用 preflight 入口已修复并通过真实调用。168 项 corpus 测试通过，详见 [修复验收报告](../prose-repair-report.md)。
