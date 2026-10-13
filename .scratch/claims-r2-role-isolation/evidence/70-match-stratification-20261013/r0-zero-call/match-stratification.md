# 34 条 matched 的匹配强度分层（代理启发式，非裁定）

- 2026-10-13　零模型调用　配对来源：A 工作表 26 + base 包 7 + r5 1 = **34**
- **这是机械分层，不是裁定**：每条都带 `flags`，可被人工推翻；层间优先序为
  `归一化需求 > 逐字 > 碎片 > 同义改写`。

| 层（强→弱） | 条数 | 判据 |
|---|---|---|
| **逐字一致** | 9 | 候选文本与金标命题/引文逐字相等或互为包含 |
| **同义改写** | 3 | 两侧互不包含，但相似度明显高 |
| **归一化后等价** | 22 | 需经 caliber_rules 归一化才能对齐（perspective/speech_role/statement_role/semantic_type 有差异） |
| **可恢复省略** | 0 | 候选是金标命题的碎片（长度比 < 0.6） |

## 交叉表（层不互斥，必须一起看）

| 层 | 条数 | 其中与金标**引文逐字相同** | 其中需归一化 | 其中是碎片 |
|---|---|---|---|---|
| 逐字一致 | 9 | 8 | 0 | 5 |
| 同义改写 | 3 | 0 | 0 | 0 |
| 归一化后等价 | 22 | 9 | 22 | 4 |
| 可恢复省略 | 0 | 0 | 0 | 0 |

## 严格度阶梯（同一批 34 对，按口径收紧）

| 口径 | 条数 | 召回 |
|---|---|---|
| ① 只认与金标引文逐字相同 | 17 | 17/48 = 0.354 |
| ② ＋ 文本互为包含 | 23 | 23/48 = 0.479 |
| ③ ＋ 同义改写（模糊相似） | 34 | 34/48 = 0.708 |
| ④ 契约口径（含 caliber 归一化后等价） | 34 | 34/48 = 0.708 |

> 34 条里有 **22 条**需要 `caliber_rules` 归一化才能对齐字段（perspective/speech_role/statement_role/semantic_type 差异）；
> 剔除它们只剩 **12 条**（9 逐字 + 3 同义）。**34 与更严口径之间的差额，取决于剔除哪一层——先定口径，再看数字。**

## 逐条明细

| # | 层 | 相似度 | gold | 候选文本 | 金标命题 | flags |
|---|---|---|---|---|---|---|
| 1 | 逐字一致 | 0.895 | NT-I07 | Q2 毛利率环比下降 0.36 个百分点。 | 2026Q2毛利率环比下降0.36个百分点 | containment |
| 2 | 逐字一致 | 0.32 | NT-I41 | 持有 + 观望。 | 报告作者对工业富联的总体建议是持有加观望 | equal、containment、fragment |
| 3 | 逐字一致 | 0.435 | NT-I02 | 中报的利润几乎是真的 | 工业富联中报利润质量较真实 | equal、containment |
| 4 | 逐字一致 | 0.609 | NT-I01 | 扣非 229.84 亿同比 +97% | 工业富联2026H1扣非净利润229.84亿元、同比增长97% | equal、containment、fragment |
| 5 | 逐字一致 | 0.65 | NT-I03 | 经营现金流 73.91 亿只盖住扣非的 0.32 倍 | 经营现金流仅覆盖扣非净利润0.32倍 | equal、containment |
| 6 | 逐字一致 | 0.529 | NT-I22 | 预计26年很少，26年就忽略不计 | 2026年CPO出货很少、可忽略不计 | equal、containment |
| 7 | 逐字一致 | 0.392 | NT-I13 | Q3 OCF/扣非回到 0.6 以上 | Q3经营现金流与扣非净利润之比达到0.6以上，是重新讨论观察仓的条件 | equal、containment、fragment |
| 8 | 逐字一致 | 0.489 | NT-I43 | 毛利率较 Q2 的 6.99% 不再回吐 | 毛利率不再低于Q2的6.99%，是重新讨论观察仓的条件之一 | equal、containment、fragment |
| 9 | 逐字一致 | 0.522 | NT-I06 | 中报验证了量 | 中报验证了AI相关业务的出货量增长 | equal、containment、fragment |
| 10 | 同义改写 | 0.714 | NT-I05 | 中报云计算收入同比增长 75.7%。 | 云计算业务增长75.7% | — |
| 11 | 同义改写 | 0.28 | NT-I44 | 有个OCS的快速看一下，渗透率反正都是吹牛的，都没准数的。 | 讲者质疑所转述的渗透率预测，认为没有可靠数字 | — |
| 12 | 同义改写 | 0.489 | NT-I28 | 整个流程下来最终拿到订单可能需要1年到1年半时间。 | 剑桥从送样到获得订单可能需要1年至1.5年 | — |
| 13 | 归一化后等价 | 0.326 | NT-I08 | 并表 7% 的加工费没有变成「系统商」。 | 当前毛利率没有证明工业富联已从加工费模式转变为系统商 | equal、containment、needs_caliber:semantic_type |
| 14 | 归一化后等价 | 0.643 | NT-I04 | 现金质量相对扣非是差的 | 工业富联现金质量相对扣非净利润较差 | equal、containment、needs_caliber:statement_role |
| 15 | 归一化后等价 | 0.114 | NT-I10 | 一旦毛利率再掉或 Rubin 延期，弹性会先打在倍数上 | 估值倍数会先受到冲击 | needs_caliber:statement_role |
| 16 | 归一化后等价 | 0.536 | NT-I20 | 墨西哥 / 美国厂是地理对冲，救不了出口管制一旦打到 GPU 系统集 | 墨西哥和美国工厂不能对冲GPU系统集成出口管制风险 | needs_caliber:semantic_type |
| 17 | 归一化后等价 | 0.8 | NT-I12 | 客户集中是结构风险 | 客户集中构成结构性风险 | equal、containment、needs_caliber:semantic_type |
| 18 | 归一化后等价 | 0.938 | NT-I11 | 2025 年前五大客户收入占比 62% | 2025年前五大客户占比62% | needs_caliber:statement_role |
| 19 | 归一化后等价 | 0.071 | NT-I35 | 公司所有说的话每个公司你都选择相信。 | 行业份额加总失真的前提 | containment、needs_caliber:statement_role |
| 20 | 归一化后等价 | 0.34 | NT-I37 | 实际上这出货量主要原因是1.6T影响了800G | 讲者以1.6T出货不及预期解释800G的出货表现 | needs_caliber:speech_role,statement_role |
| 21 | 归一化后等价 | 0.323 | NT-I40 | 你转嫁给客户不一定能够很好地转嫁的 | 新增税负未必能充分转嫁给客户 | equal、containment、needs_caliber:statement_role |
| 22 | 归一化后等价 | 0.091 | NT-I29 | 因为政策原因导致成本的上升 | 启动提价协商的条件 | equal、containment、needs_caliber:perspective,semantic_type,speech_role,statement_role |
| 23 | 归一化后等价 | 0.619 | NT-I30 | 会与客户协商，提价幅度在10%到20%之间 | 成本上升时计划与客户协商提价10%至20% | equal、containment、needs_caliber:perspective,semantic_type,speech_role,statement_role |
| 24 | 归一化后等价 | 0.486 | NT-I33 | CPO目前可以理解为还没有实际的出货，这个是真实情况。 | CPO目前尚无实际出货 | needs_caliber:statement_role |
| 25 | 归一化后等价 | 0.75 | NT-I32 | 主要群体北美的这些电力短缺的确会影响到公司出货节奏 | 北美电力短缺会影响公司出货节奏 | needs_caliber:semantic_type,statement_role |
| 26 | 归一化后等价 | 0.824 | NT-I21 | 市场成熟度不高 | CPO市场成熟度不高 | equal、containment、needs_caliber:statement_role |
| 27 | 归一化后等价 | 0.583 | NT-I27 | 剑桥在送样方面通常会经历一个为期六个月的实验室认证，之后再小批量。 | 剑桥送样通常需要六个月实验室认证 | needs_caliber:statement_role |
| 28 | 归一化后等价 | 0.452 | NT-I49 | 因为mems主要是要用300 | 讲者认为MEMS主要需要300端口 | equal、containment、needs_caliber:semantic_type,speech_role,statement_role |
| 29 | 归一化后等价 | 0.577 | NT-I25 | 在实际研发当中，128的光波导经过五个批次的流片后，良率仍然不乐观， | 128端口光波导五次流片后良率仍不理想 | needs_caliber:statement_role |
| 30 | 归一化后等价 | 0.103 | NT-I16 | 止损看两条硬的 | 若任一指定硬性恶化条件触发，考虑执行止损；这是意向而非已执行行为 | equal、containment、fragment、needs_caliber:semantic_type |
| 31 | 归一化后等价 | 0.279 | NT-I14 | 等两件事至少中一件再议 | 从零开观察仓须等待至少一个指定条件满足后再讨论，并非立即建仓承诺 | containment、fragment、needs_caliber:semantic_type,statement_role |
| 32 | 归一化后等价 | 0.267 | NT-I42 | 回撤到 52–58 | 股价回撤至52—58元且无新的大额负面管制公告，是重新讨论观察仓的条 | containment、fragment、needs_caliber:semantic_type |
| 33 | 归一化后等价 | 0.095 | NT-I15 | 下季 OCF 盖不住扣非的一半 | 止损触发条件之一 | containment、needs_caliber:semantic_type |
| 34 | 归一化后等价 | 0.515 | NT-I17 | 毛利率较 6.99% 再掉超过 1 个百分点 | 毛利率较6.99%再降超过1个百分点，且公司改口涨价/mix受阻、R | containment、fragment、needs_caliber:semantic_type |
