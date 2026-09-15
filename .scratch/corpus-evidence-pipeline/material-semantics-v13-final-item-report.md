# R2 v13 最终 item 验收报告

日期：2026-09-14  
状态：**最终 item 门失败；当前 R2 设计停止；关系阶段禁止启动**  
范围：development only；4 类材料、6 个穷举微范围；不入库、不访问 holdout

## 预算与执行

- 冻结预算：`r2-v13-final-items-budget-v7.json`
  （SHA-256 `300437b718abb8d9f890327be375c23c083bae1f8ba2a91108dc5b4d6a960e7f`）。
- 预算绑定 v13 extractor、item acceptance policy v2、scorer v2，以及通过的 v12 原始响应零调用回放。
- 范围保持为原来的 4 个 development 类目、6 个微型穷举范围、37 个系统槽。
- 唯一轮次 `v13-final-items` 实际消费 9/9 次调用，无重试；prompt 11,342 tokens，completion
  5,175 tokens。
- 关系调用 0、holdout 调用 0、入库 0。
- 主执行报告：
  `material-semantics-runs/report-46caccfc1c7d23ef3858a8a501560c07b250888b0b3f189fdff75d8ba6bc6b4b.json`
  （SHA-256 `34cc841e98257580889681907f86cce54003f4a46e5df8f14df451fbd502f8ab`）。
- item v2 评分：
  `material-semantics-runs/item-contract-score-v2-203a306ebfc2dc881fbbffc78a76b08d771a5b5c596c4cde87c3adadd40a04f0.json`
  （SHA-256 `ffcedfe0c35bfbcd1c2035f87ed26a820425aac5865e892e7ef70637a1ccfd76`）。

## 模型调用前证据

v13 系统字段改造先复用 v12 的 9 份原始响应做零模型回放。回放达到 35/35 item、35/35 唯一证据，
speech structure、attribution、polarity、behavior state + temporal、value 和 uncertainty axis 均为
100%，semantic accuracy 为 94.29%，关键错误为 0。随后 381 项 corpus 回归、Ruff、目标 Pyright、
两阶段 import smoke（336/336、385/385）和 435 文件 symbol closure 均通过。

这证明 v13 的系统字段修正有效且没有在已有 corpus 类目测试中造成退化，但离线回放不能替代一次
独立真实模型复验。

## 最终 item v2 结果

| 指标 | 结果 | 门槛 | 判定 |
|---|---:|---:|---|
| item recall | 34/35（97.14%） | 100% | 失败 |
| item precision | 34/34（100%） | 100% | 通过 |
| semantic accuracy | 31/34（91.18%） | >=90% | 通过 |
| speech structure | 34/34（100%） | 100% | 通过 |
| attribution | 34/34（100%） | 100% | 通过 |
| polarity | 34/34（100%） | 100% | 通过 |
| condition/risk retention | 4/4（100%） | 100% | 通过 |
| behavior state + temporal | 2/2（100%） | 100% | 通过 |
| value | 34/34（100%） | 100% | 通过 |
| evidence unique alignment | 34/34（100%） | 100% | 通过 |
| uncertainty axis recall | 50/50（100%） | 100% | 通过 |
| unsupported statement precision | 100% | >=95% | 通过 |
| critical errors | 1 | 0 | 失败 |

槽位终态为 36/37：行业问答 14/14、个人复盘 6/6、铜箔纪要 10/10 均有终态；公司研报 7 槽中
6 个 extracted、1 个 partial。

## 唯一失败的直接原因

缺失金标是 `mc-rating`，对应系统槽 `slot_91de9db963452478`，原文槽为“和‘强推’评级”。模型确实
返回了“维持‘强推’评级”item，字段及 `candidate_slot_id` 均存在，但选择的最短证据引文
“‘强推’评级”在同一 source packet 中出现两次。当前 `_align_quote` 在绑定槽位前执行 packet 级唯一
回取，因此该记录以 `item_failed_validation` 被拒绝，槽位最终标记为
`partial / missing_signal:claim`。

这不是文档没有该信息，也不是语义字段抽取失败；它说明当前方案虽然由系统生成了原子槽位，仍把
证据 span 的最终选择交给模型。模型返回一个语义正确但 packet 内不唯一的短引文时，系统无法利用
已冻结槽位边界消歧，也没有系统生成的唯一证据锚点作为义务的一部分。

## 决策

冻结停止规则规定：最终有限 item 轮任一 v2 阈值未达标，就停止当前 R2 设计，不运行关系抽取。
因此：

1. v13 不通过 R2 验收，不能用 34/35 或其他字段全通过作豁免。
2. 不追加修补轮、不重试模型、不访问 holdout、不入库。
3. 不冻结关系预算，R3 继续不启动。
4. v13 已验证有效的系统字段修正可以保留为实验实现，但不得标记为生产验收通过。
5. 如果未来重新立项 R2，应更换设计版本：系统不仅生成原子义务，还必须生成唯一 evidence span；
   模型只逐项填写受限语义字段或拒绝，不再自由选择用于身份和回取的引文。

该方向属于新的 R2 设计，而不是 v13 的继续优化，必须重新冻结范围、验收契约和预算后才能执行。
