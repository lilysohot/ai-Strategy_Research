# Web 会话计划口径变更（计划不含价格、规划资金、Agent 主动补数）

依据：2026-10-08 用户裁决。设计落点：

- `docs/design/web-business-data-prd.md` v0.7（§3.2、§3.4、§4.1—4.4、§5.2、§7.1、AC-03、AC-26、AC-29、AC-30）
- `docs/design/web-business-data-contract.md` v0.2（§4、§5、§6、§7、§8、§11）
- `docs/plan/web-business-persistence-tasks.md` v1.5（DATA-01—07）
- `docs/plan/web-business-ui-tasks.md` v1.6（UI-02/03/05/06/07）

## 冻结口径

1. **计划不保存价格**：`plan_price`/`plan_price_low`/`plan_price_high` 不再作为有效字段。
2. **价格真源是成交记录**：每次买入/卖出各一条；Agent 建议价存策略版本（`system_computed`）。
3. **计划新增 `allocated_capital`**（本标的规划资金，金额；币种取计划 `currency`）：保存时校验
   ≤ 所属账户可用资金，不跨研究累计。
4. **计划新增期望盈利**：`target_profit_value` + `target_profit_unit`（金额或比例＋单位）。
5. **补数请求新增触发场景**：Agent 识别研究标的后、准备给出价位/仓位结论且必填项缺失时主动创建；
   采集项＝规划资金（必需）+ 承受风险 + 期望盈利（可后补）。
6. **成交价回填重算**：用户回填实际成交价 → 成交记录 + 计划/账户新版本 + 新 Run 同一事务 → 重新分析。

## 技术决策（复核时确认）

- `target_price` 字段**保留但不再作为准入必需**；与 `target_profit` 的分工未冻结（契约 §11）。
- 旧列 `plan_price*` 保留为 **deprecated**：不写入、不出现在读接口输出，避免破坏不可变历史版本；
  物理删除另议。
- `allocated_capital` 币种沿用计划 `currency`，不新增币种列。

## 退出判据（预注册）

1. 每个 issue 的定向真 PG 用例通过，且 `tests/pg` 全套回归通过（在独立测试库，不连业务库）。
2. 仓库门禁通过：Ruff、Pyright（本批文件 0 错误）、import smoke、symbol closure、`git diff --check`。
3. 前端：`vue-tsc` + 构建通过，新增交互有隔离 fixtures 的浏览器验证。
4. 证据脱敏存入 `.scratch/web-business-session-plan/evidence/`；未通过项登记为缺口，不放行。
5. 本专项**未部署 API、未迁移生产库**；完成与否由独立复核 + 用户具名签认，实施方不自宣。

## 范围外

- 券商接入、自动下单、多账户联合优化、完整交易会计账本。
- `target_price` 去留、废弃列的物理删除、`allocated_capital` 跨研究累计占用（当前明确不做）。
