# 校准复核清单（按优先级）

- 当前 matched **29/48 = 0.604**（阈值 0.85 ⇒ 需 ≥41）

- **未 matched 19 条**拆分：
  - ① 语料本就无候选（结构性，需补跑）：**8** 条 — NT-I06, NT-I13, NT-I14, NT-I15, NT-I16, NT-I17, NT-I42, NT-I43
  - ② 有候选覆盖但未判 matched：**11** 条 — NT-I09, NT-I19, NT-I23, NT-I24, NT-I26, NT-I31, NT-I34, NT-I36, NT-I38, NT-I39, NT-I48

> **关键算术**：即使 ② 的 11 条全部改判 matched，召回上限 = 40/48 = **0.833**，仍 < 0.85（需 41）。⇒ **补跑在数学上是必要的**（至少再恢复 1 条）。

## P1 · ② 的 11 条（最高杠杆：决定是否召回 0.60→0.83）

逐条看候选原文 vs 金标命题；若候选确实表达了该命题 ⇒ 改 matched（+11 条召回）；若没有 ⇒ 记 reason 说明。

### `NT-I09` — 估值风险触发条件
- 金标字段：semantic_type=forecast / statement_role=condition / source_stance=reported / condition=毛利率继续下降或Rubin延期
- 覆盖槽位内候选 2 条：
  - `itm_36692d3ea29613ba`：贵的是「A 股唯一 NVIDIA 整柜代理」的叙事溢价
  - `itm_2f60038387b4ea72`：一旦毛利率再掉或 Rubin 延期，弹性会先打在倍数上

### `NT-I19` — 地理对冲失效的外部条件
- 金标字段：semantic_type=forecast / statement_role=condition / source_stance=reported / condition=出口管制影响GPU系统集成
- 覆盖槽位内候选 1 条：
  - `itm_659e7d6382f5fd02`：墨西哥 / 美国厂是地理对冲，救不了出口管制一旦打到 GPU 系统集成

### `NT-I23` — 128端口产品尚无固定客户
- 金标字段：semantic_type=fact / statement_role=risk / source_stance=reported / condition=—
- 覆盖槽位内候选 1 条：
  - `itm_703720fdd5630e8b`：尚无固定的客户，德科立将其视为一个过渡型的产品

### `NT-I24` — 128端口产品被视为过渡产品
- 金标字段：semantic_type=opinion / statement_role=claim / source_stance=reported / condition=—
- 覆盖槽位内候选 1 条：
  - `itm_703720fdd5630e8b`：尚无固定的客户，德科立将其视为一个过渡型的产品

### `NT-I26` — 128端口光波导设计仍有缺陷
- 金标字段：semantic_type=opinion / statement_role=claim / source_stance=reported / condition=—
- 覆盖槽位内候选 1 条：
  - `itm_a41addfcb6696346`：说明设计上仍然存在缺陷，

### `NT-I31` — 北美数据中心存在电力短缺
- 金标字段：semantic_type=fact / statement_role=risk / source_stance=reported / condition=—
- 覆盖槽位内候选 2 条：
  - `itm_7b0cfc4d08a27730`：主要群体北美的这些电力短缺的确会影响到公司出货节奏
  - `itm_cf8baa3c797556e2`：所有的出货节奏都是环环相扣的

### `NT-I34` — 到2029至2030年可插拔方案仍将是主流
- 金标字段：semantic_type=forecast / statement_role=claim / source_stance=reported / condition=材料尚未取得重大突破
- 覆盖槽位内候选 2 条：
  - `itm_15c17f04855a28b3`：可插拔仍然是主流
  - `itm_898045d75c1c3ef3`：速度还有提升空间

### `NT-I36` — 公司口径可能导致行业份额加总超过100%
- 金标字段：semantic_type=opinion / statement_role=risk / source_stance=reported / condition=—
- 覆盖槽位内候选 1 条：
  - `itm_ec18c38405c7e17f`：像当年机器人份额加起来超过100%，会不会出现这个状态？

### `NT-I38` — 讲者先称800G超预期，随后限定这并非通常意义的超预期
- 金标字段：semantic_type=opinion / statement_role=claim / source_stance=reported / condition=—
- 覆盖槽位内候选 2 条：
  - `itm_bf5fa66fb7be5a02`：Q2 800G其实是超预期的，肯定是超预期的。
  - `itm_7a4789de164cf58a`：但这也不叫超预期。

### `NT-I39` — 成本转嫁风险的条件
- 金标字段：semantic_type=forecast / statement_role=condition / source_stance=reported / condition=海外产能税率增加
- 覆盖槽位内候选 1 条：
  - `itm_a79b0be05f3456c3`：然后这里面税率加上去

### `NT-I48` — 被转述观点认为税负可转嫁，对竞争力和毛利影响不大
- 金标字段：semantic_type=opinion / statement_role=claim / source_stance=challenged / condition=—
- 覆盖槽位内候选 2 条：
  - `itm_d96a4e7b052a89c7`：由于台湾海鸥基地有免税政策，这部分会转嫁给客户
  - `itm_356f9d9b23c78892`：因此对竞争力和毛利影响不大

## P2 · 16 条断言中的字段型不符（3 条，机器可判）

- itm_09fc1a90e71fe5bf→NT-I46:{"perspective": ["quoted_other", "source_explicit"], "source_stance": ["challenged", "reported"]}
- itm_42ffb8cedfa8d7ff→NT-I45:{"perspective": ["quoted_other", "source_explicit"], "source_stance": ["challenged", "reported"]}
- itm_f2e29952886293c0→NT-I47:{"perspective": ["quoted_other", "source_explicit"], "source_stance": ["challenged", "reported"]}

> 断言要求 `perspective=quoted_other`＋`source_stance=challenged`；你录的是 `source_explicit`／`reported`。⇒ 要么换候选，要么改字段（读原文确认是否为转述质疑）。

## P3 · 引文疑似误贴（相似度 <0.35，12 条）

- `itm_ca4a8fcc4b8c53ac`（相似度 0.21）：text=「这是可能的」quote=「2.4T 27年的出货量预期在200万只，这个是之前传的，也是200万只，这是可」
- `itm_5697c7311f116fbb`（相似度 0.25）：text=「谁说的？」quote=「实际上这出货量主要原因是1.6T影响了800G，谁说的？」
- `itm_52ba8f8a7210eca1`（相似度 0.26）：text=「利润增速回到收入增速」quote=「云资本开支从「训练」切到「推理效率」，整柜需求还在但 ASP 不再上、Consi」
- `itm_f506c336e80110ee`（相似度 0.27）：text=「中报扣非与归母同步。」quote=「卖方爱用归母 +96% 和 26E 600 亿+，中报扣非虽然同步，」
- `itm_b88b791b87dcbdc5`（相似度 0.3）：text=「保理额度收紧」quote=「美元短贷 + 汇兑再来一刀，或保理额度收紧，现金缺口被融资费用放大。」
- `itm_cc8511f87cf29cf7`（相似度 0.3）：text=「你免了税还要按15%税率给你补上」quote=「这个已经是免税，应该是最后的事情了，以后再往下就不免税了，你免了税还要按15%税」
- `itm_d2f7354f8f3c3e67`（相似度 0.3）：text=「那是一个比较有意义的体量了」quote=「到26年底这些新客户开始供应，供应占比合计能达到15%左右，那是一个比较有意义的」
- `itm_c4442734f0161593`（相似度 0.31）：text=「中期不分红」quote=「中期不分红、应付股利 130.52 亿是上年股利落账；」
- `itm_5e38e7d668363dbd`（相似度 0.31）：text=「这个也是那个协会的」quote=「这个也是那个协会的。但是这个肯定不是指的高速，高速显然不是这个比例，肯定是所有的」
- `itm_3af507cde48b3bbc`（相似度 0.32）：text=「相对位置约 45.3%」quote=「52 周（2025.09.01–2026.08.28）高 84.95 / 低 4」
- `itm_3b7f3587abb8f18e`（相似度 0.34）：text=「这个肯定不是指的高速」quote=「这个也是那个协会的。但是这个肯定不是指的高速，高速显然不是这个比例，肯定是所有的」
- `itm_b9d5dfa91cd4c6f6`（相似度 0.34）：text=「高速显然不是这个比例」quote=「这个也是那个协会的。但是这个肯定不是指的高速，高速显然不是这个比例，肯定是所有的」

> 注：`evidence_quote` 是**原文侧**逐字引文，与模型归一化后的 `text` 不同属正常（164 条属预期）。只有相似度极低者才需看。

## P4 · 其他

- C9 duplicate 无同金标 matched 兄弟：`itm_17b13257df44aea8`
- judgement 分布：{"correct_extra": 187, "matched": 29, "duplicate": 1, "out_of_scope": 5} — **`incorrect = 0`，`correct_extra = 187`**
  - 若其中有本该 `incorrect` 的，precision 会被虚高（当前 ≈0.995）。建议抽查 correct_extra 样本确认标准。
