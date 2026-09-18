# I3-2 证据目标：人工裁决单（待 U 填）

> 本文件是**批准件模板**，与机器候选 [evidence-targets-candidates.json](evidence-targets-candidates.json) 分开存储；
> 未经裁决的回填不得写回候选文件（write-once），批准结果应另存为 `evidence-targets-decisions.json`（模板见 §5）。

## 0. 本次裁决的口径（先确认，再逐项裁决）

- **EvidencePass 分母 = 逐题**：逐题：满足全部必需证据的题数 / 证据题数（架构 §12.3）；60 条 item 或槽位聚合只决定每题内部是否全部满足，不能替代分母；
  item 条数与槽位聚合只作诊断展示，**不得**用来替代分母（槽位聚合若降低必需证据要求
  即为改变验收合同，须先改架构 §12.3 而不是在本单里选）。
- 机器候选规则 `evidence-mapping-4`：`role=required` 必需 ／ `role=supporting` 可替代 ／
  `role=suggested` 待批准锚点（批准前不计入必需）。
- 机器**不代决**的事项：定性要件的语义归属、数值等价确认、多来源覆盖指定、
  答案侧口径确认、负例覆盖依据；本次共 **36** 项需逐项给出『批准/改选/驳回』与理由。
- 裁决前不得把候选当正式金标，也不得先跑候选业务结果再补答案。

## 1. 逐题状态总表

| 题号 | 类别 | 机器状态 | 必需 | 可替代 | 待批准锚点 | 待裁决 |
|---|---|---|---|---|---|---|
| company-001 | company | machine_ready | 1 | 3 | 0 | 0 |
| company-002 | company | pending_human | 2 | 0 | 0 | 1 |
| company-003 | company | pending_human | 6 | 0 | 0 | 1 |
| company-004 | company | pending_human | 1 | 0 | 0 | 2 |
| company-005 | company | machine_ready | 2 | 1 | 0 | 0 |
| company-006 | company | machine_ready | 2 | 0 | 0 | 0 |
| company-007 | company | pending_human | 1 | 0 | 0 | 1 |
| company-008 | company | pending_human | 0 | 0 | 2 | 4 |
| company-009 | company | negative_opt_out | 0 | 0 | 0 | 0 |
| company-010 | company | negative_opt_out | 0 | 0 | 0 | 0 |
| industry-001 | industry | pending_human | 3 | 0 | 1 | 1 |
| industry-002 | industry | pending_human | 2 | 0 | 2 | 2 |
| industry-003 | industry | pending_human | 2 | 0 | 1 | 1 |
| industry-004 | industry | pending_human | 0 | 0 | 2 | 3 |
| industry-005 | industry | pending_human | 1 | 0 | 0 | 1 |
| industry-006 | industry | pending_human | 0 | 0 | 1 | 3 |
| industry-007 | industry | pending_human | 2 | 0 | 0 | 1 |
| industry-008 | industry | pending_human | 1 | 0 | 1 | 3 |
| industry-009 | industry | negative_opt_out | 0 | 0 | 0 | 0 |
| industry-010 | industry | negative_opt_out | 0 | 0 | 0 | 0 |
| macro-001 | macro | pending_human | 1 | 0 | 0 | 1 |
| macro-002 | macro | pending_human | 2 | 0 | 0 | 1 |
| macro-003 | macro | blocked | 1 | 0 | 1 | 2 |
| macro-004 | macro | blocked | 0 | 0 | 1 | 3 |
| macro-005 | macro | pending_human | 1 | 0 | 1 | 2 |
| macro-006 | macro | pending_human | 1 | 0 | 1 | 1 |
| macro-007 | macro | pending_human | 2 | 0 | 0 | 1 |
| macro-008 | macro | pending_human | 1 | 0 | 1 | 1 |
| macro-009 | macro | negative_opt_out | 0 | 0 | 0 | 0 |
| macro-010 | macro | negative_opt_out | 0 | 0 | 0 | 0 |

## 2. 待裁决事项（逐项）

### company-002（pending_human）

- **`I32-company-002-01`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足）：'不能混淆半年与单季'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### company-003（pending_human）

- **`I32-company-003-01`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足）：'引用对应行列且标明预测'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### company-004（pending_human）

- **`I32-company-004-01`**（value_equivalence）确认数值等价：要求写作 '13.40'，原文逐字为 ['13.4', '13.4']（原文 quote 不改写，按同一数值接受）
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-company-004-02`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'不得当作实际收入或券商盈利预测'
    - 机器锚点候选（首选）：company-018-claim-001#2（condition）page:1；content_overlap(shared=3, idf=1.75, ratio=0.30)
        - quote：'其设定的2026—2028 年的营业收入触发\n值和目标值分别为8.84/12.06/15.81 亿元（26-28 年同比增速为\n32%/36%/31% ）和9.38/13.4/18.09 亿元'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### company-007（pending_human）

- **`I32-company-007-01`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'华创云信为华创证券控股股东，不能误记成华创证券持有茅台集团'
    - 机器锚点候选（首选）：company-013-claim-001#0（value）page:7；content_overlap(shared=13, idf=11.83, ratio=0.72)
        - quote：'贵州茅台的控股股东茅台集团持有本公司的控股股东华创云信4.06%的股\n份。'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### company-008（pending_human）

- **`I32-company-008-01`**（source_coverage）该子句要求引用多份材料，已转由来源覆盖规则承接：'必须取得两份材料：贵州茅台为强推（维持），光力科技为优于大市（首次覆盖）'
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-company-008-02`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足）：'通用评级定义页不能代替具体评级'
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-company-008-03`**（source_coverage）该题 satisfy_rule=all：来源 2026-08-16_6f14cc14 目前没有必需证据目标，请指定承载 item（或裁定该来源不提供必需证据）
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-company-008-04`**（source_coverage）该题 satisfy_rule=all：来源 2026-09-06_dddc7cd0 目前没有必需证据目标，请指定承载 item（或裁定该来源不提供必需证据）
    - 决定：`批准 / 改选 / 驳回`；依据：____

### industry-001（pending_human）

- **`I32-industry-001-01`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'分位不是价格涨幅，开工率是注2所述期间平均'
    - 机器锚点候选（首选）：industry-009-claim-001#9（condition）page:10；note_ref(注2)
        - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### industry-002（pending_human）

- **`I32-industry-002-01`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'按注3属配额，不能解释为实际产量'
    - 机器锚点候选（首选）：industry-009-claim-001#10（condition）page:10；note_ref(注3)
        - quote：'注3：制冷剂R22、R32、R134a 的产能为配额'
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-industry-002-02`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'价格分位窗口2016-01-01至2026-07-27'
    - 机器锚点候选（首选）：industry-009-claim-001#8（condition）page:10；content_overlap(shared=3, idf=3.00, ratio=0.60)
        - quote：'注1：价格、价差分位为2016 年1 月1 日至2026 年7 月27 日'
    - 机器锚点候选（备选）：industry-009-claim-001#0（table_cell）page:10 row:纯碱 col:价格分位；content_overlap(shared=3, idf=3.00, ratio=0.60)
        - quote：'0.0%'
    - 机器锚点候选（备选）：industry-009-claim-001#3（table_cell）page:10 row:R32 col:价格分位；content_overlap(shared=3, idf=3.00, ratio=0.60)
        - quote：'99.6%'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### industry-003（pending_human）

- **`I32-industry-003-01`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'区分开工率与产能，2026E为预测列'
    - 机器锚点候选（首选）：industry-009-claim-001#9（condition）page:10；content_overlap(shared=2, idf=2.00, ratio=0.29)
        - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
    - 机器锚点候选（备选）：industry-009-claim-001#2（table_cell）page:10 row:纯碱 col:开工率；content_overlap(shared=2, idf=2.00, ratio=0.29)
        - quote：'82.9%'
    - 机器锚点候选（备选）：industry-009-claim-001#6（table_cell）page:10 row:尿素 col:开工率；content_overlap(shared=2, idf=2.00, ratio=0.29)
        - quote：'89.9%'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### industry-004（pending_human）

- **`I32-industry-004-01`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'价格/价差分位为2016-01-01至2026-07-27'
    - 机器锚点候选（首选）：industry-009-claim-001#8（condition）page:10；content_overlap(shared=4, idf=4.00, ratio=1.00)
        - quote：'注1：价格、价差分位为2016 年1 月1 日至2026 年7 月27 日'
    - 机器锚点候选（备选）：industry-009-claim-001#1（table_cell）page:10 row:纯碱 col:价差分位；content_overlap(shared=3, idf=3.00, ratio=0.75)
        - quote：'0.0%'
    - 机器锚点候选（备选）：industry-009-claim-001#0（table_cell）page:10 row:纯碱 col:价格分位；content_overlap(shared=2, idf=2.00, ratio=0.50)
        - quote：'0.0%'
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-industry-004-02`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'开工率为2026-01-01至07-26平均或2026年1—6月平均'
    - 机器锚点候选（首选）：industry-009-claim-001#9（condition）page:10；content_overlap(shared=3, idf=3.00, ratio=1.00)
        - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
    - 机器锚点候选（备选）：industry-009-claim-001#2（table_cell）page:10 row:纯碱 col:开工率；content_overlap(shared=3, idf=3.00, ratio=1.00)
        - quote：'82.9%'
    - 机器锚点候选（备选）：industry-009-claim-001#6（table_cell）page:10 row:尿素 col:开工率；content_overlap(shared=3, idf=3.00, ratio=1.00)
        - quote：'89.9%'
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-industry-004-03`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'不得擅自把二选一窗口分配到各品种'
    - 机器锚点候选（首选）：industry-009-claim-001#9（condition）page:10；content_overlap(shared=2, idf=2.00, ratio=0.22)
        - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### industry-005（pending_human）

- **`I32-industry-005-01`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足）：'不是所有电子特气共同涨幅，也不是单日涨幅'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### industry-006（pending_human）

- **`I32-industry-006-01`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'报告援引供应链消息：计划用于NVSwitch板卡及Rubin Ultra正交背板主力选材'
    - 机器锚点候选（首选）：industry-057-claim-001#2（condition）page:1；content_overlap(shared=14, idf=14.00, ratio=0.74)
        - quote：'英伟达计划在NVSwitch\n板卡中使用PTFE 材料，并将该材料作为英伟达新一代服务器平台Rubin Ultra\n正交背板的主力选材。Rubin Ultra 预计于2027 年推出。'
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-industry-006-02`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'Rubin Ultra预计2027年推出'
    - 机器锚点候选（首选）：industry-057-claim-001#2（condition）page:1；content_overlap(shared=3, idf=3.00, ratio=1.00)
        - quote：'英伟达计划在NVSwitch\n板卡中使用PTFE 材料，并将该材料作为英伟达新一代服务器平台Rubin Ultra\n正交背板的主力选材。Rubin Ultra 预计于2027 年推出。'
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-industry-006-03`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'须保留消息来源与“计划/预计”限定'
    - 机器锚点候选（首选）：industry-057-claim-001#2（condition）page:1；content_overlap(shared=3, idf=3.00, ratio=0.38)
        - quote：'英伟达计划在NVSwitch\n板卡中使用PTFE 材料，并将该材料作为英伟达新一代服务器平台Rubin Ultra\n正交背板的主力选材。Rubin Ultra 预计于2027 年推出。'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### industry-007（pending_human）

- **`I32-industry-007-01`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足）：'保持指数名和数值配对'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### industry-008（pending_human）

- **`I32-industry-008-01`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'不能：R32为历史价格分位（2016-01-01至2026-07-27）'
    - 机器锚点候选（首选）：industry-009-claim-001#3（table_cell）page:10 row:R32 col:价格分位；content_overlap(shared=4, idf=3.50, ratio=0.67)
        - quote：'99.6%'
    - 机器锚点候选（备选）：industry-009-claim-001#0（table_cell）page:10 row:纯碱 col:价格分位；content_overlap(shared=3, idf=2.50, ratio=0.50)
        - quote：'0.0%'
    - 机器锚点候选（备选）：industry-009-claim-001#5（table_cell）page:10 row:R134a col:价格分位；content_overlap(shared=3, idf=2.50, ratio=0.50)
        - quote：'98.8%'
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-industry-008-02`**（source_coverage）该子句要求引用多份材料，已转由来源覆盖规则承接：'须引用两份材料证明统计含义不同'
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-industry-008-03`**（source_coverage）该题 satisfy_rule=all：来源 2026-08-13_174b6462 目前没有必需证据目标，请指定承载 item（或裁定该来源不提供必需证据）
    - 决定：`批准 / 改选 / 驳回`；依据：____

### macro-001（pending_human）

- **`I32-macro-001-01`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'前值修订与8月数据分开'
    - 机器锚点候选（首选）：macro-038-claim-001#0（value）page:1；content_overlap(shared=2, idf=2.00, ratio=0.50)
        - quote：'新增非农就业16.2\n万人，预期5.6 万人，前值由-2.3 万人修正为2.1 万人'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### macro-002（pending_human）

- **`I32-macro-002-01`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足）：'均为报告所述'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### macro-003（blocked）

- **`I32-macro-003-01`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'条件是后续通胀下行幅度有限'
    - 机器锚点候选（首选）：macro-038-claim-001#3（condition）page:1；content_overlap(shared=7, idf=7.00, ratio=1.00)
        - quote：'若后续公布的通胀数\n据下行幅度有限，美联储9 月加息的可能性将很难被忽视。'
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-macro-003-02`**（qualification）该定性要件在冻结标注中没有承载 item，需人工补标注或裁定：'强就业降低加息顾虑'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### macro-004（blocked）

- **`I32-macro-004-01`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'五主体为政府、准财政、企业、居民、海外'
    - 机器锚点候选（首选）：macro-039-claim-001#1（condition）page:1；content_overlap(shared=6, idf=5.50, ratio=0.86)
        - quote：'这五个主体分别是政府、准财政（如城投等）、企业、居民、海\n外。'
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-macro-004-02`**（qualification）该定性要件在冻结标注中没有承载 item，需人工补标注或裁定：'本文聚焦前四者'
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-macro-004-03`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'四路径为财政支出增加、缓解城投化债压力、企业投资增加、居民支出增加'
    - 机器锚点候选（首选）：macro-039-claim-001#1（condition）page:1；content_overlap(shared=4, idf=3.50, ratio=0.20)
        - quote：'这五个主体分别是政府、准财政（如城投等）、企业、居民、海\n外。'
    - 机器锚点候选（备选）：macro-060-claim-001#4（condition）page:2；content_overlap(shared=2, idf=1.50, ratio=0.10)
        - quote：'使用上市公司或者发债企业的数据代表性可能欠佳，获得的结论有\n一定的偏差。可能存在其他收敛路径。'
    - 机器锚点候选（备选）：macro-039-claim-001#2（value）page:1；content_overlap(shared=2, idf=1.50, ratio=0.10)
        - quote：'2026 年，预计\n两本账支出增速为-0.5%左右，仍低于名义GDP 增速。'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### macro-005（pending_human）

- **`I32-macro-005-01`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'堵点为收入依赖旧动能且受其下行拖累、新动能综合税负偏低'
    - 机器锚点候选（首选）：macro-039-claim-001#0（condition）page:1；content_overlap(shared=2, idf=2.00, ratio=0.14)
        - quote：'新动\n能（包括装备制造业、信息业、租赁和商务服务业），旧动能（地产、建筑、\n上游材料制造业）'
    - 决定：`批准 / 改选 / 驳回`；依据：____
- **`I32-macro-005-02`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足）：'须标注预测'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### macro-006（pending_human）

- **`I32-macro-006-01`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'样本为偏头部发债企业，不等于全国所有国企'
    - 机器锚点候选（首选）：macro-060-claim-001#4（condition）page:2；content_overlap(shared=3, idf=2.50, ratio=0.33)
        - quote：'使用上市公司或者发债企业的数据代表性可能欠佳，获得的结论有\n一定的偏差。可能存在其他收敛路径。'
    - 机器锚点候选（备选）：macro-039-claim-001#3（value）page:1；content_overlap(shared=2, idf=1.50, ratio=0.22)
        - quote：'2025 年，央企样本企业的有息负\n债增速为4.6%，低于2024 年的5.9%。2025 年，地方国有企业样本企业的有\n息负债增速为6.1%，低于2024 年的6.2%。'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### macro-007（pending_human）

- **`I32-macro-007-01`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足）：'不能混用口径'
    - 决定：`批准 / 改选 / 驳回`；依据：____

### macro-008（pending_human）

- **`I32-macro-008-01`**（qualification）确认该定性要件已由下列候选原文承载（或改选/裁定需补标注）：'上市公司/发债企业样本代表性可能欠佳，结论可能偏差且可能有其他收敛路径'
    - 机器锚点候选（首选）：macro-060-claim-001#4（condition）page:2；content_overlap(shared=14, idf=12.00, ratio=1.00)
        - quote：'使用上市公司或者发债企业的数据代表性可能欠佳，获得的结论有\n一定的偏差。可能存在其他收敛路径。'
    - 机器锚点候选（备选）：macro-039-claim-001#3（value）page:1；content_overlap(shared=2, idf=1.00, ratio=0.14)
        - quote：'2025 年，央企样本企业的有息负\n债增速为4.6%，低于2024 年的5.9%。2025 年，地方国有企业样本企业的有\n息负债增速为6.1%，低于2024 年的6.2%。'
    - 机器锚点候选（备选）：macro-039-claim-001#4（value）page:1；content_overlap(shared=2, idf=1.00, ratio=0.14)
        - quote：'2025 年，中国（使用全\n部A 股）为9.8%，美国（使用标普500 成分股）为20.4%，日本（使用日经\n225 成分股）为14.8%，韩国（使用KOSPI200 成分股）为26.7%。'
    - 决定：`批准 / 改选 / 驳回`；依据：____

## 3. 6 道负例的覆盖确认

负例不进入 EvidencePass 正例分母（既有合同），但仍须参加误报/伪造引用检查，
并须人工确认『材料全文确实没有该证据』，不得以未检索到来代替没有证据。

- `company-009`：human_basis 是否仍写『待/需确认全文覆盖』=**False**；覆盖检查：`误报 / 伪造引用 / 分母`；决定：____
- `company-010`：human_basis 是否仍写『待/需确认全文覆盖』=**True**；覆盖检查：`误报 / 伪造引用 / 分母`；决定：____
- `industry-009`：human_basis 是否仍写『待/需确认全文覆盖』=**False**；覆盖检查：`误报 / 伪造引用 / 分母`；决定：____
- `industry-010`：human_basis 是否仍写『待/需确认全文覆盖』=**True**；覆盖检查：`误报 / 伪造引用 / 分母`；决定：____
- `macro-009`：human_basis 是否仍写『待/需确认全文覆盖』=**False**；覆盖检查：`误报 / 伪造引用 / 分母`；决定：____
- `macro-010`：human_basis 是否仍写『待/需确认全文覆盖』=**True**；覆盖检查：`误报 / 伪造引用 / 分母`；决定：____

## 4. 已登记的人工状态冲突（先澄清再裁决）

- `macro-039-claim-001`：human_basis 文本仍写『待复核/需确认』，但 reviewer/reviewed_at 已有值
    - human_basis：'待真人复核。依据：已校验SHA-256的原PDF第1页及该槽原文。摘要对产业分化和四条需求收敛路径作定义，并给出财政预测及企业样本数据。'
    - reviewer=xyl；reviewed_at=2026-09-15T10:40:49+00:00
    - 澄清结论（残留描述 / 实质未决）：____

## 5. 决策回填模板

```json
{
  "artifact": "i3-2-evidence-targets-decisions",
  "rule_rev": "evidence-mapping-4",
  "reviewer": "<U>",
  "reviewed_at": "<ISO8601>",
  "decisions": [
    {"item_id": "I32-<query_id>-01", "decision": "批准|改选|驳回",
     "chosen": [{"slot": "...", "item_index": 0}], "reason": "..."}
  ]
}
```

回填后由 `i3s2_verify_candidates.py` 的完整性门复核：未裁决/未批准/要件未决一律 blocked，
不得宣告 I3-2 完成。
