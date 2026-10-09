/**
 * 补数请求 ↔ 结构化补数弹窗（`BusinessInputRequestDialog`）的适配判定。
 *
 * 弹窗是**固定表单**：主账户资金（只读）+ 本标的规划资金（必需）+ 承受风险/期望盈利
 * （可后补）。它只能采集并申报自己那几个字段；而补数请求的字段集由服务端按用途裁决
 * （`evaluate_purpose`），还可能包含弹窗根本不采集的字段（`plan.symbol`、`plan.market`、
 * `plan.direction` 等）。
 *
 * 回答必须覆盖请求的全部字段才续接，所以字段集不匹配时自动弹窗只会把用户送进
 * "仍有待澄清项：请补齐后用同一条请求重试"的死循环——2026-10-09 实测：研究还没有
 * 账户/计划时，worker 意图落库出的请求含 8 个字段，弹窗里怎么填都走不完。
 * 这类请求应留在补数中心（`BusinessRequestCenter` 按 `request.fields` 逐项渲染）。
 */

/** 弹窗采集、并会在回答里申报的计划字段。 */
export const DIALOG_PLAN_FIELDS: readonly string[] = [
  'plan.allocated_capital',
  'plan.risk_budget_value',
  'plan.risk_budget_unit',
  'plan.target_profit_value',
  'plan.target_profit_unit',
]

/** 弹窗内联创建主账户时会一并申报的账户事实。 */
export const DIALOG_ACCOUNT_FIELDS: readonly string[] = [
  'account.total_capital',
  'account.available_capital',
  'account.currency',
  'account.capital_basis',
  'account.as_of',
]

/**
 * 该请求能否只靠补数弹窗走完。
 *
 * `accountBound` 为真表示研究已绑定主账户：此时弹窗只读展示账户资金，不会、也不该再
 * 申报账户事实，因此账户字段必须交给补数中心。没有缺失项时返回 false——循环补数请求
 * 交给补数中心处理，不弹这个一次性采集窗。
 */
export function dialogCoversRequest(
  remaining: readonly string[],
  { accountBound }: { accountBound: boolean },
): boolean {
  if (!remaining.length) return false
  const coverable = new Set<string>(DIALOG_PLAN_FIELDS)
  if (!accountBound) {
    for (const name of DIALOG_ACCOUNT_FIELDS) coverable.add(name)
  }
  return remaining.every((name) => coverable.has(name))
}
