# D1 同花顺数据契约与精确调用证据

Status: needs-info
Execution: not-started — new-government-data-contract-pending
Requirements: PR-DATA-03, PR-DATA-06, PR-DATA-11, PR-DATA-12

## 交付与验收

- 复用既有行情/历史/财务实现，核对用户提供的同花顺接口是否相同，以及实际政府宏观能力。
- 确认所需端点、合法权限、字段、单位、统计期间、发布时间、版本/修订与行情时点；不输出密钥。
- 精确绑定本 Run 的逻辑调用、参数、原始响应及取回时点，不以同标的历史任意记录代替本次调用。
- 新端点先做单样本实测；既有代码或历史 API 文档不能替代当前权限、实时性及数据覆盖验收。
- 无权限、超时和缺少历史版本分别记录，不用研报数字补位，不回爬 BLS 作为默认替代。
- 本任务的信息依赖不阻塞 R1—R3；没有授权不购买、安装插件或提交外部请求订阅。

## CLI 优先补充（2026-09-14）

- 按 [实施计划](../../../docs/plan/r2-local-redesign-cli-closure-plan.md) P7 复用既有市场实现；本计划未启动真实请求。
- 精确关联 CLI execution、session、逻辑调用、provider request 与 retry attempt；聚合结果保留所有输入调用引用。
- 现有 trace resolver 解析 request_id 后未按其过滤；必须补跨 Run、错误调用 ID、同标的旧记录负控，不能只查数字是否出现。
- 与 R2 私有重设计分开评审市场模块修改范围和预算；政府统计契约待确认不影响材料分支。
