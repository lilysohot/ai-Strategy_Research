# I3-2 补料：证据目标候选核对单（待 U 裁决）

- 生成时间：2026-09-18T19:56:02+08:00；规则版本：`evidence-mapping-6`
- 输入：`query-gold-frozen.jsonl` sha256=6f6c5a25d55b…、`source-gold-frozen.jsonl` sha256=37662c77a76c…
- 机器状态：machine_ready **2** ／ pending_human **21** ／ blocked **1** ／ 负例 **6**
- 目标：必需 **44** ／ 补充（非必需）**20** ／ 待批准锚点 **18**（合计 82 条）
- 要件裁决队列：**40** 项；另有整题验收 24 题、负例覆盖 6 题、来源状态澄清 1 项

> 证据来源全部是 I0A-4 人工标注槽位（reviewer=xyl），quote 为原文逐字子串；
> **机器候选不等于批准**：`role=required` 是机器判定的必需证据，`role=supplementary` 是补充证据（**非必需**，本版**不声明替代关系**），`role=suggested` 是待批准锚点（批准前不得计入必需；`adequacy=partial` 的锚点必须补标注或改选）。
> **EvidencePass 分母 = 逐题**（逐题：满足全部必需证据的题数 / 证据题数（架构 §12.3）；item 条数或槽位聚合只决定每题内部是否全部满足，不能替代分母）；item/槽位计数只作诊断，不得替代分母。

> 版本记录：v1 子串误命中；v2 连续汉字串当关键词；v3 只证数字覆盖/丢表格身份/日期碎片；v4 建要求覆盖账与三层角色，但定性要件只在无数字时才登记、锚点未验覆盖度、批准路径未接通（详见 `supersedes`）；本版 v5 按段并行登记数值与限定、锚点给未覆盖词元与覆盖度、补充/锚点不再称「可替代」、审批走独立审批件。

## company-001（company，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 1 条、补充 4 条），但仍有 2 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：company-001-claim-001、company-008-claim-001、company-013-claim-001、company-ai-supplement-2026-08-16_6f14cc14-p1、company-ai-supplement-2026-08-16_6f14cc14-p7
- 要求覆盖账（按段）：
    - `c1` '必须同时给出EPS 67.74/70.77/73.84元与年度对应、一年目标价2030元、维持强推'
        - 数值要件 `f1` '67.74' → required
        - 数值要件 `f2` '70.77' → required
        - 数值要件 `f3` '73.84' → required
        - 数值要件 `f4` '2030' → required
        - 定性要件 `q5` → suggested（锚点 3 条）
    - `c2` '并标明是报告预测'
        - 定性要件 `q6` → usage_constraint（锚点 0 条）
- 必需证据（计入 EvidencePass）：
    - `e4` 2026-08-16_6f14cc14 page:1 ← company-008-claim-001#4（rating；约束 {'unit': '元', 'period': '报告日2026-08-16；目标价期限一年'}）
        - quote：'我们维持26-28 年EPS 预测值\n67.74/70.77/73.84 元，维持一年目标价2030 元和“强推”评级。'
- 补充证据（非必需；不声明替代关系）：
    - `e1` 2026-08-16_6f14cc14 page:3 row:EPS(摊薄)（元） col:2026E ← company-001-claim-001#2（table_cell；约束 {'row': 'EPS(摊薄)（元）', 'col': '2026E', 'cell': 'EPS(摊薄)（元） × 2026E', 'unit': '元/股', 'period': '2026E'}）
        - quote：'67.74'
    - `e2` 2026-08-16_6f14cc14 page:3 row:EPS(摊薄)（元） col:2027E ← company-001-claim-001#6（table_cell；约束 {'row': 'EPS(摊薄)（元）', 'col': '2027E', 'cell': 'EPS(摊薄)（元） × 2027E', 'unit': '元/股', 'period': '2027E'}）
        - quote：'70.77'
    - `e3` 2026-08-16_6f14cc14 page:3 row:EPS(摊薄)（元） col:2028E ← company-001-claim-001#10（table_cell；约束 {'row': 'EPS(摊薄)（元）', 'col': '2028E', 'cell': 'EPS(摊薄)（元） × 2028E', 'unit': '元/股', 'period': '2028E'}）
        - quote：'73.84'
    - `e5` 2026-08-16_6f14cc14 page:1 ← company-ai-supplement-2026-08-16_6f14cc14-p1#1（body；约束 {}）
        - quote：'综上，茅台经营向上明确，底层逻辑未变，我们维持26-28 年EPS 预测值\n67.74/70.77/73.84 元，维持一年目标价2030 元和“强推”评级。'
- 答案侧约束（不产生证据目标，核验落点 I3-5）：
    - `q6` '并标明是报告预测'
- 要件裁决队列（2 项）：
    - `I32-company-001-01`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'必须同时给出EPS 67.74/70.77/73.84元与年度对应、一年目标价2030元、维持强推'；**机器锚点联合仍未覆盖**：同时、年度、持强、时给 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - `I32-company-001-02`（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'并标明是报告预测'
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：company-001-claim-001×3、company-008-claim-001×1、company-ai-supplement-2026-08-16_6f14cc14-p1×1

## company-002（company，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 3 条、补充 0 条），但仍有 1 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：company-001-claim-001、company-008-claim-001、company-013-claim-001、company-ai-supplement-2026-08-16_6f14cc14-p1、company-ai-supplement-2026-08-16_6f14cc14-p7
- 要求覆盖账（按段）：
    - `c1` 'H1收入922.8亿元/+1.3%、归母445.2亿元/-2.0%'
        - 数值要件 `f1` '922.8' → required
        - 数值要件 `f2` '1.3%' → required
        - 数值要件 `f3` '445.2' → required
        - 数值要件 `f4` '2.0%' → required
    - `c2` 'Q2收入375.8亿元/-5.2%、归母172.7亿元/-6.9%'
        - 数值要件 `f5` '375.8' → required
        - 数值要件 `f6` '5.2%' → required
        - 数值要件 `f7` '172.7' → required
        - 数值要件 `f8` '6.9%' → required
    - `c3` '不能混淆半年与单季'
        - 定性要件 `q9` → usage_constraint（锚点 0 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-08-16_6f14cc14 page:1 ← company-008-claim-001#0（value；约束 {'unit': '亿元；%', 'period': '2026H1'}）
        - quote：'26H1 实现总收入922.8 亿元，同增1.3%，归母净利润\n445.2 亿元，同降2.0%。'
    - `e2` 2026-08-16_6f14cc14 page:1 ← company-008-claim-001#1（value；约束 {'unit': '亿元；%', 'period': '2026Q2'}）
        - quote：'单Q2 总收入375.8 亿元，同降5.2%，归母净利润\n172.7 亿元，同降6.9%。'
    - `e3` 2026-08-16_6f14cc14 page:1 ← company-ai-supplement-2026-08-16_6f14cc14-p1#2（body；约束 {}）
        - quote：'公司公布2026 年中报，26H1 实现总收入922.8 亿元，同增1.3%，归母净利润\n445.2 亿元，同降2.0%。单Q2 总收入375.8 亿元，同降5.2%，归母净利润\n172.7 亿元，同降6.9%。'
- 答案侧约束（不产生证据目标，核验落点 I3-5）：
    - `q9` '不能混淆半年与单季'
- 要件裁决队列（1 项）：
    - `I32-company-002-01`（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'不能混淆半年与单季'
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：company-008-claim-001×2、company-ai-supplement-2026-08-16_6f14cc14-p1×1

## company-003（company，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 6 条、补充 1 条），但仍有 2 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 页码提示（不参与匹配）：page:20
- 候选槽位：company-003-claim-001、company-018-claim-001、company-024-claim-001、company-028-claim-001、company-032-claim-001、company-036-claim-001、company-040-claim-001、company-044-claim-001、company-048-claim-001、company-052-claim-001、company-056-claim-001、company-060-claim-001、company-ai-supplement-2026-09-06_dddc7cd0-p1、company-ai-supplement-2026-09-06_dddc7cd0-p3、company-ai-supplement-2026-09-06_dddc7cd0-p7、company-ai-supplement-2026-09-06_dddc7cd0-p20
- 要求覆盖账（按段）：
    - `c1` 'EPS依次0.36/0.59/0.93元'
        - 数值要件 `f1` '0.36' → required
        - 数值要件 `f2` '0.59' → required
        - 数值要件 `f3` '0.93' → required
    - `c2` '经营现金流依次-222/-138/-17百万元'
        - 数值要件 `f4` '222' → required
        - 数值要件 `f5` '138' → required
        - 数值要件 `f6` '17' → required
    - `c3` '括号须解为负数'
        - 定性要件 `q7` → usage_constraint（锚点 0 条）
    - `c4` '引用对应行列且标明预测'
        - 定性要件 `q8` → usage_constraint（锚点 0 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-09-06_dddc7cd0 page:20 row:每股收益 col:2026E ← company-003-claim-001#0（table_cell；约束 {'row': '每股收益', 'col': '2026E', 'cell': '每股收益 × 2026E', 'unit': '元/股', 'period': '2026E'}）
        - quote：'0.36'
    - `e2` 2026-09-06_dddc7cd0 page:20 row:经营活动现金流 col:2026E ← company-003-claim-001#2（table_cell；约束 {'row': '经营活动现金流', 'col': '2026E', 'cell': '经营活动现金流 × 2026E', 'unit': '百万元', 'period': '2026E'}）
        - quote：'(222)'
    - `e3` 2026-09-06_dddc7cd0 page:20 row:每股收益 col:2027E ← company-003-claim-001#3（table_cell；约束 {'row': '每股收益', 'col': '2027E', 'cell': '每股收益 × 2027E', 'unit': '元/股', 'period': '2027E'}）
        - quote：'0.59'
    - `e4` 2026-09-06_dddc7cd0 page:20 row:经营活动现金流 col:2027E ← company-003-claim-001#5（table_cell；约束 {'row': '经营活动现金流', 'col': '2027E', 'cell': '经营活动现金流 × 2027E', 'unit': '百万元', 'period': '2027E'}）
        - quote：'(138)'
    - `e5` 2026-09-06_dddc7cd0 page:20 row:每股收益 col:2028E ← company-003-claim-001#6（table_cell；约束 {'row': '每股收益', 'col': '2028E', 'cell': '每股收益 × 2028E', 'unit': '元/股', 'period': '2028E'}）
        - quote：'0.93'
    - `e6` 2026-09-06_dddc7cd0 page:20 row:经营活动现金流 col:2028E ← company-003-claim-001#8（table_cell；约束 {'row': '经营活动现金流', 'col': '2028E', 'cell': '经营活动现金流 × 2028E', 'unit': '百万元', 'period': '2028E'}）
        - quote：'(17)'
- 补充证据（非必需；不声明替代关系）：
    - `e7` 2026-09-06_dddc7cd0 page:20 ← company-ai-supplement-2026-09-06_dddc7cd0-p20#1（body；约束 {}）
        - quote：'经营活动现金流\n176\n(105)\n(222)\n(138)\n(17)'
- 答案侧约束（不产生证据目标，核验落点 I3-5）：
    - `q7` '括号须解为负数'
    - `q8` '引用对应行列且标明预测'
- 要件裁决队列（2 项）：
    - `I32-company-003-01`（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'括号须解为负数'
    - `I32-company-003-02`（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'引用对应行列且标明预测'
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：company-003-claim-001×6、company-ai-supplement-2026-09-06_dddc7cd0-p20×1

## company-004（company，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 1 条、补充 1 条），但仍有 2 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：company-003-claim-001、company-018-claim-001、company-024-claim-001、company-028-claim-001、company-032-claim-001、company-036-claim-001、company-040-claim-001、company-044-claim-001、company-048-claim-001、company-052-claim-001、company-056-claim-001、company-060-claim-001、company-ai-supplement-2026-09-06_dddc7cd0-p1、company-ai-supplement-2026-09-06_dddc7cd0-p3、company-ai-supplement-2026-09-06_dddc7cd0-p7、company-ai-supplement-2026-09-06_dddc7cd0-p20
- 要求覆盖账（按段）：
    - `c1` '按年度同时列出触发值8.84/12.06/15.81亿元与目标值9.38/13.40/18.09亿元'
        - 数值要件 `f1` '8.84' → required
        - 数值要件 `f2` '12.06' → required
        - 数值要件 `f3` '15.81' → required
        - 数值要件 `f4` '9.38' → required
        - 数值要件 `f5` '13.40' → required
        - 数值要件 `f6` '18.09' → required
    - `c2` '不得当作实际收入或券商盈利预测'
        - 定性要件 `q7` → suggested（锚点 1 条）
- 必需证据（计入 EvidencePass）：
    - `e2` 2026-09-06_dddc7cd0 page:1 ← company-ai-supplement-2026-09-06_dddc7cd0-p1#1（body；约束 {}）
        - quote：'公司发布新一期股权激励，订单承接向好，有望进入经营拐点。公司近期\n公告了新一期股权激励计划，其设定的2026—2028 年的营业收入触发\n值和目标值分别为8.84/12.06/15.81 亿元（26-28 年同比增速为\n32%/36%/31% ）和9.38/13.4/18.09 亿元（26-28 年同比增速为\n40%/43%/35%）。'
        - 数值等价：{'13.40': ['13.4']}
- 补充证据（非必需；不声明替代关系）：
    - `e1` 2026-09-06_dddc7cd0 page:1 ← company-018-claim-001#2（condition；约束 {'unit': '亿元', 'period': '2026—2028'}）
        - quote：'其设定的2026—2028 年的营业收入触发\n值和目标值分别为8.84/12.06/15.81 亿元（26-28 年同比增速为\n32%/36%/31% ）和9.38/13.4/18.09 亿元'
        - 数值等价：{'13.40': ['13.4', '13.4']}
- 要件裁决队列（2 项）：
    - `I32-company-004-01`（value_equivalence）确认数值等价：要求写作 '13.40'，原文逐字为 ['13.4']（原文 quote 不改写，按同一数值接受）
    - `I32-company-004-02`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'不得当作实际收入或券商盈利预测'；**机器锚点联合仍未覆盖**：作实、利预、券商、商盈、实际、当作、盈利、际收、预测 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：company-018-claim-001×1、company-ai-supplement-2026-09-06_dddc7cd0-p1×1

## company-005（company，machine_ready，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：全部要求要件均为数值且已由人工标注 item 承载（必需 2 条）；仍需**整题**对照冻结 requirement 人工验收后才成为金标
- 候选槽位：company-003-claim-001、company-018-claim-001、company-024-claim-001、company-028-claim-001、company-032-claim-001、company-036-claim-001、company-040-claim-001、company-044-claim-001、company-048-claim-001、company-052-claim-001、company-056-claim-001、company-060-claim-001、company-ai-supplement-2026-09-06_dddc7cd0-p1、company-ai-supplement-2026-09-06_dddc7cd0-p3、company-ai-supplement-2026-09-06_dddc7cd0-p7、company-ai-supplement-2026-09-06_dddc7cd0-p20
- 要求覆盖账（按段）：
    - `c1` '8230先进封装已批量应用'
        - 数值要件 `f1` '8230' → required
    - `c2` '8231支持全切/DBG半切/Edge Trimming且已形成正式订单'
        - 数值要件 `f2` '8231' → required
    - `c3` '9130 Low-k开槽、9320超薄硅/SiC/GaN/MEMS隐切，后两款均在客户验证'
        - 数值要件 `f3` '9130' → required
        - 数值要件 `f4` '9320' → required
- 必需证据（计入 EvidencePass）：
    - `e2` 2026-09-06_dddc7cd0 page:3 ← company-028-claim-001#0（condition；约束 {}）
        - quote：'8230 已在先进封装领域实现批量应用，8231 支持晶圆全切、DBG 半切\n及Edge Trimming 等工艺，并已形成正式订单。'
    - `e3` 2026-09-06_dddc7cd0 page:3 ← company-028-claim-001#1（condition；约束 {'period': '报告时点2026-09-06'}）
        - quote：'公司已推出激光开槽机9130 和激光隐切机9320。其中9130 主要用\n于Low-k 晶圆表面开槽，9320 主要用于超薄硅晶圆、碳化硅和氮化镓等第三代半\n导体材料及MEMS 器件的隐形切割。目前，两款设备均处于客户端验证阶段。'
- 补充证据（非必需；不声明替代关系）：
    - `e1` 2026-09-06_dddc7cd0 page:2 ← company-024-claim-001#2（condition；约束 {}）
        - quote：'主\n要包括12 英寸全自动双轴划片机8230、8231，半自动双轴划片机6230、6231，\n用于第三代半导体切割的6110'
    - `e4` 2026-09-06_dddc7cd0 page:3 ← company-ai-supplement-2026-09-06_dddc7cd0-p3#0（body；约束 {}）
        - quote：'其中，8230 已在先进封装领域实现批量应用，8231 支持晶圆全切、DBG 半切\n及Edge Trimming 等工艺，并已形成正式订单。'
    - `e5` 2026-09-06_dddc7cd0 page:3 ← company-ai-supplement-2026-09-06_dddc7cd0-p3#1（body；约束 {}）
        - quote：'公司已推出激光开槽机9130 和激光隐切机9320。其中9130 主要用\n于Low-k 晶圆表面开槽，9320 主要用于超薄硅晶圆、碳化硅和氮化镓等第三代半\n导体材料及MEMS 器件的隐形切割。目前，两款设备均处于客户端验证阶段。'
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：company-024-claim-001×1、company-028-claim-001×2、company-ai-supplement-2026-09-06_dddc7cd0-p3×2

## company-006（company，machine_ready，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：全部要求要件均为数值且已由人工标注 item 承载（必需 3 条）；仍需**整题**对照冻结 requirement 人工验收后才成为金标
- 候选槽位：company-003-claim-001、company-018-claim-001、company-024-claim-001、company-028-claim-001、company-032-claim-001、company-036-claim-001、company-040-claim-001、company-044-claim-001、company-048-claim-001、company-052-claim-001、company-056-claim-001、company-060-claim-001、company-ai-supplement-2026-09-06_dddc7cd0-p1、company-ai-supplement-2026-09-06_dddc7cd0-p3、company-ai-supplement-2026-09-06_dddc7cd0-p7、company-ai-supplement-2026-09-06_dddc7cd0-p20
- 要求覆盖账（按段）：
    - `c1` '直接32.60%，经全资宁波万丰隆间接4.00%，合计36.60%'
        - 数值要件 `f1` '32.60%' → required
        - 数值要件 `f2` '4.00%' → required
        - 数值要件 `f3` '36.60%' → required
    - `c2` '陈淑兰1.70%、赵彤亚0.57%不计入'
        - 数值要件 `f4` '1.70%' → required
        - 数值要件 `f5` '0.57%' → required
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-09-06_dddc7cd0 page:7 ← company-044-claim-001#0（value；约束 {'unit': '%', 'period': '2026-06-30'}）
        - quote：'赵彤宇直接持有公司32.60%股份，并通过其持股100%的宁波万丰隆贸\n易有限公司间接控制公司4.00%股份，合计控制公司36.60%股份。'
    - `e2` 2026-09-06_dddc7cd0 page:7 ← company-044-claim-001#1（condition；约束 {'unit': '%', 'period': '2026-06-30'}）
        - quote：'陈淑兰和赵彤\n亚分别持有公司1.70%和0.57%股份，虽与赵彤宇存在亲属关系，但未计入上述实\n际控制人控制比例。'
    - `e3` 2026-09-06_dddc7cd0 page:7 ← company-ai-supplement-2026-09-06_dddc7cd0-p7#0（body；约束 {}）
        - quote：'截至2026 年6 月30 日，公司控股股东、\n实际控制人赵彤宇直接持有公司32.60%股份，并通过其持股100%的宁波万丰隆贸\n易有限公司间接控制公司4.00%股份，合计控制公司36.60%股份。陈淑兰和赵彤\n亚分别持有公司1.70%和0.57%股份，虽与赵彤宇存在亲属关系，但未计入上述实\n际控制人控制比例。'
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：company-044-claim-001×2、company-ai-supplement-2026-09-06_dddc7cd0-p7×1

## company-007（company，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 1 条、补充 1 条），但仍有 1 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：company-001-claim-001、company-008-claim-001、company-013-claim-001、company-ai-supplement-2026-08-16_6f14cc14-p1、company-ai-supplement-2026-08-16_6f14cc14-p7
- 要求覆盖账（按段）：
    - `c1` '茅台集团持有华创云信4.06%股份'
        - 数值要件 `f1` '4.06%' → required
    - `c2` '华创云信为华创证券控股股东，不能误记成华创证券持有茅台集团'
        - 定性要件 `q2` → usage_constraint（锚点 3 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-08-16_6f14cc14 page:7 ← company-013-claim-001#0（value；约束 {'unit': '%', 'period': '报告披露时点2026-08-16'}）
        - quote：'贵州茅台的控股股东茅台集团持有本公司的控股股东华创云信4.06%的股\n份。'
- 补充证据（非必需；不声明替代关系）：
    - `e2` 2026-08-16_6f14cc14 page:7 ← company-ai-supplement-2026-08-16_6f14cc14-p7#0（body；约束 {}）
        - quote：'本报告涉及股票贵州茅台（600519），根据上市公司公告，贵州茅台的控股股东茅台集团持有本公司的控股股东华创云信4.06%的股\n份。'
- 答案侧约束（不产生证据目标，核验落点 I3-5）：
    - `q2` '华创云信为华创证券控股股东，不能误记成华创证券持有茅台集团'
- 要件裁决队列（1 项）：
    - `I32-company-007-01`（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'华创云信为华创证券控股股东，不能误记成华创证券持有茅台集团'
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：company-013-claim-001×1、company-ai-supplement-2026-08-16_6f14cc14-p7×1

## company-008（company，pending_human，satisfy_rule=all）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 0 条、补充 0 条），但仍有 4 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：company-001-claim-001、company-003-claim-001、company-008-claim-001、company-013-claim-001、company-018-claim-001、company-024-claim-001、company-028-claim-001、company-032-claim-001、company-036-claim-001、company-040-claim-001、company-044-claim-001、company-048-claim-001、company-052-claim-001、company-056-claim-001、company-060-claim-001、company-ai-supplement-2026-08-16_6f14cc14-p1、company-ai-supplement-2026-08-16_6f14cc14-p7、company-ai-supplement-2026-09-06_dddc7cd0-p1、company-ai-supplement-2026-09-06_dddc7cd0-p3、company-ai-supplement-2026-09-06_dddc7cd0-p7、company-ai-supplement-2026-09-06_dddc7cd0-p20
- 要求覆盖账（按段）：
    - `c1` '必须取得两份材料：贵州茅台为强推（维持），光力科技为优于大市（首次覆盖）'
        - 定性要件 `q1` → source_coverage（锚点 3 条）
    - `c2` '通用评级定义页不能代替具体评级'
        - 定性要件 `q2` → usage_constraint（锚点 0 条）
- 待批准锚点（批准前不得计入必需）：
    - `s1` 2026-08-16_6f14cc14 page:1 ← company-ai-supplement-2026-08-16_6f14cc14-p1#0（body；约束 {}）
        - quote：'贵州茅台（600519）2026 年中报点评 \n \n 强推 （维持）'
        - **部分覆盖，未覆盖词元：光力、力科、大市、次覆、科技、覆盖、首次**
    - `s2` 2026-09-06_dddc7cd0 page:1 ← company-018-claim-001#3（rating；约束 {'unit': '亿元；倍', 'period': '2026—2028E'}）
        - quote：'我\n们预计公司2026—2028 年归母净利润分别为1.32/2.19/3.43 亿元，对\n应PE 分别为79/48/30 倍，首次覆盖给予“优于大市”评级。'
        - **部分覆盖，未覆盖词元：光力、力科、州茅、强推、科技、维持、茅台、贵州**
- 答案侧约束（不产生证据目标，核验落点 I3-5）：
    - `q2` '通用评级定义页不能代替具体评级'
- 要件裁决队列（4 项）：
    - `I32-company-008-01`（source_coverage）该子句要求引用多份材料：'必须取得两份材料：贵州茅台为强推（维持），光力科技为优于大市（首次覆盖）'；**机器锚点联合仍未覆盖**：光力、力科、科技 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - `I32-company-008-02`（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'通用评级定义页不能代替具体评级'
    - `I32-company-008-03`（source_coverage）该题 satisfy_rule=all：来源 2026-08-16_6f14cc14 目前没有必需证据目标，必须指定该来源的承载 item；若改变来源义务须另行修订金标，不能以理由豁免
    - `I32-company-008-04`（source_coverage）该题 satisfy_rule=all：来源 2026-09-06_dddc7cd0 目前没有必需证据目标，必须指定该来源的承载 item；若改变来源义务须另行修订金标，不能以理由豁免
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：company-018-claim-001×1、company-ai-supplement-2026-08-16_6f14cc14-p1×1

## company-009（company，negative_opt_out，satisfy_rule=None）

- evidence_required：`false`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：负例题：答案为『库中无答案』，不适用证据目标，按评分器契约显式 evidence_required=false（该例外有独立业务依据，不得用于规避证据缺口）；仍须参加误报/伪造引用检查并人工确认全文覆盖

## company-010（company，negative_opt_out，satisfy_rule=None）

- evidence_required：`false`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：负例题：答案为『库中无答案』，不适用证据目标，按评分器契约显式 evidence_required=false（该例外有独立业务依据，不得用于规避证据缺口）；仍须参加误报/伪造引用检查并人工确认全文覆盖

## industry-001（industry，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 3 条、补充 2 条），但仍有 1 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：industry-009-claim-001、industry-020-claim-001、industry-ai-supplement-2026-08-13_174b6462-p10
- 要求覆盖账（按段）：
    - `c1` '图6续表纯碱行：价格分位0.0%、价差分位0.0%、开工率82.9%'
        - 数值要件 `f1` '0.0%' → required
        - 数值要件 `f2` '0.0%' → required
        - 数值要件 `f3` '82.9%' → required
    - `c2` '分位不是价格涨幅，开工率是注2所述期间平均'
        - 定性要件 `q4` → suggested（锚点 2 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-08-13_174b6462 page:10 row:纯碱 col:价格分位 ← industry-009-claim-001#0（table_cell；约束 {'row': '纯碱', 'col': '价格分位', 'cell': '纯碱 × 价格分位', 'unit': '%', 'period': '2016-01-01至2026-07-27'}）
        - quote：'0.0%'
    - `e2` 2026-08-13_174b6462 page:10 row:纯碱 col:价差分位 ← industry-009-claim-001#1（table_cell；约束 {'row': '纯碱', 'col': '价差分位', 'cell': '纯碱 × 价差分位', 'unit': '%', 'period': '2016-01-01至2026-07-27'}）
        - quote：'0.0%'
    - `e3` 2026-08-13_174b6462 page:10 row:纯碱 col:开工率 ← industry-009-claim-001#2（table_cell；约束 {'row': '纯碱', 'col': '开工率', 'cell': '纯碱 × 开工率', 'unit': '%', 'period': '2026年年初至7月26日或1—6月平均（见注2）'}）
        - quote：'82.9%'
- 补充证据（非必需；不声明替代关系）：
    - `e4` 2026-08-13_174b6462 page:10 ← industry-ai-supplement-2026-08-13_174b6462-p10#6（body；约束 {}）
        - quote：'纯碱\n0.0%\n0.0%\n82.9%'
        - 数值等价：{'0.0%': ['0.0%', '0.0%']}
    - `e5` 2026-08-13_174b6462 page:10 ← industry-ai-supplement-2026-08-13_174b6462-p10#8（body；约束 {}）
        - quote：'24.0\n28.5\n28.5\n-\n18.8%\n0.0%'
- 待批准锚点（批准前不得计入必需）：
    - `s1` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#9（condition；约束 {}）
        - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
        - **部分覆盖，未覆盖词元：价格、分位、格涨、涨幅、述期、间平**
    - `s2` 2026-08-13_174b6462 page:10 ← industry-ai-supplement-2026-08-13_174b6462-p10#2（body；约束 {}）
        - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
        - **部分覆盖，未覆盖词元：价格、分位、格涨、涨幅、述期、间平**
- 要件裁决队列（1 项）：
    - `I32-industry-001-01`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'分位不是价格涨幅，开工率是注2所述期间平均'；**机器锚点联合仍未覆盖**：价格、分位、格涨、涨幅、述期、间平 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
- 弱 token（年份/单字符，不参与匹配）：6、2
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：industry-009-claim-001×4、industry-ai-supplement-2026-08-13_174b6462-p10×3

## industry-002（industry，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 2 条、补充 0 条），但仍有 2 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：industry-009-claim-001、industry-020-claim-001、industry-ai-supplement-2026-08-13_174b6462-p10
- 要求覆盖账（按段）：
    - `c1` 'R32价格分位99.6%，2026E产能28.5万吨/年'
        - 数值要件 `f1` '99.6%' → required
        - 数值要件 `f2` '28.5' → required
    - `c2` '按注3属配额，不能解释为实际产量'
        - 定性要件 `q3` → suggested（锚点 2 条）
    - `c3` '价格分位窗口2016-01-01至2026-07-27'
        - 定性要件 `q4` → suggested（锚点 3 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-08-13_174b6462 page:10 row:R32 col:价格分位 ← industry-009-claim-001#3（table_cell；约束 {'row': 'R32', 'col': '价格分位', 'cell': 'R32 × 价格分位', 'unit': '%', 'period': '2016-01-01至2026-07-27'}）
        - quote：'99.6%'
    - `e2` 2026-08-13_174b6462 page:10 row:R32 col:2026E产能（配额） ← industry-009-claim-001#4（table_cell；约束 {'row': 'R32', 'col': '2026E产能（配额）', 'cell': 'R32 × 2026E产能（配额）', 'unit': '万吨/年', 'period': '2026E'}）
        - quote：'28.5'
- 待批准锚点（批准前不得计入必需）：
    - `s1` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#10（condition；约束 {}）
        - quote：'注3：制冷剂R22、R32、R134a 的产能为配额'
        - **部分覆盖，未覆盖词元：产量、实际、属配、按注、解释、际产**
    - `s2` 2026-08-13_174b6462 page:10 ← industry-ai-supplement-2026-08-13_174b6462-p10#3（body；约束 {}）
        - quote：'注3：制冷剂R22、R32、R134a 的产能为配额'
        - **部分覆盖，未覆盖词元：产量、实际、属配、按注、解释、际产**
    - `s3` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#8（condition；约束 {}）
        - quote：'注1：价格、价差分位为2016 年1 月1 日至2026 年7 月27 日'
        - **部分覆盖，未覆盖词元：位窗、格分、窗口**
- 要件裁决队列（2 项）：
    - `I32-industry-002-01`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'按注3属配额，不能解释为实际产量'；**机器锚点联合仍未覆盖**：产量、实际、属配、按注、解释、际产 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - `I32-industry-002-02`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'价格分位窗口2016-01-01至2026-07-27'；**机器锚点联合仍未覆盖**：位窗、格分、窗口 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
- 弱 token（年份/单字符，不参与匹配）：2026、3
- 期间 token（已掩码，另作期间要件）：2016-01-01、2026-07-27
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：industry-009-claim-001×4、industry-ai-supplement-2026-08-13_174b6462-p10×1

## industry-003（industry，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 2 条、补充 1 条），但仍有 1 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：industry-009-claim-001、industry-020-claim-001、industry-ai-supplement-2026-08-13_174b6462-p10
- 要求覆盖账（按段）：
    - `c1` '尿素开工率89.9%，2026E产能8068.0万吨/年'
        - 数值要件 `f1` '89.9%' → required
        - 数值要件 `f2` '8068.0' → required
    - `c2` '区分开工率与产能，2026E为预测列'
        - 定性要件 `q3` → suggested（锚点 3 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-08-13_174b6462 page:10 row:尿素 col:开工率 ← industry-009-claim-001#6（table_cell；约束 {'row': '尿素', 'col': '开工率', 'cell': '尿素 × 开工率', 'unit': '%', 'period': '2026年年初至7月26日或1—6月平均（见注2）'}）
        - quote：'89.9%'
    - `e2` 2026-08-13_174b6462 page:10 row:尿素 col:2026E产能 ← industry-009-claim-001#7（table_cell；约束 {'row': '尿素', 'col': '2026E产能', 'cell': '尿素 × 2026E产能', 'unit': '万吨/年', 'period': '2026E'}）
        - quote：'8068.0'
- 补充证据（非必需；不声明替代关系）：
    - `e3` 2026-08-13_174b6462 page:10 ← industry-ai-supplement-2026-08-13_174b6462-p10#9（body；约束 {}）
        - quote：'尿素\n32.1%\n10.9%\n89.9%'
- 待批准锚点（批准前不得计入必需）：
    - `s1` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#9（condition；约束 {}）
        - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
        - **部分覆盖，未覆盖词元：2026、分开、区分、测列、预测**
- 要件裁决队列（1 项）：
    - `I32-industry-003-01`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'区分开工率与产能，2026E为预测列'；**机器锚点联合仍未覆盖**：2026、分开、区分、测列、预测 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
- 弱 token（年份/单字符，不参与匹配）：2026
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：industry-009-claim-001×3、industry-ai-supplement-2026-08-13_174b6462-p10×1

## industry-004（industry，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 0 条、补充 0 条），但仍有 3 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：industry-009-claim-001、industry-020-claim-001、industry-ai-supplement-2026-08-13_174b6462-p10
- 要求覆盖账（按段）：
    - `c1` '价格/价差分位为2016-01-01至2026-07-27'
        - 定性要件 `q1` → suggested（锚点 3 条）
    - `c2` '开工率为2026-01-01至07-26平均或2026年1—6月平均'
        - 定性要件 `q2` → suggested（锚点 3 条）
    - `c3` '不得擅自把二选一窗口分配到各品种'
        - 定性要件 `q3` → usage_constraint（锚点 1 条）
- 待批准锚点（批准前不得计入必需）：
    - `s1` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#8（condition；约束 {}）
        - quote：'注1：价格、价差分位为2016 年1 月1 日至2026 年7 月27 日'
    - `s2` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#9（condition；约束 {}）
        - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
- 答案侧约束（不产生证据目标，核验落点 I3-5）：
    - `q3` '不得擅自把二选一窗口分配到各品种'
- 要件裁决队列（3 项）：
    - `I32-industry-004-01`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'价格/价差分位为2016-01-01至2026-07-27'
    - `I32-industry-004-02`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'开工率为2026-01-01至07-26平均或2026年1—6月平均'
    - `I32-industry-004-03`（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'不得擅自把二选一窗口分配到各品种'
- 期间 token（已掩码，另作期间要件）：07-26、1—6月、2016-01-01、2026-01-01、2026-07-27、2026年
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：industry-009-claim-001×2

## industry-005（industry，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 2 条、补充 0 条），但仍有 1 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：industry-057-claim-001、industry-ai-supplement-2026-09-06_f8e31696-p1
- 要求覆盖账（按段）：
    - `c1` '从720元/吨升至2459元/吨'
        - 数值要件 `f1` '720' → required
        - 数值要件 `f2` '2459' → required
    - `c2` '约四个月，报告称涨幅超过240%'
        - 数值要件 `f3` '240%' → required
    - `c3` '不是所有电子特气共同涨幅，也不是单日涨幅'
        - 定性要件 `q4` → usage_constraint（锚点 1 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#4（value；约束 {'unit': '元/吨；%', 'period': '2026年5月初至9月2日'}）
        - quote：'截至9\n月2 日，氩气价格报2459 元/吨，相比5 月初的720 元/吨，在4 个月时间里涨\n幅超过240%'
    - `e2` 2026-09-06_f8e31696 page:1 ← industry-ai-supplement-2026-09-06_f8e31696-p1#4（body；约束 {}）
        - quote：'国内氩气市场又走出一轮暴涨行情。自今年5 月\n涨价以来，7—8 月价格加速拉升，部分区域单日涨幅显著。数据显示，截至9\n月2 日，氩气价格报2459 元/吨，相比5 月初的720 元/吨，在4 个月时间里涨\n幅超过240%。'
- 答案侧约束（不产生证据目标，核验落点 I3-5）：
    - `q4` '不是所有电子特气共同涨幅，也不是单日涨幅'
- 要件裁决队列（1 项）：
    - `I32-industry-005-01`（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'不是所有电子特气共同涨幅，也不是单日涨幅'
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：industry-057-claim-001×1、industry-ai-supplement-2026-09-06_f8e31696-p1×1

## industry-006（industry，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 0 条、补充 0 条），但仍有 3 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：industry-057-claim-001、industry-ai-supplement-2026-09-06_f8e31696-p1
- 要求覆盖账（按段）：
    - `c1` '报告援引供应链消息：计划用于NVSwitch板卡及Rubin Ultra正交背板主力选材'
        - 定性要件 `q1` → suggested（锚点 2 条）
    - `c2` 'Rubin Ultra预计2027年推出'
        - 定性要件 `q2` → suggested（锚点 2 条）
    - `c3` '须保留消息来源与“计划/预计”限定'
        - 定性要件 `q3` → suggested（锚点 2 条）
- 待批准锚点（批准前不得计入必需）：
    - `s1` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#2（condition；约束 {'period': '报告时点；2027为预期'}）
        - quote：'英伟达计划在NVSwitch\n板卡中使用PTFE 材料，并将该材料作为英伟达新一代服务器平台Rubin Ultra\n正交背板的主力选材。Rubin Ultra 预计于2027 年推出。'
        - **部分覆盖，未覆盖词元：供应、划用、告援、应链、引供、援引、板主、消息、链消**
- 要件裁决队列（3 项）：
    - `I32-industry-006-01`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'报告援引供应链消息：计划用于NVSwitch板卡及Rubin Ultra正交背板主力选材'；**机器锚点联合仍未覆盖**：供应、划用、告援、应链、引供、援引、板主、消息、链消 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - `I32-industry-006-02`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'Rubin Ultra预计2027年推出'
    - `I32-industry-006-03`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'须保留消息来源与“计划/预计”限定'；**机器锚点联合仍未覆盖**：保留、息来、来源、消息、留消、限定 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
- 期间 token（已掩码，另作期间要件）：2027年
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：industry-057-claim-001×1

## industry-007（industry，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 3 条、补充 1 条），但仍有 1 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：industry-057-claim-001、industry-ai-supplement-2026-09-06_f8e31696-p1
- 要求覆盖账（按段）：
    - `c1` 'Wind新材料5611.65点、环比-4.2%'
        - 数值要件 `f1` '5611.65' → required
        - 数值要件 `f2` '4.2%' → required
    - `c2` '申万三级半导体材料12576.94点、环比-9.12%'
        - 数值要件 `f3` '12576.94' → required
        - 数值要件 `f4` '9.12%' → required
    - `c3` '保持指数名和数值配对'
        - 定性要件 `q5` → usage_constraint（锚点 0 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#0（value；约束 {'unit': '点；%', 'period': '2026-09-06周报本周'}）
        - quote：'Wind 新材料指数收报5611.65 点，环比下跌4.2%'
    - `e2` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#1（value；约束 {'unit': '点；%', 'period': '2026-09-06周报本周'}）
        - quote：'申万三级行业半导体材料指数收报12576.94 点，环比下跌\n9.12%'
    - `e3` 2026-09-06_f8e31696 page:1 ← industry-ai-supplement-2026-09-06_f8e31696-p1#1（body；约束 {}）
        - quote：'本周，Wind 新材料指数收报5611.65 点，环比下跌4.2%。'
- 补充证据（非必需；不声明替代关系）：
    - `e4` 2026-09-06_f8e31696 page:1 ← industry-ai-supplement-2026-09-06_f8e31696-p1#2（body；约束 {}）
        - quote：'六个子行业中，申万三级行业半导体材料指数收报12576.94 点，环比下跌\n9.12%；'
- 答案侧约束（不产生证据目标，核验落点 I3-5）：
    - `q5` '保持指数名和数值配对'
- 要件裁决队列（1 项）：
    - `I32-industry-007-01`（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'保持指数名和数值配对'
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：industry-057-claim-001×2、industry-ai-supplement-2026-09-06_f8e31696-p1×2

## industry-008（industry，pending_human，satisfy_rule=all）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 1 条、补充 1 条），但仍有 3 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：industry-009-claim-001、industry-020-claim-001、industry-057-claim-001、industry-ai-supplement-2026-08-13_174b6462-p10、industry-ai-supplement-2026-09-06_f8e31696-p1
- 要求覆盖账（按段）：
    - `c1` '不能：R32为历史价格分位（2016-01-01至2026-07-27）'
        - 定性要件 `q1` → suggested（锚点 3 条）
    - `c2` '氩气为2026年5月初720至9月2日2459元/吨的价格涨幅'
        - 数值要件 `f2` '2459' → required
    - `c3` '须引用两份材料证明统计含义不同'
        - 定性要件 `q3` → source_coverage（锚点 0 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#4（value；约束 {'unit': '元/吨；%', 'period': '2026年5月初至9月2日'}）
        - quote：'截至9\n月2 日，氩气价格报2459 元/吨，相比5 月初的720 元/吨，在4 个月时间里涨\n幅超过240%'
- 补充证据（非必需；不声明替代关系）：
    - `e2` 2026-09-06_f8e31696 page:1 ← industry-ai-supplement-2026-09-06_f8e31696-p1#4（body；约束 {}）
        - quote：'国内氩气市场又走出一轮暴涨行情。自今年5 月\n涨价以来，7—8 月价格加速拉升，部分区域单日涨幅显著。数据显示，截至9\n月2 日，氩气价格报2459 元/吨，相比5 月初的720 元/吨，在4 个月时间里涨\n幅超过240%。'
- 待批准锚点（批准前不得计入必需）：
    - `s1` 2026-08-13_174b6462 page:10 row:R32 col:价格分位 ← industry-009-claim-001#3（table_cell；约束 {'row': 'R32', 'col': '价格分位', 'cell': 'R32 × 价格分位', 'unit': '%', 'period': '2016-01-01至2026-07-27'}）
        - quote：'99.6%'
        - **部分覆盖，未覆盖词元：32、价格、分位、历史、史价、格分**
- 要件裁决队列（3 项）：
    - `I32-industry-008-01`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'不能：R32为历史价格分位（2016-01-01至2026-07-27）'；**机器锚点联合仍未覆盖**：32、价格、分位、历史、史价、格分 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - `I32-industry-008-02`（source_coverage）该子句要求引用多份材料：'须引用两份材料证明统计含义不同'
    - `I32-industry-008-03`（source_coverage）该题 satisfy_rule=all：来源 2026-08-13_174b6462 目前没有必需证据目标，必须指定该来源的承载 item；若改变来源义务须另行修订金标，不能以理由豁免
- 弱 token（年份/单字符，不参与匹配）：7、2
- 期间 token（已掩码，另作期间要件）：2016-01-01、2026-07-27、2026年5月、20至9月
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：industry-009-claim-001×1、industry-057-claim-001×1、industry-ai-supplement-2026-09-06_f8e31696-p1×1

## industry-009（industry，negative_opt_out，satisfy_rule=None）

- evidence_required：`false`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：负例题：答案为『库中无答案』，不适用证据目标，按评分器契约显式 evidence_required=false（该例外有独立业务依据，不得用于规避证据缺口）；仍须参加误报/伪造引用检查并人工确认全文覆盖

## industry-010（industry，negative_opt_out，satisfy_rule=None）

- evidence_required：`false`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：负例题：答案为『库中无答案』，不适用证据目标，按评分器契约显式 evidence_required=false（该例外有独立业务依据，不得用于规避证据缺口）；仍须参加误报/伪造引用检查并人工确认全文覆盖

## macro-001（macro，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 2 条、补充 1 条），但仍有 1 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：macro-019-claim-001、macro-038-claim-001、macro-ai-supplement-2026-09-06_793b3967-p1、macro-ai-supplement-2026-09-06_793b3967-p3
- 要求覆盖账（按段）：
    - `c1` '8月16.2万人，预期5.6万人'
        - 数值要件 `f1` '16.2' → required
        - 数值要件 `f2` '5.6' → required
    - `c2` '7月由-2.3万人修正为2.1万人'
        - 数值要件 `f3` '2.3' → required
        - 数值要件 `f4` '2.1' → required
    - `c3` '前值修订与8月数据分开'
        - 定性要件 `q5` → suggested（锚点 1 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#0（value；约束 {'unit': '万人', 'period': '2026-08；2026-07前值修订'}）
        - quote：'新增非农就业16.2\n万人，预期5.6 万人，前值由-2.3 万人修正为2.1 万人'
    - `e2` 2026-09-06_793b3967 page:1 ← macro-ai-supplement-2026-09-06_793b3967-p1#0（body；约束 {}）
        - quote：'2026 年9 月4 日，美国劳工部公布2026 年8 月非农数据：新增非农就业16.2\n万人，预期5.6 万人，前值由-2.3 万人修正为2.1 万人；8 月失业率4.1%，预期\n4.1%，前值4.1%；平均时薪同比升3.1%，预期升3.0%，前值升3.2%。'
- 补充证据（非必需；不声明替代关系）：
    - `e3` 2026-09-06_793b3967 page:1 ← macro-ai-supplement-2026-09-06_793b3967-p1#2（body；约束 {}）
        - quote：'8 月超预期的非农数据、回升的劳动参与率、处于低位的\n失业率数据，都指向就业市场韧性比之前市场预期的更强，若后续公布的通胀数\n据下行幅度有限，美联储9 月加息的可能性将很难被忽视。 \n非农数据高于预期，生产与服务部门同步回暖。 \n（一）休闲酒店业：8 月休闲酒店业新增就业+6.2 万人，大幅高于前值的-2.1 万\n人，回补迹象明显。（二）信息业：信息业就业再次转负至-2.3 万人，反映AI\n对科技行业就业的冲击。（三）政府部门：政府部门新增就业从前值的-5.0 万人\n升至+3.5 万人，其中地方政府教育行业新增就业增加4.2 万人，由于暑期的季节\n性调整有关，近期地方政府部门就业波动较大。 \n劳动参与率回升，失业率持平于前值。 \n8 月劳动参与率为61.6%，高于上月的61.4%，中青年群体就业意愿回升。从失\n业人口看，8 月失业人口增加了11.5 万人，8 月U3 失业率（=失业人数/劳动力\n人数）稳定在4.1%。从结构看，8 月暂时性失业者减少8.2 万人，前值为增加\n15.3 万人，永久性失业者增加6.2 万人，前值为减少5.4 万人，反映临时性工作\n需求增加。 \n从加息角度看，在杰克逊霍尔会议上，沃什主张“通胀优先”，以鹰派措辞抬高\n了加息预期，8 月就业数据整体偏强，大大减少了加息的“顾虑”，也让8 月通\n胀数据变得更为关键。 \n8 月超预期的非农数据、回升的劳动参与率、处于低位的失业率数据，都指向就\n业市场韧性比之前市场预期的更强，若后续公布的通胀数据下行幅度有限，美联\n储9 月加息的可能性将很难被忽视。在非农数据公布后，市场预期9 月加息的概\n率已经超过60%。'
- 要件裁决队列（1 项）：
    - `I32-macro-001-01`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'前值修订与8月数据分开'；**机器锚点联合仍未覆盖**：修订、值修、分开、据分 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
- 期间 token（已掩码，另作期间要件）：7月、8月
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：macro-038-claim-001×1、macro-ai-supplement-2026-09-06_793b3967-p1×2

## macro-002（macro，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 3 条、补充 2 条），但仍有 1 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：macro-019-claim-001、macro-038-claim-001、macro-ai-supplement-2026-09-06_793b3967-p1、macro-ai-supplement-2026-09-06_793b3967-p3
- 要求覆盖账（按段）：
    - `c1` '失业率4.1%/前值4.1%，劳动参与率61.6%/前值61.4%，平均时薪同比3.1%/前值3.2%'
        - 数值要件 `f1` '4.1%' → required
        - 数值要件 `f2` '4.1%' → required
        - 数值要件 `f3` '61.6%' → required
        - 数值要件 `f4` '61.4%' → required
        - 数值要件 `f5` '3.1%' → required
        - 数值要件 `f6` '3.2%' → required
    - `c2` '均为报告所述'
        - 定性要件 `q7` → usage_constraint（锚点 0 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#1（value；约束 {'unit': '%', 'period': '2026-08'}）
        - quote：'8 月失业率4.1%，预期\n4.1%，前值4.1%；平均时薪同比升3.1%，预期升3.0%，前值升3.2%。'
    - `e3` 2026-09-06_793b3967 page:1 ← macro-ai-supplement-2026-09-06_793b3967-p1#0（body；约束 {}）
        - quote：'2026 年9 月4 日，美国劳工部公布2026 年8 月非农数据：新增非农就业16.2\n万人，预期5.6 万人，前值由-2.3 万人修正为2.1 万人；8 月失业率4.1%，预期\n4.1%，前值4.1%；平均时薪同比升3.1%，预期升3.0%，前值升3.2%。'
    - `e4` 2026-09-06_793b3967 page:1 ← macro-ai-supplement-2026-09-06_793b3967-p1#2（body；约束 {}）
        - quote：'8 月超预期的非农数据、回升的劳动参与率、处于低位的\n失业率数据，都指向就业市场韧性比之前市场预期的更强，若后续公布的通胀数\n据下行幅度有限，美联储9 月加息的可能性将很难被忽视。 \n非农数据高于预期，生产与服务部门同步回暖。 \n（一）休闲酒店业：8 月休闲酒店业新增就业+6.2 万人，大幅高于前值的-2.1 万\n人，回补迹象明显。（二）信息业：信息业就业再次转负至-2.3 万人，反映AI\n对科技行业就业的冲击。（三）政府部门：政府部门新增就业从前值的-5.0 万人\n升至+3.5 万人，其中地方政府教育行业新增就业增加4.2 万人，由于暑期的季节\n性调整有关，近期地方政府部门就业波动较大。 \n劳动参与率回升，失业率持平于前值。 \n8 月劳动参与率为61.6%，高于上月的61.4%，中青年群体就业意愿回升。从失\n业人口看，8 月失业人口增加了11.5 万人，8 月U3 失业率（=失业人数/劳动力\n人数）稳定在4.1%。从结构看，8 月暂时性失业者减少8.2 万人，前值为增加\n15.3 万人，永久性失业者增加6.2 万人，前值为减少5.4 万人，反映临时性工作\n需求增加。 \n从加息角度看，在杰克逊霍尔会议上，沃什主张“通胀优先”，以鹰派措辞抬高\n了加息预期，8 月就业数据整体偏强，大大减少了加息的“顾虑”，也让8 月通\n胀数据变得更为关键。 \n8 月超预期的非农数据、回升的劳动参与率、处于低位的失业率数据，都指向就\n业市场韧性比之前市场预期的更强，若后续公布的通胀数据下行幅度有限，美联\n储9 月加息的可能性将很难被忽视。在非农数据公布后，市场预期9 月加息的概\n率已经超过60%。'
- 补充证据（非必需；不声明替代关系）：
    - `e2` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#2（value；约束 {'unit': '%', 'period': '2026-08；2026-07'}）
        - quote：'8 月劳动参与率为61.6%，高于上月的61.4%'
    - `e5` 2026-09-06_793b3967 page:1 ← macro-ai-supplement-2026-09-06_793b3967-p1#3（body；约束 {}）
        - quote：'8 月劳动参与率为61.6%，高于上月的61.4%'
- 答案侧约束（不产生证据目标，核验落点 I3-5）：
    - `q7` '均为报告所述'
- 要件裁决队列（1 项）：
    - `I32-macro-002-01`（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'均为报告所述'
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：macro-038-claim-001×2、macro-ai-supplement-2026-09-06_793b3967-p1×3

## macro-003（macro，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 1 条、补充 1 条），但仍有 3 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：macro-019-claim-001、macro-038-claim-001、macro-ai-supplement-2026-09-06_793b3967-p1、macro-ai-supplement-2026-09-06_793b3967-p3
- 要求覆盖账（按段）：
    - `c1` '条件是后续通胀下行幅度有限'
        - 定性要件 `q1` → suggested（锚点 2 条）
    - `c2` '强就业降低加息顾虑'
        - 定性要件 `q2` → suggested（锚点 2 条）
    - `c3` '报告称非农公布后市场预期概率超过60%'
        - 数值要件 `f3` '60%' → required
    - `c4` '必须区分附条件判断、市场预期和正式决定'
        - 定性要件 `q4` → suggested（锚点 3 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#4（value；约束 {'unit': '%', 'period': '2026-09-04非农公布后'}）
        - quote：'在非农数据公布后，市场预期9 月加息的概\n率已经超过60%。'
- 补充证据（非必需；不声明替代关系）：
    - `e2` 2026-09-06_793b3967 page:1 ← macro-ai-supplement-2026-09-06_793b3967-p1#2（body；约束 {}）
        - quote：'8 月超预期的非农数据、回升的劳动参与率、处于低位的\n失业率数据，都指向就业市场韧性比之前市场预期的更强，若后续公布的通胀数\n据下行幅度有限，美联储9 月加息的可能性将很难被忽视。 \n非农数据高于预期，生产与服务部门同步回暖。 \n（一）休闲酒店业：8 月休闲酒店业新增就业+6.2 万人，大幅高于前值的-2.1 万\n人，回补迹象明显。（二）信息业：信息业就业再次转负至-2.3 万人，反映AI\n对科技行业就业的冲击。（三）政府部门：政府部门新增就业从前值的-5.0 万人\n升至+3.5 万人，其中地方政府教育行业新增就业增加4.2 万人，由于暑期的季节\n性调整有关，近期地方政府部门就业波动较大。 \n劳动参与率回升，失业率持平于前值。 \n8 月劳动参与率为61.6%，高于上月的61.4%，中青年群体就业意愿回升。从失\n业人口看，8 月失业人口增加了11.5 万人，8 月U3 失业率（=失业人数/劳动力\n人数）稳定在4.1%。从结构看，8 月暂时性失业者减少8.2 万人，前值为增加\n15.3 万人，永久性失业者增加6.2 万人，前值为减少5.4 万人，反映临时性工作\n需求增加。 \n从加息角度看，在杰克逊霍尔会议上，沃什主张“通胀优先”，以鹰派措辞抬高\n了加息预期，8 月就业数据整体偏强，大大减少了加息的“顾虑”，也让8 月通\n胀数据变得更为关键。 \n8 月超预期的非农数据、回升的劳动参与率、处于低位的失业率数据，都指向就\n业市场韧性比之前市场预期的更强，若后续公布的通胀数据下行幅度有限，美联\n储9 月加息的可能性将很难被忽视。在非农数据公布后，市场预期9 月加息的概\n率已经超过60%。'
- 待批准锚点（批准前不得计入必需）：
    - `s1` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#3（condition；约束 {'period': '2026-09预期'}）
        - quote：'若后续公布的通胀数\n据下行幅度有限，美联储9 月加息的可能性将很难被忽视。'
        - **部分覆盖，未覆盖词元：条件、续通**
    - `s2` 2026-09-06_793b3967 page:1 ← macro-ai-supplement-2026-09-06_793b3967-p1#1（body；约束 {}）
        - quote：'从加息角度看，在杰克逊霍尔会议上，沃什主张“通胀优先”，以鹰派措辞抬高\n了加息预期，8 月就业数据整体偏强，大大减少了加息的“顾虑”，也让8 月通\n胀数据变得更为关键。'
        - **部分覆盖，未覆盖词元：业降、低加、息顾、降低**
- 要件裁决队列（3 项）：
    - `I32-macro-003-01`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'条件是后续通胀下行幅度有限'；**机器锚点联合仍未覆盖**：条件、续通 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - `I32-macro-003-02`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'强就业降低加息顾虑'；**机器锚点联合仍未覆盖**：业降、低加、息顾、降低 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - `I32-macro-003-03`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'必须区分附条件判断、市场预期和正式决定'；**机器锚点联合仍未覆盖**：件判、决定、分附、判断、区分、场预、市场、式决、条件、正式、附条、预期 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：macro-038-claim-001×2、macro-ai-supplement-2026-09-06_793b3967-p1×2

## macro-004（macro，blocked，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：存在无承载 item 的要件 1 项：需补人工标注或由 U 裁定，候选不得据此冻结为金标
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001、macro-ai-supplement-2026-09-06_cc03f55b-p1、macro-ai-supplement-2026-09-06_cc03f55b-p2、macro-ai-supplement-2026-09-06_cc03f55b-p11
- 要求覆盖账（按段）：
    - `c1` '五主体为政府、准财政、企业、居民、海外'
        - 定性要件 `q1` → suggested（锚点 2 条）
    - `c2` '本文聚焦前四者'
        - 定性要件 `q2` → missing（锚点 0 条）
    - `c3` '四路径为财政支出增加、缓解城投化债压力、企业投资增加、居民支出增加'
        - 定性要件 `q3` → suggested（锚点 3 条）
- 待批准锚点（批准前不得计入必需）：
    - `s1` 2026-09-06_cc03f55b page:1 ← macro-039-claim-001#1（condition；约束 {}）
        - quote：'这五个主体分别是政府、准财政（如城投等）、企业、居民、海\n外。'
        - **部分覆盖，未覆盖词元：五主**
    - `s2` 2026-09-06_cc03f55b page:1 ← macro-ai-supplement-2026-09-06_cc03f55b-p1#3（body；约束 {}）
        - quote：'二、路径2：缓解城投化债压力'
        - **部分覆盖，未覆盖词元：业投、企业、出增、四路、增加、居民、投资、支出、政支、民支、财政、资增**
- 要件裁决队列（3 项）：
    - `I32-macro-004-01`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'五主体为政府、准财政、企业、居民、海外'；**机器锚点联合仍未覆盖**：五主 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - `I32-macro-004-02`（qualification）该定性要件在冻结标注中没有承载 item，需人工补标注或裁定：'本文聚焦前四者'
    - `I32-macro-004-03`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'四路径为财政支出增加、缓解城投化债压力、企业投资增加、居民支出增加'；**机器锚点联合仍未覆盖**：业投、企业、出增、四路、增加、居民、投资、支出、政支、民支、财政、资增 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：macro-039-claim-001×1、macro-ai-supplement-2026-09-06_cc03f55b-p1×1

## macro-005（macro，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 1 条、补充 1 条），但仍有 2 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001、macro-ai-supplement-2026-09-06_cc03f55b-p1、macro-ai-supplement-2026-09-06_cc03f55b-p2、macro-ai-supplement-2026-09-06_cc03f55b-p11
- 要求覆盖账（按段）：
    - `c1` '两本账支出增速预计约-0.5%，低于名义GDP增速'
        - 数值要件 `f1` '0.5%' → required
    - `c2` '堵点为收入依赖旧动能且受其下行拖累、新动能综合税负偏低'
        - 定性要件 `q2` → suggested（锚点 3 条）
    - `c3` '须标注预测'
        - 定性要件 `q3` → usage_constraint（锚点 0 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-09-06_cc03f55b page:1 ← macro-039-claim-001#2（value；约束 {'unit': '%', 'period': '2026E'}）
        - quote：'2026 年，预计\n两本账支出增速为-0.5%左右，仍低于名义GDP 增速。'
- 补充证据（非必需；不声明替代关系）：
    - `e2` 2026-09-06_cc03f55b page:1 ← macro-ai-supplement-2026-09-06_cc03f55b-p1#6（body；约束 {}）
        - quote：'3、财政的支出现状如何？支出端，主要的问题是，增速低于名义GDP 增速。\n2021-2025 年，两本账合计支出增速持续低于名义GDP 增速，2026 年，预计\n两本账支出增速为-0.5%左右，仍低于名义GDP 增速。'
- 待批准锚点（批准前不得计入必需）：
    - `s1` 2026-09-06_cc03f55b page:1 ← macro-ai-supplement-2026-09-06_cc03f55b-p1#5（body；约束 {}）
        - quote：'2、路径1 的堵点在哪？在两点。一是财政的收入端较为依赖旧动能，旧动能\n的增速下行仍在负向拖累财政收入。二是新动能的综合税负（每百元收入缴纳\n的税收）偏低，不利于财政收入增加。'
        - **部分覆盖，未覆盖词元：入依、行拖、负偏**
- 答案侧约束（不产生证据目标，核验落点 I3-5）：
    - `q3` '须标注预测'
- 要件裁决队列（2 项）：
    - `I32-macro-005-01`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'堵点为收入依赖旧动能且受其下行拖累、新动能综合税负偏低'；**机器锚点联合仍未覆盖**：入依、行拖、负偏 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
    - `I32-macro-005-02`（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'须标注预测'
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：macro-039-claim-001×1、macro-ai-supplement-2026-09-06_cc03f55b-p1×2

## macro-006（macro，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 2 条、补充 0 条），但仍有 1 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001、macro-ai-supplement-2026-09-06_cc03f55b-p1、macro-ai-supplement-2026-09-06_cc03f55b-p2、macro-ai-supplement-2026-09-06_cc03f55b-p11
- 要求覆盖账（按段）：
    - `c1` '央企4.6%对5.9%，地方国企6.1%对6.2%，均下降'
        - 数值要件 `f1` '4.6%' → required
        - 数值要件 `f2` '5.9%' → required
        - 数值要件 `f3` '6.1%' → required
        - 数值要件 `f4` '6.2%' → required
    - `c2` '样本为偏头部发债企业，不等于全国所有国企'
        - 定性要件 `q5` → suggested（锚点 3 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-09-06_cc03f55b page:1 ← macro-039-claim-001#3（value；约束 {'unit': '%', 'period': '2025；2024'}）
        - quote：'2025 年，央企样本企业的有息负\n债增速为4.6%，低于2024 年的5.9%。2025 年，地方国有企业样本企业的有\n息负债增速为6.1%，低于2024 年的6.2%。'
    - `e2` 2026-09-06_cc03f55b page:1 ← macro-ai-supplement-2026-09-06_cc03f55b-p1#7（body；约束 {}）
        - quote：'3、国企的支出现状如何？我们借助其有息负债的增速观察其支出情况。选择\n偏头部的发债企业财务数据作为观察对象。2025 年，央企样本企业的有息负\n债增速为4.6%，低于2024 年的5.9%。2025 年，地方国有企业样本企业的有\n息负债增速为6.1%，低于2024 年的6.2%。'
- 要件裁决队列（1 项）：
    - `I32-macro-006-01`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'样本为偏头部发债企业，不等于全国所有国企'；**机器锚点联合仍未覆盖**：全国、有国、部发 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：macro-039-claim-001×1、macro-ai-supplement-2026-09-06_cc03f55b-p1×1

## macro-007（macro，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 3 条、补充 0 条），但仍有 1 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001、macro-ai-supplement-2026-09-06_cc03f55b-p1、macro-ai-supplement-2026-09-06_cc03f55b-p2、macro-ai-supplement-2026-09-06_cc03f55b-p11
- 要求覆盖账（按段）：
    - `c1` '消费倾向=消费/可支配收入，2026/2025/2019Q2为67.5%/68.6%/70.5%'
        - 数值要件 `f1` '67.5%' → required
        - 数值要件 `f2` '68.6%' → required
        - 数值要件 `f3` '70.5%' → required
    - `c2` '支出倾向=(消费+新房购房)/可支配收入，为80.3%/83.7%/110.3%'
        - 数值要件 `f4` '80.3%' → required
        - 数值要件 `f5` '83.7%' → required
        - 数值要件 `f6` '110.3%' → required
    - `c3` '不能混用口径'
        - 定性要件 `q7` → usage_constraint（锚点 0 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#2（value；约束 {'unit': '%', 'period': '2026Q2；2025Q2；2019Q2'}）
        - quote：'从消费倾向（消费/可支配收\n入）来看，2 季度，消费倾向为67.5%，低于2025 年同期的68.6%以及2019\n年同期的70.5%。'
    - `e2` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#3（value；约束 {'unit': '%', 'period': '2026Q2；2025Q2；2019Q2'}）
        - quote：'从支出倾向（消费叠加新房购房与可支配收入之比），2 季度\n为80.3%，低于2025 年同期的83.7%以及2019 年同期的110.3%。'
    - `e3` 2026-09-06_cc03f55b page:2 ← macro-ai-supplement-2026-09-06_cc03f55b-p2#1（body；约束 {}）
        - quote：'3、居民支出的现状如何？支出意愿或依然偏低。从消费倾向（消费/可支配收\n入）来看，2 季度，消费倾向为67.5%，低于2025 年同期的68.6%以及2019\n年同期的70.5%。从支出倾向（消费叠加新房购房与可支配收入之比），2 季度\n为80.3%，低于2025 年同期的83.7%以及2019 年同期的110.3%。'
- 答案侧约束（不产生证据目标，核验落点 I3-5）：
    - `q7` '不能混用口径'
- 要件裁决队列（1 项）：
    - `I32-macro-007-01`（answer_constraint）确认答案侧口径（不产生证据目标，但答案必须满足；核验落点 I3-5（答案侧检查））：'不能混用口径'
- 弱 token（年份/单字符，不参与匹配）：2026、2025
- 期间 token（已掩码，另作期间要件）：2019Q2
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：macro-060-claim-001×2、macro-ai-supplement-2026-09-06_cc03f55b-p2×1

## macro-008（macro，pending_human，satisfy_rule=any）

- evidence_required：`true`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：机器已定位全部数值要件（必需 2 条、补充 0 条），但仍有 1 项需人工裁决（定性要件锚点/数值等价/多来源覆盖/答案侧口径）；批准前不得计入必需证据，且机器状态不等于人工已核验
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001、macro-ai-supplement-2026-09-06_cc03f55b-p1、macro-ai-supplement-2026-09-06_cc03f55b-p2、macro-ai-supplement-2026-09-06_cc03f55b-p11
- 要求覆盖账（按段）：
    - `c1` '2026年1—6月本年施工项目计划总投资同比-4.3%，本年新开工项目计划总投资增速-29.4%'
        - 数值要件 `f1` '4.3%' → required
        - 数值要件 `f2` '29.4%' → required
    - `c2` '上市公司/发债企业样本代表性可能欠佳，结论可能偏差且可能有其他收敛路径'
        - 定性要件 `q3` → suggested（锚点 3 条）
- 必需证据（计入 EvidencePass）：
    - `e1` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#0（value；约束 {'unit': '%', 'period': '2026-01至2026-06'}）
        - quote：'1-6 月，本年施工项目计划总投资累计同比\n为-4.3%，本年新开工项目计划总投资增速为-29.4%。'
    - `e2` 2026-09-06_cc03f55b page:2 ← macro-ai-supplement-2026-09-06_cc03f55b-p2#2（body；约束 {}）
        - quote：'3、固定资产投资的现状如何？我们重点关注项目端的情况，当前固定资产投\n资或受制于项目不足，表现偏弱。1-6 月，本年施工项目计划总投资累计同比\n为-4.3%，本年新开工项目计划总投资增速为-29.4%。'
- 待批准锚点（批准前不得计入必需）：
    - `s1` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#4（condition；约束 {}）
        - quote：'使用上市公司或者发债企业的数据代表性可能欠佳，获得的结论有\n一定的偏差。可能存在其他收敛路径。'
        - **部分覆盖，未覆盖词元：业样**
- 要件裁决队列（1 项）：
    - `I32-macro-008-01`（qualification）确认该定性要件已由候选原文承载（或改选/裁定需补标注）：'上市公司/发债企业样本代表性可能欠佳，结论可能偏差且可能有其他收敛路径'；**机器锚点联合仍未覆盖**：业样 —— 实质缺证须改选/补标；仅词面差异可用逐项原文 lexical_review，禁止 residual 豁免
- 期间 token（已掩码，另作期间要件）：1—6月、2026年
- item 覆盖统计（**诊断用，不是 EvidencePass 分母**）：macro-060-claim-001×2、macro-ai-supplement-2026-09-06_cc03f55b-p2×1

## macro-009（macro，negative_opt_out，satisfy_rule=None）

- evidence_required：`false`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：负例题：答案为『库中无答案』，不适用证据目标，按评分器契约显式 evidence_required=false（该例外有独立业务依据，不得用于规避证据缺口）；仍须参加误报/伪造引用检查并人工确认全文覆盖

## macro-010（macro，negative_opt_out，satisfy_rule=None）

- evidence_required：`false`；候选文件内状态：`pending`（信息字段，不作批准凭据）
- 机器判定：负例题：答案为『库中无答案』，不适用证据目标，按评分器契约显式 evidence_required=false（该例外有独立业务依据，不得用于规避证据缺口）；仍须参加误报/伪造引用检查并人工确认全文覆盖
