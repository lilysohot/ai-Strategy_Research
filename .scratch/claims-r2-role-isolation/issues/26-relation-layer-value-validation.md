# 26 · relation 层对研报抽取价值的有界配对验证

Status: completed
Type: task
Parent: [25 · Relation boolean v2 最终有界真实服从性复验](25-final-relation-live-compliance.md)
Model attempts: 预检 0；签认后主线最多 10 次（5 题 × A/B）；relation 抽取 0；judge 0
Production database access: 0

## 授权与当前边界

用户已签认价值金标并授权执行 Issue 26。2026-10-10 已冻结 r1 执行身份并完成 10 次主线 A/B；
盲化配对人工裁定已由 xyl 签认，随后完成零调用解盲和最终 relation 去留裁决。

- 不修改或取代已签认 gold-v2。
- 不追加 relation 抽取调用，不复活 Issue 25 已关闭路线。
- 不发布，不写生产库；publication/生产 query/生产库访问均为 0。M_main 已按冻结顺序执行 10/10，
  每格一次且无补跑；交付采用离线冻结包，不经过生产索引。
- 本任务只判断冻结铜箔访谈快照上的方向性业务增益，不声称统计显著性或跨材料普遍性。

## 目标

使用同源配对消融回答：把 Issue 25 真实保留的 213 条 relation 交付给主线 Agent，是否比
items-only 更能提高研报证据完整性、限定保留和观点平衡性；若不能，则将 R2 验收重心移回 items。

## 冻结输入

- snapshot：`sha256:561401b409e329fba8306c392bfc203da23ff1cc666faf9b7e919d88c2a9f080`
- Issue 25 batch：`batch:3269051ddc97ebc979132d5110bdf923c22f28b9f87dd579717b27acb120f920`
- items payload：`sha256:592065e674a8a0c1b2ff6764014781b029f8e22f616f0460dc921426b8a2c896`
- relations payload：`sha256:a4af367954dc9a6214d3b1f87f71c6eedb85a78225d6ead9bfe5a5db18deacfb`
- relation 数：213；candidate-v5 数：333；items 数：469。

condition A 只允许交付冻结 items；condition B 交付完全相同的 items，并允许查询和交付上述
relations payload。不得使用 gold 修补 treatment，也不得重新抽取关系。

## 零调用预检发现

原提案 Q4 使用 `pair_f88743227fb48b8b`，但 Issue 25 实际将其判为 absent，213 条 relation 中没有
该边，因此 A/B 不会形成 relation 暴露差异。Q4 改为 `pair_1f74637d78897251`：该错误保留的
`challenges` 会把“22—23 年较好”与“今年到明年更好”连接为挑战关系，可直接检验虚假对立风险。

condition C 从本任务删除；不得根据 A/B 结果临时追加。若 A/B 证明其他关系有益而 challenges
有害，后续另立过滤/新 Schema 任务。

## 五题样本

| 题 | 研究问题 | 主要覆盖 | treatment 中的冻结锚点 |
| --- | --- | --- | --- |
| Q1 | 每万吨铜箔主设备资本开支及口径 | answers | `pair_82e38a002735f044` |
| Q2 | HVLP 良品率的设备/工艺归因及依据 | answers/supports | 四条 answer target + `pair_e0122f78caaf1a43` |
| Q3 | 快速占据国内及部分海外市场的前提 | conditions | `pair_3e579daa7d92e267` |
| Q4 | 历史业绩与未来展望是否被错误写成冲突 | challenges 风险 | `pair_1f74637d78897251` |
| Q5 | 全球表面处理设备主要厂商 | 无关系依赖控制 | `itm_ba3a8f228e6ab791` |

完整问题措辞、必需事实、限定、反向证据、禁止推断和逐字引文见 evidence 中的
`utility-gold.agent-draft.json` 与 `human-review.md`，二者须由用户签认。

## A/B 设计

- 相同主线模型、系统提示、问题提示、工具集合、快照、items、总上下文上限、最大工具步数。
- A 的语义查询强制 `material_items`；B 允许 `material_items` + `material_relations`。
- A/B 使用独立会话，不共享对话、缓存或压缩摘要。
- 十次运行顺序在执行前写入冻结 manifest；并发 1；每格恰好一次，不自动补跑。
- temperature=0 只能减少波动，不能据此声称确定性或统计显著性。
- 输出使用相同的结构化短报告模板，并要求每条结论引用消费账中的 evidence/item 标识。

## 评分

每题人工金标预先冻结：

- `required_facts`：必须覆盖的事实概念；
- `required_qualifiers`：必须随结论保留的条件、范围、时间或口径；
- `adverse_or_counter_evidence`：应正确呈现的反向/限定证据；
- `forbidden_inferences`：不得由关系边引入的推断；
- `traceability_required=true`：每条实质结论必须能回到实际送达证据，否则该题失败。

人工 rubric 在隐藏 A/B 标签后评分；确定性程序只核验消费账、引用 ID、运行预算和冻结身份，
不以字面短语完全相等替代人工语义判断。

## 预注册裁决

- 关系相关题为 Q1—Q4；Q5 只检查无害性。
- 保留 relation 富化：B 在 Q1—Q4 至少 3 题的预注册主质量分高于 A，其余关系题不下降，Q5
  不下降，且没有新增错误对立、答非所问或不可追溯结论。
- 判定无正向价值：未达到上述增益，或任一 relation 诱发足以改变研报结论的禁止推断。
- 成本止损：若 B 的配对中位输入 token 或工具调用数相对 A 增加超过 20%，而主质量分未提升，
  判定不保留默认 relation 富化。
- 规则与五题金标在执行前冻结，不得按结果修改。

## 最终裁决

- r1 真实主线运行 10/10 全部成功；模型为冻结配置 `glm-5.3-flash`，temperature=0，并发 1，
  自动补跑 0，工具调用 0。
- relation/Claims/items 抽取调用 0；judge 0；publication/生产 query/生产库访问 0。
- 盲评解盲：Q1、Q4 为 A（items-only）更好；Q2、Q3 相同；Q5 控制题相同。B 在关系题提升
  0/4、回退 2/4、持平 2/4，并在 Q1 引入不可追溯表述，在 Q4 留下错误 challenges 的语义痕迹。
- B 相对 A 的中位输入 token 增加 24.33%，总 token 增加 40.74%；质量无提升，成本止损触发。
- 预注册保留门未通过。关闭默认 relation 富化，R2 默认交付 `material_items`；relations 仅保留为
  非阻断、按需实验能力，R2 验收重心回到 items 证据完整性。
- Issue 27 的 challenges 收紧保留，但不据此复活默认 relation 路线；gold-v2 未修改。

## 收口后的执行边界

- 当前 R2 不再继续修复、调参、换模或验收 relations；其质量门不再是 Claims/items 发布前置条件。
- 该结论是已经完成的负向业务价值裁决，不登记为待修复缺陷或未完成验收债务。
- 现有 relation 工件、协议和 Issue 27 防护仅保留作审计与未来实验资产，不进入默认查询上下文。
- 未来若有明确业务用例，必须新建版本，预注册独立价值门并取得单独预算授权；不得复用本票授权，
  不得通过修改 gold-v2、降低旧门槛或占用 material_items 收尾预算来重启。

## Evidence

- `../evidence/26-relation-layer-value-validation-20261010/r0-preflight/`
- `../evidence/26-relation-layer-value-validation-20261010/r1-live/`
