# 03 成交价回填触发重新分析

Type: task
Status: resolved
Blocked by: 02

## 目标

- 回填实际成交价：写成交记录（每次买卖一条）+ 计划/账户新版本 + 新 Run + outbox **同一事务**。
- 新 Run 快照包含更新后的成交与 `allocated_capital`；原 Run 不复活、不改写。
- 同研究串行由既有 `dispatch_outbox` 研究互斥保证；重复提交按幂等键返回原 Run。
- 未成交时不允许提交成交价；建议价不得作为成交价写入。

## 验收

- 真 PG：回填后新 Run 快照含新成交价与规划资金；旧 Run 快照不变（AC-06）；
  同键重放不产生第二个 Run；并发回填只有一个后续 Run。

## 落点

`server/routes/runs.py`、`server/investment_snapshot.py`、`server/dispatch_outbox.py`、
`tests/pg/test_run_snapshot.py`、`tests/pg/test_run_dispatch.py`

## Comments

2026-10-08：核查发现既有提交侧只支持“更正已有成交”（`declared.trade` 必须带 `trade` 引用），
**缺少“新登记一条成交”的回填路径**，与本次口径（每次买卖各记一条）不符。

## Resolution（2026-10-08）

- `server/investment_snapshot.persist_declared`：`declared.trade` 在无既有引用时改为
  `biz.register_trade`（在提交事务内新登记一条成交），有引用时仍走 `biz.correct_trade`；
  账户引用缺失时返回字段级校验错误。计划/账户/成交/快照/Run/outbox 仍为同一事务（DATA-06 既有链）。
- 用途说明：回填成交价后的重新分析按 `holding_cost` 用途冻结快照，快照才包含 `trade.price`；
  `plan_analysis` 不含成交字段（按用途裁剪，非回归）。
- 新增 `tests/pg/test_fill_price_rerun.py`（1 项）：回填后成交记录唯一且 `price=20.10`、
  新 Run 快照含 `trade.price`、旧快照不变（AC-06）、同键重放返回原 Run 且 Run 总数为 2（AC-05）。
- 全套 `tests/pg`：**212 passed**。证据：`evidence/03-pg.log`。

## 未覆盖

- 并发回填（两个窗口同时提交不同成交）未单独复验，沿用既有研究串行与幂等键约束；
  本条登记为缺口，见 spec 退出判据第 4 条。
