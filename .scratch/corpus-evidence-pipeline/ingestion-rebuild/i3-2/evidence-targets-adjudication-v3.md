# I3-2 证据目标：人工裁决单（待 U 填）

> 本文件是**批准件模板**，与机器候选 [evidence-targets-candidates.json](evidence-targets-candidates.json) 分开存储；
> 批准结果写进 `evidence-targets-decisions.json`，由 `i3s2_apply_decisions.py` 生成**批准投影** `evidence-targets-approved.json` 并给出完整性门结论。

## 0. 本次裁决的口径（先确认，再逐项裁决）

- **EvidencePass 分母 = 逐题**：逐题：满足全部必需证据的题数 / 证据题数（架构 §12.3）；item 条数或槽位聚合只决定每题内部是否全部满足，不能替代分母；
  item 条数与槽位聚合只作诊断展示，**不得**用来替代分母。
- 机器候选规则 `evidence-mapping-6`：`role=required` 必需 ／ `role=supplementary` 补充（**非必需**，本版不声明替代关系）／ `role=suggested` 待批准锚点（批准前不计入必需）。
- **本次要填的不是只有要件裁决**，共四类：① 要件裁决 **40** 项（定性锚点/数值等价/多来源覆盖/答案侧口径）；② 有答案题**整题验收** **24** 题（对照冻结 `evidence_requirement` 逐项确认，含 `machine_ready` 题——它们没有待裁决要件，但**不等于**无需人工审核）；③ 负例覆盖确认 **6** 题；④ 来源槽位人工状态澄清 **1** 项。
- **改候选文件里的 `adjudication.status` 不能开门**：完整性门只认审批件（`facet_decisions` / `question_reviews` / `negative_reviews` / `human_status_clarifications` + 输入哈希）。审批件必须绑定它所针对的候选/金标哈希，哈希不符即视为过期。
- `adequacy=partial` 的机器锚点（「部分覆盖」）不得直接批准：必须改选覆盖更全的 item、补人工标注。`residual_accepted=true` 禁用；仅词面差异可提交 lexical_review，逐项绑定未覆盖词元、原文片段和理由，不得豁免缺失事实。
- `search_hint`/非首选锚点不得直接批准：须 decision=改选 与 anchor_review 原文承载映射。text/period 等标注元数据只供搜寻，不替代 quote；同义映射仍是人工判断，不是机器语义认证。
- 来源专属项须选择同一 source_id；答案侧约束禁止 chosen，不生成证据目标。全部审批数组禁止重复/未知身份，负例必须写覆盖依据。
- 「驳回」只表示**驳回这个候选锚点**，不删除原题要求：要件仍在覆盖账里，必须给出改选或补标注，否则完整性门保持不放行。
- 裁决前不得把候选当正式金标，也不得先跑候选业务结果再补答案。

## 1. 逐题状态总表

| 题号 | 类别 | 机器状态 | 必需 | 补充 | 待批准锚点 | 要件裁决 | 整题验收 |
|---|---|---|---|---|---|---|---|
| company-001 | company | pending_human | 1 | 3 | 0 | 2 | 需验收 |
| company-002 | company | pending_human | 2 | 0 | 0 | 1 | 需验收 |
| company-003 | company | pending_human | 6 | 0 | 0 | 2 | 需验收 |
| company-004 | company | pending_human | 1 | 0 | 0 | 2 | 需验收 |
| company-005 | company | machine_ready | 2 | 1 | 0 | 0 | 需验收 |
| company-006 | company | machine_ready | 2 | 0 | 0 | 0 | 需验收 |
| company-007 | company | pending_human | 1 | 0 | 0 | 1 | 需验收 |
| company-008 | company | pending_human | 0 | 0 | 2 | 4 | 需验收 |
| company-009 | company | negative_opt_out | 0 | 0 | 0 | 0 | 负例 |
| company-010 | company | negative_opt_out | 0 | 0 | 0 | 0 | 负例 |
| industry-001 | industry | pending_human | 3 | 0 | 1 | 1 | 需验收 |
| industry-002 | industry | pending_human | 2 | 0 | 2 | 2 | 需验收 |
| industry-003 | industry | pending_human | 2 | 0 | 1 | 1 | 需验收 |
| industry-004 | industry | pending_human | 0 | 0 | 2 | 3 | 需验收 |
| industry-005 | industry | pending_human | 1 | 0 | 0 | 1 | 需验收 |
| industry-006 | industry | pending_human | 0 | 0 | 1 | 3 | 需验收 |
| industry-007 | industry | pending_human | 2 | 0 | 0 | 1 | 需验收 |
| industry-008 | industry | pending_human | 1 | 0 | 1 | 3 | 需验收 |
| industry-009 | industry | negative_opt_out | 0 | 0 | 0 | 0 | 负例 |
| industry-010 | industry | negative_opt_out | 0 | 0 | 0 | 0 | 负例 |
| macro-001 | macro | pending_human | 1 | 0 | 0 | 1 | 需验收 |
| macro-002 | macro | pending_human | 2 | 0 | 0 | 1 | 需验收 |
| macro-003 | macro | blocked | 1 | 0 | 1 | 3 | 需验收 |
| macro-004 | macro | blocked | 0 | 0 | 1 | 3 | 需验收 |
| macro-005 | macro | pending_human | 1 | 0 | 1 | 2 | 需验收 |
| macro-006 | macro | pending_human | 1 | 0 | 1 | 1 | 需验收 |
| macro-007 | macro | pending_human | 2 | 0 | 0 | 1 | 需验收 |
| macro-008 | macro | pending_human | 1 | 0 | 1 | 1 | 需验收 |
| macro-009 | macro | negative_opt_out | 0 | 0 | 0 | 0 | 负例 |
| macro-010 | macro | negative_opt_out | 0 | 0 | 0 | 0 | 负例 |

## 2. 要件裁决（逐项）

### company-001（pending_human）

- **`I32-company-001-01`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'必须同时给出EPS 67.74/70.77/73.84元与年度对应、一年目标价2030元、维持强推'；**机器锚点联合仍未覆盖**：同时、年度、持强、时给 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：company-008-claim-001#4（rating）page:1；content_overlap(shared=15, idf=11.50, ratio=0.83)
        - 未覆盖词元：同时、年度、持强、时给
        - quote：'我们维持26-28 年EPS 预测值\n67.74/70.77/73.84 元，维持一年目标价2030 元和“强推”评级。'
    - 机器锚点候选[2]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：company-001-claim-001#2（table_cell）page:3 row:EPS(摊薄)（元） col:2026E；content_overlap(shared=3, idf=1.50, ratio=0.17)
        - 未覆盖词元：2030、70、73、77、84、eps、一年、同时、年度、年目、强推、持强、时给、标价、目标、维持
        - quote：'67.74'
    - 机器锚点候选[3]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：company-001-claim-001#6（table_cell）page:3 row:EPS(摊薄)（元） col:2027E；content_overlap(shared=3, idf=1.50, ratio=0.17)
        - 未覆盖词元：2030、67、73、74、84、eps、一年、同时、年度、年目、强推、持强、时给、标价、目标、维持
        - quote：'70.77'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标
- **`I32-company-001-02`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'并标明是报告预测'
    - 决定口径：`批准（确认答案侧口径） / 驳回`；依据：____（本项不产生证据目标，无需 chosen；核验落点在 I3-5 答案侧检查）

### company-002（pending_human）

- **`I32-company-002-01`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'不能混淆半年与单季'
    - 决定口径：`批准（确认答案侧口径） / 驳回`；依据：____（本项不产生证据目标，无需 chosen；核验落点在 I3-5 答案侧检查）

### company-003（pending_human）

- **`I32-company-003-01`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'括号须解为负数'
    - 决定口径：`批准（确认答案侧口径） / 驳回`；依据：____（本项不产生证据目标，无需 chosen；核验落点在 I3-5 答案侧检查）
- **`I32-company-003-02`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'引用对应行列且标明预测'
    - 决定口径：`批准（确认答案侧口径） / 驳回`；依据：____（本项不产生证据目标，无需 chosen；核验落点在 I3-5 答案侧检查）

### company-004（pending_human）

- **`I32-company-004-01`**（value_equivalence）确认数值等价：要求写作 '13.40'，原文逐字为 ['13.4', '13.4']（原文 quote 不改写，按同一数值接受）
    - 决定口径：`批准（确认数值等价） / 改选 / 驳回`；chosen：____；依据：____
- **`I32-company-004-02`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'不得当作实际收入或券商盈利预测'；**机器锚点联合仍未覆盖**：作实、利预、券商、商盈、实际、当作、盈利、际收、预测 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：company-018-claim-001#2（condition）page:1；content_overlap(shared=3, idf=1.75, ratio=0.30)
        - 未覆盖词元：作实、利预、券商、商盈、实际、当作、盈利、际收、预测
        - quote：'其设定的2026—2028 年的营业收入触发\n值和目标值分别为8.84/12.06/15.81 亿元（26-28 年同比增速为\n32%/36%/31% ）和9.38/13.4/18.09 亿元'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标

### company-007（pending_human）

- **`I32-company-007-01`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'华创云信为华创证券控股股东，不能误记成华创证券持有茅台集团'
    - 机器锚点候选[1]（首选；**部分覆盖**）：company-013-claim-001#0（value）page:7；content_overlap(shared=13, idf=11.83, ratio=0.72)
        - 未覆盖词元：创证、券持、券控、成华、有茅、记成、证券、误记
        - quote：'贵州茅台的控股股东茅台集团持有本公司的控股股东华创云信4.06%的股\n份。'
    - 决定口径：`批准（确认答案侧口径） / 驳回`；依据：____（本项不产生证据目标，无需 chosen；核验落点在 I3-5 答案侧检查）

### company-008（pending_human）

- **`I32-company-008-01`**（source_coverage）该子句要求引用多份材料：'必须取得两份材料：贵州茅台为强推（维持），光力科技为优于大市（首次覆盖）'；**机器锚点联合仍未覆盖**：光力、力科、州茅、科技、茅台、贵州 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：company-008-claim-001#4（rating）page:1；content_overlap(shared=2, idf=2.00, ratio=0.17)
        - 未覆盖词元：光力、力科、大市、州茅、次覆、科技、茅台、覆盖、贵州、首次
        - quote：'我们维持26-28 年EPS 预测值\n67.74/70.77/73.84 元，维持一年目标价2030 元和“强推”评级。'
    - 机器锚点候选[2]（首选；**部分覆盖**）：company-018-claim-001#3（rating）page:1；content_overlap(shared=4, idf=3.33, ratio=0.33)
        - 未覆盖词元：光力、力科、州茅、强推、科技、维持、茅台、贵州
        - quote：'我\n们预计公司2026—2028 年归母净利润分别为1.32/2.19/3.43 亿元，对\n应PE 分别为79/48/30 倍，首次覆盖给予“优于大市”评级。'
    - 机器锚点候选[3]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：company-024-claim-001#0（condition）page:2；content_overlap(shared=3, idf=1.33, ratio=0.25)
        - 未覆盖词元：光力、力科、大市、州茅、强推、次覆、科技、维持、茅台、覆盖、贵州、首次
        - quote：'煤矿安全检测业务是公司的起家业务，是发展的基本盘。'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标
- **`I32-company-008-02`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'通用评级定义页不能代替具体评级'
    - 决定口径：`批准（确认答案侧口径） / 驳回`；依据：____（本项不产生证据目标，无需 chosen；核验落点在 I3-5 答案侧检查）
- **`I32-company-008-03`**（source_coverage）该题 satisfy_rule=all：来源 2026-08-16_6f14cc14 目前没有必需证据目标，必须指定该来源的承载 item；若改变来源义务须另行修订金标，不能以理由豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：company-008-claim-001#4（rating）page:1；content_overlap(shared=2, idf=2.00, ratio=0.17)
        - 未覆盖词元：光力、力科、大市、州茅、次覆、科技、茅台、覆盖、贵州、首次
        - quote：'我们维持26-28 年EPS 预测值\n67.74/70.77/73.84 元，维持一年目标价2030 元和“强推”评级。'
    - 决定口径：`批准（指定该来源的承载 item） / 驳回`；chosen：____；chosen 必须来自本项 source_id，不得用其他来源替代
- **`I32-company-008-04`**（source_coverage）该题 satisfy_rule=all：来源 2026-09-06_dddc7cd0 目前没有必需证据目标，必须指定该来源的承载 item；若改变来源义务须另行修订金标，不能以理由豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：company-018-claim-001#3（rating）page:1；content_overlap(shared=4, idf=3.33, ratio=0.33)
        - 未覆盖词元：光力、力科、州茅、强推、科技、维持、茅台、贵州
        - quote：'我\n们预计公司2026—2028 年归母净利润分别为1.32/2.19/3.43 亿元，对\n应PE 分别为79/48/30 倍，首次覆盖给予“优于大市”评级。'
    - 机器锚点候选[2]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：company-024-claim-001#0（condition）page:2；content_overlap(shared=3, idf=1.33, ratio=0.25)
        - 未覆盖词元：光力、力科、大市、州茅、强推、次覆、科技、维持、茅台、覆盖、贵州、首次
        - quote：'煤矿安全检测业务是公司的起家业务，是发展的基本盘。'
    - 决定口径：`批准（指定该来源的承载 item） / 驳回`；chosen：____；chosen 必须来自本项 source_id，不得用其他来源替代

### industry-001（pending_human）

- **`I32-industry-001-01`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'分位不是价格涨幅，开工率是注2所述期间平均'；**机器锚点联合仍未覆盖**：价格、分位、格涨、涨幅、述期、间平 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：industry-009-claim-001#9（condition）page:10；note_ref(注2)
        - 未覆盖词元：价格、分位、格涨、涨幅、述期、间平
        - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标

### industry-002（pending_human）

- **`I32-industry-002-01`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'按注3属配额，不能解释为实际产量'；**机器锚点联合仍未覆盖**：产量、实际、属配、按注、解释、际产 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：industry-009-claim-001#10（condition）page:10；note_ref(注3)
        - 未覆盖词元：产量、实际、属配、按注、解释、际产
        - quote：'注3：制冷剂R22、R32、R134a 的产能为配额'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标
- **`I32-industry-002-02`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'价格分位窗口2016-01-01至2026-07-27'；**机器锚点联合仍未覆盖**：位窗、格分、窗口 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：industry-009-claim-001#8（condition）page:10；content_overlap(shared=3, idf=3.00, ratio=0.60)
        - 未覆盖词元：位窗、格分、窗口
        - quote：'注1：价格、价差分位为2016 年1 月1 日至2026 年7 月27 日'
    - 机器锚点候选[2]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：industry-009-claim-001#0（table_cell）page:10 row:纯碱 col:价格分位；content_overlap(shared=3, idf=3.00, ratio=0.60)
        - 未覆盖词元：价格、位窗、分位、格分、窗口
        - quote：'0.0%'
    - 机器锚点候选[3]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：industry-009-claim-001#3（table_cell）page:10 row:R32 col:价格分位；content_overlap(shared=3, idf=3.00, ratio=0.60)
        - 未覆盖词元：价格、位窗、分位、格分、窗口
        - quote：'99.6%'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标

### industry-003（pending_human）

- **`I32-industry-003-01`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'区分开工率与产能，2026E为预测列'；**机器锚点联合仍未覆盖**：2026、分开、区分、测列、预测 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：industry-009-claim-001#9（condition）page:10；content_overlap(shared=2, idf=2.00, ratio=0.29)
        - 未覆盖词元：2026、分开、区分、测列、预测
        - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
    - 机器锚点候选[2]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：industry-009-claim-001#2（table_cell）page:10 row:纯碱 col:开工率；content_overlap(shared=2, idf=2.00, ratio=0.29)
        - 未覆盖词元：2026、分开、区分、工率、开工、测列、预测
        - quote：'82.9%'
    - 机器锚点候选[3]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：industry-009-claim-001#6（table_cell）page:10 row:尿素 col:开工率；content_overlap(shared=2, idf=2.00, ratio=0.29)
        - 未覆盖词元：2026、分开、区分、工率、开工、测列、预测
        - quote：'89.9%'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标

### industry-004（pending_human）

- **`I32-industry-004-01`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'价格/价差分位为2016-01-01至2026-07-27'
    - 机器锚点候选[1]（首选；原文词面覆盖（非语义证明））：industry-009-claim-001#8（condition）page:10；content_overlap(shared=4, idf=4.00, ratio=1.00)
        - quote：'注1：价格、价差分位为2016 年1 月1 日至2026 年7 月27 日'
    - 机器锚点候选[2]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：industry-009-claim-001#1（table_cell）page:10 row:纯碱 col:价差分位；content_overlap(shared=3, idf=3.00, ratio=0.75)
        - 未覆盖词元：价差、价格、分位、差分
        - quote：'0.0%'
    - 机器锚点候选[3]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：industry-009-claim-001#0（table_cell）page:10 row:纯碱 col:价格分位；content_overlap(shared=2, idf=2.00, ratio=0.50)
        - 未覆盖词元：价差、价格、分位、差分
        - quote：'0.0%'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标
- **`I32-industry-004-02`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'开工率为2026-01-01至07-26平均或2026年1—6月平均'
    - 机器锚点候选[1]（首选；原文词面覆盖（非语义证明））：industry-009-claim-001#9（condition）page:10；content_overlap(shared=3, idf=3.00, ratio=1.00)
        - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
    - 机器锚点候选[2]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：industry-009-claim-001#2（table_cell）page:10 row:纯碱 col:开工率；content_overlap(shared=3, idf=3.00, ratio=1.00)
        - 未覆盖词元：工率、平均、开工
        - quote：'82.9%'
    - 机器锚点候选[3]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：industry-009-claim-001#6（table_cell）page:10 row:尿素 col:开工率；content_overlap(shared=3, idf=3.00, ratio=1.00)
        - 未覆盖词元：工率、平均、开工
        - quote：'89.9%'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标
- **`I32-industry-004-03`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'不得擅自把二选一窗口分配到各品种'
    - 机器锚点候选[1]（首选；**部分覆盖**）：industry-009-claim-001#9（condition）page:10；content_overlap(shared=2, idf=2.00, ratio=0.22)
        - 未覆盖词元：一窗、二选、分配、口分、各品、品种、擅自、窗口、选一
        - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
    - 决定口径：`批准（确认答案侧口径） / 驳回`；依据：____（本项不产生证据目标，无需 chosen；核验落点在 I3-5 答案侧检查）

### industry-005（pending_human）

- **`I32-industry-005-01`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'不是所有电子特气共同涨幅，也不是单日涨幅'
    - 决定口径：`批准（确认答案侧口径） / 驳回`；依据：____（本项不产生证据目标，无需 chosen；核验落点在 I3-5 答案侧检查）

### industry-006（pending_human）

- **`I32-industry-006-01`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'报告援引供应链消息：计划用于NVSwitch板卡及Rubin Ultra正交背板主力选材'；**机器锚点联合仍未覆盖**：供应、划用、告援、应链、引供、援引、板主、消息、链消 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：industry-057-claim-001#2（condition）page:1；content_overlap(shared=14, idf=14.00, ratio=0.74)
        - 未覆盖词元：供应、划用、告援、应链、引供、援引、板主、消息、链消
        - quote：'英伟达计划在NVSwitch\n板卡中使用PTFE 材料，并将该材料作为英伟达新一代服务器平台Rubin Ultra\n正交背板的主力选材。Rubin Ultra 预计于2027 年推出。'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标
- **`I32-industry-006-02`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'Rubin Ultra预计2027年推出'
    - 机器锚点候选[1]（首选；原文词面覆盖（非语义证明））：industry-057-claim-001#2（condition）page:1；content_overlap(shared=3, idf=3.00, ratio=1.00)
        - quote：'英伟达计划在NVSwitch\n板卡中使用PTFE 材料，并将该材料作为英伟达新一代服务器平台Rubin Ultra\n正交背板的主力选材。Rubin Ultra 预计于2027 年推出。'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标
- **`I32-industry-006-03`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'须保留消息来源与“计划/预计”限定'；**机器锚点联合仍未覆盖**：保留、息来、来源、消息、留消、限定 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：industry-057-claim-001#2（condition）page:1；content_overlap(shared=3, idf=3.00, ratio=0.38)
        - 未覆盖词元：保留、息来、来源、消息、留消、限定
        - quote：'英伟达计划在NVSwitch\n板卡中使用PTFE 材料，并将该材料作为英伟达新一代服务器平台Rubin Ultra\n正交背板的主力选材。Rubin Ultra 预计于2027 年推出。'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标

### industry-007（pending_human）

- **`I32-industry-007-01`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'保持指数名和数值配对'
    - 决定口径：`批准（确认答案侧口径） / 驳回`；依据：____（本项不产生证据目标，无需 chosen；核验落点在 I3-5 答案侧检查）

### industry-008（pending_human）

- **`I32-industry-008-01`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'不能：R32为历史价格分位（2016-01-01至2026-07-27）'；**机器锚点联合仍未覆盖**：32、价格、分位、历史、史价、格分 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：industry-009-claim-001#3（table_cell）page:10 row:R32 col:价格分位；content_overlap(shared=4, idf=3.50, ratio=0.67)
        - 未覆盖词元：32、价格、分位、历史、史价、格分
        - quote：'99.6%'
    - 机器锚点候选[2]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：industry-009-claim-001#0（table_cell）page:10 row:纯碱 col:价格分位；content_overlap(shared=3, idf=2.50, ratio=0.50)
        - 未覆盖词元：32、价格、分位、历史、史价、格分
        - quote：'0.0%'
    - 机器锚点候选[3]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：industry-009-claim-001#5（table_cell）page:10 row:R134a col:价格分位；content_overlap(shared=3, idf=2.50, ratio=0.50)
        - 未覆盖词元：32、价格、分位、历史、史价、格分
        - quote：'98.8%'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标
- **`I32-industry-008-02`**（source_coverage）该子句要求引用多份材料：'须引用两份材料证明统计含义不同'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标
- **`I32-industry-008-03`**（source_coverage）该题 satisfy_rule=all：来源 2026-08-13_174b6462 目前没有必需证据目标，必须指定该来源的承载 item；若改变来源义务须另行修订金标，不能以理由豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：industry-009-claim-001#3（table_cell）page:10 row:R32 col:价格分位；content_overlap(shared=4, idf=3.50, ratio=0.67)
        - 未覆盖词元：32、价格、分位、历史、史价、格分
        - quote：'99.6%'
    - 机器锚点候选[2]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：industry-009-claim-001#0（table_cell）page:10 row:纯碱 col:价格分位；content_overlap(shared=3, idf=2.50, ratio=0.50)
        - 未覆盖词元：32、价格、分位、历史、史价、格分
        - quote：'0.0%'
    - 机器锚点候选[3]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：industry-009-claim-001#5（table_cell）page:10 row:R134a col:价格分位；content_overlap(shared=3, idf=2.50, ratio=0.50)
        - 未覆盖词元：32、价格、分位、历史、史价、格分
        - quote：'98.8%'
    - 决定口径：`批准（指定该来源的承载 item） / 驳回`；chosen：____；chosen 必须来自本项 source_id，不得用其他来源替代

### macro-001（pending_human）

- **`I32-macro-001-01`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'前值修订与8月数据分开'；**机器锚点联合仍未覆盖**：修订、值修、分开、据分 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：macro-038-claim-001#0（value）page:1；content_overlap(shared=2, idf=2.00, ratio=0.50)
        - 未覆盖词元：修订、值修、分开、据分
        - quote：'新增非农就业16.2\n万人，预期5.6 万人，前值由-2.3 万人修正为2.1 万人'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标

### macro-002（pending_human）

- **`I32-macro-002-01`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'均为报告所述'
    - 决定口径：`批准（确认答案侧口径） / 驳回`；依据：____（本项不产生证据目标，无需 chosen；核验落点在 I3-5 答案侧检查）

### macro-003（blocked）

- **`I32-macro-003-01`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'条件是后续通胀下行幅度有限'；**机器锚点联合仍未覆盖**：条件、续通 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：macro-038-claim-001#3（condition）page:1；content_overlap(shared=7, idf=7.00, ratio=1.00)
        - 未覆盖词元：条件、续通
        - quote：'若后续公布的通胀数\n据下行幅度有限，美联储9 月加息的可能性将很难被忽视。'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标
- **`I32-macro-003-02`**（qualification）该定性要件在冻结标注中没有承载 item，需人工补标注或裁定：'强就业降低加息顾虑'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标
- **`I32-macro-003-03`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'必须区分附条件判断、市场预期和正式决定'；**机器锚点联合仍未覆盖**：件判、决定、分附、判断、区分、场预、市场、式决、条件、正式、附条、预期 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：macro-038-claim-001#3（condition）page:1；content_overlap(shared=6, idf=6.00, ratio=0.50)
        - 未覆盖词元：件判、决定、分附、判断、区分、场预、市场、式决、条件、正式、附条、预期
        - quote：'若后续公布的通胀数\n据下行幅度有限，美联储9 月加息的可能性将很难被忽视。'
    - 机器锚点候选[2]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：macro-038-claim-001#4（value）page:1；content_overlap(shared=3, idf=3.00, ratio=0.25)
        - 未覆盖词元：件判、决定、分附、判断、区分、式决、条件、正式、附条
        - quote：'在非农数据公布后，市场预期9 月加息的概\n率已经超过60%。'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标

### macro-004（blocked）

- **`I32-macro-004-01`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'五主体为政府、准财政、企业、居民、海外'；**机器锚点联合仍未覆盖**：五主 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：macro-039-claim-001#1（condition）page:1；content_overlap(shared=6, idf=5.50, ratio=0.86)
        - 未覆盖词元：五主
        - quote：'这五个主体分别是政府、准财政（如城投等）、企业、居民、海\n外。'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标
- **`I32-macro-004-02`**（qualification）该定性要件在冻结标注中没有承载 item，需人工补标注或裁定：'本文聚焦前四者'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标
- **`I32-macro-004-03`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'四路径为财政支出增加、缓解城投化债压力、企业投资增加、居民支出增加'；**机器锚点联合仍未覆盖**：业投、债压、出增、化债、压力、四路、增加、投化、投资、支出、政支、民支、缓解、解城、资增、路径 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：macro-039-claim-001#1（condition）page:1；content_overlap(shared=4, idf=3.50, ratio=0.20)
        - 未覆盖词元：业投、债压、出增、化债、压力、四路、增加、投化、投资、支出、政支、民支、缓解、解城、资增、路径
        - quote：'这五个主体分别是政府、准财政（如城投等）、企业、居民、海\n外。'
    - 机器锚点候选[2]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：macro-060-claim-001#4（condition）page:2；content_overlap(shared=2, idf=1.50, ratio=0.10)
        - 未覆盖词元：业投、债压、出增、化债、压力、四路、城投、增加、居民、投化、投资、支出、政支、民支、缓解、解城、财政、资增
        - quote：'使用上市公司或者发债企业的数据代表性可能欠佳，获得的结论有\n一定的偏差。可能存在其他收敛路径。'
    - 机器锚点候选[3]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：macro-039-claim-001#2（value）page:1；content_overlap(shared=2, idf=1.50, ratio=0.10)
        - 未覆盖词元：业投、企业、债压、化债、压力、四路、城投、增加、居民、投化、投资、政支、民支、缓解、解城、财政、资增、路径
        - quote：'2026 年，预计\n两本账支出增速为-0.5%左右，仍低于名义GDP 增速。'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标

### macro-005（pending_human）

- **`I32-macro-005-01`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'堵点为收入依赖旧动能且受其下行拖累、新动能综合税负偏低'；**机器锚点联合仍未覆盖**：依赖、偏低、入依、合税、堵点、拖累、收入、税负、综合、行拖、负偏、赖旧 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：macro-039-claim-001#0（condition）page:1；content_overlap(shared=2, idf=2.00, ratio=0.14)
        - 未覆盖词元：依赖、偏低、入依、合税、堵点、拖累、收入、税负、综合、行拖、负偏、赖旧
        - quote：'新动\n能（包括装备制造业、信息业、租赁和商务服务业），旧动能（地产、建筑、\n上游材料制造业）'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标
- **`I32-macro-005-02`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'须标注预测'
    - 决定口径：`批准（确认答案侧口径） / 驳回`；依据：____（本项不产生证据目标，无需 chosen；核验落点在 I3-5 答案侧检查）

### macro-006（pending_human）

- **`I32-macro-006-01`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'样本为偏头部发债企业，不等于全国所有国企'；**机器锚点联合仍未覆盖**：偏头、全国、国企、头部、有国、部发 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：macro-060-claim-001#4（condition）page:2；content_overlap(shared=3, idf=2.50, ratio=0.33)
        - 未覆盖词元：偏头、全国、国企、头部、有国、部发
        - quote：'使用上市公司或者发债企业的数据代表性可能欠佳，获得的结论有\n一定的偏差。可能存在其他收敛路径。'
    - 机器锚点候选[2]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：macro-039-claim-001#3（value）page:1；content_overlap(shared=2, idf=1.50, ratio=0.22)
        - 未覆盖词元：债企、偏头、全国、发债、国企、头部、有国、部发
        - quote：'2025 年，央企样本企业的有息负\n债增速为4.6%，低于2024 年的5.9%。2025 年，地方国有企业样本企业的有\n息负债增速为6.1%，低于2024 年的6.2%。'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标

### macro-007（pending_human）

- **`I32-macro-007-01`**（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'不能混用口径'
    - 决定口径：`批准（确认答案侧口径） / 驳回`；依据：____（本项不产生证据目标，无需 chosen；核验落点在 I3-5 答案侧检查）

### macro-008（pending_human）

- **`I32-macro-008-01`**（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'上市公司/发债企业样本代表性可能欠佳，结论可能偏差且可能有其他收敛路径'；**机器锚点联合仍未覆盖**：业样 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - 机器锚点候选[1]（首选；**部分覆盖**）：macro-060-claim-001#4（condition）page:2；content_overlap(shared=14, idf=12.00, ratio=1.00)
        - 未覆盖词元：业样
        - quote：'使用上市公司或者发债企业的数据代表性可能欠佳，获得的结论有\n一定的偏差。可能存在其他收敛路径。'
    - 机器锚点候选[2]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：macro-039-claim-001#3（value）page:1；content_overlap(shared=2, idf=1.00, ratio=0.14)
        - 未覆盖词元：代表、债企、偏差、公司、发债、市公、收敛、敛路、欠佳、结论、表性、路径
        - quote：'2025 年，央企样本企业的有息负\n债增速为4.6%，低于2024 年的5.9%。2025 年，地方国有企业样本企业的有\n息负债增速为6.1%，低于2024 年的6.2%。'
    - 机器锚点候选[3]（备选（仅供检索线索；须显式改选及原文承载核验）；**部分覆盖**）：macro-039-claim-001#4（value）page:1；content_overlap(shared=2, idf=1.00, ratio=0.14)
        - 未覆盖词元：业样、代表、企业、债企、偏差、公司、发债、市公、收敛、敛路、欠佳、结论、表性、路径
        - quote：'2025 年，中国（使用全\n部A 股）为9.8%，美国（使用标普500 成分股）为20.4%，日本（使用日经\n225 成分股）为14.8%，韩国（使用KOSPI200 成分股）为26.7%。'
    - 决定口径：`批准 / 改选 / 补标注 / 驳回`；chosen（可多选，按联合覆盖）：____；仅词面差异填 lexical_review 原文映射；线索改选填 anchor_review；实质缺证补标

## 3. 有答案题整题验收（对照冻结 requirement）

要件裁决完成**不等于**整题验收完成：还须逐题确认覆盖账没有漏掉冻结 `evidence_requirement` 里的对象、期间、单位、条件、否定与归属要求。发现漏项时，必须新增要件（补标注）或写明裁定依据，不得只勾「批准」。

- `company-001`：冻结 requirement 分段 = '必须同时给出EPS 67.74/70.77/73.84元与年度对应、一年目标价2030元、维持强推；并标明是报告预测'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `company-002`：冻结 requirement 分段 = 'H1收入922.8亿元/+1.3%、归母445.2亿元/-2.0%；Q2收入375.8亿元/-5.2%、归母172.7亿元/-6.9%；不能混淆半年与单季'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `company-003`：冻结 requirement 分段 = 'EPS依次0.36/0.59/0.93元；经营现金流依次-222/-138/-17百万元；括号须解为负数；引用对应行列且标明预测'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `company-004`：冻结 requirement 分段 = '按年度同时列出触发值8.84/12.06/15.81亿元与目标值9.38/13.40/18.09亿元；不得当作实际收入或券商盈利预测'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `company-005`：冻结 requirement 分段 = '8230先进封装已批量应用；8231支持全切/DBG半切/Edge Trimming且已形成正式订单；9130 Low-k开槽、9320超薄硅/SiC/GaN/MEMS隐切，后两款均在客户验证'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `company-006`：冻结 requirement 分段 = '直接32.60%，经全资宁波万丰隆间接4.00%，合计36.60%；陈淑兰1.70%、赵彤亚0.57%不计入'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `company-007`：冻结 requirement 分段 = '茅台集团持有华创云信4.06%股份；华创云信为华创证券控股股东，不能误记成华创证券持有茅台集团'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `company-008`：冻结 requirement 分段 = '必须取得两份材料：贵州茅台为强推（维持），光力科技为优于大市（首次覆盖）；通用评级定义页不能代替具体评级'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `industry-001`：冻结 requirement 分段 = '图6续表纯碱行：价格分位0.0%、价差分位0.0%、开工率82.9%；分位不是价格涨幅，开工率是注2所述期间平均'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `industry-002`：冻结 requirement 分段 = 'R32价格分位99.6%，2026E产能28.5万吨/年；按注3属配额，不能解释为实际产量；价格分位窗口2016-01-01至2026-07-27'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `industry-003`：冻结 requirement 分段 = '尿素开工率89.9%，2026E产能8068.0万吨/年；区分开工率与产能，2026E为预测列'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `industry-004`：冻结 requirement 分段 = '价格/价差分位为2016-01-01至2026-07-27；开工率为2026-01-01至07-26平均或2026年1—6月平均；不得擅自把二选一窗口分配到各品种'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `industry-005`：冻结 requirement 分段 = '从720元/吨升至2459元/吨；约四个月，报告称涨幅超过240%；不是所有电子特气共同涨幅，也不是单日涨幅'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `industry-006`：冻结 requirement 分段 = '报告援引供应链消息：计划用于NVSwitch板卡及Rubin Ultra正交背板主力选材；Rubin Ultra预计2027年推出；须保留消息来源与“计划/预计”限定'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `industry-007`：冻结 requirement 分段 = 'Wind新材料5611.65点、环比-4.2%；申万三级半导体材料12576.94点、环比-9.12%；保持指数名和数值配对'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `industry-008`：冻结 requirement 分段 = '不能：R32为历史价格分位（2016-01-01至2026-07-27）；氩气为2026年5月初720至9月2日2459元/吨的价格涨幅；须引用两份材料证明统计含义不同'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `macro-001`：冻结 requirement 分段 = '8月16.2万人，预期5.6万人；7月由-2.3万人修正为2.1万人；前值修订与8月数据分开'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `macro-002`：冻结 requirement 分段 = '失业率4.1%/前值4.1%，劳动参与率61.6%/前值61.4%，平均时薪同比3.1%/前值3.2%；均为报告所述'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `macro-003`：冻结 requirement 分段 = '条件是后续通胀下行幅度有限；强就业降低加息顾虑；报告称非农公布后市场预期概率超过60%；必须区分附条件判断、市场预期和正式决定'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `macro-004`：冻结 requirement 分段 = '五主体为政府、准财政、企业、居民、海外；本文聚焦前四者；四路径为财政支出增加、缓解城投化债压力、企业投资增加、居民支出增加'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `macro-005`：冻结 requirement 分段 = '两本账支出增速预计约-0.5%，低于名义GDP增速；堵点为收入依赖旧动能且受其下行拖累、新动能综合税负偏低；须标注预测'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `macro-006`：冻结 requirement 分段 = '央企4.6%对5.9%，地方国企6.1%对6.2%，均下降；样本为偏头部发债企业，不等于全国所有国企'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `macro-007`：冻结 requirement 分段 = '消费倾向=消费/可支配收入，2026/2025/2019Q2为67.5%/68.6%/70.5%；支出倾向=(消费+新房购房)/可支配收入，为80.3%/83.7%/110.3%；不能混用口径'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____
- `macro-008`：冻结 requirement 分段 = '2026年1—6月本年施工项目计划总投资同比-4.3%，本年新开工项目计划总投资增速-29.4%；上市公司/发债企业样本代表性可能欠佳，结论可能偏差且可能有其他收敛路径'
    - 决定：`批准 / 需补要件`；依据（含未覆盖项说明）：____

## 4. 负例覆盖确认

负例不进入 EvidencePass 正例分母（既有合同），但仍须参加误报/伪造引用检查，
并须人工确认『材料全文确实没有该证据』，不得以未检索到来代替没有证据。

- `company-009`：human_basis 是否仍写『待/需确认全文覆盖』=**False**；决定：`批准 / 待补`；full_text_coverage_confirmed：____；依据：____
- `company-010`：human_basis 是否仍写『待/需确认全文覆盖』=**True**；决定：`批准 / 待补`；full_text_coverage_confirmed：____；依据：____
- `industry-009`：human_basis 是否仍写『待/需确认全文覆盖』=**False**；决定：`批准 / 待补`；full_text_coverage_confirmed：____；依据：____
- `industry-010`：human_basis 是否仍写『待/需确认全文覆盖』=**True**；决定：`批准 / 待补`；full_text_coverage_confirmed：____；依据：____
- `macro-009`：human_basis 是否仍写『待/需确认全文覆盖』=**False**；决定：`批准 / 待补`；full_text_coverage_confirmed：____；依据：____
- `macro-010`：human_basis 是否仍写『待/需确认全文覆盖』=**True**；决定：`批准 / 待补`；full_text_coverage_confirmed：____；依据：____

## 5. 来源槽位人工状态澄清

- `macro-039-claim-001`：human_basis 文本仍写『待复核/需确认』，但 reviewer/reviewed_at 已有值
    - human_basis：'待真人复核。依据：已校验SHA-256的原PDF第1页及该槽原文。摘要对产业分化和四条需求收敛路径作定义，并给出财政预测及企业样本数据。'
    - reviewer=xyl；reviewed_at=2026-09-15T10:40:49+00:00
    - resolution（`残留描述` / `实质未决`）与依据：____

## 6. 决策回填模板

```json
{
  "artifact": "i3-2-evidence-targets-decisions",
  "rule_rev": "evidence-mapping-6",
  "reviewer": "<U>",
  "reviewed_at": "<ISO8601>",
  "based_on": {
    "candidates_sha256": "<候选文件 sha256>",
    "query_gold_sha256": "6f6c5a25d55be2b58c7f7ae65152b9b58c8e876aeb60101d13c08c9ccca7b39f",
    "source_gold_sha256": "c360a132ad63c16caf58d2cd66e7081754c5ac801d4761b3cb9d0bb95b7768b2"
  },
  "question_reviews": [
    {
      "query_id": "<题号>",
      "decision": "批准|需补要件",
      "reviewed_against_requirement": true,
      "reason": "..."
    }
  ],
  "facet_decisions": [
    {
      "item_id": "I32-<题号>-01",
      "facet_id": "<facet>",
      "query_id": "<题号>",
      "decision": "批准|改选|补标注|驳回",
      "chosen": [
        {
          "slot": "...",
          "item_index": 0
        }
      ],
      "lexical_review": {
        "kind": "lexical_mismatch",
        "facet_id": "<与本项相同，来源专属项为null>",
        "requirement": "<对应facet原文>",
        "evidence_complete": true,
        "missing_evidence": false,
        "mappings": [
          {
            "terms": [
              "<机器列出的未覆盖词元，合计须精确覆盖>"
            ],
            "slot": "...",
            "item_index": 0,
            "quote_span": "<chosen原文逐字子串，不得取自text/period>",
            "reason": "<同义依据>"
          }
        ]
      },
      "supplement": {
        "slot": "...",
        "item_index": 3,
        "source_gold_revision": "..."
      },
      "reviewed_against_clause": "<段原文>",
      "reason": "..."
    }
  ],
  "negative_reviews": [
    {
      "query_id": "<负例题号>",
      "decision": "批准|待补",
      "full_text_coverage_confirmed": true,
      "reason": "..."
    }
  ],
  "human_status_clarifications": [
    {
      "gold_id": "<槽位>",
      "resolution": "残留描述|实质未决",
      "reason": "..."
    }
  ]
}
```

lexical_review 只在词面不一致但原文实质完整时填写；每个 chosen 均须被映射引用，mappings.terms 的并集须等于机器列出的缺词。实质缺证不得填写 evidence_complete=true。
anchor_review 仅用于改选：结构同 lexical_review，但 kind=anchor_reselection，每条 mappings.terms=[]；它核验改选依据，不替代所需的 lexical_review。无例外时省略两字段。
answer_constraint 只填批准/驳回及理由，必须省略 chosen、lexical_review、anchor_review。来源专属项 facet_id=null、requirement为空串。不得把模板占位符当成真实审批。
I3-5 本轮零模型只验证答案约束登记与投影保真；真实生成答案的语义验收未执行，若需要须另行制定输入/人工评分规则与有限预算，不得据检索分数宣称答案合规。
回填后运行 `i3s2_apply_decisions.py`：它校验输入哈希、逐项裁决覆盖、整题验收、
负例覆盖、状态澄清、引用真源与投影一致性（不接受缺证豁免），
生成 `evidence-targets-approved.json`（批准投影）与 `approval-report.json`（完整性门结论）。
`ready=true` 时必须**另建冻结修订**并同步台账，不得复用旧快照。
