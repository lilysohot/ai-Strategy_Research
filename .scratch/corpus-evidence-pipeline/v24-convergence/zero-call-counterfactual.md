# material-semantics-24 零调用反事实复盘

日期：2026-10-09。真实模型调用：**0**。生产数据库、holdout、发布和 M_main：**均未访问**。

## 结论

v8 的主要问题不是 16 槽批容量。43 份保存响应全部以 `finish_reason=stop` 结束，最高 completion tokens 为
3510，低于配置上限 8192；失败也不集中在批尾。把同一批响应和同一组冻结槽位交给
`material-semantics-24` 重放后，65 个 partial 槽中 **51 个转为 extracted**，剩余 14 个。

这 51 个翻转来自确定性后处理而不是重新询问模型：

- `claim`/`summary` 软信号不再阻断完整性；
- `question`/`evidence` 被误填到 `semantic_type` 时，在与 `statement_role` 一致的条件下归一到
  `unknown`，不再丢弃合法 item；
- 已验证的 `candidate_slot_id` 把引文唯一性限定在本槽，未知槽 ID 仍保持 packet 级唯一、fail closed；
- `item_failed_validation` 现在保留稳定的 quote/schema/scope 原因，不再只有一个总括码。

## 数字

| 项目 | v8 实际 | v24 固定槽反事实 |
|---|---:|---:|
| partial slots | 65 | 14 |
| item_failed_validation slots | 22 | 8 |
| terminal_record_missing slots | 1 | 1 |
| partial packets | 7 | 6 |
| completed candidate packets | 0 | 1 |

逐材料 partial 槽：company `9→3`，industry QA `8→2`，trade review `0→0`，copper foil
`48→9`。

剩余 14 个 partial 槽中：8 个存在跨越当前槽边界的模型引文，1 个真实缺少终态，另外 5 个属于硬信号或
终态语义未闭合。跨槽引文继续 fail closed；本轮没有为追求通过而放宽证据边界。

## 通用切分修复

v24 进一步修复了报告标题、HTML/CSS、常见元数据冒号和“分析完之后／第二个问题”等短引导语造成的
碎片槽，并清退四条样本专用 boundary pattern。确定性计划从 43 次降为 42 次：候选槽分别为
`65 / 52 / 11 / 487`；冻结 gold 的严格覆盖损失为 0。

## 下一道且唯一一道真实门

[v10 预算](../r2-extraction-convergence-development-budget-v10.json) 将执行一次 42-call、item-only、
单轮 development 复验。通过则冻结 v24 并离开抽取节点；失败则停止新增 v11 提示词/词表补丁，转为
重构抽取接口或分阶段模型。该轮不测 relations，也不声称把收益归因于单一改动。

证据：

- [v8 source report](../material-semantics-runs/report-e54423a80d6df2eeefe40b34ddabd2040e3f298e48aeaa368c2393274dd46ac7.json)
- [v24 fixed-shape replay](../material-semantics-runs/raw-replay-eda771486850cfdbeff9d8d7be362ba6673156a8d73ba716ce80e65108146c70.json)
- [机器可读摘要](zero-call-counterfactual.json)
