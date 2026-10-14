# 93 号治理层方案 · 拒签记录

状态：`refused`（拒签已登记）。零模型调用。**未签认、未代签、未预填。**
93 号 md / plan / corrections / template / MANIFEST 字节一字未改。

裁定的判据（U，2026-10-14）：**若该方案未给治理带来效果，则拒签。**

## 一、结论

净治理效果为空，条件成立，故拒签。

## 二、凭什么说"没效果"

| 检查面 | 实测 | 结论 |
|---|---|---|
| 今天是否阻断什么 | `rules_in_force.status = pending_human_signature` ⇒ 检查项 `pass-not-dependent-on-unfrozen-axis` 实测 `[NOTE] / blocking=false`（checker `exit 0, verdict=pass`） | 不阻断 |
| 签了之后呢 | 升为阻塞后唯一 uncovered 行是**已签的** 91 号 `verdict.release_line`；豁免需 `governance-corrections.json` 的 `status == 'signed'`，而该文件全仓无签署路径 | 指向错的目标（已签产物），且豁免不可达 ⇒ 要么锁红、要么永不生效 |
| 是否影响交付物读数 | `pending_caliber` / `unfrozen_axes` / `expired_to_report_only` / `rules_in_force` 四个词只出现在 3 个工具与 3 个测试里，无产出/报告/导出/评分路径读取 | 不改变任何交付物 |
| 是否影响 claims 去留 | M1 只决定新分**读法**；M2 可不签；M3 与去留无关 | 不改变新分高低 |
| 自身是否自洽 | R4 与模板要求登记件必填 `owner + decide_by`，计划件三格缺 `decide_by`；物化脚本强制三格齐填，与"M2 可不签"矛盾 | 违反自身规则 |

留下的真实效果只有两项，且都不依赖签认：91 号那处"已签 PASS 以未裁轴为前提"变成了可复算的 `[NOTE]` 检出；三格 `reopen_history` 把同一概念在 OPEN-A / C5 / M1 的三次改名归档。

## 三、拒签带来什么状态

- `rules_in_force` 保持 `pending_human_signature`；不产 96 号签名物化件。
- checker 保持 `exit 0 / verdict=pass / blocking_failures=[]`；该检查项维持 `[NOTE]`（检出但不阻塞）。
- 91 号 `release_line` 仍按 `governance-corrections.json` 的人工读法读作 `pending_caliber`；该登记不豁免任何东西。
- 三项待裁（M1 accepted 下限 / M2 分源精度轴 / M3 cite 侧轴归属）维持未裁，登记在案，不因拒签消失。
- 检出能力保留：此后不得因本次拒签删除或弱化该检查项。

## 四、什么条件下可重开

1. 把 91 号更正做成**独立、可签认**的登记（自身有签署路径），不与 R1–R4 捆绑。
2. 若保留 R1/R2：阻塞目标从"已签产物"改到"新证据 / 新门"（断言层面），并给出解套路径，使签认后不锁红。
3. 三格补齐 `decide_by` 或显式声明三格豁免 R4；物化脚本允许 M2 待定。

## 五、复核命令

```
uv run python tools/check_claims_gate.py                 # exit 0, verdict=pass, 该项 [NOTE]
uv run pytest tests/test_claims_governance_plan.py \
  tests/test_claims_governance_signoff.py \
  tests/test_claims_governance_apply.py -q               # 44 passed
```

签认栏不由本件填写：若需正式具名拒签，由 U 在 93 号件上签署。
