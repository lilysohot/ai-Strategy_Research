# R2 item 验收契约 v2：冻结与 v12 零调用回放

日期：2026-09-14  
状态：**契约已冻结；v12 回放失败；允许最后一次结构化字段优化**  
模型调用：0；holdout：0；关系调用：0；入库：0

## 冻结内容

新策略 `r2-item-acceptance-policy-v2.json` 绑定 R1 金标、六个微型穷举范围、v12 原报告和 v12 预算
的 SHA-256。它只作为最后一次 item 优化的前瞻口径，不覆盖或修改 v12 原 scorer 结论。

item 身份采用一对一匹配：优先允许“预测短引文唯一包含于一个金标长引文”，否则使用冻结的 0.5
规范化相似度。短引文仍必须在对应 source revision 的 packet 中按 start/end 精确且唯一回取；一个
短引文若能落入多个金标 item，则不能使用包含关系放行。

字段验收不再要求自由文本 `unknown_fields` 集合逐字相等，但也不忽略未知项：将身份、时间、数值、
外部核验、归属和话轮切分归一为六类 uncertainty axis，并要求全部需要保留的轴被显式表达。
行为的 `behavior_status` 和 `temporal_frame` 只在 behavior item 上精确检查；其余核心语义、表达结构、
视角、极性、表达者类别和 identity status 继续严格检查。

## v12 零调用回放

| 指标 | v12 | 门槛 | 结果 |
|---|---:|---:|---|
| item recall | 100% | 100% | 通过 |
| item precision | 100% | 100% | 通过 |
| semantic accuracy | 91.4% | 90% | 通过 |
| speech structure | 57.1% | 100% | 失败 |
| attribution | 85.7% | 100% | 失败 |
| polarity | 94.3% | 100% | 失败 |
| condition/risk retention | 100% | 100% | 通过 |
| behavior state + temporal | 0/2 | 2/2 | 失败 |
| value accuracy | 80% | 100% | 失败 |
| evidence unique alignment | 100% | 100% | 通过 |
| uncertainty axis recall | 6/50（12%） | 50/50 | 失败 |
| unsupported statement precision | 100% | >=95% | 通过 |

关键错误共 9 个：极性 2，行为状态/时间 2，归属 5。归属错误分布在行业问答 1、铜箔总结 1、
铜箔引用论据 3；没有证据回取、条件或风险关键错误。

## 设计判断

原子义务与内容覆盖已经收敛：37/37 终态、35/35 item、35/35 唯一证据。剩余失败不应再通过增加
文档切分规则或重复抽取解决，而应把可观察字段转成系统拥有的有限结构：

1. 从编号问答/显式话轮结构确定 `speech_role`，模型不得把 answer 回退成普通 statement。
2. 由槽位 attribution capability、显式角色、summary/document voice 和 quoted frame 决定表达者及
   perspective；模型只填写无法确定的语义内容。
3. 行为时间由 today/yesterday/复盘等原文标志确定；模型不得把明确 contemporaneous 写成 unknown。
4. 极性在逐字引文上确定性校正，保留“不及预期/不必然/没”等否定。
5. 将 `unknown_fields` 的自由字符串输出降级为审计原文，新增系统归一 uncertainty axes；否则跨模型
   无法稳定比较“author_identity”和“speaker_identity”等同类未知。
6. 数值由 item 引文中的明确 span 确定性标准化；无明确值保持 null。

这构成此前约定的最后一次优化机会。完成离线实现和测试后，必须先用本策略 plan-only 验证 scorer
与槽位未漂移，再另行冻结最后一个有限 item 预算。若该轮仍有任一关键错误或未达门槛，应停止当前
R2 设计，且不得进入关系抽取。

## 产物

- 策略：`r2-item-acceptance-policy-v2.json`
  （SHA-256 `c0fed47f53ddc6b7966a32a30054e4a87c28914234077a0dc2b5122775473852`）
- 验收器：`verify_material_item_contract_v2.py`
  （SHA-256 `442ff9c69d3266ba137cc662befe13d7041e1e7ceb5fdf55277107939fe361a6`）
- 回放：`material-semantics-runs/item-contract-score-v2-76525bcdee094fbb621db58a802afad78faeabc0f4573b4c61e8f45520c41e51.json`
  （SHA-256 `ea50201370d6fa318efbfe7bd90496bb465d4b5089850f006fc57a3f93dcacc3`）
- 验证：Ruff 通过，Pyright 0 errors，R2 material semantics 单测 34 passed。

## 最终执行结果

v13 系统字段改造使用 v12 原始响应零调用回放后，item v2 全门通过：35/35 item，semantic 94.29%，
其余核心字段、证据和 uncertainty axis 均为 100%，关键错误 0。随后冻结的最终真实模型轮仍以
34/35 item recall 失败；唯一缺失来自模型选择了 packet 内重复出现的“‘强推’评级”短引文，记录被
唯一回取校验拒绝。按本契约预先写明的 stop rule，当前 R2 设计停止，关系阶段不启动。详见
[v13 最终 item 验收报告](material-semantics-v13-final-item-report.md)。
