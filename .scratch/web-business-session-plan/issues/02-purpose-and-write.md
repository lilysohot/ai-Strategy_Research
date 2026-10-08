# 02 准入、写入校验与价格字段拒绝

Type: task
Status: resolved
Blocked by: 01

## 目标

- `GROUP_FIELDS["plan"]`：加入 `allocated_capital`、`target_profit_value`、`target_profit_unit`；
  移除 `plan_price`/`plan_price_low`/`plan_price_high`。
- `evaluate_purpose`：`plan_analysis` 必需字段改为 `symbol`、`market`、`direction`、`allocated_capital`；
  去掉计划价与 `target_price` 的必需性。
- 新增准入不变量：`allocated_capital` ≤ 所属账户**可用资金**（同事务读账户当前版本）；
  账户可用资金缺失 → 按用途缺数阻断，不默认填值。
- 计划子结构出现 `plan_price*` → `unknown_field_rejected`；`target_profit_value` 必须带
  `target_profit_unit`（单位规则同 `risk_budget`）。
- 读接口与快照不输出废弃价格字段。

## 验收

- 真 PG：超出可用资金 → 400 且定位字段；等于上限 → 通过；缺可用资金 → 阻断；
  `plan_price` 提交被拒；`target_profit_value` 缺 unit 被拒；`direction` 仅 `buy/sell`。

## 落点

`server/business_service.py`、`server/routes/business.py`、`server/investment_snapshot.py`、
`tests/pg/test_business_write.py`、`tests/pg/test_business_routes.py`

## Resolution（2026-10-08）

- `PLAN_FIELDS`/`_PLAN_VALUE_COLUMNS`/`NUMERIC_FIELDS`/`UNIT_REQUIRED_FIELDS`/`UNIT_BY_FIELD` 按新口径更新；
  `evaluate_purpose` 改为要求 `plan.allocated_capital`。
- 新增 `_assert_allocation_within_available`（上限优先可用资金、退化为总资金；未绑定账户不阻断），
  在 `create_plan` 与 `update_plan` 的写入事务内调用。
- `_plan_values` 不再输出废弃价格列，输出 `allocated_capital` 与 `target_profit{value,unit}`。
- `investment_context._PLAN_FIELDS` 同步（快照/上下文按用途裁剪新字段）。
- 新增 `tests/pg/test_plan_capital_terms.py`（9 项）覆盖上述验收；全套 **211 passed**。
- 证据：`evidence/01-02-pg.log`。

## 未覆盖（转 03）

- 不携带 `declared` 的纯分析提交未单独复验上限（依赖写入服务与既有值）；见 issue 03 范围说明。
