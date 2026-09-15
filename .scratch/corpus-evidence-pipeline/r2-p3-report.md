# R2 P3：固定开发回放、原子分母与逐类非回归诊断

日期：2026-09-14。结论：**P3 已执行并触发停止条件；不进入 P4。**

## 执行结论

用户在 PG 只读核查后指示继续，视为接受“历史零影响无法补证”的边界并允许恢复**封锁 PG 的
纯离线 P3**，不是确认事故无影响，也不是解锁 PG 或模型预算。

P3 确认 P2-B 的执行/审计/验收接口方向可保留，但冻结 planner 无法给真实开发范围产生可执行
原子义务：六个微范围的35个金标目标全部落入 `compound_or_condition`，形成6个粗粒度 unresolved
义务、0个 candidate；四类开发范围共17,044字符、14个输入根同样全部 unresolved、0个 candidate。

因此当前系统不是“模型效果还差一点”，而是**模型之前的义务生成层没有输出**。继续冻结 P4
模型预算不会获得新证据；即使模型完美，也没有被授权填写的义务。按计划 §6 的停止条件，P3
状态为 `blocked_by_non_replayable_legacy_wire_and_unapproved_atomic_mapping`。

真实模型、judge、PostgreSQL、市场和入库调用均为0；只打开四个已冻结 development 来源路径，
没有打开独立留出来源。没有修改公共 parser、EvidenceRun、旧 material_semantics、service、scorer、
gold、budget、CLI 或三份已冻结的 P2 私有模块。

## v12/v13 回放资产到底缺什么

v12/v13 各9份 raw response 均存在且响应SHA匹配，JSONL无损解析。每版都覆盖冻结的37个旧槽位：
35条item + 2条coverage/exclusion终态，四类分别7/14/6/10，缺失和未知ID均为0。

但新 `ItemWire` 接受数为0。旧响应只有 `candidate_slot_id` 及旧 item/speaker/coverage 行，没有新协议
要求的 `protocol_version`、`plan_id`、`obligation_id`、统一terminal/item envelope、span IDs，也没有
OfflineGrant journal。用gold或适配器补这些字段会伪造身份与审计，所以被标为 not_replayable，
没有调用旧 extractor 生成“看起来能过”的新结果。

历史评分继续保留，不追溯改写：

| 版本 | 旧item recall / precision | 旧semantic | 关键错误 | 结论 |
|---|---:|---:|---:|---|
| v12实际轮 | 35/35 / 1.0 | 0.9143 | 9 | 失败；后续旧系统零调用重放曾通过，但不是新协议证据 |
| v13实际轮 | 34/35 / 1.0 | 0.9118 | 1 | 失败；公司评级缺失及关键错误保留 |

这说明旧响应资产完整性不是主要阻点；主要阻点是新旧义务身份不兼容，以及新 planner 本身没有
候选。两版不能择优拼成一次虚构基线，旧重放通过也不能替代新接口的 raw/audit 证明。

## 六微范围与四类结果

| 范围 | 目标 | 关系正/负 | 新义务 | candidate / unresolved | 估算调用 |
|---|---:|---:|---:|---:|---:|
| 公司推荐 | 7 | 0/0 | 1 | 0/1 | 0 |
| 行业Q7-Q8 | 14 | 11/3 | 1 | 0/1 | 0 |
| 个人交易TTD | 4 | 0/2 | 1 | 0/1 | 0 |
| 铜箔总结 | 1 | 0/0 | 1 | 0/1 | 0 |
| 铜箔录音 | 1 | 0/0 | 1 | 0/1 | 0 |
| 铜箔良率 | 8 | 6/3 | 1 | 0/1 | 0 |
| 合计 | 35 | 17/8 | 6 | 0/6 | 0 |

微范围741字符，35个目标在粗义务文本中都可逐字定位，因此不是来源丢失；但一个 unresolved 根
同时覆盖1—14个目标，不能当作已批准原子分母。35条记录全部进入 proposed、未批准复核队列，
不能用人工“批准整段”等同35个原子映射。

四类完整开发输入结果：公司8根/3,047字符、行业1根/1,508字符、个人交易1根/674字符、电话纪要
4根/11,815字符；分别产生8/1/1/4个 unresolved，candidate均为0。容量上没有静默截断或超上限，
真正失败的是粒度策略，而非调用上限。对话、研报、交易复盘和电话纪要四类同时受影响，不能以
单类特判修补。

## G0—G6 判定

| 门 | 判定 | 依据 |
|---|---|---|
| G0 身份与范围 | passed | P0/P1/P2及本轮范围SHA固定；四类development、六微范围一致 |
| G1 终态与容量 | not_evaluated | 没有新协议模型输出；planner 0 candidate，不能测终态完整性 |
| G2 内容忠实度 | not_evaluated | 35条映射均未批准；不能自动给自然语言转述盖章 |
| G3 字段语义 | not_evaluated | 无新协议输出及绑定人工裁决 |
| G4 关系 | not_evaluated | 按计划留到P5；fake协议不等于17正/8负实测 |
| G5 旧流程隔离 | passed | P2冻结快照/605项保护证据复核，原2336保护文件仍不变 |
| G6 四类非回归 | not_evaluated | 没有新协议候选输出，无法与v12/v13同口径比较 |

必需门未评估即不放行。P3 测试11项通过；与P1 65、P2-A 73、P2-B 75组合为224项通过。
新增脚本Ruff通过；import smoke 339/339、388/388，check_symbols 438文件、0缺失；P2 guard复核通过。
这些工程结果不能抵消G1/G2/G3/G6缺失。

## 根因与是否值得继续

当前 `_ranges()` 把逗号、顿号、条件词、转折、并列或引号视为“不可拆”，随后只返回整个范围并
标 unresolved。这个安全原则避免了错误拆分，却没有第二层将 unresolved 转化为一组有限、可核验
的候选。P2 runtime 只处理 candidate，因此安全降级变成了100%停摆。

结论不是取消整个 R2：以下部分已有独立价值，应保留。

- EvidenceRun/source/plan/request/result/hash 的身份链；
- 模型不能自造义务、端点、系统终态和审计完成标志；
- 发送前预留、raw完整保存、未知结果占额、从raw重建；
- 运行时协议校验与开发语义评分分离；
- 公共 parser/旧流程隔离。

需要重设计的是 planner 和 scope-provider 之间这一条局部 seam，而不是重写 EvidenceRun、审计器、
验收器或旧入库流程。继续研究有价值，但**沿用当前“遇复杂结构整段 unresolved”思路没有价值**。

推荐下一设计为“有限边界格（bounded clause lattice）”：系统只基于可定位边界生成有限备选，
同时保留 whole span、子句span、共享条件/归属span和依赖边；不提前认证任何一个为原子事实。
模型或人工只在系统给定节点上填 terminal/字段，不能改边界；验收器检查覆盖、重叠、条件继承、
对象/否定保留与唯一终态。每根最大节点/组合数硬限制，超过即保留 unresolved，不静默截断。

这仍符合“系统生成有限、可核验原子义务，模型逐项填写”，但把“有限候选”与“已验证原子分母”
分开。先在 scratch 做零模型 v2 planner 原型，对六微范围要求：35目标可映射、无gold参与生成、
17正/8负关系端点保持可引用、每根容量有上限；再由人工批准分母。通过前不改P1冻结契约和
`plugins/corpus/_r2_plan.py`，不进入P4。

## 交付与停止点

- [回放/容量清单](r2-p3-replay-inventory.json)：不含自动通过结论。
- [人工复核队列](r2-p3-review-queue.json)：35条均为 proposed_not_approved。
- [P3执行脚本](p3_replay_review.py) 与 [11项测试](test_p3_replay_review.py)。
- [P3冻结清单](r2-p3-manifest.json) 绑定输入和交付；其外部SHA记录在issue 20最新执行项。
- [本轮范围](r2-p3-change-scope.json)，外部SHA：
  `1f4a25b1919460a2b941e1da4cd30d20d5775d79e08753c27d3a8979b27996d0`。

两份未登记的JUnit过程文件已删除，可由pytest重建；它们不进入冻结证据。未删除或覆盖历史
v12/v13/P0/P1/P2结果。下一步不是P4，而是由用户决定是否授权一个独立的 P3-R 局部planner原型；
若不接受该局部重设计，应将完整自动R2降级为“证据辅助读取 + 人工确认”，不再投入模型轮次。
