# 门 33 的 14 条 FN 逐条归因（零模型调用；机械归因输入，非裁定）

- 2026-10-13　零调用　基准：`gate33-honest-score.json`（A 工作表权威 + r5/base 签认批）
- 金标 `frozen-gold.json` role=material_items 48 条；matched 34，FN 14（源1 2 / 源2 12）
- 16 条高危断言未中 8 条：源1 ['NT-I09', 'NT-I19']、源2 ['NT-I38', 'NT-I39', 'NT-I45', 'NT-I46', 'NT-I47', 'NT-I48']

> **这是机械归因，不是裁定。**A/B 桶只说明「池内已有近似候选、但已被具名裁定为非匹配」，
> 是否改判必须由 xyl 具名，并会触碰「片段/缺限定是否算原子命题命中」的口径。

## 〇、首要结论

**14 条 FN 全部是同源候选『已抽到但被判不等价』，没有一条是抽取覆盖缺口。**

- A 近逐字但已判 ce/dup：12 条
- B 候选已被邻近金标占用：2 条
- C 池内无近似候选：0 条
- D 落在 9 个未产出槽：0 条

直接推翻的既有表述（详见末节）：

- `evidence/69-union-adjudication-20261013/r1-score/gate33-honest-score.json:88`：缺口为真实 FN（金标无候选匹配），非流程问题
  - 机器实测：14/14 条 FN 在同源候选里都有近似文本（12 条 sim>=0.75 或互为包含，2 条候选已被邻近金标占用且带具名理由）；『无匹配』字面为真，但读作『模型没产出相关内容』与实测不符
- `evidence/69-union-adjudication-20261013/r1-score/gate33-full-verdict.md:26-30`：14 条 FN 为真实抽取覆盖缺口（三次独立抽取均未覆盖）
  - 机器实测：0 条落在 evidence/32 记录的 9 个未产出槽；0 条为『池内无近似候选』
- `evidence/69-union-adjudication-20261013/r1-score/gate33-full-verdict.md:17 与 report.md:14`：8 条未过断言全部属于源2 文档段
  - 机器实测：NT-I09、NT-I19 属于源1（locator 为 char: 体系；源2 为 body[N] 体系），与其自身判据 2『源1 20/22』自相矛盾
- `evidence/70-closure-20261013/r0-zero-call/closure.md:29 与 gate33-full-verdict.md:34`：源2 召回 0.538 + 8 条断言未过：需对源2 对应片段定向补抽
  - 机器实测：补抽同样会产出这些片段，而它们已被具名裁定为非等价（原子度/限定/承载/断言形态）；要翻必须先裁口径，不是抽取问题

## 一、桶分布

| 桶 | 条数 | 金标 | 含义 |
|---|---|---|---|
| A 近逐字候选但已判 ce/dup | 12 | NT-I23、NT-I24、NT-I26、NT-I31、NT-I34、NT-I36、NT-I38、NT-I39、NT-I45、NT-I46、NT-I47、NT-I48 | 池内有近似逐字候选，但被裁为 correct_extra/duplicate：属裁定口径问题，不是抽取缺口 |
| B 最近候选已被其他金标占用 | 2 | NT-I09、NT-I19 | 最近候选已被另一条金标占用（一对一映射），须重划归属或拆分相邻断言 |

## 二、情景推演（仅供决策；改判后重算才有效）

| 情景 | 追加 matched | 总召回 | 源1 | 源2 | 断言 | 判定 |
|---|---|---|---|---|---|---|
| S0_as_scored | 0 | 34/48 = 0.708 | 20/22 = 0.909 | 14/26 = 0.538 | 8/16 | **still FAIL** |
| S1_A_only | 12 | 46/48 = 0.958 | 20/22 = 0.909 | 26/26 = 1.0 | 14/16 | **still FAIL** |
| S2_A_and_B | 14 | 48/48 = 1.0 | 22/22 = 1.0 | 26/26 = 1.0 | 16/16 | **PASS** |
| S3_A_B_minus_u_calibration | 11 | 45/48 = 0.938 | 22/22 = 1.0 | 23/26 = 0.885 | 13/16 | **still FAIL** |
| S4_all_fn | 14 | 48/48 = 1.0 | 22/22 = 1.0 | 26/26 = 1.0 | 16/16 | **PASS** |

## 三、逐条明细

| # | 桶 | gold | 源 | 断言 | locator | 金标引文 | 最近候选 | sim | 该候选裁定 | 指向金标 | agent draft 机制 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | A | NT-I23 | 源2 |  | body[63] | `尚无固定的客户` | `itm_703720fdd5630e8b` | 0.483 | correct_extra | — | 候选缺承载主体：裁定理由为缺主语『128端口产品』，仅余谓词 |
| 2 | A | NT-I24 | 源2 |  | body[63] | `德科立将其视为一个过渡型的产品` | `itm_703720fdd5630e8b` | 0.811 | correct_extra | — | 候选缺承载主体：同 I23（同一候选拆出的另一条） |
| 3 | A | NT-I26 | 源2 |  | body[72] | `说明设计上仍然存在缺陷` | `itm_a41addfcb6696346` | 1.0 | correct_extra | — | 候选缺承载主体：文本逐字相同，但裁定理由为缺主语『128端口光波导』 |
| 4 | A | NT-I31 | 源2 |  | body[37] | `北美的这些电力短缺` | `itm_7b0cfc4d08a27730` | 0.529 | matched | NT-I32 | 金标比候选细/切分不同：I31 与 I32 为同一句的两种切分，候选被 I32 占用 |
| 5 | A | NT-I34 | 源2 |  | body[37] | `预计到29年30年在材料取得重大突破前，可插拔仍然是主流` | `itm_15c17f04855a28b3` | 0.483 | correct_extra | — | 候选缺时间框架与条件：裁定理由为缺『2029-2030 年』与『材料未突破』 |
| 6 | A | NT-I36 | 源2 |  | body[115] | `像当年机器人份额加起来超过100%` | `itm_ec18c38405c7e17f` | 0.78 | correct_extra | — | 断言形态不符：候选为类比式问句而非肯定断言 |
| 7 | A | NT-I38 | 源2 | Y | body[51] | `Q2 800G其实是超预期的，肯定是超预期的。但这也不叫超预期` | `itm_bf5fa66fb7be5a02` | 0.833 | correct_extra | — | 金标比候选粗：金标把前半+后半两个原子并为一条，候选正确拆成两条，各自不完整均判 ce |
| 8 | A | NT-I39 | 源2 | Y | body[26] | `这里面税率加上去` | `itm_a79b0be05f3456c3` | 0.889 | correct_extra | — | 候选缺限定：裁定理由为未提『海外产能』且仅为片段 |
| 9 | A | NT-I45 | 源2 | Y | body[1] | `29年NPO到10%` | `itm_42ffb8cedfa8d7ff` | 1.0 | correct_extra | — | U 2026-10-12 校准撤销：金标为被转述且被质疑的预测（quoted_other/challenged），候选为材料自身陈述 |
| 10 | A | NT-I46 | 源2 | Y | body[1] | `CPO到30%` | `itm_09fc1a90e71fe5bf` | 1.0 | correct_extra | — | U 2026-10-12 校准撤销：同 I45 |
| 11 | A | NT-I47 | 源2 | Y | body[1] | `可插拔主导70%` | `itm_f2e29952886293c0` | 1.0 | correct_extra | — | U 2026-10-12 校准撤销：同 I45 |
| 12 | A | NT-I48 | 源2 | Y | body[26] | `由于台湾海鸥基地有免税政策，这部分会转嫁给客户，因此对竞争力和毛利影响不大` | `itm_d96a4e7b052a89c7` | 0.772 | correct_extra | — | 金标比候选粗：同 I38，金标合并『税负可转嫁』+『对竞争力毛利影响不大』两半 |
| 13 | B | NT-I09 | 源1 | Y | char:3925-4239 | `一旦毛利率再掉或 Rubin 延期` | `itm_2f60038387b4ea72` | 0.769 | matched | NT-I10 | 金标比候选细：金标把一句拆成『条件(I09)+结论(I10)』，候选整句被 I10 占用，一对一映射必有一条落空 |
| 14 | B | NT-I19 | 源1 | Y | char:4385-4657 | `出口管制一旦打到 GPU 系统集成` | `itm_659e7d6382f5fd02` | 0.682 | matched | NT-I20 | 金标比候选细：同上，I19 条件从句与 I20 主命题同句，候选被 I20 占用 |

## 四、每条的三档信号明细

### NT-I23（源2，`body[63]`，桶 A_near_duplicate_ce）

- 金标引文：`尚无固定的客户`
- 金标命题：128端口产品尚无固定客户
- 16 断言：否；critical：否；U 2026-10-12 校准撤销：否
- agent draft 机制：候选缺承载主体：裁定理由为缺主语『128端口产品』，仅余谓词
- 信号2（同源最近候选，代理相似度）：
  - `itm_703720fdd5630e8b`（A_pool，裁定 **correct_extra**）sim=0.483 flags=containment,judged_correct_extra
    - 候选文本：`尚无固定的客户，德科立将其视为一个过渡型的产品`
    - 裁定理由：命题『尚无固定的客户，德科立将其视为过渡型产品』缺主语主题『128端口产品』，仅余谓词（无固定客户/过渡型产品）；与itm_356f9d9b缺NT-I48主题同理，截掉主题的弱化版≠同一原子命题→correct_extra。NT-I23/NT-I24留未覆盖（若启用话语回指恢复契约则主题可由前文128端口产品补回，但其与NT-I48裁定需保持一致）。
  - `itm_6e2923485c37dd60`（A_pool，裁定 **correct_extra**）sim=0.429 flags=judged_correct_extra
    - 候选文本：`中心是它的客户`
    - 裁定理由：中心是它的客户，为事实，金标无，correct_extra。
  - `itm_1f3315d7df3255ea`（A_pool，裁定 **correct_extra**）sim=0.273 flags=judged_correct_extra
    - 候选文本：`你们莫名其妙，说的就是这些新客户。`
    - 裁定理由：『莫名其妙说的就是这些新客户』，为观点，金标无，correct_extra。
- 信号1（reason 提及该 gold）2 条：
  - `itm_e6b94f6820523c98`（correct_extra）：128刚推出、正在中心验证（问句），金标NT-I23/24未含『验证中』，correct_extra。
  - `itm_703720fdd5630e8b`（correct_extra）：命题『尚无固定的客户，德科立将其视为过渡型产品』缺主语主题『128端口产品』，仅余谓词（无固定客户/过渡型产品）；与itm_356f9d9b缺NT-I48主题同理，截掉主题的弱化版≠同一原子命题→correct_extra。NT-I23/NT-I24留未覆盖（若启用话语回指恢复契约则主题可由前文128端口产品补回，但其与NT-I48裁定需保持一致）。
- 信号3（落在未产出槽）：无

### NT-I24（源2，`body[63]`，桶 A_near_duplicate_ce）

- 金标引文：`德科立将其视为一个过渡型的产品`
- 金标命题：128端口产品被视为过渡产品
- 16 断言：否；critical：否；U 2026-10-12 校准撤销：否
- agent draft 机制：候选缺承载主体：同 I23（同一候选拆出的另一条）
- 信号2（同源最近候选，代理相似度）：
  - `itm_703720fdd5630e8b`（A_pool，裁定 **correct_extra**）sim=0.811 flags=containment,sim>=thr,judged_correct_extra
    - 候选文本：`尚无固定的客户，德科立将其视为一个过渡型的产品`
    - 裁定理由：命题『尚无固定的客户，德科立将其视为过渡型产品』缺主语主题『128端口产品』，仅余谓词（无固定客户/过渡型产品）；与itm_356f9d9b缺NT-I48主题同理，截掉主题的弱化版≠同一原子命题→correct_extra。NT-I23/NT-I24留未覆盖（若启用话语回指恢复契约则主题可由前文128端口产品补回，但其与NT-I48裁定需保持一致）。
  - `itm_9bcf569cc80261ee`（A_pool，裁定 **correct_extra**）sim=0.296 flags=judged_correct_extra
    - 候选文本：`这个就是金像电的这个产品`
    - 裁定理由：「这个就是金像电的这个产品」，对前述预测的归属说明，金标无，correct_extra。
  - `itm_6c8aa33624f6a362`（A_pool，裁定 **correct_extra**）sim=0.24 flags=judged_correct_extra
    - 候选文本：`这是二者取其一的事情`
    - 裁定理由：二者取其一，观点，金标无，correct_extra。
- 信号1（reason 提及该 gold）1 条：
  - `itm_703720fdd5630e8b`（correct_extra）：命题『尚无固定的客户，德科立将其视为过渡型产品』缺主语主题『128端口产品』，仅余谓词（无固定客户/过渡型产品）；与itm_356f9d9b缺NT-I48主题同理，截掉主题的弱化版≠同一原子命题→correct_extra。NT-I23/NT-I24留未覆盖（若启用话语回指恢复契约则主题可由前文128端口产品补回，但其与NT-I48裁定需保持一致）。
- 信号3（落在未产出槽）：无

### NT-I26（源2，`body[72]`，桶 A_near_duplicate_ce）

- 金标引文：`说明设计上仍然存在缺陷`
- 金标命题：128端口光波导设计仍有缺陷
- 16 断言：否；critical：否；U 2026-10-12 校准撤销：否
- agent draft 机制：候选缺承载主体：文本逐字相同，但裁定理由为缺主语『128端口光波导』
- 信号2（同源最近候选，代理相似度）：
  - `itm_a41addfcb6696346`（A_pool，裁定 **correct_extra**）sim=1.0 flags=containment,sim>=thr,judged_correct_extra
    - 候选文本：`说明设计上仍然存在缺陷，`
    - 裁定理由：说明设计上仍然存在缺陷，为观点；同句语境指128光波导，含NT-I26『128端口光波导设计仍有缺陷』谓词，但命题缺主语『128端口光波导』，按itm_703720fdd5630e8b（缺主题→correct_extra）口径，correct_extra。
  - `itm_5de2e5ebfaa12f38`（A_pool，裁定 **matched**，指向 NT-I25）sim=0.311 flags=judged_matched_other
    - 候选文本：`在实际研发当中，128的光波导经过五个批次的流片后，良率仍然不乐观，`
    - 裁定理由：与金标NT-I25『128端口光波导五次流片后良率仍不理想』同义：主体『128的光波导』≡128端口光波导（省单位词，同NT-I49尺度）；『五个批次的流片后』≡五次流片后；『良率仍然不乐观』≡良率仍不理想。主体/事件/结论三一致，matched。
  - `itm_49e72647189fa999`（A_pool，裁定 **correct_extra**）sim=0.258 flags=judged_correct_extra
    - 候选文本：`虽然NVIDIA可能对128有需求`
    - 裁定理由：NVIDIA可能对128有需求，金标无此条，correct_extra。
- 信号1（reason 提及该 gold）1 条：
  - `itm_a41addfcb6696346`（correct_extra）：说明设计上仍然存在缺陷，为观点；同句语境指128光波导，含NT-I26『128端口光波导设计仍有缺陷』谓词，但命题缺主语『128端口光波导』，按itm_703720fdd5630e8b（缺主题→correct_extra）口径，correct_extra。
- 信号3（落在未产出槽）：无

### NT-I31（源2，`body[37]`，桶 A_near_duplicate_ce）

- 金标引文：`北美的这些电力短缺`
- 金标命题：北美数据中心存在电力短缺
- 16 断言：否；critical：否；U 2026-10-12 校准撤销：否
- agent draft 机制：金标比候选细/切分不同：I31 与 I32 为同一句的两种切分，候选被 I32 占用
- 信号2（同源最近候选，代理相似度）：
  - `itm_7b0cfc4d08a27730`（A_pool，裁定 **matched**，指向 NT-I32）sim=0.529 flags=containment,judged_matched_other
    - 候选文本：`主要群体北美的这些电力短缺的确会影响到公司出货节奏`
    - 裁定理由：与金标NT-I32『北美电力短缺会影响公司出货节奏』同义（『北美的电力短缺的确会影响到公司出货节奏』），matched。
  - `itm_a41addfcb6696346`（A_pool，裁定 **correct_extra**）sim=0.261 flags=judged_correct_extra
    - 候选文本：`说明设计上仍然存在缺陷，`
    - 裁定理由：说明设计上仍然存在缺陷，为观点；同句语境指128光波导，含NT-I26『128端口光波导设计仍有缺陷』谓词，但命题缺主语『128端口光波导』，按itm_703720fdd5630e8b（缺主题→correct_extra）口径，correct_extra。
  - `itm_1f3315d7df3255ea`（A_pool，裁定 **correct_extra**）sim=0.25 flags=judged_correct_extra
    - 候选文本：`你们莫名其妙，说的就是这些新客户。`
    - 裁定理由：『莫名其妙说的就是这些新客户』，为观点，金标无，correct_extra。
- 信号1（reason 提及该 gold）：0 条
- 信号3（落在未产出槽）：无

### NT-I34（源2，`body[37]`，桶 A_near_duplicate_ce）

- 金标引文：`预计到29年30年在材料取得重大突破前，可插拔仍然是主流`
- 金标命题：到2029至2030年可插拔方案仍将是主流
- 16 断言：否；critical：是；U 2026-10-12 校准撤销：否
- agent draft 机制：候选缺时间框架与条件：裁定理由为缺『2029-2030 年』与『材料未突破』
- 信号2（同源最近候选，代理相似度）：
  - `itm_15c17f04855a28b3`（A_pool，裁定 **correct_extra**）sim=0.483 flags=containment,judged_correct_extra
    - 候选文本：`可插拔仍然是主流`
    - 裁定理由：可插拔仍然是主流，金标NT-I34含『2029-2030年』时间框架与『材料未突破』条件，候选缺框架与条件，为截短版，correct_extra。
  - `itm_a182c96df99ecd98`（A_pool，裁定 **correct_extra**）sim=0.323 flags=judged_correct_extra
    - 候选文本：`可插拔并没有成为主流`
    - 裁定理由：可插拔并没有成为主流（否定），与NT-I34『可插拔仍将是主流』方向相反，非匹配，correct_extra。
  - `itm_f2e29952886293c0`（A_pool，裁定 **correct_extra**）sim=0.286 flags=judged_correct_extra
    - 候选文本：`可插拔主导70%。`
    - 裁定理由：【2026-10-12 U 校准裁定】原判 matched 撤销：金标为「被转述且被质疑的预测」(perspective=quoted_other, source_stance=challenged)；候选为「材料自身陈述的预测」(source_explicit, reported)。归属与来源态度不同 ⇒ 语义不等价（契约 matching.items 要求保留归属/来源态度）⇒ 不匹配。候选内
- 信号1（reason 提及该 gold）4 条：
  - `itm_a182c96df99ecd98`（correct_extra）：可插拔并没有成为主流（否定），与NT-I34『可插拔仍将是主流』方向相反，非匹配，correct_extra。
  - `itm_7f8414769e6a2a07`（correct_extra）：可插拔CPO没有成为主流（否定），与NT-I34方向相反，非匹配，correct_extra。
  - `itm_933ebba82bb09be7`（correct_extra）：可插拔仍有生命周期，金标NT-I34为『2029-2030主流』含时间框架，候选无框架，correct_extra。
  - `itm_15c17f04855a28b3`（correct_extra）：可插拔仍然是主流，金标NT-I34含『2029-2030年』时间框架与『材料未突破』条件，候选缺框架与条件，为截短版，correct_extra。
- 信号3（落在未产出槽）：无

### NT-I36（源2，`body[115]`，桶 A_near_duplicate_ce）

- 金标引文：`像当年机器人份额加起来超过100%`
- 金标命题：公司口径可能导致行业份额加总超过100%
- 16 断言：否；critical：否；U 2026-10-12 校准撤销：否
- agent draft 机制：断言形态不符：候选为类比式问句而非肯定断言
- 信号2（同源最近候选，代理相似度）：
  - `itm_ec18c38405c7e17f`（A_pool，裁定 **correct_extra**）sim=0.78 flags=containment,sim>=thr,judged_correct_extra
    - 候选文本：`像当年机器人份额加起来超过100%，会不会出现这个状态？`
    - 裁定理由：以「当年机器人份额加起来超过100%」作历史类比，与NT-I36现象同源但为类比式问句，非金标肯定断言，correct_extra。
  - `itm_39f7ca0b5c2e1e73`（A_pool，裁定 **correct_extra**）sim=0.533 flags=judged_correct_extra
    - 候选文本：`你说的加起来总不能超过100%。`
    - 裁定理由：「加起来总不能超过100%」为否定式反驳，与NT-I36（份额可能超过100%）方向相反，属独立观点，correct_extra。
  - `itm_42ffb8cedfa8d7ff`（A_pool，裁定 **correct_extra**）sim=0.24 flags=judged_correct_extra
    - 候选文本：`29年NPO到10%，`
    - 裁定理由：【2026-10-12 U 校准裁定】原判 matched 撤销：金标为「被转述且被质疑的预测」(perspective=quoted_other, source_stance=challenged)；候选为「材料自身陈述的预测」(source_explicit, reported)。归属与来源态度不同 ⇒ 语义不等价（契约 matching.items 要求保留归属/来源态度）⇒ 不匹配。候选内
- 信号1（reason 提及该 gold）5 条：
  - `itm_0398b930d1777c44`（correct_extra）：「加起来是不是会出现一个状态」为修辞问句，传达份额加总失真的关切点，金标NT-I36为肯定式风险断言，本句为问句形式，correct_extra。
  - `itm_ec18c38405c7e17f`（correct_extra）：以「当年机器人份额加起来超过100%」作历史类比，与NT-I36现象同源但为类比式问句，非金标肯定断言，correct_extra。
  - `itm_39f7ca0b5c2e1e73`（correct_extra）：「加起来总不能超过100%」为否定式反驳，与NT-I36（份额可能超过100%）方向相反，属独立观点，correct_extra。
  - `itm_5e38e7d668363dbd`（correct_extra）：『这个也是那个协会的』，为份额口径讨论片段，金标NT-I35/37已另由候选命中，本片段单独不构整句，correct_extra（关联NT-I36份额加总）。
  - `itm_a0c3595e9860c57c`（correct_extra）：『肯定是所有的光模块全算进去的』，协会份额加总机制片段；金标NT-I36为『口径导致加总超100%』，候选只给机制未给结论，correct_extra。
- 信号3（落在未产出槽）：无

### NT-I38（源2，`body[51]`，桶 A_near_duplicate_ce）

- 金标引文：`Q2 800G其实是超预期的，肯定是超预期的。但这也不叫超预期`
- 金标命题：讲者先称800G超预期，随后限定这并非通常意义的超预期
- 16 断言：是；critical：否；U 2026-10-12 校准撤销：否
- agent draft 机制：金标比候选粗：金标把前半+后半两个原子并为一条，候选正确拆成两条，各自不完整均判 ce
- 信号2（同源最近候选，代理相似度）：
  - `itm_bf5fa66fb7be5a02`（A_pool，裁定 **correct_extra**）sim=0.833 flags=containment,sim>=thr,judged_correct_extra
    - 候选文本：`Q2 800G其实是超预期的，肯定是超预期的。`
    - 裁定理由：Q2 800G超预期，为NT-I38『先称800G超预期、后限定非通常意义超预期』的前半句，缺后半限定，correct_extra（与itm_7a4789de164cf58a合起来覆盖NT-I38）。
  - `itm_7a4789de164cf58a`（A_pool，裁定 **correct_extra**）sim=0.444 flags=containment,judged_correct_extra
    - 候选文本：`但这也不叫超预期。`
    - 裁定理由：但不叫超预期，为NT-I38后半句（限定非通常意义超预期），缺前半，correct_extra（与itm_bf5fa66fb7be5a02合起来覆盖NT-I38）。
  - `itm_0d765014a64939ef`（A_pool，裁定 **out_of_scope**）sim=0.32 flags=—
    - 候选文本：`二季度800G出货量未达市场预期的原因是什么？`
    - 裁定理由：「二季度800G出货量未达预期的原因是什么？」纯疑问句，无命题内容，out_of_scope。
- 信号1（reason 提及该 gold）3 条：
  - `itm_e3109b1c8250afaf`（correct_extra）：「那反正不是旭创的数字」为数据归属 claim（800G相关数字非中际旭创），与NT-I38（800G超预期但限定）非同一命题，correct_extra。
  - `itm_bf5fa66fb7be5a02`（correct_extra）：Q2 800G超预期，为NT-I38『先称800G超预期、后限定非通常意义超预期』的前半句，缺后半限定，correct_extra（与itm_7a4789de164cf58a合起来覆盖NT-I38）。
  - `itm_7a4789de164cf58a`（correct_extra）：但不叫超预期，为NT-I38后半句（限定非通常意义超预期），缺前半，correct_extra（与itm_bf5fa66fb7be5a02合起来覆盖NT-I38）。
- 信号3（落在未产出槽）：无

### NT-I39（源2，`body[26]`，桶 A_near_duplicate_ce）

- 金标引文：`这里面税率加上去`
- 金标命题：成本转嫁风险的条件
- 16 断言：是；critical：否；U 2026-10-12 校准撤销：否
- agent draft 机制：候选缺限定：裁定理由为未提『海外产能』且仅为片段
- 信号2（同源最近候选，代理相似度）：
  - `itm_a79b0be05f3456c3`（A_pool，裁定 **correct_extra**）sim=0.889 flags=containment,sim>=thr,judged_correct_extra
    - 候选文本：`然后这里面税率加上去`
    - 裁定理由：税率加上去，金标NT-I39条件为『海外产能税率增加』，候选未提海外产能且仅为片段，不构成干净匹配，correct_extra。
  - `itm_806cac42d71917ad`（A_pool，裁定 **correct_extra**）sim=0.286 flags=judged_correct_extra
    - 候选文本：`你不可能全部转嫁给客户的`
    - 裁定理由：『不可能全部转嫁给客户』与NT-I40同命题但措辞异于已matched的itm_a8be3a946325fa22，非逐字重复，correct_extra（NT-I40的同义异述）。
  - `itm_e295d711292b83a2`（A_pool，裁定 **matched**，指向 NT-I29）sim=0.273 flags=judged_matched_other
    - 候选文本：`因为政策原因导致成本的上升`
    - 裁定理由：与金标NT-I29『启动提价协商的条件=政策变化导致成本上升』同主题同结论（『因为政策原因导致成本的上升』≡政策导致成本上升，即提价协商的触发条件），matched。
- 信号1（reason 提及该 gold）1 条：
  - `itm_a79b0be05f3456c3`（correct_extra）：税率加上去，金标NT-I39条件为『海外产能税率增加』，候选未提海外产能且仅为片段，不构成干净匹配，correct_extra。
- 信号3（落在未产出槽）：无

### NT-I45（源2，`body[1]`，桶 A_near_duplicate_ce）

- 金标引文：`29年NPO到10%`
- 金标命题：被转述预测称2029年NPO渗透率为10%
- 16 断言：是；critical：否；U 2026-10-12 校准撤销：是
- agent draft 机制：U 2026-10-12 校准撤销：金标为被转述且被质疑的预测（quoted_other/challenged），候选为材料自身陈述
- 信号2（同源最近候选，代理相似度）：
  - `itm_42ffb8cedfa8d7ff`（A_pool，裁定 **correct_extra**）sim=1.0 flags=containment,sim>=thr,judged_correct_extra
    - 候选文本：`29年NPO到10%，`
    - 裁定理由：【2026-10-12 U 校准裁定】原判 matched 撤销：金标为「被转述且被质疑的预测」(perspective=quoted_other, source_stance=challenged)；候选为「材料自身陈述的预测」(source_explicit, reported)。归属与来源态度不同 ⇒ 语义不等价（契约 matching.items 要求保留归属/来源态度）⇒ 不匹配。候选内
  - `itm_09fc1a90e71fe5bf`（A_pool，裁定 **correct_extra**）sim=0.533 flags=judged_correct_extra
    - 候选文本：`CPO到30%，`
    - 裁定理由：【2026-10-12 U 校准裁定】原判 matched 撤销：金标为「被转述且被质疑的预测」(perspective=quoted_other, source_stance=challenged)；候选为「材料自身陈述的预测」(source_explicit, reported)。归属与来源态度不同 ⇒ 语义不等价（契约 matching.items 要求保留归属/来源态度）⇒ 不匹配。候选内
  - `itm_64a666c2efc4b5d8`（A_pool，裁定 **correct_extra**）sim=0.385 flags=judged_correct_extra
    - 候选文本：`27年5万到10万个水平，这是合理的`
    - 裁定理由：27年5万到10万个水平，为27年CPO出货预测，与NT-I22的26年口径不同，correct_extra。
- 信号1（reason 提及该 gold）1 条：
  - `itm_42ffb8cedfa8d7ff`（correct_extra）：【2026-10-12 U 校准裁定】原判 matched 撤销：金标为「被转述且被质疑的预测」(perspective=quoted_other, source_stance=challenged)；候选为「材料自身陈述的预测」(source_explicit, reported)。归属与来源态度不同 ⇒ 语义不等价（契约 matching.items 要求保留归属/来源态度）⇒ 不匹配。候选内
- 信号3（落在未产出槽）：无

### NT-I46（源2，`body[1]`，桶 A_near_duplicate_ce）

- 金标引文：`CPO到30%`
- 金标命题：被转述预测称2029年CPO渗透率为30%
- 16 断言：是；critical：否；U 2026-10-12 校准撤销：是
- agent draft 机制：U 2026-10-12 校准撤销：同 I45
- 信号2（同源最近候选，代理相似度）：
  - `itm_09fc1a90e71fe5bf`（A_pool，裁定 **correct_extra**）sim=1.0 flags=containment,sim>=thr,judged_correct_extra
    - 候选文本：`CPO到30%，`
    - 裁定理由：【2026-10-12 U 校准裁定】原判 matched 撤销：金标为「被转述且被质疑的预测」(perspective=quoted_other, source_stance=challenged)；候选为「材料自身陈述的预测」(source_explicit, reported)。归属与来源态度不同 ⇒ 语义不等价（契约 matching.items 要求保留归属/来源态度）⇒ 不匹配。候选内
  - `itm_42ffb8cedfa8d7ff`（A_pool，裁定 **correct_extra**）sim=0.533 flags=judged_correct_extra
    - 候选文本：`29年NPO到10%，`
    - 裁定理由：【2026-10-12 U 校准裁定】原判 matched 撤销：金标为「被转述且被质疑的预测」(perspective=quoted_other, source_stance=challenged)；候选为「材料自身陈述的预测」(source_explicit, reported)。归属与来源态度不同 ⇒ 语义不等价（契约 matching.items 要求保留归属/来源态度）⇒ 不匹配。候选内
  - `itm_bd6cd536f1fc2c56`（A_pool，裁定 **correct_extra**）sim=0.375 flags=judged_correct_extra
    - 候选文本：`CPO主要在交换机侧`
    - 裁定理由：CPO主要在交换机侧，为事实，金标NT-I21为『CPO市场成熟度不高』，本候选主语不同，correct_extra。
- 信号1（reason 提及该 gold）1 条：
  - `itm_09fc1a90e71fe5bf`（correct_extra）：【2026-10-12 U 校准裁定】原判 matched 撤销：金标为「被转述且被质疑的预测」(perspective=quoted_other, source_stance=challenged)；候选为「材料自身陈述的预测」(source_explicit, reported)。归属与来源态度不同 ⇒ 语义不等价（契约 matching.items 要求保留归属/来源态度）⇒ 不匹配。候选内
- 信号3（落在未产出槽）：无

### NT-I47（源2，`body[1]`，桶 A_near_duplicate_ce）

- 金标引文：`可插拔主导70%`
- 金标命题：被转述预测称2029年可插拔份额为70%
- 16 断言：是；critical：否；U 2026-10-12 校准撤销：是
- agent draft 机制：U 2026-10-12 校准撤销：同 I45
- 信号2（同源最近候选，代理相似度）：
  - `itm_f2e29952886293c0`（A_pool，裁定 **correct_extra**）sim=1.0 flags=containment,sim>=thr,judged_correct_extra
    - 候选文本：`可插拔主导70%。`
    - 裁定理由：【2026-10-12 U 校准裁定】原判 matched 撤销：金标为「被转述且被质疑的预测」(perspective=quoted_other, source_stance=challenged)；候选为「材料自身陈述的预测」(source_explicit, reported)。归属与来源态度不同 ⇒ 语义不等价（契约 matching.items 要求保留归属/来源态度）⇒ 不匹配。候选内
  - `itm_15c17f04855a28b3`（A_pool，裁定 **correct_extra**）sim=0.533 flags=judged_correct_extra
    - 候选文本：`可插拔仍然是主流`
    - 裁定理由：可插拔仍然是主流，金标NT-I34含『2029-2030年』时间框架与『材料未突破』条件，候选缺框架与条件，为截短版，correct_extra。
  - `itm_a182c96df99ecd98`（A_pool，裁定 **correct_extra**）sim=0.471 flags=judged_correct_extra
    - 候选文本：`可插拔并没有成为主流`
    - 裁定理由：可插拔并没有成为主流（否定），与NT-I34『可插拔仍将是主流』方向相反，非匹配，correct_extra。
- 信号1（reason 提及该 gold）1 条：
  - `itm_f2e29952886293c0`（correct_extra）：【2026-10-12 U 校准裁定】原判 matched 撤销：金标为「被转述且被质疑的预测」(perspective=quoted_other, source_stance=challenged)；候选为「材料自身陈述的预测」(source_explicit, reported)。归属与来源态度不同 ⇒ 语义不等价（契约 matching.items 要求保留归属/来源态度）⇒ 不匹配。候选内
- 信号3（落在未产出槽）：无

### NT-I48（源2，`body[26]`，桶 A_near_duplicate_ce）

- 金标引文：`由于台湾海鸥基地有免税政策，这部分会转嫁给客户，因此对竞争力和毛利影响不大`
- 金标命题：被转述观点认为税负可转嫁，对竞争力和毛利影响不大
- 16 断言：是；critical：否；U 2026-10-12 校准撤销：否
- agent draft 机制：金标比候选粗：同 I38，金标合并『税负可转嫁』+『对竞争力毛利影响不大』两半
- 信号2（同源最近候选，代理相似度）：
  - `itm_d96a4e7b052a89c7`（A_pool，裁定 **correct_extra**）sim=0.772 flags=containment,sim>=thr,judged_correct_extra
    - 候选文本：`由于台湾海鸥基地有免税政策，这部分会转嫁给客户`
    - 裁定理由：台湾海鸥基地免税、税负转嫁客户，为NT-I48「税负可转嫁」半句；金标NT-I48合并「税负可转嫁+对竞争力和毛利影响不大」两句，本候选仅含前半，不完整，correct_extra。
  - `itm_356f9d9b23c78892`（A_pool，裁定 **correct_extra**）sim=0.611 flags=containment,judged_correct_extra
    - 候选文本：`因此对竞争力和毛利影响不大`
    - 裁定理由：对竞争力和毛利影响不大，为NT-I48后半句；金标NT-I48为合并claim，本候选仅含后半，不完整，correct_extra。
  - `itm_b761f5c084e6360a`（A_pool，裁定 **correct_extra**）sim=0.419 flags=judged_correct_extra
    - 候选文本：`你如果转嫁了，对你的竞争力就会有影响，对不对？`
    - 裁定理由：转嫁会影响竞争力，与NT-I48『对竞争力影响不大』方向相反，非匹配，correct_extra。
- 信号1（reason 提及该 gold）4 条：
  - `itm_d96a4e7b052a89c7`（correct_extra）：台湾海鸥基地免税、税负转嫁客户，为NT-I48「税负可转嫁」半句；金标NT-I48合并「税负可转嫁+对竞争力和毛利影响不大」两句，本候选仅含前半，不完整，correct_extra。
  - `itm_356f9d9b23c78892`（correct_extra）：对竞争力和毛利影响不大，为NT-I48后半句；金标NT-I48为合并claim，本候选仅含后半，不完整，correct_extra。
  - `itm_b761f5c084e6360a`（correct_extra）：转嫁会影响竞争力，与NT-I48『对竞争力影响不大』方向相反，非匹配，correct_extra。
  - `itm_703720fdd5630e8b`（correct_extra）：命题『尚无固定的客户，德科立将其视为过渡型产品』缺主语主题『128端口产品』，仅余谓词（无固定客户/过渡型产品）；与itm_356f9d9b缺NT-I48主题同理，截掉主题的弱化版≠同一原子命题→correct_extra。NT-I23/NT-I24留未覆盖（若启用话语回指恢复契约则主题可由前文128端口产品补回，但其与NT-I48裁定需保持一致）。
- 信号3（落在未产出槽）：无

### NT-I09（源1，`char:3925-4239`，桶 B_occupied_by_gold）

- 金标引文：`一旦毛利率再掉或 Rubin 延期`
- 金标命题：估值风险触发条件
- 16 断言：是；critical：否；U 2026-10-12 校准撤销：否
- agent draft 机制：金标比候选细：金标把一句拆成『条件(I09)+结论(I10)』，候选整句被 I10 占用，一对一映射必有一条落空
- 信号2（同源最近候选，代理相似度）：
  - `itm_2f60038387b4ea72`（A_pool，裁定 **matched**，指向 NT-I10）sim=0.769 flags=containment,sim>=thr,judged_matched_other
    - 候选文本：`一旦毛利率再掉或 Rubin 延期，弹性会先打在倍数上`
    - 裁定理由：『一旦毛利率再掉或Rubin延期，弹性会先打在倍数上』即金标NT-I10『估值倍数会先受到冲击』（forecast/affirmed），匹配 NT-I10。
  - `slot_90af9c4e66866cda#4`（signed_base，裁定 **duplicate**）sim=0.636 flags=containment
    - 候选文本：`Rubin 延期`
  - `itm_2a32de1669ff155d`（A_pool，裁定 **correct_extra**）sim=0.414 flags=judged_correct_extra
    - 候选文本：`Rubin / GB300 爬坡再延`
    - 裁定理由：Rubin/GB300爬坡再延为风险预测，不在金标内，correct_extra。
- 信号1（reason 提及该 gold）：0 条
- 信号3（落在未产出槽）：无

### NT-I19（源1，`char:4385-4657`，桶 B_occupied_by_gold）

- 金标引文：`出口管制一旦打到 GPU 系统集成`
- 金标命题：地理对冲失效的外部条件
- 16 断言：是；critical：是；U 2026-10-12 校准撤销：否
- agent draft 机制：金标比候选细：同上，I19 条件从句与 I20 主命题同句，候选被 I20 占用
- 信号2（同源最近候选，代理相似度）：
  - `itm_659e7d6382f5fd02`（A_pool，裁定 **matched**，指向 NT-I20）sim=0.682 flags=containment,judged_matched_other
    - 候选文本：`墨西哥 / 美国厂是地理对冲，救不了出口管制一旦打到 GPU 系统集成`
    - 裁定理由：与金标NT-I20「墨西哥和美国工厂不能对冲GPU系统集成出口管制风险」同一命题（地理对冲救不了GPU系统集成出口管制），matched。
  - `itm_f80c5549dbc66cd1`（A_pool，裁定 **correct_extra**）sim=0.231 flags=judged_correct_extra
    - 候选文本：`GPU 线绑定英伟达节奏`
    - 裁定理由：GPU线绑定英伟达节奏，为事实陈述，不在金标内，correct_extra。
  - `slot_6d633216b432f293#1`（signed_r5，裁定 **correct_extra**）sim=0.188 flags=judged_correct_extra
    - 候选文本：`GPU/ASIC 机柜出货 +3.2 / +3 倍`
- 信号1（reason 提及该 gold）：0 条
- 信号3（落在未产出槽）：无

## 五、口径与校验

- 两份 48 条金标 id 集合一致：True；引文不一致 0 条；来源不一致 0 条
- 参与计算候选 253 条：{'A_pool': 222, 'signed_base': 16, 'signed_r5': 15}
- 来源分布：{'源1': 119, '源2': 134}
- 31 条签认批候选全部属于源1；源2 的 FN 只可能由 222 池内的源2 候选解释。

## 六、与既有表述的矛盾（需更正记录）

| 既有表述 | 出处 | 机器实测 |
|---|---|---|
| 缺口为真实 FN（金标无候选匹配），非流程问题 | `evidence/69-union-adjudication-20261013/r1-score/gate33-honest-score.json:88` | 14/14 条 FN 在同源候选里都有近似文本（12 条 sim>=0.75 或互为包含，2 条候选已被邻近金标占用且带具名理由）；『无匹配』字面为真，但读作『模型没产出相关内容』与实测不符 |
| 14 条 FN 为真实抽取覆盖缺口（三次独立抽取均未覆盖） | `evidence/69-union-adjudication-20261013/r1-score/gate33-full-verdict.md:26-30` | 0 条落在 evidence/32 记录的 9 个未产出槽；0 条为『池内无近似候选』 |
| 8 条未过断言全部属于源2 文档段 | `evidence/69-union-adjudication-20261013/r1-score/gate33-full-verdict.md:17 与 report.md:14` | NT-I09、NT-I19 属于源1（locator 为 char: 体系；源2 为 body[N] 体系），与其自身判据 2『源1 20/22』自相矛盾 |
| 源2 召回 0.538 + 8 条断言未过：需对源2 对应片段定向补抽 | `evidence/70-closure-20261013/r0-zero-call/closure.md:29 与 gate33-full-verdict.md:34` | 补抽同样会产出这些片段，而它们已被具名裁定为非等价（原子度/限定/承载/断言形态）；要翻必须先裁口径，不是抽取问题 |

> 更正须按『新版本记录 + 旧哈希留存』办理，不得编辑上述已执行产物的字节。

## 七、复现

```bash
uv run python .scratch/claims-r2-role-isolation/evidence/71-fn-attribution-20261013/r0-zero-call/build_fn_attribution.py
```
