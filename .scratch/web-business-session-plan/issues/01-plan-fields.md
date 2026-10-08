# 01 计划字段调整与迁移

Type: task
Status: resolved

## 目标

- `InvestmentPlanRevision` 新增：`allocated_capital`（MONEY）、`target_profit_value`（MONEY）、
  `target_profit_unit`（String）。
- `plan_price`/`plan_price_low`/`plan_price_high` 标为 deprecated（保留列、不再写入）。
- Alembic 迁移 `0018_plan_capital_terms`：加列 + 说明旧列处置；升级/降级往返通过。
- SQLite `create_all` 路径同步建出新列。

## 验收

- 真 PG：新列类型正确、精度往返一致；迁移 head 一致；既有计划历史行升级后仍可读（不丢数据）。
- 迁移降级再升回 head 不破坏既有行。

## 落点

`server/store.py`、`server/alembic/versions/0018_plan_capital_terms.py`、`tests/pg/test_business_models.py`

## Resolution（2026-10-08）

- 模型新增三列（`allocated_capital`、`target_profit_value`、`target_profit_unit`），
  `plan_price*` 保留为 deprecated 并注明不再写入；迁移 `0018_plan_capital_terms` 加列、降级可回退。
- 列形状断言扩展：`allocated_capital`/`target_profit_value` 为 NUMERIC(30,10)，`plan_price` 仍在库中。
- 迁移往返用例修正：指纹只比较 0005 建立的列（新增列在降级往返中按迁移语义丢失，不算历史行被改写）。
- 证据：`evidence/01-02-pg.log`（终轮 `tests/pg` **211 passed**，独立库 `apodex_sp_test`）。
