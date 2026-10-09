# 补数回答字段集与无快照续接修复（2026-10-09）

发起：用户实测报告。截图证据：补数弹窗"保存并继续分析"返回

```json
{"error":{"code":"unknown_field_rejected","message":"回答包含未请求的字段",
 "fields":{"plan.risk_budget_value":"请只回答本次待补字段","plan.target_profit_unit":"…",
 "plan.risk_budget_unit":"…","plan.target_profit_value":"…"},
 "current":{},"retryable":false,"remedy":"fix_fields"}}
```

"服务端标记的待补字段"为 8 项：`account.as_of`、`account.capital_basis`、`account.currency`、
`account.total_capital`、`plan.allocated_capital`、`plan.direction`、`plan.market`、`plan.symbol`。

依据文档（不改其口径，只按它们判定）：

- `docs/design/web-business-data-prd.md` v0.7 §4.2（2026-10-08 裁决）、AC-29、AC-30；
- `docs/design/web-business-data-contract.md` §2（错误信封）、§8（补数请求与回答）；
- `.scratch/web-business-session-plan/spec.md`（本批上游冻结口径）与
  `issues/04-agent-input-request.md`（已登记的缺口 3：无主账户引导语未实现）。

## 判定（根因层）

**我方缺陷**，不是模型行为。worker 只表达缺料意图（方案 A）合规；错在

1. 回答端点额外要求"只能回答本次请求列举的字段"，与 AC-30 "弹窗三项（规划资金/承受风险/
   期望盈利）一次收集并持久保存"直接冲突 —— 后两项依 `evaluate_purpose` 不是必需字段，
   于是整条回答被拒（截图里的 400）。
2. 无快照续接（研究还没有账户/计划）把续接里的对象引用冻结成 `null`、并且不记录当时版本；
   用户按引导补齐账户/计划后回答仍撞"保存资料需要明确的目标对象"/"回答缺少资料版本"。
3. 前端只认 FastAPI 的 `detail`，业务信封 `{"error":{...}}` 被当成整段 JSON 文本展示，
   字段级原因反而看不到。
4. 专用补数弹窗对**任何** pending 请求都自动弹出，而它只能采集/申报固定几个字段；字段集
   不匹配时用户会永远停在"仍有待澄清项"。

## 修复口径（已实现）

- 回答只受"业务契约"约束：契约外字段仍 `unknown_field_rejected`（负例覆盖）；契约内、未被
  本次请求列举的字段允许随回答落库（AC-30 的"可后补"项）。
- 无快照续接在回答时按研究**当前绑定**补全 `null` 引用（锁下读当前版本），并在续接里记录
  当时版本（`known_versions`），使回答有可比版本。
- 前端解包业务错误信封；补数弹窗只对"它采集得全"的字段集自动打开，其余留在补数中心。

## 退出判据（预注册）

1. `tests/pg/test_input_request_field_scope.py` 4 项通过（含 1 项负例），且 `tests/pg` 全套回归通过
   ——**需 PG 环境**（本机无 PostgreSQL，见下）。
2. 仓库门禁：Ruff、Pyright（本批文件 0 错误）、`git diff --check`、import smoke stage 1、
   symbol closure。
3. 前端：单测 + `vue-tsc --noEmit` + 生产构建通过。
4. 证据脱敏存入 `evidence/`；未通过项登记为缺口，不放行。
5. 完成与否由独立复核 + 用户具名签认，实施方不自宣。

## 范围外 / 待裁决

- **口径变更需签认**：回答端点的字段范围由"本次请求列举"放宽为"业务契约内"。这是修掉 400 的
  前提；契约 §8 未规定该限制，AC-30 要求放宽，但仍是行为变更。
- **产品口径待裁决**：研究还没有主计划时，`plan.symbol/market/direction` 无人可采集（PRD §4.1
  规定计划从"会话计划"入口创建），弹窗走不完、补数中心会如实报"请先选择或创建资料对象"。
  是否在弹窗内联创建计划，需要用户裁决。
- 无浏览器/端到端验收（本批只做单测 + 类型检查 + 构建）。
- 未部署 API、未迁移生产库、未改生产数据。
