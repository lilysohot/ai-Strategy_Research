# I3-2 尾巴收口记录

- 生成：2026-09-19T18:26:12+08:00；授权：U（2026-09-19 会话：『把 I3-2 的尾巴彻底收干净，授权』）
- 范围：I3-2 阶段签认记录（i0c-r30）not_covered 清单中的可收项 + 复核观察项

| # | 事项 | 状态 | 处置 |
|---|---|---|---|
| T1 | prose 留出未纳入守卫隔离 | **closed** | 把 prose_holdout_manifest.json 声明的天风件加入 guards/i3.json forbidden_roots（4 → 6 份）；完成门新增『留出隔离覆盖』判据 |
| T2 | 19 题旧锚点映射 confirmed=false（待人工复核） | **closed** | 按确定性规则复核关闭（归一化标题子串唯一命中 + 来源路径在磁盘 + 与已标注 source-gold 同源）；closure.kind = rule_verified_by_authorization，**非逐题人工通读**，基础材料可由机器复算 |
| T3 | 20 条人工同义映射 warning | **closed** | 作为**已接受风险**入册：字面出处由机器核验（quote/source_id/locator 与 source-gold 一致），语义等价由决定 1 的具名人工承担；warning 原样保留供后续抽样审计 |
| T4 | I3-5 真实非回归 / I3-1 三类 E2E / I3-5·I3-7 真实答案语义 | **blocked_needs_environment** | 非 I3-2 冻结范围：需隔离 PG、来源读取、模型与预算授权；I3-1 另需 i3-e2e 阶段守卫。本记录不代替业务通过 |
| T5 | M5 F3：validate_i1_freeze.py 对工作区 13 项失配 | **registered_out_of_scope** | 属 **i1 链**（I1 阶段冻结）的历史漂移：`plugins/corpus/preparation/*.py` 4 件 + `tests/test_corpus_preparation_*.py` 9 件在 I2 阶段被合法改动，i1-r3 的绑定未随之更新。按诊断稿『单列跟踪、不与 I0-C 链混为同一故障』**本轮不动 i1 链**；建议后续以 **i1-r5** 重绑这 13 项（并登记：改动前字节早于本会话、无法归档，溯源依 I2 阶段的修订记录） |

## 残留风险

- 20 条同义映射仍属语义风险（已接受，可抽样审计）
- 19 题映射关闭基于确定性规则 + 授权，未逐题人工通读
- I3-5/I3-1/I3-7 未执行；M5 F3 待 i1-r5
