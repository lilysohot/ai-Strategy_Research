# R2 P1：有限义务 Interface 与前瞻验收契约

| 项 | 内容 |
|---|---|
| 状态 | **有效 · P1 设计冻结 v1**；不是生产实现或 R2 业务验收通过 |
| 日期 | 2026-09-14 |
| 归属 | [唯一总清单](claims-market-closed-loop-plan.md) R2；[局部计划](r2-local-redesign-cli-closure-plan.md) P1 |
| 需求 | PR-DATA-02/09/10、PR-OUT-06/07；CLI 优先，Web 暂缓 |
| 前提 | P0-A 保护基线复核通过；P0-PG 未验证，不在本阶段连接数据库 |
| 证据 | [P1 执行报告](../../.scratch/corpus-evidence-pipeline/r2-p1-report.md)；合成可执行规格，不使用开发金标生成计划 |

## 1. 决策与能力边界

保留有限义务路线，但不再把“结构槽”当作已证明的“原子命题”。系统拥有固定来源、范围、父子义务、
全部来源坐标和容量；模型只回答每个义务，不新增 ID 或临时递归拆分。一个候选只允许提交一个独立
命题；发现多命题、条件依赖或归属歧义时返回 unresolved，不能任选一条后声称覆盖完成。

这里的原子命题是：一个可独立判断是否忠实于来源的断言及其不可分离的对象、否定、条件、时间、
归属约束。问句可成为待理解条目，但不是回答者的承诺；寒暄也纳入来源台账，不能依据“专家”标签
提前判 answer。条件与结论不能因标点被分离成无条件结论。

**P1 证明的是有限规划、来源无损与诚实阻塞可表达，不是通用自动原子化已经解决。** 缺少风险信号
不证明候选语义原子性。无法拆分的真实比例、四类召回/忠实度、人工成本仍是 P3 投入评审的必需项；
如果大量内容只能 unresolved，不能以“降级可读”为由放行完整 R2，也不自动取消原需求。

本契约是新实验版本，不修改 R1 需求、历史金标、v12/v13 评分或失败结论。

## 2. 一个对外 Interface，三个明确动作

下列是 P2 实现目标，不是当前可执行的生产函数或 CLI 命令：

```text
R2Material.prepare(verified_evidence_run, MaterialRequest) -> PreparedMaterial | PrepareFailure
R2Material.execute(prepared, execution_adapter, audit_sink) -> MaterialResult
R2Material.validate(prepared, result) -> ValidationReport
```

prepare 与 validate 为无网络、无数据库、无模型的纯处理。execute 以注入的真实模型或已有响应
Adapter 工作；fake/replay 不伪称真实生成。显式持久化属于 P6，不能藏在 prepare、失败分支或 validate。
AuditSink 只用于已授权调用的预算预留/结果留存，不向普通读取引入数据库依赖。

| 输入/产物 | 必需字段与不变量 |
|---|---|
| MaterialRequest | contract_version、source binding、按文档顺序的显式 scopes、task=item/relation、planner policy hash；默认预算 0，不自动全文 |
| PreparedMaterial | evidence_run_id 与完整产物 hash、source_rev、parse_rev、request/contract/planner hash、plan_id、固定 parent/obligation/span 集合、容量计数、未覆盖范围、拒绝原因 |
| MaterialResult | 新版本标识、plan_id、result hash、每义务 terminal、items/relations、原始响应安全引用、attempt 账本、ValidationReport；旧 MaterialRun 不原地改 schema |
| ValidationReport | source/plan/response binding、坐标与字段约束、合法终态数、未解决数、语义未核验轴、关系状态、审计完整性；不读 gold、不声称来源事实独立真实 |
| EvaluationReport | 独立开发评测产物，绑定 result/contract/gold/adjudication/policy hash；逐类指标、分母、关键错误、未裁决/不可重放项、实际准入结论 |

验证配置、版本、身份、范围及容量必须早于创建真实模型和任何写入。未知版本 fail closed；不同
EvidenceRun 即便文本相同，也不偷偷替换请求的 run。执行不得用新 plan_id 绕过原轮次预算。

读取新文档没有金标时仍能返回来源与部分理解，但 semantic_status=not_evaluated/needs_review。
不得把“坐标合法”显示为“语义已验收”。CLI 是否满足请求用途按显式所需门决定，不能拿只读取证成功
宣称完整理解成功。EvaluationReport 不进入生产 imports；正式生产层也不调用离线评分工具。

## 3. Span 身份及有限 planner

### 3.1 来源约定

SpanRef 使用 source_rev、parse_rev、packet_id、原始 locator、start/end、text_sha256 和 span_id。
start/end 是 **packet.text 上的 Unicode code point 下标，左闭右开**，不是 UTF-8 字节、UTF-16 单元、
PDF 页坐标或 locator 内局部下标。不做 NFC、strip、标点修订、空格折叠或文本拼接。空范围不合法。

span_id 为上述字段的规范 JSON SHA-256；plan_id 还绑定 EvidenceRun 身份、顺序、范围、规则和容量。
外部运行清单固定 plan_id；重新计算一个自洽 hash 不能替换已批准的计划。原 packet 身份沿用公共
EvidenceDocument，不改变它的算法。P2 需先调用现有 EvidenceRun 身份验证，再生成只读视图。

相同引文可在不同坐标出现：各自合法，不再要求字符串在整个包中仅出现一次。模型不能提交新坐标；
系统从 obligation_id 回取 focus/support/context。模型如选择附加证据，只能引用已提供的 span_id。
错误义务、错版本、越界、错 locator、引文 hash 不符均拒绝。跨包依据列多条原始 SpanRef，不制造
不存在的连续短引文。表格的行列引用保留原公共表示；散文 planner 不冒充表格原子化。

### 3.2 首版保守算法（纯结构，不裁决语义）

1. scopes 必须有序、不重叠、不重复，每个 scope 是一个 parent；子范围以外不宣称已覆盖。
2. 先检查来源/范围及输入容量。全 scope 原文作为 support 保留，前后各一个已选 parent 作为 context。
   context 明示为“所选范围邻接”，不保证原文连续或存在问答/论证；缺必要上下文则 unresolved。
3. 只对没有已识别风险信号的 parent 按 `。！？；?!;` 和换行切结构候选；保留每一个字符。
   逗号/顿号、条件/并列连接词、引号/括号、明显指代或省略等信号只用于阻止拆分，绝不自动推断语义。
   精确信号集以哈希绑定的可执行规格为准；它不是完整汉语语法识别器。
4. 存在风险时将整个 parent 作为一个 unresolved 义务，保留原因。unknown/不可用/表格 packet 也不
   静默丢弃；空白保留台账待判。未触发风险的候选 atomicity 仍是 not_verified。
5. children 串接必须逐字还原各自 parent；focus 无重复/遗漏，support 可重复作为上下文。
   所有子项保留 parent_id；拆分到这里结束，不允许模型执行中生成新义务树。

首版容量固定：depth=1，最多 32 parents、每 parent 8 children、总义务 128、每 parent 4096 字符、
总选中范围 32768 字符。超过任何一项返回 PrepareFailure，不截取前 N 条、不将超容量归为无内容，
不自动变更 scope。容量是零模型规格的上限，**不是模型调用或 token 预算**。

最多 128 个义务，每个携带 focus、完整 support 和最多两个 context，每个引用至多 4096 字符；
文本展开粗上界为 128×4×4096=2,097,152 字符，显然不能直接当成一个提示词。P2/P3 必须先精确去重
并计算实际序列化 token、批次和输出容量；没有 provider tokenizer/输出上限证据时不声称适配 9 次。
真实长范围与跨包依赖按 EC8 另测，不允许提高这些数值来绕过容量失败。

### 3.3 P1 六组结构案例

| 组 | 正向保留行为 | 必须阻止的误判 |
|---|---|---|
| 并列 | 独立的“甲增产；乙减产”产生两个候选 | 顿号/连接词多命题不可只保留一家并算完成 |
| 嵌套条件 | 条件、否定和结果整体保留 unresolved | 将条件尾句独立为无条件断言；跨分号的条件丢失 |
| 跨段问答 | 两段独立坐标和双向 context 引用 | 把“不会”补成明确主体，或把邻接直接当 answers |
| 否定 | 否定逐字保留；引述整体保留 | 短引文没变但转述变肯定，不能靠定位检查放行 |
| 无标签对话 | 来源可读；未知表达者不猜专家/投资者 | 问句或发言身份不能自动生成承诺/角色 |
| 寒暄 | 寒暄纳入计划，混合预测不整体过滤 | 专家欢迎语判 answer；通过 no_supported_item 隐藏预测 |

这些例子使用合成文本。P1 负控检查删除叶子、来源改写、伪造完成、坐标/容量/外部 plan 绑定；
“转述否定翻转”等模型输出级反例留在 P2 scorer mutation，不能混报为本轮已验收。

## 4. 单义务协议与字段来源

模型每条 JSONL 对应一个已冻结 obligation_id；带 protocol_version 与 plan_id。schema 拒绝未知字段
和枚举；不以截断修复或默认值补造缺失语义。执行器处理单条坏记录时保留其他合法记录及原始审计。

| terminal | 内容 | 协议与业务含义 |
|---|---|---|
| extracted | 恰好一条候选 item；完整命题与约束 | 合法终态不等于语义通过；多命题无法可靠表达必须 unresolved |
| no_supported_item | 无 item、可核查理由及已提供证据引用 | 只是模型的无项主张；运行时不自动证明正确，开发需绑定裁决 |
| unresolved | 不确定点、原因、来源保留；不得给确定 item | 唯一合法终态，但不是内容已解决 |
| failed | 错误码与安全诊断，保留对应 attempt | 系统可为坏记录产生失败终态；缺响应不能伪称已收到 |
| deferred | 未执行原因，如关系未授权/预算 0 | 不消费调用、不算内容完成；必须列范围 |

每个冻结义务恰好一个最终 terminal。相同 ID 重复即协议失败，不最后一条覆盖；遗漏由系统补审计
failed/deferred，仍计模型响应缺失；未知 ID 留审计但不能增加分母。planner unresolved 默认不发模型，
不得通过同一次 execute 动态重新拆分。需要新计划时显式评审版本和范围，旧义务记录不删除。

字段统一使用 value + origin + support_span_ids + transform_rule_id（仅转换时）+ unknown_reason。
origin 为 source_observed / validated_transform / model_interpreted / unknown：

- 原始文本、坐标、明确原文标签可以 source_observed；标签不自动成为 speech_role、行为时间等语义。
- 只有指定、版本化、可复算的规则才可 validated_transform；数值需原文值/单位绑定，不复用模型数字。
- 改写 text、语义类型、归属、极性、行为状态、关系等判断明确标 model_interpreted，不能通过规则命中
  改名为已观察事实。独立真实性不在本契约保证内。
- unknown 必须 value=null/对应轴 unknown 且给原因；已填确定值与同一轴 unknown 冲突即非法。
  value=null 的定性预测可以合法；不得把 null 转 0 或丢弃。具体语义是否应 unknown 仍需内容裁决。

parent 完整性单独报告：没有叶子遗漏不代表所有命题已被抽取。保持 source_scope、字符覆盖、候选数、
protocol_completion、resolved_content、atomicity、content_fidelity、semantic_status、relation_status
和审计完整性。不得用一个 complete 布尔量折叠这些轴。

## 5. 开发评分契约（P2 实现目标）

### 5.1 判定顺序与阈值

各门同时产出诊断，任一必需门 failed/not_evaluated/needs_review 即不放行新预算。先验证身份、
范围、policy/result/adjudication hash，再计算指标；非法 hash 不靠忽略记录改善 precision。

| 指标 | 前瞻门槛 | 分母/规则 |
|---|---|---|
| G0 来源/范围/唯一坐标 | min=1.0；错误 max=0 | 全部输出与全部义务，而非仅成功映射项 |
| G1 terminal 完整 | min=1.0；重复/未知/漏响应 max=0 | 全冻结义务；系统补失败不消除模型漏响应 |
| G1 内容解决 | unresolved/failed/deferred max=0（item 必需范围） | extracted + 已裁决 no_supported_item 才可解决；全拒绝不得通过 |
| G2 微范围 item recall / precision | 各 min=1.0 | 全部预先冻结目标/全部预测 item；额外项未裁决不能算正确 |
| G2 忠实度 | min=1.0；关键错误 max=0 | 全部已输出命题及对象/条件/否定/时间/归属约束；未知裁决阻塞 |
| G3 semantic precision / recall | 各 min=0.9，逐类逐轴 | 各语义标签真实分母，不能只算匹配项的正确率代替 recall |
| G3 关键轴与未知诚实 | min=1.0；矛盾 max=0 | 归属/问答、否定/条件、行为/时间、数值依据及 unknown 正反向 |
| G4 source_explicit 关系 | precision min=1.0、recall min=0.9；错误 max=0 | 全部预测关系；负例端点缺失列不可判，不当真负例 |
| G5 / G6 | 公共保护与逐类差异门全部通过 | 四类、六微范围分开；任一保护指标下降即停 |

空分母是 not_applicable，不自动令必需门通过；范围或必需类别缺失是 not_evaluated。每个门显式
min/max，错误数量只按 max 比较。所有关键错误独立否决，不能以正确项抵消；旧 R1 阈值和历史评分
均保留。更严格的新忠实度门是前瞻约束，不追溯把旧轮次判为通过。

### 5.2 粒度与人工裁决

不读取 gold 决定义务数，不强保旧 37 槽，也不把新候选数当真实命题分母。首批开发人工工作限既有
35 item 与 17 正/8 负关系目标范围。旧长总结可能需要拆成多个命题；必须先生成粒度差异表，明确
old_target_id → atom/constraint 列表与 source hash，经用户或指定审核者确认，才冻结新原子分母。
保留旧目标组召回供对照，不把一个旧总结命中自动算所有原子命题正确。

新原子分母尚未完成裁决是 **P3 阻塞条件，不是 P1 已拥有新金标**。若需超出35项范围的新增标注，
先报数量和理由。人工工作不无限扩展，模型 judge 预算仍为 0。

裁决记录至少包括 reviewer_id/身份类型、source_rev/source hash、scope/plan/contract/gold 版本、
output text/约束的 hash、判断、理由和时间。代理分析只能为 proposed；不能自动签成人工 approved。
输出 text 或约束变化则裁决失效；只引用旧标签不足以证明新转述忠实。零模型 mutation 可使用明确
的合成正误预期，不冒称真实开发文本已经由人审核。

旧响应在 replay Adapter 缺少新字段时标 not_replayable；不得从 gold 填字段。已经有坐标可确定性
回绑的部分允许重放，但保留转换审计和范围。只存 MaterialRun 无 raw 的历史资产只做产物评分。

### 5.3 关系不暗中缩减

保留 R1 八类型 supports/challenges/conditions/invalidates/answers/motivates/attributes/elaborates。
关系义务是固定的有向端点对 + 一个类型，模型只填 present/absent/unresolved，不自造端点或类型。
item 不合法则依赖关系保持 unresolved。相邻不是 source_explicit，system_inferred 单列。

P1 关系状态 deferred，未实现/验收候选器。P2 先用 fake 验证协议与端点约束；P5 另冻结类型范围、
候选容量与预算。现有17正例只涵盖部分类型，不能宣称八类型都通过，也不能未经用户同意删掉其余。

## 6. 兼容/例外清单与 P2 移交

| 位置/对象 | P1 行为及后续要求 |
|---|---|
| 公共 parser / EvidenceRun / Claims / derivation / ingest / fetch | 不修改；P0 原 hash 保护持续有效 |
| material_semantics.py / service.py | 本轮仍严格整文件保护；旧 understand_material 默认保持。新实验入口将来需精确白名单，不自动解锁 |
| 新 R2 私有 Module | P2 才开始实现；禁止导入 scratch、gold、benchmarks。P1 规格是设计证据，不作为生产依赖 |
| 旧 scorer / policy / budget / raw | 原路径原 hash 保留；新版 scorer 另路径，不重写 v12/v13 |
| CLI / tools / profiles / runtime / market / Web / schema | 本轮不接线、不修改；P6/P7 按清单独立评审 |
| 旧输入/输出兼容 | 不静默把旧 MaterialRun 升级成新语义已通过；旧命令仍用旧版本；精确 run_id 读取不变 |

P2 按顺序：先构建独立 EvaluationReport 与输出级 mutation suite → 再做 R2 私有执行/校验 Module →
用同一 Interface 跑 fake/replay → 预算 reservation 崩溃故障注入、全部公开响应留存/落盘失败停止。
本轮没有实现后两项，也没有任何真实调用额度。若私有新文件需要进入 P0 扫描根，必须新增候选变更
清单，外部绑定 P0 manifest + 新增文件集合/方法 diff；不重写 P0 的原文件 hash 或扩大豁免。

执行前再次校验 P0 与本契约清单；本设计修改须新版本，不能在看完候选结果后改阈值。P2 不删除任何
旧公共安全测试；即使通用设计技能建议替换浅层测试，本项目的保护要求优先。
