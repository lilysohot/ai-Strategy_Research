# V14 S5 全量矩阵失败题目人工复核清单

- 矩阵：204/204 次会话
- 失败会话：42
- 涉及题目：19
- 冻结 holdout：保持不变；本清单只读取结果和参考证据。
- 判定列可点击打开对应会话的 `result.json`，查看完整回答与 Judge 输出。

## 总览

| # | 稳定性 | target_id | 领域/证据角色 | Control | Candidate R1 | Candidate R2 | Candidate R3 |
|---:|---|---|---|---|---|---|---|
| 1 | 持续失败 4/4 | `2f8aa709-fedtable` | macro / supplementary | [❌ fail](../../.s5runs_v14_full/control/2f8aa709-fedtable/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/2f8aa709-fedtable/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/2f8aa709-fedtable/run-02/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/2f8aa709-fedtable/run-03/result.json) |
| 2 | 持续失败 4/4 | `a91d95c7-cxmt` | industry / required | [❌ fail](../../.s5runs_v14_full/control/a91d95c7-cxmt/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/a91d95c7-cxmt/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/a91d95c7-cxmt/run-02/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/a91d95c7-cxmt/run-03/result.json) |
| 3 | 持续失败 4/4 | `b7e932c8-index` | industry / required | [❌ fail](../../.s5runs_v14_full/control/b7e932c8-index/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/b7e932c8-index/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/b7e932c8-index/run-02/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/b7e932c8-index/run-03/result.json) |
| 4 | 持续失败 4/4 | `f3b28791-table1` | macro / required | [❌ fail](../../.s5runs_v14_full/control/f3b28791-table1/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/f3b28791-table1/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/f3b28791-table1/run-02/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/f3b28791-table1/run-03/result.json) |
| 5 | 持续失败 4/4 | `f7f65d7e-risk` | macro / supplementary | [❌ fail](../../.s5runs_v14_full/control/f7f65d7e-risk/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/f7f65d7e-risk/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/f7f65d7e-risk/run-02/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/f7f65d7e-risk/run-03/result.json) |
| 6 | 高频失败 3/4 | `5e305376-nonfarm` | macro / required | [❌ fail](../../.s5runs_v14_full/control/5e305376-nonfarm/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/5e305376-nonfarm/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/5e305376-nonfarm/run-02/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/5e305376-nonfarm/run-03/result.json) |
| 7 | 高频失败 3/4 | `d179b615-chart3` | macro / required | [✅ pass](../../.s5runs_v14_full/control/d179b615-chart3/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/d179b615-chart3/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/d179b615-chart3/run-02/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/d179b615-chart3/run-03/result.json) |
| 8 | 高频失败 3/4 | `d179b615-hikerate` | macro / required | [❌ fail](../../.s5runs_v14_full/control/d179b615-hikerate/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/d179b615-hikerate/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/d179b615-hikerate/run-02/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/d179b615-hikerate/run-03/result.json) |
| 9 | 高频失败 3/4 | `d179b615-passive` | macro / required | [❌ fail](../../.s5runs_v14_full/control/d179b615-passive/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/d179b615-passive/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/d179b615-passive/run-02/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/d179b615-passive/run-03/result.json) |
| 10 | 偶发失败 1/4 | `0c25f0e9-eptable` | industry / required | [✅ pass](../../.s5runs_v14_full/control/0c25f0e9-eptable/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/0c25f0e9-eptable/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/0c25f0e9-eptable/run-02/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/0c25f0e9-eptable/run-03/result.json) |
| 11 | 偶发失败 1/4 | `0c25f0e9-figure35` | industry / required | [❌ fail](../../.s5runs_v14_full/control/0c25f0e9-figure35/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/0c25f0e9-figure35/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/0c25f0e9-figure35/run-02/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/0c25f0e9-figure35/run-03/result.json) |
| 12 | 偶发失败 1/4 | `2f8aa709-oil` | macro / required | [❌ fail](../../.s5runs_v14_full/control/2f8aa709-oil/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/2f8aa709-oil/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/2f8aa709-oil/run-02/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/2f8aa709-oil/run-03/result.json) |
| 13 | 偶发失败 1/4 | `b7e932c8-pmi` | industry / supplementary | [❌ fail](../../.s5runs_v14_full/control/b7e932c8-pmi/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/b7e932c8-pmi/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/b7e932c8-pmi/run-02/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/b7e932c8-pmi/run-03/result.json) |
| 14 | 偶发失败 1/4 | `c1ddcd8a-summarytable` | industry / supplementary | [❌ fail](../../.s5runs_v14_full/control/c1ddcd8a-summarytable/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/c1ddcd8a-summarytable/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/c1ddcd8a-summarytable/run-02/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/c1ddcd8a-summarytable/run-03/result.json) |
| 15 | 偶发失败 1/4 | `f3b28791-fedwatch` | macro / required | [✅ pass](../../.s5runs_v14_full/control/f3b28791-fedwatch/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/f3b28791-fedwatch/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/f3b28791-fedwatch/run-02/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/f3b28791-fedwatch/run-03/result.json) |
| 16 | 偶发失败 1/4 | `f3b28791-rotation` | macro / required | [✅ pass](../../.s5runs_v14_full/control/f3b28791-rotation/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/f3b28791-rotation/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/f3b28791-rotation/run-02/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/f3b28791-rotation/run-03/result.json) |
| 17 | 偶发失败 1/4 | `f7f65d7e-alloc` | macro / required | [✅ pass](../../.s5runs_v14_full/control/f7f65d7e-alloc/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/f7f65d7e-alloc/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/f7f65d7e-alloc/run-02/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/f7f65d7e-alloc/run-03/result.json) |
| 18 | 偶发失败 1/4 | `f7f65d7e-payroll` | macro / required | [✅ pass](../../.s5runs_v14_full/control/f7f65d7e-payroll/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/f7f65d7e-payroll/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/f7f65d7e-payroll/run-02/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/f7f65d7e-payroll/run-03/result.json) |
| 19 | 偶发失败 1/4 | `f86c6d2c-wuqi-order` | industry / required | [✅ pass](../../.s5runs_v14_full/control/f86c6d2c-wuqi-order/run-01/result.json) | [❌ fail](../../.s5runs_v14_full/candidate/f86c6d2c-wuqi-order/run-01/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/f86c6d2c-wuqi-order/run-02/result.json) | [✅ pass](../../.s5runs_v14_full/candidate/f86c6d2c-wuqi-order/run-03/result.json) |

## 逐题复核

### 1. 2f8aa709-fedtable — 持续失败 4/4

**问题：** 报告中美联储官员沃什、威廉姆斯、沃勒对通胀与加息的表态各是什么？

**来源：** `2026-09-06_2026.09.06-国金证券-a股策略周报-迷雾与罗盘-fb9b3c67.pdf`；定位：`page:3`

**冻结参考证据：** 美联储官员 表态 通胀仍是第一优先级：通胀仍然高于2%的目标，因此美联储当前的主要关注点应该放在价格上；以PCE衡量的2%目标是坚定、固定的目标。

**可接受证据规则：** 需指出该表为美联储官员(沃什/威廉姆斯/沃勒)对通胀与加息政策的表态汇总，沃什主张通胀为第一优先级且对2%通胀目标坚定

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [❌ fail](../../.s5runs_v14_full/control/2f8aa709-fedtable/run-01/result.json) | 是 | 0 | 493.7 |
| Candidate R1 | [❌ fail](../../.s5runs_v14_full/candidate/2f8aa709-fedtable/run-01/result.json) | 是 | 0 | 604.9 |
| Candidate R2 | [❌ fail](../../.s5runs_v14_full/candidate/2f8aa709-fedtable/run-02/result.json) | 是 | 0 | 551.9 |
| Candidate R3 | [❌ fail](../../.s5runs_v14_full/candidate/2f8aa709-fedtable/run-03/result.json) | 是 | 0 | 573.9 |

**失败会话的 Judge 原因：**

- **Control：** 回答中威廉姆斯、沃勒的通胀与加息表态内容未在参考证据中得到支持，属于编造信息，不符合通过要求。
- **Candidate R1：** 模型回答中关于威廉姆斯、沃勒的通胀与加息表态内容未被参考证据支持，且参考证据仅明确沃什的相关表态，未覆盖另外两位官员的对应信息，不符合问题要求。
- **Candidate R2：** 模型回答未提供沃什、威廉姆斯、沃勒三人关于通胀与加息的具体表态，仅提及报告块的位置，未满足问题要求。
- **Candidate R3：** 回答中威廉姆斯、沃勒的通胀与加息表态、沃什的额外表态及相关市场影响内容均未被参考证据支持，仅沃什的部分表态符合要求，且未完整覆盖三位官员的全部要求内容。

人工复核：

- [ ] Judge 判定正确
- [ √] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：没问题，回答内容检索了资料库的其他内容

### 2. a91d95c7-cxmt — 持续失败 4/4

**问题：** 长鑫存储 LPDDR6 内存落地商用在产业上意味着什么？

**来源：** `2026-09-06_2026.09.06-国金证券-通信行业研究-hbm市场极度紧缺-字节获296亿美元银团贷款-7ee005e2.pdf`；定位：`page:1`

**冻结参考证据：** 长鑫存储LPDDR6 内存正式量产，实现全球首次落地商用，标志着中国存储企业首次在高端内存标准上打破海外厂商长期垄断产品先发的局面

**可接受证据规则：** 第 1 页通信周观点第 6 点证据，须包含长鑫存储 LPDDR6 内存正式量产、全球首次落地商用、中国存储企业首次在高端内存标准打破海外垄断。

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [❌ fail](../../.s5runs_v14_full/control/a91d95c7-cxmt/run-01/result.json) | 否 | 0 | 958.7 |
| Candidate R1 | [❌ fail](../../.s5runs_v14_full/candidate/a91d95c7-cxmt/run-01/result.json) | 否 | 0 | 747.4 |
| Candidate R2 | [❌ fail](../../.s5runs_v14_full/candidate/a91d95c7-cxmt/run-02/result.json) | 否 | 0 | 1111.2 |
| Candidate R3 | [❌ fail](../../.s5runs_v14_full/candidate/a91d95c7-cxmt/run-03/result.json) | 否 | 0 | 881.1 |

**失败会话的 Judge 原因：**

- **Control：** 模型回答未回应长鑫存储LPDDR6内存落地商用的产业意义，未包含参考证据要求的核心事实，属于答非所问。
- **Candidate R1：** 回答虽包含参考证据要求的核心事实，但大量内容未被给定参考证据支持，属于编造的外部信息，不符合验收要求。
- **Candidate R2：** 回答虽包含参考证据要求的核心事实，但大量引入参考证据未提及的DRAM格局、供需价格、产业链拉动、风险等扩展内容，超出给定参考证据的支持范围。
- **Candidate R3：** 模型回答包含大量参考证据未提及的内容，如长鑫存储的成立时间、全球DRAM排名、HBM3E相关信息、存储行业周期数据、国产AI算力链影响、资本市场表现、风险提示等，超出参考证据范围，不符合验收要求。

人工复核：

- [ ] Judge 判定正确
- [√ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：证据存在第一页，定位没问题。回答内容用了资料库的其他内容，没问题

### 3. b7e932c8-index — 持续失败 4/4

**问题：** 本周A股各主要宽基指数表现如何，上证综指、沪深300、创业板指等分别涨跌了多少？

**来源：** `2026-09-05_2026.09.05-中信建投-行业数据周报9月第1期-市场普遍下跌-机构低配板块表现居前-a6a30359.pdf`；定位：`page:2`

**冻结参考证据：** 本周主要宽基指数普遍下跌 ，上证综指、东财全A分别下跌0.56%、1.20%，沪深300下跌1.33%；成长风格方面 ，创业板指下跌 4.03%，科创50下跌5.10%

**可接受证据规则：** 研报本周市场回顾或指数图表给出上证综指-0.56%、东财全A-1.20%、沪深300-1.33%、创业板指-4.03%、科创50-5.10%等任一指数周涨跌幅即为可接受证据。

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [❌ fail](../../.s5runs_v14_full/control/b7e932c8-index/run-01/result.json) | 是 | 0 | 554.7 |
| Candidate R1 | [❌ fail](../../.s5runs_v14_full/candidate/b7e932c8-index/run-01/result.json) | 是 | 0 | 583.7 |
| Candidate R2 | [❌ fail](../../.s5runs_v14_full/candidate/b7e932c8-index/run-02/result.json) | 是 | 0 | 645.4 |
| Candidate R3 | [❌ fail](../../.s5runs_v14_full/candidate/b7e932c8-index/run-03/result.json) | 是 | 0 | 404.7 |

**失败会话的 Judge 原因：**

- **Control：** 回答中上证综指、沪深300、创业板指的涨跌幅与参考证据一致，但编造了深证成指、中证500等多个未在参考证据中提及的指数涨跌幅，还虚构了上证50微涨的结论，与参考证据中“主要宽基指数普遍下跌”的表述矛盾，存在大量无依据的编造内容。
- **Candidate R1：** 模型回答编造了数据覆盖时间、研报来源及上证50、中证500等多个未在参考证据中出现的指数涨跌幅，未按要求提供本周A股主要宽基指数的涨跌数据。
- **Candidate R2：** 模型回答中上证综指、沪深300、创业板指的周涨跌幅与参考证据一致，但编造了参考证据未提及的2026年8月31日-9月4日的统计区间、上证50、深证成指等多个指数的涨跌幅及点位数据，还虚构了多份研报来源，不符合验收要求。
- **Candidate R3：** 回答中上证综指、沪深300、创业板指、科创50、东财全A的涨跌幅与参考证据一致，但编造了上证50、中证500、中证1000、中证2000的涨跌幅及行业涨跌、ETF净申购等参考证据未提及的内容，不符合要求。

人工复核：

- [ √] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：模型拿到正确信息，但是把页中的图标信息也返回了

### 4. f3b28791-table1 — 持续失败 4/4

**问题：** 兴业证券表1中，7月以来2026E净利润上修的典型细分方向包括哪些？电子光学光电子的数据如何？

**来源：** `2026-09-06_2026.09.06-兴业证券-极致轮动如何收敛-探讨几个契机-733fc399.pdf`；定位：`page:9`

**冻结参考证据：** 板块 一级行业 二级行业 7 月以来 2026E 净利润上修幅度 2026 年预测净利润增速 7 月以来 涨跌幅 年初以来 涨跌幅 龙一 龙二 龙三 AI 算力硬件 电子 光学光电子 27.1% 194% -29.6% 6.9% 京东方 A 惠科股份 TCL 科技

**可接受证据规则：** 需给出电子光学光电子行：上修幅度27.1%、预测增速194%、7月以来涨跌幅-29.6%、年初以来6.9%、龙头京东方A/惠科股份/TCL科技

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [❌ fail](../../.s5runs_v14_full/control/f3b28791-table1/run-01/result.json) | 否 | 0 | 919.7 |
| Candidate R1 | [❌ fail](../../.s5runs_v14_full/candidate/f3b28791-table1/run-01/result.json) | 否 | 0 | 585.5 |
| Candidate R2 | [❌ fail](../../.s5runs_v14_full/candidate/f3b28791-table1/run-02/result.json) | 否 | 0 | 627.6 |
| Candidate R3 | [❌ fail](../../.s5runs_v14_full/candidate/f3b28791-table1/run-03/result.json) | 否 | 0 | 553.5 |

**失败会话的 Judge 原因：**

- **Control：** 模型回答未提及7月以来2026E净利润上修的典型细分方向，也未提供电子光学光电子的相关数据，完全未响应问题要求。
- **Candidate R1：** 模型回答中除电子光学光电子行的指定数据外，其余18个细分方向的相关数据均未在参考证据中出现，属于编造内容，不符合验收要求。
- **Candidate R2：** 模型回答中除电子-光学光电子的相关数据符合参考证据外，其余18个细分上修方向、上修幅度、排名、反方证据等内容均无参考证据支持，属于编造。
- **Candidate R3：** 回答中除电子光学光电子的相关数据符合参考证据外，其余大量细分方向、上修幅度、排名、风险提示等内容均无参考证据支持，属于编造信息。

人工复核：

- [ ] Judge 判定正确
- [√ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：模型返回了完整的表格内容，核验模型可能无法正确解析表格内容

### 5. f7f65d7e-risk — 持续失败 4/4

**问题：** 本期研报列出了哪些主要风险提示？

**来源：** `2026-09-06_2026.09.06-天风证券-a股策略周报-非农大超预期-加息预期升温-5e671b67.pdf`；定位：`page:9`

**冻结参考证据：** 地缘冲突超预期，海外通胀持续性超预期，流动性收紧超预期。

**可接受证据规则：** 复述三项风险提示：地缘冲突超预期、海外通胀持续性超预期、流动性收紧超预期

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [❌ fail](../../.s5runs_v14_full/control/f7f65d7e-risk/run-01/result.json) | 是 | 0 | 1463.6 |
| Candidate R1 | [❌ fail](../../.s5runs_v14_full/candidate/f7f65d7e-risk/run-01/result.json) | 否 | 0 | 1114.3 |
| Candidate R2 | [❌ fail](../../.s5runs_v14_full/candidate/f7f65d7e-risk/run-02/result.json) | 是 | 0 | 1082.1 |
| Candidate R3 | [❌ fail](../../.s5runs_v14_full/candidate/f7f65d7e-risk/run-03/result.json) | 是 | 0 | 818.3 |

**失败会话的 Judge 原因：**

- **Control：** 模型回答未列出参考证据要求的三项风险提示，仅提及两项且表述与参考证据不符，还未完成贝特利新股报告风险提示的确认，未满足问题要求。
- **Candidate R1：** 模型回答列出的风险提示与参考证据要求的三项核心风险完全不符，未准确复述指定的风险内容，属于编造无关信息。
- **Candidate R2：** 模型回答未按要求列出参考证据指定的三项核心风险提示，反而编造了大量其他研报的风险内容，核心事实未受参考证据支持，不符合问题要求。
- **Candidate R3：** 模型回答未按要求列出参考证据指定的三项核心风险提示，反而罗列了大量无参考证据支持的其他研报风险内容，不符合问题要求。

人工复核：

- [√ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：定位错误，内容是在第9页

### 6. 5e305376-nonfarm — 高频失败 3/4

**问题：** 美国 8 月新增非农就业人数是多少，与市场预期相比如何？

**来源：** `2026-09-06_2026.09.06-华泰证券-宏观海外周报-联储加息悬念白热化-d571f138.pdf`；定位：`page:1`

**冻结参考证据：** 美国 8 月新增非农就业为 16.2 万，大幅高于预期的 5.6万，前两个月累计上修 5.5万。

**可接受证据规则：** 第 1 页'上周主要宏观数据'证据，须包含美国 8 月新增非农就业 16.2 万、预期 5.6 万、前两月累计上修 5.5 万。

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [❌ fail](../../.s5runs_v14_full/control/5e305376-nonfarm/run-01/result.json) | 是 | 0 | 417.0 |
| Candidate R1 | [✅ pass](../../.s5runs_v14_full/candidate/5e305376-nonfarm/run-01/result.json) | 是 | 0 | 564.9 |
| Candidate R2 | [❌ fail](../../.s5runs_v14_full/candidate/5e305376-nonfarm/run-02/result.json) | 是 | 0 | 709.8 |
| Candidate R3 | [❌ fail](../../.s5runs_v14_full/candidate/5e305376-nonfarm/run-03/result.json) | 是 | 0 | 791.5 |

**失败会话的 Judge 原因：**

- **Control：** 回答中关于美国8月新增非农就业16.2万、市场预期5.6万、前两月累计上修5.5万的核心事实符合参考证据，但编造了2026年的年份信息，还额外添加了失业率、劳动参与率、市场加息预期等参考证据未提及的内容，不符合要求。
- **Candidate R2：** 模型回答未提供美国8月新增非农就业人数及与市场预期对比的相关信息，未满足问题要求。
- **Candidate R3：** 模型回答编造了2026年的年份、失业率、劳动参与率、薪资增速、加息概率等大量参考证据未提及的内容，超出了参考证据的支持范围。

人工复核：

- [ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：

### 7. d179b615-chart3 — 高频失败 3/4

**问题：** 被动补库阶段，各类资产及A股指数的月均涨跌幅是多少？

**来源：** `2026-09-06_2026.09.06-中银国际-中银证券-策略周报-外部加息扰动未消-短期以守为攻-880f5e5e.pdf`；定位：`page:3`

**冻结参考证据：** 涨跌幅:% 万得全 A 南华商品 中证全债 上证 沪深 300 创业板 工业品 金属 能化 农产品 被动补库 (1.83) (0.10) 0.29 (1.80) (2.21) (1.28) 0.21 0.29 0.14 (0.26)

**可接受证据规则：** 被动补库行各列数值需与(1.83)(0.10)0.29(1.80)(2.21)(1.28)0.21 0.29 0.14(0.26)逐列对应

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [✅ pass](../../.s5runs_v14_full/control/d179b615-chart3/run-01/result.json) | 否 | 0 | 708.1 |
| Candidate R1 | [❌ fail](../../.s5runs_v14_full/candidate/d179b615-chart3/run-01/result.json) | 否 | 2 | 868.6 |
| Candidate R2 | [❌ fail](../../.s5runs_v14_full/candidate/d179b615-chart3/run-02/result.json) | 否 | 0 | 720.5 |
| Candidate R3 | [❌ fail](../../.s5runs_v14_full/candidate/d179b615-chart3/run-03/result.json) | 否 | 0 | 854.9 |

**失败会话的 Judge 原因：**

- **Candidate R1：** 回答中A股指数及大类资产的核心涨跌幅数值与参考证据逐列对应一致，但编造了胜率、A股大类行业涨跌幅、研报出处、解读结论等参考证据未提及的内容，且未按要求仅回答月均涨跌幅，存在大量无关编造信息。
- **Candidate R2：** 回答中被动补库阶段的月均涨跌幅数值与参考证据逐列对应一致，但编造了参考证据未提及的胜率、其他库存周期阶段数据、报告解读及投资建议等额外内容。
- **Candidate R3：** 回答中被动补库阶段各类资产及A股指数的月均涨跌幅数值与参考证据逐列对应一致，但编造了参考证据未提及的月度胜率、行业层面涨跌幅、研报来源、对照反方证据等大量无关内容，超出问题要求的回答范围。

人工复核：

- [ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：

### 8. d179b615-hikerate — 高频失败 3/4

**问题：** 非农数据发布后，市场对9月加息的定价以及美债长端利率有何变化？

**来源：** `2026-09-06_2026.09.06-中银国际-中银证券-策略周报-外部加息扰动未消-短期以守为攻-880f5e5e.pdf`；定位：`page:3`

**冻结参考证据：** 非农强化加息预期， 短期利率扰动难消。8 月非农数据发布后， 市场对9 月加息的定价进一步抬升。当前 CME 隐含的 9 月加息概率已升至59%， 美债长端利率随之走高，10 年期收益率一度触及4.79%。

**可接受证据规则：** 需给出CME隐含9月加息概率59%、10年期美债收益率一度触及4.79%

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [❌ fail](../../.s5runs_v14_full/control/d179b615-hikerate/run-01/result.json) | 是 | 0 | 750.6 |
| Candidate R1 | [❌ fail](../../.s5runs_v14_full/candidate/d179b615-hikerate/run-01/result.json) | 是 | 0 | 791.1 |
| Candidate R2 | [❌ fail](../../.s5runs_v14_full/candidate/d179b615-hikerate/run-02/result.json) | 是 | 0 | 676.6 |
| Candidate R3 | [✅ pass](../../.s5runs_v14_full/candidate/d179b615-hikerate/run-03/result.json) | 是 | 0 | 766.1 |

**失败会话的 Judge 原因：**

- **Control：** 模型回答未提及非农数据发布后市场对9月加息的定价变化及美债长端利率变化，未包含CME隐含9月加息概率59%、10年期美债收益率一度触及4.79%的核心信息，内容与问题无关。
- **Candidate R1：** 模型回答未提供问题要求的CME隐含9月加息概率59%、10年期美债收益率一度触及4.79%的核心信息，未回应非农数据发布后市场对9月加息定价及美债长端利率的变化情况。
- **Candidate R2：** 回答中大量内容（如非农新增就业数据、失业率、其他机构研报观点、全周美债收益率变动、鸽派官员表态、年内加息预期变化等）均未在给定参考证据中提及，属于编造的无依据信息，不符合验收要求。

人工复核：

- [ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：

### 9. d179b615-passive — 高频失败 3/4

**问题：** 历史复盘显示被动补库阶段各类资产的月均表现如何？

**来源：** `2026-09-06_2026.09.06-中银国际-中银证券-策略周报-外部加息扰动未消-短期以守为攻-880f5e5e.pdf`；定位：`page:3`

**冻结参考证据：** 被动补库阶段多为权益资产表现最差的时期。 万得全A 月均收益-1.83%、 胜率仅13%， 上证月均-1.80%、胜率 0%；大类资产角度，债券资产则全面占优，中证全债月均+0.29%、胜率 75%。

**可接受证据规则：** 需给出被动补库阶段权益表现最差、万得全A月均收益-1.83%胜率13%、上证月均-1.80%胜率0%、中证全债月均+0.29%胜率75%

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [❌ fail](../../.s5runs_v14_full/control/d179b615-passive/run-01/result.json) | 是 | 0 | 751.8 |
| Candidate R1 | [✅ pass](../../.s5runs_v14_full/candidate/d179b615-passive/run-01/result.json) | 是 | 0 | 745.6 |
| Candidate R2 | [❌ fail](../../.s5runs_v14_full/candidate/d179b615-passive/run-02/result.json) | 是 | 1 | 695.4 |
| Candidate R3 | [❌ fail](../../.s5runs_v14_full/candidate/d179b615-passive/run-03/result.json) | 是 | 0 | 595.4 |

**失败会话的 Judge 原因：**

- **Control：** 模型回答包含参考证据未提及的沪深300、创业板、商品类资产、行业层面表现等编造内容，超出给定参考证据范围。
- **Candidate R2：** 模型回答包含大量参考证据未提及的资产、行业、四阶段对比及局限反证等编造内容，超出了参考证据支持的范围。
- **Candidate R3：** 模型回答未提供被动补库阶段各类资产月均表现的相关数据，仅提及文档定位与取数问题，未满足问题要求。

人工复核：

- [ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：

### 10. 0c25f0e9-eptable — 偶发失败 1/4

**问题：** 根据表 1 盈利预测表，珞石机器人（3752.HK）当周的周度涨跌幅是多少？

**来源：** `2026-09-06_2026.09.06-国泰海通-国泰海通证券-机器人行业周报-figure斥35亿美元加码helix算力-李飞飞创企world-labs发布全模态世界模型atlas-dd6c23f9.pdf`；定位：`page:8`, `row:3752.HK 珞石机器人`

**冻结参考证据：** 3752.HK 珞石机器人 143 54.10 -17.34% -0.25 0.64 1.29 - 85 42 -

**可接受证据规则：** 盈利预测表第 8 页中珞石机器人 3752.HK 数据行，须含 -17.34% 周度涨跌幅，EPS 与 PE 下方为该股按年份（如 -0.25/0.64/1.29）分列，需结合第 7 页'跌幅最大的为珞石机器人，跌幅为-17.34%'交叉印证。

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [✅ pass](../../.s5runs_v14_full/control/0c25f0e9-eptable/run-01/result.json) | 否 | 0 | 217.6 |
| Candidate R1 | [❌ fail](../../.s5runs_v14_full/candidate/0c25f0e9-eptable/run-01/result.json) | 否 | 0 | 195.9 |
| Candidate R2 | [✅ pass](../../.s5runs_v14_full/candidate/0c25f0e9-eptable/run-02/result.json) | 否 | 0 | 200.7 |
| Candidate R3 | [✅ pass](../../.s5runs_v14_full/candidate/0c25f0e9-eptable/run-03/result.json) | 否 | 0 | 222.2 |

**失败会话的 Judge 原因：**

- **Candidate R1：** 回答中关于周度区间、相邻公司、报告名称、页码及表格行号等细节未在参考证据中得到支持，属于编造内容。

人工复核：

- [ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：

### 11. 0c25f0e9-figure35 — 偶发失败 1/4

**问题：** Figure 为训练 Helix 大模型承诺采购的首期算力规模是多少？

**来源：** `2026-09-06_2026.09.06-国泰海通-国泰海通证券-机器人行业周报-figure斥35亿美元加码helix算力-李飞飞创企world-labs发布全模态世界模型atlas-dd6c23f9.pdf`；定位：`page:3`

**冻结参考证据：** Figure 宣布采购 35 亿美元算力训练 Helix， 规划最高配置 10 万张 GPU。

**可接受证据规则：** 正文第 3 页'行业新闻及公司动态'小节证据，须包含 Figure 采购 35 亿美元算力、规划最高配置 10 万张 GPU（依托 NVIDIA Vera Rubin 平台训练 Helix）。

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [❌ fail](../../.s5runs_v14_full/control/0c25f0e9-figure35/run-01/result.json) | 是 | 0 | 146.5 |
| Candidate R1 | [✅ pass](../../.s5runs_v14_full/candidate/0c25f0e9-figure35/run-01/result.json) | 是 | 0 | 315.3 |
| Candidate R2 | [✅ pass](../../.s5runs_v14_full/candidate/0c25f0e9-figure35/run-02/result.json) | 是 | 0 | 70.7 |
| Candidate R3 | [✅ pass](../../.s5runs_v14_full/candidate/0c25f0e9-figure35/run-03/result.json) | 是 | 0 | 106.0 |

**失败会话的 Judge 原因：**

- **Control：** 回答中提及的约合人民币235亿元、合作方为Nscale、首批部署时间为2027年下半年、后续意向扩大至超60亿美元等内容未在给定参考证据中出现，属于编造的信息。

人工复核：

- [ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：

### 12. 2f8aa709-oil — 偶发失败 1/4

**问题：** 美伊冲突再度升级背景下，霍尔木兹海峡通航量和布油价格情况如何？

**来源：** `2026-09-06_2026.09.06-国金证券-a股策略周报-迷雾与罗盘-fb9b3c67.pdf`；定位：`page:7`

**冻结参考证据：** 与之对应的是， 霍尔木兹海峡通航量再度接近清零， 布油价格重回95 美元/桶以上。

**可接受证据规则：** 需给出霍尔木兹海峡通航量再度接近清零、布油价格重回95美元/桶以上

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [❌ fail](../../.s5runs_v14_full/control/2f8aa709-oil/run-01/result.json) | 是 | 0 | 491.7 |
| Candidate R1 | [✅ pass](../../.s5runs_v14_full/candidate/2f8aa709-oil/run-01/result.json) | 是 | 0 | 765.7 |
| Candidate R2 | [✅ pass](../../.s5runs_v14_full/candidate/2f8aa709-oil/run-02/result.json) | 是 | 1 | 789.6 |
| Candidate R3 | [✅ pass](../../.s5runs_v14_full/candidate/2f8aa709-oil/run-03/result.json) | 是 | 0 | 568.6 |

**失败会话的 Judge 原因：**

- **Control：** 模型回答未提及霍尔木兹海峡通航量和布油价格的相关情况，未满足问题要求。

人工复核：

- [ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：

### 13. b7e932c8-pmi — 偶发失败 1/4

**问题：** 8月制造业采购经理指数是多少、较上月变化如何？生产指数和新订单指数分别是多少？

**来源：** `2026-09-05_2026.09.05-中信建投-行业数据周报9月第1期-市场普遍下跌-机构低配板块表现居前-a6a30359.pdf`；定位：`page:3`

**冻结参考证据：** 国家统计局发布数据显示 ，8月制造业采购经理指数 （PMI）为49.8%，较上月上升0.6个百分点；生产指数和新订单指数分别为 50.4%和50.6%，均位于扩张区间

**可接受证据规则：** 研报宏观基本面部分给出2026年8月制造业PMI为49.8%（环比+0.6pct）、生产指数和新订单指数分别为50.4%和50.6%等任一数字即为可接受证据。

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [❌ fail](../../.s5runs_v14_full/control/b7e932c8-pmi/run-01/result.json) | 是 | 0 | 262.2 |
| Candidate R1 | [✅ pass](../../.s5runs_v14_full/candidate/b7e932c8-pmi/run-01/result.json) | 是 | 0 | 143.0 |
| Candidate R2 | [✅ pass](../../.s5runs_v14_full/candidate/b7e932c8-pmi/run-02/result.json) | 是 | 0 | 379.0 |
| Candidate R3 | [✅ pass](../../.s5runs_v14_full/candidate/b7e932c8-pmi/run-03/result.json) | 是 | 0 | 416.0 |

**失败会话的 Judge 原因：**

- **Control：** 模型回答中生产指数较上月回升0.5个百分点、新订单指数较上月回升2.1个百分点及非制造业、综合PMI、企业规模相关数据未在参考证据中提及，属于编造内容。

人工复核：

- [ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：

### 14. c1ddcd8a-summarytable — 偶发失败 1/4

**问题：** 研报的量价利汇总表中，螺纹钢在2026-9-4的价格、7日涨幅、30日涨幅和年内涨幅分别是多少？

**来源：** `2026-09-06_2026.09.06-光大证券-金属行业周期品高频数据周报-焦煤期货收盘价周内下跌3-64-46877bac.pdf`；定位：`page:2`, `row:1`, `col:0`

**冻结参考证据：** 螺纹钢 元/吨 3240 0.9% 4.2% -2.4% -0.6% 6000

**可接受证据规则：** 量价利汇总表（表1）中螺纹钢所在行给出的价格3240元/吨、7日涨幅0.9%、30日涨幅4.2%、年内涨幅-2.4%、365日涨幅-0.6%、历史最高值6000元/吨等任一数字与所在列对应正确即可。

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [❌ fail](../../.s5runs_v14_full/control/c1ddcd8a-summarytable/run-01/result.json) | 否 | 0 | 680.4 |
| Candidate R1 | [✅ pass](../../.s5runs_v14_full/candidate/c1ddcd8a-summarytable/run-01/result.json) | 是 | 0 | 569.3 |
| Candidate R2 | [✅ pass](../../.s5runs_v14_full/candidate/c1ddcd8a-summarytable/run-02/result.json) | 是 | 0 | 351.9 |
| Candidate R3 | [✅ pass](../../.s5runs_v14_full/candidate/c1ddcd8a-summarytable/run-03/result.json) | 是 | 0 | 130.1 |

**失败会话的 Judge 原因：**

- **Control：** 模型回答错误声称螺纹钢2026-9-4的年内涨幅在参考证据中残缺无法给出，遗漏了参考证据明确提供的年内涨幅-2.4%，未完整回答问题要求的全部四项指标。

人工复核：

- [ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：

### 15. f3b28791-fedwatch — 偶发失败 1/4

**问题：** 兴业证券建议重点观察哪些影响美联储决策、有助于降低宏观不确定性的事件节点？

**来源：** `2026-09-06_2026.09.06-兴业证券-极致轮动如何收敛-探讨几个契机-733fc399.pdf`；定位：`page:5`

**冻结参考证据：** 几个影响美联储决策的重要观察点已不远，有助于市场分歧的弥合、宏观不确定性的下降。包括 9.11 美国 CPI 数据，以及 9.17 FOMC 会议。

**可接受证据规则：** 需给出影响美联储决策的关键观察点：9.11美国CPI数据、9.17 FOMC会议

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [✅ pass](../../.s5runs_v14_full/control/f3b28791-fedwatch/run-01/result.json) | 是 | 0 | 303.6 |
| Candidate R1 | [✅ pass](../../.s5runs_v14_full/candidate/f3b28791-fedwatch/run-01/result.json) | 否 | 0 | 226.7 |
| Candidate R2 | [✅ pass](../../.s5runs_v14_full/candidate/f3b28791-fedwatch/run-02/result.json) | 是 | 0 | 317.7 |
| Candidate R3 | [❌ fail](../../.s5runs_v14_full/candidate/f3b28791-fedwatch/run-03/result.json) | 是 | 0 | 832.0 |

**失败会话的 Judge 原因：**

- **Candidate R3：** 回答虽正确列出了9.11美国CPI数据、9.17 FOMC会议两个符合要求的核心事件节点，但额外提及了图8中不属于影响美联储决策、降低宏观不确定性的其他事件节点，超出了参考证据的要求范围。

人工复核：

- [ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：

### 16. f3b28791-rotation — 偶发失败 1/4

**问题：** 兴业证券认为近期A股市场呈现什么特征？行业轮动强度指标走势如何？

**来源：** `2026-09-06_2026.09.06-兴业证券-极致轮动如何收敛-探讨几个契机-733fc399.pdf`；定位：`page:2`

**冻结参考证据：** 近期市场给人的最大感受，依然是混沌、轮动、缺乏主线。我们构造的行业轮动强度指标仍在持续上行，本周再创年内新高。

**可接受证据规则：** 需指出市场特征为混沌、轮动、缺乏主线，行业轮动强度指标持续上行且本周再创年内新高

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [✅ pass](../../.s5runs_v14_full/control/f3b28791-rotation/run-01/result.json) | 是 | 0 | 839.7 |
| Candidate R1 | [✅ pass](../../.s5runs_v14_full/candidate/f3b28791-rotation/run-01/result.json) | 是 | 1 | 674.5 |
| Candidate R2 | [❌ fail](../../.s5runs_v14_full/candidate/f3b28791-rotation/run-02/result.json) | 是 | 0 | 517.9 |
| Candidate R3 | [✅ pass](../../.s5runs_v14_full/candidate/f3b28791-rotation/run-03/result.json) | 是 | 0 | 342.5 |

**失败会话的 Judge 原因：**

- **Candidate R2：** 模型回答未提及兴业证券对近期A股市场特征及行业轮动强度指标走势的任何相关内容，完全未回应问题要求。

人工复核：

- [ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：

### 17. f7f65d7e-alloc — 偶发失败 1/4

**问题：** 本期研报建议投资者关注哪几个投资主线方向？

**来源：** `2026-09-06_2026.09.06-天风证券-a股策略周报-非农大超预期-加息预期升温-5e671b67.pdf`；定位：`page:7`

**冻结参考证据：** 根据经济复苏与市场流动性，可以把投资主线降维为三个方向： 1）AI 产业革命带来的算力、存力、电力及应用的科技主线机会， 2）内外共振，经济逐步修复，牛市主线风格“强者恒强” ，但周期后半段易有所表现， 3）赔率思维，即考虑风格轮动、底部反转的可能性。连续三年跑输但第四年跑赢概率较大的行业有食品饮料、农林牧渔、社会服务、医药生物。

**可接受证据规则：** 能复述三个主线方向(科技主线产业趋势、内外共振强者恒强、赔率思维风格轮动)及食品饮料/农林牧渔/社会服务/医药生物四类连续三年跑输但第四年跑赢概率较大的行业

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [✅ pass](../../.s5runs_v14_full/control/f7f65d7e-alloc/run-01/result.json) | 是 | 0 | 647.0 |
| Candidate R1 | [❌ fail](../../.s5runs_v14_full/candidate/f7f65d7e-alloc/run-01/result.json) | 是 | 0 | 803.1 |
| Candidate R2 | [✅ pass](../../.s5runs_v14_full/candidate/f7f65d7e-alloc/run-02/result.json) | 是 | 0 | 716.5 |
| Candidate R3 | [✅ pass](../../.s5runs_v14_full/candidate/f7f65d7e-alloc/run-03/result.json) | 是 | 0 | 306.3 |

**失败会话的 Judge 原因：**

- **Candidate R1：** 模型回答未按要求列出研报建议的三个投资主线方向及相关行业，仅提及投资主线降维为三个方向的出处，未覆盖问题要求的核心内容。

人工复核：

- [ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：

### 18. f7f65d7e-payroll — 偶发失败 1/4

**问题：** 2026年8月美国新增非农就业人数和失业率数据各是多少？

**来源：** `2026-09-06_2026.09.06-天风证券-a股策略周报-非农大超预期-加息预期升温-5e671b67.pdf`；定位：`page:6`

**冻结参考证据：** 8 月美国非农就业数据 高于预期，失业率 持平 。8 月失业率报 4.1%，前值 4.1%，预期 4.1%。8 月新增非农就业人数 增 16.2 万人，预期增 5.6 万人，前值自 -2.3 万人修正至+2.1 万人。

**可接受证据规则：** 需要同时给出新增非农就业16.2万人、预期5.6万人、前值自-2.3万修正至+2.1万，失业率4.1%且与前值/预期持平

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [✅ pass](../../.s5runs_v14_full/control/f7f65d7e-payroll/run-01/result.json) | 是 | 0 | 366.4 |
| Candidate R1 | [✅ pass](../../.s5runs_v14_full/candidate/f7f65d7e-payroll/run-01/result.json) | 是 | 0 | 340.2 |
| Candidate R2 | [✅ pass](../../.s5runs_v14_full/candidate/f7f65d7e-payroll/run-02/result.json) | 是 | 0 | 291.3 |
| Candidate R3 | [❌ fail](../../.s5runs_v14_full/candidate/f7f65d7e-payroll/run-03/result.json) | 是 | 0 | 389.8 |

**失败会话的 Judge 原因：**

- **Candidate R3：** 回答虽正确给出了2026年8月美国新增非农就业16.2万人、预期5.6万人、失业率4.1%且与前值/预期持平的核心数据，但未按可接受证据规则要求提及前值自-2.3万人修正至+2.1万人的关键信息，不符合完整要求。

人工复核：

- [ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：

### 19. f86c6d2c-wuqi-order — 偶发失败 1/4

**问题：** 截至 2026Q2，药明康德持续经营业务的在手订单金额和同比增速是多少？

**来源：** `2026-09-06_2026.09.06-国联民生证券-医药行业周报-cxo中报我们看到了什么-c1e12af2.pdf`；定位：`page:5`

**冻结参考证据：** 1）截至 2026Q2，药明康德持续经营业务在手订单 664.3 亿元，同比+25.2%。

**可接受证据规则：** 正文第 5 页 1.2 节 D＆M 小节证据，须包含截至 2026Q2 药明康德持续经营业务在手订单 664.3 亿元、同比+25.2%。

| 会话 | 判定 | 取得目标引文 | 工具错误 | 耗时（秒） |
|---|---|---:|---:|---:|
| Control | [✅ pass](../../.s5runs_v14_full/control/f86c6d2c-wuqi-order/run-01/result.json) | 是 | 0 | 246.9 |
| Candidate R1 | [❌ fail](../../.s5runs_v14_full/candidate/f86c6d2c-wuqi-order/run-01/result.json) | 是 | 0 | 315.5 |
| Candidate R2 | [✅ pass](../../.s5runs_v14_full/candidate/f86c6d2c-wuqi-order/run-02/result.json) | 是 | 1 | 785.1 |
| Candidate R3 | [✅ pass](../../.s5runs_v14_full/candidate/f86c6d2c-wuqi-order/run-03/result.json) | 是 | 0 | 435.5 |

**失败会话的 Judge 原因：**

- **Candidate R1：** 模型回答的核心数据虽与参考证据一致，但引用的证据来源为正文第6页，不符合可接受证据规则要求的正文第5页1.2节D＆M小节的来源要求。

人工复核：

- [ ] Judge 判定正确
- [ ] 冻结参考证据正确且足以回答问题
- [ ] 失败归因：漏检索 / 漏取回 / 误取回 / 答案遗漏 / 无依据扩写 / Judge 边界 / 题目或证据缺陷
- [ ] 备注：
