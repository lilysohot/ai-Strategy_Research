# I06/I41 候选裁定工作表（r3，可进出分）

候选 15 条 | 裁定人：xyl 日期：2026-10-13

> **填写状态（2026-10-13）**：表格已由**代理预填**（`drafted_by=agent`），
> 依据 = 契约 v4.1 的 `matching` 规则 + 现有 222 条的匹配占用情况（1:1 映射）。
> **这是预填草稿，不是裁定**：核实后请在「裁定人」处署名，`reviewer` 必须是你。

## 金标参照

**NT-I06**（char:1393-1655）：「中报验证了量」→ 中报验证了AI相关业务的出货量增长 ｜ opinion/claim/reported/affirmed

**NT-I41**（char:5055-5071）：「持有 + 观望」→ 报告作者对工业富联的总体建议是持有加观望 ｜ opinion/claim/reported/affirmed

## 逐条裁定

judgement 枚举：matched / correct_extra / incorrect / duplicate / unresolved / out_of_scope

| # | candidate_id | 候选文本 | 模型抽取(sem/role/pol) | 提示 | judgement | matched_gold_id | semantic_type | statement_role | source_stance | condition |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `slot_214372468938afb1#1` | 卖方讲三条 | opinion/claim/affirmed | | correct_extra | — | opinion | claim | reported | absent |
| 2 | `slot_3d7a7290c7f874fa#1` | CSP/GPU 机柜量、Rubin 卡位、CPO/高速网络 | opinion/claim/affirmed | | correct_extra | — | opinion | claim | reported | absent |
| 3 | `slot_60052220425de312#1` | 中报验证了量 | opinion/claim/affirmed | NT-I06 | **matched** | **NT-I06** | opinion | claim | reported | absent |
| 4 | `slot_29321fd57ac9ff2e#1` | 云计算 +75.7% | fact/evidence/affirmed | | duplicate | NT-I05 | fact | evidence | reported | absent |
| 5 | `slot_fa65168fd657b4cc#1` | CSP AI 服务器 +2.3 倍 | fact/evidence/affirmed | | correct_extra | — | fact | evidence | reported | absent |
| 6 | `slot_6d633216b432f293#1` | GPU/ASIC 机柜出货 +3.2 / +3 倍 | fact/evidence/affirmed | | correct_extra | — | fact | evidence | reported | absent |
| 7 | `slot_f97e5c740c8137e0#1` | Q2 营收 3067.83 亿环比 +22% | fact/evidence/affirmed | | correct_extra | — | fact | evidence | reported | absent |
| 8 | `slot_a7980f0dce789e71#1` | 卖方爱用归母 +96% | opinion/claim/affirmed | | correct_extra | — | opinion | claim | reported | absent |
| 9 | `slot_a7980f0dce789e71#2` | 卖方爱用 26E 600 亿+ | opinion/claim/affirmed | | correct_extra | — | opinion | claim | reported | absent |
| 10 | `slot_a7980f0dce789e71#3` | 中报扣非虽然同步 | fact/claim/affirmed | | correct_extra | — | fact | claim | reported | absent |
| 11 | `slot_214c423c9dffff90#1` | 但 OCF 只有 73.91 亿； | fact/claim/affirmed | | correct_extra | — | fact | claim | reported | absent |
| 12 | `slot_976f4b2891010ed3#1` | Q2 毛利率环比 −0.36pct，并表 7% 的加工费没有变成「系统商」。 | fact/claim/affirmed | | duplicate | NT-I07 | fact | claim | reported | absent |
| 13 | `slot_976f4b2891010ed3#2` | 并表 7% 的加工费没有变成「系统商」。 | fact/claim/negated | | duplicate | NT-I08 | fact | claim | reported | absent |
| 14 | `slot_0941b49532217294#1` | 框架站扣非、OCF 和毛利率，不站归母标题，也不站 90 元共识当明天的地板价 | opinion/claim/mixed | | correct_extra | — | opinion | claim | reported | absent |
| 15 | `slot_f01c72a4463f094b#1` | 持有 + 观望 | behavior/claim/affirmed | NT-I41 | duplicate | NT-I41 | behavior | claim | reported | absent |

> deterministic 字段（speech_role/perspective/polarity/proposition）由 P01 装配器从候选自身重算，**不要填**；
> `condition` 无则填 `absent`；evidence 缺省用候选自带 evidence_quote。

## 逐条依据（代理预填，待你核实）

| # | 依据 |
|---|---|
| 1 | 卖方三条核心发现的总括句；48 条金标无对应原子命题，内容为真 ⇒ correct_extra。 |
| 2 | 三条并列枚举；金标 NT-I21/I22/I33 讲的是 CPO 出货与成熟度，非本句 ⇒ correct_extra。 |
| 3 | 金标 NT-I06 当前**未匹配**。候选省略宾语，但原句紧跟「云计算 +75.7%，CSP AI 服务器 +2.3 倍，GPU/ASIC 机柜出货 +3.2 / +3 倍」，「量」语境唯一指向 AI 相关出货量 ⇒ 可恢复省略、命题未变、同义改写可接受。语义类型 opinion／话语角色 claim 与金标一致。 |
| 4 | NT-I05「云计算业务增长75.7%」**已有匹配候选** `itm_abebb2a7163927e9`，按 1:1 映射同一金标不得二次匹配 ⇒ duplicate。 |
| 5 | CSP AI 服务器出货倍数；金标无对应 ⇒ correct_extra。 |
| 6 | GPU/ASIC 机柜出货倍数；金标无对应 ⇒ correct_extra。 |
| 7 | Q2 营收与环比；金标无营收类记录 ⇒ correct_extra。 |
| 8 | 归母口径增速；金标 NT-I01 断言的是扣非净利润 229.84 亿 / +97%，命题不同 ⇒ correct_extra。 |
| 9 | 卖方 26E 预测值；金标无对应 ⇒ correct_extra。 |
| 10 | 转折句前半；NT-I01 断言扣非绝对额与同比，命题不同。另注：原句含转折「但 OCF 只有 73.91 亿」，本候选未取 ⇒ 语义不完整（非事实错误）。 |
| 11 | OCF 绝对额；与 NT-I03「经营现金流仅覆盖扣非净利润0.32倍」相关但命题不同（绝对额 vs 覆盖倍数），且 statement_role=claim 与金标 evidence 不一致 ⇒ correct_extra。 |
| 12 | NT-I07「2026Q2毛利率环比下降0.36个百分点」**已有匹配候选** `itm_d0e9f3a0a75f5157` ⇒ duplicate。另注：本候选为**复合命题**（同时携带 NT-I08 语义），1:1 下只能取一，属抽取粒度问题，建议记 backlog。 |
| 13 | NT-I08「当前毛利率没有证明…系统商」**已有匹配候选** `itm_9960b6f5d20e37ed` ⇒ duplicate。待核：候选 polarity=negated，金标为 affirmed（两侧均为否定式命题）。 |
| 14 | 报告自身的取价框架；金标无对应 ⇒ correct_extra。 |
| 15 | NT-I41「报告作者对工业富联的总体建议是持有加观望」**已有匹配候选** `itm_c71e15d5cebf1e85` ⇒ duplicate。另注：候选 semantic_type=behavior 与金标 opinion 不一致（契约不自动归一化），即使无前者也不应直接判 matched。 |

**汇总：matched 1 ／ duplicate 4 ／ correct_extra 10 ⇒ 本包净增召回 +1（NT-I06，26 → 27）。**

## 机械提示（仅观察，非裁定）

{
 "slot_60052220425de312#1": "NT-I06",
 "slot_f01c72a4463f094b#1": "NT-I41"
}
