# R2 v12 同规模 item 复验报告

日期：2026-09-14  
状态：**终态协议通过；冻结 item 总门未通过；关系继续冻结**  
范围：development only；4 类材料、6 个穷举微范围；不入库、不访问 holdout

## 预算与执行

- 新预算：`r2-v12-atomic-items-budget-v6.json`
- 预算 SHA-256：`d6a3e15300255f4a73e9ed6e8a7bc712fdc9b996f1e92b02c3aea545b49d47ca`
- 冻结 37 个系统槽；每批最多 6 槽；批次为 2+3+1+3；计划/总上限均为 9 次。
- 唯一轮次：`v12-terminal-items`；实际 9 次，无重试。
- 用量：prompt 11,342 tokens，completion 5,022 tokens。
- 关系调用 0、holdout 0、入库 0。
- 主报告：`material-semantics-runs/report-09b119120285666aac93fcb41ce1f8c0ebe3c4bb563f50a964bdc30b0b301b40.json`
  （SHA-256 `ac6acd4aee29aa13e4e2903c3b217692093521135def82b9a6c05489d06b151a`）。
- 微型评分：`material-semantics-runs/micro-score-4b352a608fbf40cba2cb22f3e9e4a84d723993408983a3b67db5fa27d917f13e.json`
  （SHA-256 `5400ae32587a400ab6d05e2f54f1bdad58d39e6cd2afd50f612293a2b12871fa`）。

## 分层判定

### 1. item 终态协议：通过

37/37 槽均恰好得到合法终态：

- 公司研报：7 extracted；
- 行业问答：14 extracted；
- 个人复盘：4 extracted + 2 no-supported；
- 铜箔纪要：10 extracted。

没有 failed/partial 槽，没有重复 item，没有缺终态。v11 的漏槽 ID、问句过切、词法信号误拒和
“明白”寒暄槽均未复现。因此“系统生成有限原子义务，模型逐项填写”的结构机制获得验证。

主报告中的 packet `partial` 仅来自预算显式设置 `relation_mode=deferred`，不能反向解释为 item 槽不完整。

### 2. 冻结微型 item 门：失败

冻结 scorer 结果为 33/35 recall、33/35 precision（均为 94.29%）：

| 微范围 | 命中/金标 | 预测 | 结果 |
|---|---:|---:|---|
| 公司研报推荐段 | 7/7 | 7 | 通过 |
| 行业问答 Q7-Q8 | 14/14 | 14 | 通过 |
| 个人复盘 TTD | 4/4 | 4 | 通过 |
| 铜箔总结 | 0/1 | 1 | 失败 |
| 铜箔听音 | 0/1 | 1 | 失败 |
| 铜箔良品率问答 | 8/8 | 8 | 通过 |

两个失败范围都存在且仅存在一个对应预测 item。预测引文分别是金标长引文中的唯一短子串：总结使用
“总体而言，铜箔设备行业正处于国产替代加速期”，听音使用“请问能听到吗”。这符合抽取提示中的
“最短唯一引文”，但冻结 scorer 以引文长度相似度匹配，因短引文比例低于 0.5 而把它们判成两个漏项
和两个额外项。

零模型 containment 审计可将两条唯一映射回对应金标，内容定位为 35/35；但这是执行后的诊断，不能
追溯修改冻结口径并宣称 v12 总门通过。

### 3. item 字段契约：仍未通过

使用上述唯一 containment 映射对 35 条作零模型字段审计：semantic_type 91.4%、statement_role 60%、
speech_role 60%、perspective 85.7%、polarity 94.3%、behavior_status 100%、speaker role 88.6%。
`temporal_frame` 精确一致 14.3%、`unknown_fields` 精确集合一致 11.4%，说明这两个字段的现有金标/提示/
评分定义仍不一致；不能把它们的低分全部当作内容抽取失败。35 条中没有一条达到当前“所有字段逐项
精确相等”的口径。

## 决策

v12 证明了结构层已经收敛，但没有完成完整 item 验收。预算停止条件包含 item recall/precision 必须
为 100%，所以本轮正式判为失败，关系预算不冻结、不执行。

这轮同时消耗了此前约定的第一次数量受限优化机会。R2 当前只剩一次值得投入的优化机会，并且重点
不应再是增加文档结构规则或重复调用模型，而应先离线重构验收契约：

1. 冻结“item 身份匹配”规则，允许唯一、可回取的短引文映射到包含它的长金标引文，同时防止一个
   短引文匹配多个金标；新 scorer 必须改版本，不能覆盖本轮结果。
2. 将结构完整性与字段正确性分开评分；明确 statement_role/speech_role 的问答继承口径。
3. `temporal_frame` 只对行为或明确时态字段设硬门；`unknown_fields` 改为“不补造/未知诚实性”，不再
   要求人工枚举集合逐字相等。
4. 在任何新模型预算前，用 v10/v11/v12 已有 artifact 做零调用回放，证明新口径不会只修复这两条、
   也不会放过错误 item。

只有上述评分契约冻结并通过历史回放后，才值得决定是否进行最后一次 item 复验。最后一次仍不能同时
达到内容定位、核心字段和跨类目不退化时，应停止当前 R2 设计；不应进入关系阶段。

## 后续：item 验收契约 v2

上述口径已在零模型条件下冻结为 `r2-item-acceptance-policy-v2.json`，并用独立版本 scorer 回放
本轮。唯一包含匹配确认 35/35 item 和 35/35 唯一证据；但 speech structure 57.1%、attribution
85.7%、polarity 94.3%、behavior state + temporal 0/2、value 80%、uncertainty axis 6/50，关键
错误 9 个，仍失败。该结果不改写上文 v12 原 scorer。

最后一次优化必须转向系统接管表达结构、归属、行为时间、极性、数值和受控未知轴；若仍失败则停止
当前 R2。详见 [item 验收契约 v2 报告](material-semantics-item-contract-v2-report.md)。
