# I3-2 补料：证据目标候选（待 U 裁决）

- 生成时间：2026-09-18T15:01:56+08:00；规则版本：`evidence-mapping-1`
- 输入：`query-gold-frozen.jsonl` sha256=6f6c5a25d55b…、`source-gold-frozen.jsonl` sha256=c360a132ad63…
- 统计：mapped **21** / partial **1** / unmapped **2** / 负例显式不做证据评分 **6**；候选证据目标合计 **133** 条

> 本文件是**机器建议**：证据来源全部是 I0A-4 人工标注槽位（reviewer=xyl），quote 为原文逐字子串；
> 未命中项一律登记不猜。裁决后方可进入 I3-2 正式冻结。

## company-001（company，mapped）

- evidence_required：`true`
- 候选槽位：company-001-claim-001、company-008-claim-001、company-013-claim-001
- `e1` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#2（命中 67.74）
    - quote：'67.74'
- `e2` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#6（命中 70.77）
    - quote：'70.77'
- `e3` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#10（命中 73.84）
    - quote：'73.84'
- `e4` 2026-08-16_6f14cc14 page:1 ← company-008-claim-001#4（命中 67.74、70.77、73.84）
    - quote：'我们维持26-28 年EPS 预测值\n67.74/70.77/73.84 元，维持一年目标价2030 元和“强推”评级。'

## company-002（company，mapped）

- evidence_required：`true`
- 候选槽位：company-001-claim-001、company-008-claim-001、company-013-claim-001
- `e1` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#0（命中 1、2）
    - quote：'178,657'
- `e2` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#1（命中 2）
    - quote：'84,679'
- `e3` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#2（命中 2）
    - quote：'67.74'
- `e4` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#3（命中 2）
    - quote：'25,756'
- `e5` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#4（命中 1、2）
    - quote：'186,196'
- `e6` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#5（命中 2）
    - quote：'88,470'
- `e7` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#6（命中 2）
    - quote：'70.77'
- `e8` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#7（命中 2）
    - quote：'30,089'
- `e9` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#8（命中 1、2）
    - quote：'194,063'
- `e10` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#9（命中 2）
    - quote：'92,302'
- `e11` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#10（命中 2）
    - quote：'73.84'
- `e12` 2026-08-16_6f14cc14 page:3 ← company-001-claim-001#11（命中 1、2）
    - quote：'35,014'
- `e13` 2026-08-16_6f14cc14 page:1 ← company-008-claim-001#0（命中 1、922.8、1.3%、445.2、2.0%、2）
    - quote：'26H1 实现总收入922.8 亿元，同增1.3%，归母净利润\n445.2 亿元，同降2.0%。'
- `e14` 2026-08-16_6f14cc14 page:1 ← company-008-claim-001#1（命中 1、2、375.8、5.2%、172.7、6.9%）
    - quote：'单Q2 总收入375.8 亿元，同降5.2%，归母净利润\n172.7 亿元，同降6.9%。'
- `e15` 2026-08-16_6f14cc14 page:1 ← company-008-claim-001#2（命中 1、2）
    - quote：'单Q2 直销占比同比大幅提升17.8pcts 至61.1%，i 茅台收入同\n增282.6%至187.1 亿'
- `e16` 2026-08-16_6f14cc14 page:1 ← company-008-claim-001#3（命中 1、2）
    - quote：'经营性现金流\n净额同增915.8%，主要系财务公司吸收集团公司成员单位存款增加及不可随\n时支取的同业存款减少所致。'
- `e17` 2026-08-16_6f14cc14 page:1 ← company-008-claim-001#4（命中 1、2）
    - quote：'我们维持26-28 年EPS 预测值\n67.74/70.77/73.84 元，维持一年目标价2030 元和“强推”评级。'
- `e18` 2026-08-16_6f14cc14 page:7 ← company-013-claim-001#0（命中 1、2）
    - quote：'贵州茅台的控股股东茅台集团持有本公司的控股股东华创云信4.06%的股\n份。'

## company-003（company，mapped）

- evidence_required：`true`
- 候选槽位：company-003-claim-001、company-018-claim-001、company-024-claim-001、company-028-claim-001、company-032-claim-001、company-036-claim-001、company-040-claim-001、company-044-claim-001、company-048-claim-001、company-052-claim-001、company-056-claim-001、company-060-claim-001
- `e1` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#0（命中 0.36、20）
    - quote：'0.36'
- `e2` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#1（命中 20）
    - quote：'78.6'
- `e3` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#2（命中 222、20）
    - quote：'(222)'
- `e4` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#3（命中 0.59、20）
    - quote：'0.59'
- `e5` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#4（命中 20）
    - quote：'47.5'
- `e6` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#5（命中 138、20）
    - quote：'(138)'
- `e7` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#6（命中 0.93、20）
    - quote：'0.93'
- `e8` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#7（命中 20）
    - quote：'30.3'
- `e9` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#8（命中 17、20）
    - quote：'(17)'
- `e10` 2026-09-06_dddc7cd0 page:1 ← company-018-claim-001#0（命中 20）
    - quote：'2026 年上半年公\n司实现营业收入4.53 亿元，同比+57.23%；实现归母净利润0.74 亿元，\n同比+194.56%；扣非归母净利润0.70 亿元，同比+552.69%。'
- `e11` 2026-09-06_dddc7cd0 page:1 ← company-018-claim-001#1（命中 20）
    - quote：'2026 年上半\n年半导体封测装备制造业务实现收入3.51 亿元，同比增长162.25%，收\n入占比提升至77.63%；毛利率44.97%，同比提升3.4 个百分点。'
- `e12` 2026-09-06_dddc7cd0 page:1 ← company-018-claim-001#2（命中 20）
    - quote：'其设定的2026—2028 年的营业收入触发\n值和目标值分别为8.84/12.06/15.81 亿元（26-28 年同比增速为\n32%/36%/31% ）和9.38/13.4/18.09 亿元'
- `e13` 2026-09-06_dddc7cd0 page:1 ← company-018-claim-001#3（命中 20）
    - quote：'我\n们预计公司2026—2028 年归母净利润分别为1.32/2.19/3.43 亿元，对\n应PE 分别为79/48/30 倍，首次覆盖给予“优于大市”评级。'
- `e14` 2026-09-06_dddc7cd0 page:3 ← company-028-claim-001#1（命中 20）
    - quote：'公司已推出激光开槽机9130 和激光隐切机9320。其中9130 主要用\n于Low-k 晶圆表面开槽，9320 主要用于超薄硅晶圆、碳化硅和氮化镓等第三代半\n导体材料及MEMS 器件的隐形切割。目前，两款设备均处于客户端验证阶段。'
- `e15` 2026-09-06_dddc7cd0 page:4 ← company-032-claim-001#0（命中 20）
    - quote：'公司已布\n局晶圆研磨机3230 和研磨抛光一体机3330，分别面向常规晶圆减薄和超薄晶圆\n加工，具有高稳定性超薄化加工的能力。目前相关产品正处于客户验证及样机测\n试阶段。'
- `e16` 2026-09-06_dddc7cd0 page:5 ← company-036-claim-001#1（命中 20）
    - quote：'子公司ADT 在刀片领域拥有\n长期技术和客户积累，产品已向全球客户供货。目前公司正在推进刀片国内产能\n爬坡，国产硬刀处于客户端验证阶段。'
- `e17` 2026-09-06_dddc7cd0 page:6 ← company-040-claim-001#1（命中 20）
    - quote：'2025 年，公司半导体封测装备制造\n业务实现收入3.62 亿元，同比增长31.16%，占营业收入的53.99%；相关装备销\n量达351 台（套），同比增长28.57%。'
- `e18` 2026-09-06_dddc7cd0 page:7 ← company-044-claim-001#0（命中 20）
    - quote：'赵彤宇直接持有公司32.60%股份，并通过其持股100%的宁波万丰隆贸\n易有限公司间接控制公司4.00%股份，合计控制公司36.60%股份。'
- `e19` 2026-09-06_dddc7cd0 page:7 ← company-044-claim-001#1（命中 20）
    - quote：'陈淑兰和赵彤\n亚分别持有公司1.70%和0.57%股份，虽与赵彤宇存在亲属关系，但未计入上述实\n际控制人控制比例。'
- `e20` 2026-09-06_dddc7cd0 page:9 ← company-052-claim-001#0（命中 20）
    - quote：'2018—2025 年，公司营业收入由2.54 亿元增长至6.70 亿元，CAGR 为\n14.9%'
- `e21` 2026-09-06_dddc7cd0 page:9 ← company-052-claim-001#1（命中 20）
    - quote：'2024 年受收入下降及商誉减值影响亏损1.13 亿元，2025 年归母净\n利润恢复至0.40 亿元、实现扭亏。'
- `e22` 2026-09-06_dddc7cd0 page:9 ← company-052-claim-001#2（命中 20）
    - quote：'2026 年上半\n年，公司综合毛利率为50.39%，同比下降6.87 个百分点，主要系毛利率相对较\n低的半导体装备业务收入占比快速提升。'
- `e23` 2026-09-06_dddc7cd0 page:9 ← company-052-claim-001#3（命中 20）
    - quote：'同期公司期间费用率由上年同期的50.64%下\n降至34.02%，其中销售、管理和研发费用率分别下降至12.50%、8.29%和12.21%'
- `e24` 2026-09-06_dddc7cd0 page:10 ← company-056-claim-001#0（命中 20）
    - quote：'2025 年公司研发费用为1.11 亿元，2026\n年上半年研发投入0.55 亿元，同比增长2.52%；在收入快速增长带动下，研发费\n用率由上年同期的18.72%下降至12.21%。'
- `e25` 2026-09-06_dddc7cd0 page:10 ← company-056-claim-001#1（命中 20）
    - quote：'ROE 进一步升至4.1%（未年化)'
- `e26` 2026-09-06_dddc7cd0 page:11 ← company-060-claim-001#0（命中 20）
    - quote：'2025 年全球半导体销售额达到7,956 亿美元，同比增长26.2%'
- `e27` 2026-09-06_dddc7cd0 page:11 ← company-060-claim-001#1（命中 20）
    - quote：'2025 年，全球硅晶圆\n出货量增长5.8%至129.73 亿平方英寸'
- `e28` 2026-09-06_dddc7cd0 page:11 ← company-060-claim-001#2（命中 20）
    - quote：'2026 年上半年，8230CF、\n82WT 等高端机型获得批量订单'

## company-004（company，partial）

- evidence_required：`true`
- 候选槽位：company-003-claim-001、company-018-claim-001、company-024-claim-001、company-028-claim-001、company-032-claim-001、company-036-claim-001、company-040-claim-001、company-044-claim-001、company-048-claim-001、company-052-claim-001、company-056-claim-001、company-060-claim-001
- `e1` 2026-09-06_dddc7cd0 page:1 ← company-018-claim-001#2（命中 8.84、12.06、15.81、9.38、18.09）
    - quote：'其设定的2026—2028 年的营业收入触发\n值和目标值分别为8.84/12.06/15.81 亿元（26-28 年同比增速为\n32%/36%/31% ）和9.38/13.4/18.09 亿元'
- **未命中 token（不得猜，待人工裁决）**：13.40

## company-005（company，mapped）

- evidence_required：`true`
- 候选槽位：company-003-claim-001、company-018-claim-001、company-024-claim-001、company-028-claim-001、company-032-claim-001、company-036-claim-001、company-040-claim-001、company-044-claim-001、company-048-claim-001、company-052-claim-001、company-056-claim-001、company-060-claim-001
- `e1` 2026-09-06_dddc7cd0 page:2 ← company-024-claim-001#2（命中 8230、8231）
    - quote：'主\n要包括12 英寸全自动双轴划片机8230、8231，半自动双轴划片机6230、6231，\n用于第三代半导体切割的6110'
- `e2` 2026-09-06_dddc7cd0 page:3 ← company-028-claim-001#0（命中 8230、8231）
    - quote：'8230 已在先进封装领域实现批量应用，8231 支持晶圆全切、DBG 半切\n及Edge Trimming 等工艺，并已形成正式订单。'
- `e3` 2026-09-06_dddc7cd0 page:3 ← company-028-claim-001#1（命中 9130、9320）
    - quote：'公司已推出激光开槽机9130 和激光隐切机9320。其中9130 主要用\n于Low-k 晶圆表面开槽，9320 主要用于超薄硅晶圆、碳化硅和氮化镓等第三代半\n导体材料及MEMS 器件的隐形切割。目前，两款设备均处于客户端验证阶段。'
- `e4` 2026-09-06_dddc7cd0 page:11 ← company-060-claim-001#2（命中 8230）
    - quote：'2026 年上半年，8230CF、\n82WT 等高端机型获得批量订单'

## company-006（company，mapped）

- evidence_required：`true`
- 候选槽位：company-003-claim-001、company-018-claim-001、company-024-claim-001、company-028-claim-001、company-032-claim-001、company-036-claim-001、company-040-claim-001、company-044-claim-001、company-048-claim-001、company-052-claim-001、company-056-claim-001、company-060-claim-001
- `e1` 2026-09-06_dddc7cd0 page:7 ← company-044-claim-001#0（命中 32.60%、4.00%、36.60%）
    - quote：'赵彤宇直接持有公司32.60%股份，并通过其持股100%的宁波万丰隆贸\n易有限公司间接控制公司4.00%股份，合计控制公司36.60%股份。'
- `e2` 2026-09-06_dddc7cd0 page:7 ← company-044-claim-001#1（命中 36.60%、1.70%、0.57%）
    - quote：'陈淑兰和赵彤\n亚分别持有公司1.70%和0.57%股份，虽与赵彤宇存在亲属关系，但未计入上述实\n际控制人控制比例。'

## company-007（company，mapped）

- evidence_required：`true`
- 候选槽位：company-001-claim-001、company-008-claim-001、company-013-claim-001
- `e1` 2026-08-16_6f14cc14 page:7 ← company-013-claim-001#0（命中 4.06%）
    - quote：'贵州茅台的控股股东茅台集团持有本公司的控股股东华创云信4.06%的股\n份。'

## company-008（company，unmapped）

- evidence_required：`true`
- 候选槽位：company-001-claim-001、company-003-claim-001、company-008-claim-001、company-013-claim-001、company-018-claim-001、company-024-claim-001、company-028-claim-001、company-032-claim-001、company-036-claim-001、company-040-claim-001、company-044-claim-001、company-048-claim-001、company-052-claim-001、company-056-claim-001、company-060-claim-001

## company-009（company，negative_opt_out）

- evidence_required：`false`
- 说明：负例题：其答案为『库中无答案』，不适用证据目标。按评分器契约显式 evidence_required=false；该例外有独立业务依据（负例任务本身即不得命中）

## company-010（company，negative_opt_out）

- evidence_required：`false`
- 说明：负例题：其答案为『库中无答案』，不适用证据目标。按评分器契约显式 evidence_required=false；该例外有独立业务依据（负例任务本身即不得命中）

## industry-001（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-009-claim-001、industry-020-claim-001
- `e1` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#0（命中 6、0.0%、2）
    - quote：'0.0%'
- `e2` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#1（命中 6、0.0%、2）
    - quote：'0.0%'
- `e3` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#2（命中 6、82.9%、2）
    - quote：'82.9%'
- `e4` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#3（命中 6、2）
    - quote：'99.6%'
- `e5` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#4（命中 6、2）
    - quote：'28.5'
- `e6` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#5（命中 6、2）
    - quote：'98.8%'
- `e7` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#6（命中 6、2）
    - quote：'89.9%'
- `e8` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#7（命中 6、2）
    - quote：'8068.0'
- `e9` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#8（命中 6、2）
    - quote：'注1：价格、价差分位为2016 年1 月1 日至2026 年7 月27 日'
- `e10` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#9（命中 6、2）
    - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
- `e11` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#10（命中 2）
    - quote：'注3：制冷剂R22、R32、R134a 的产能为配额'

## industry-002（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-009-claim-001、industry-020-claim-001
- `e1` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#0（命中 01、07、27）
    - quote：'0.0%'
- `e2` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#1（命中 01、07、27）
    - quote：'0.0%'
- `e3` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#3（命中 32、99.6%、3、01、07、27）
    - quote：'99.6%'
- `e4` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#4（命中 32、28.5、3）
    - quote：'28.5'
- `e5` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#5（命中 3、01、07、27）
    - quote：'98.8%'
- `e6` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#8（命中 01、07、27）
    - quote：'注1：价格、价差分位为2016 年1 月1 日至2026 年7 月27 日'
- `e7` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#10（命中 32、3）
    - quote：'注3：制冷剂R22、R32、R134a 的产能为配额'

## industry-003（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-009-claim-001、industry-020-claim-001
- `e1` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#6（命中 89.9%）
    - quote：'89.9%'
- `e2` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#7（命中 8068.0）
    - quote：'8068.0'

## industry-004（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-009-claim-001、industry-020-claim-001
- `e1` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#0（命中 01、07、27、26、1、6）
    - quote：'0.0%'
- `e2` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#1（命中 01、07、27、26、1、6）
    - quote：'0.0%'
- `e3` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#2（命中 26、1、6）
    - quote：'82.9%'
- `e4` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#3（命中 01、07、27、26、1、6）
    - quote：'99.6%'
- `e5` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#4（命中 26、6）
    - quote：'28.5'
- `e6` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#5（命中 01、07、27、26、1、6）
    - quote：'98.8%'
- `e7` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#6（命中 26、1、6）
    - quote：'89.9%'
- `e8` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#7（命中 26、6）
    - quote：'8068.0'
- `e9` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#8（命中 01、07、27、26、1、6）
    - quote：'注1：价格、价差分位为2016 年1 月1 日至2026 年7 月27 日'
- `e10` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#9（命中 26、1、6）
    - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
- `e11` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#10（命中 1）
    - quote：'注3：制冷剂R22、R32、R134a 的产能为配额'

## industry-005（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-057-claim-001
- `e1` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#4（命中 720、2459、240%）
    - quote：'截至9\n月2 日，氩气价格报2459 元/吨，相比5 月初的720 元/吨，在4 个月时间里涨\n幅超过240%'

## industry-006（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-057-claim-001
- `e1` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#2（命中 2027）
    - quote：'英伟达计划在NVSwitch\n板卡中使用PTFE 材料，并将该材料作为英伟达新一代服务器平台Rubin Ultra\n正交背板的主力选材。Rubin Ultra 预计于2027 年推出。'

## industry-007（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-057-claim-001
- `e1` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#0（命中 5611.65、4.2%）
    - quote：'Wind 新材料指数收报5611.65 点，环比下跌4.2%'
- `e2` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#1（命中 12576.94、9.12%）
    - quote：'申万三级行业半导体材料指数收报12576.94 点，环比下跌\n9.12%'

## industry-008（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-009-claim-001、industry-020-claim-001、industry-057-claim-001
- `e1` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#0（命中 01、07、27、2）
    - quote：'0.0%'
- `e2` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#1（命中 01、07、27、2）
    - quote：'0.0%'
- `e3` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#2（命中 9、2）
    - quote：'82.9%'
- `e4` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#3（命中 32、01、07、27、9、2）
    - quote：'99.6%'
- `e5` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#4（命中 32、5、2）
    - quote：'28.5'
- `e6` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#5（命中 01、07、27、9、2）
    - quote：'98.8%'
- `e7` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#6（命中 9、2）
    - quote：'89.9%'
- `e8` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#7（命中 2）
    - quote：'8068.0'
- `e9` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#8（命中 01、07、27、2）
    - quote：'注1：价格、价差分位为2016 年1 月1 日至2026 年7 月27 日'
- `e10` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#9（命中 2）
    - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
- `e11` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#10（命中 32、2）
    - quote：'注3：制冷剂R22、R32、R134a 的产能为配额'
- `e12` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#0（命中 5、9、2）
    - quote：'Wind 新材料指数收报5611.65 点，环比下跌4.2%'
- `e13` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#1（命中 5、9、2）
    - quote：'申万三级行业半导体材料指数收报12576.94 点，环比下跌\n9.12%'
- `e14` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#2（命中 27、2）
    - quote：'英伟达计划在NVSwitch\n板卡中使用PTFE 材料，并将该材料作为英伟达新一代服务器平台Rubin Ultra\n正交背板的主力选材。Rubin Ultra 预计于2027 年推出。'
- `e15` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#3（命中 2）
    - quote：'10GHz 条件下介电常数Dk=2.1，介质损耗Dk 低至0.0004'
- `e16` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#4（命中 5、720、9、2、2459）
    - quote：'截至9\n月2 日，氩气价格报2459 元/吨，相比5 月初的720 元/吨，在4 个月时间里涨\n幅超过240%'
- `e17` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#5（命中 9、2）
    - quote：'强于大市（维持评级）'

## industry-009（industry，negative_opt_out）

- evidence_required：`false`
- 说明：负例题：其答案为『库中无答案』，不适用证据目标。按评分器契约显式 evidence_required=false；该例外有独立业务依据（负例任务本身即不得命中）

## industry-010（industry，negative_opt_out）

- evidence_required：`false`
- 说明：负例题：其答案为『库中无答案』，不适用证据目标。按评分器契约显式 evidence_required=false；该例外有独立业务依据（负例任务本身即不得命中）

## macro-001（macro，mapped）

- evidence_required：`true`
- 候选槽位：macro-019-claim-001、macro-038-claim-001
- `e1` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#0（命中 8、16.2、5.6、7、2.3、2.1）
    - quote：'新增非农就业16.2\n万人，预期5.6 万人，前值由-2.3 万人修正为2.1 万人'
- `e2` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#1（命中 8）
    - quote：'8 月失业率4.1%，预期\n4.1%，前值4.1%；平均时薪同比升3.1%，预期升3.0%，前值升3.2%。'
- `e3` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#2（命中 8、7）
    - quote：'8 月劳动参与率为61.6%，高于上月的61.4%'

## macro-002（macro，mapped）

- evidence_required：`true`
- 候选槽位：macro-019-claim-001、macro-038-claim-001
- `e1` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#1（命中 4.1%、3.1%、3.2%）
    - quote：'8 月失业率4.1%，预期\n4.1%，前值4.1%；平均时薪同比升3.1%，预期升3.0%，前值升3.2%。'
- `e2` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#2（命中 61.6%、61.4%）
    - quote：'8 月劳动参与率为61.6%，高于上月的61.4%'

## macro-003（macro，mapped）

- evidence_required：`true`
- 候选槽位：macro-019-claim-001、macro-038-claim-001
- `e1` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#4（命中 60%）
    - quote：'在非农数据公布后，市场预期9 月加息的概\n率已经超过60%。'

## macro-004（macro，unmapped）

- evidence_required：`true`
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001

## macro-005（macro，mapped）

- evidence_required：`true`
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001
- `e1` 2026-09-06_cc03f55b page:1 ← macro-039-claim-001#2（命中 0.5%）
    - quote：'2026 年，预计\n两本账支出增速为-0.5%左右，仍低于名义GDP 增速。'
- `e2` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#2（命中 0.5%）
    - quote：'从消费倾向（消费/可支配收\n入）来看，2 季度，消费倾向为67.5%，低于2025 年同期的68.6%以及2019\n年同期的70.5%。'

## macro-006（macro，mapped）

- evidence_required：`true`
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001
- `e1` 2026-09-06_cc03f55b page:1 ← macro-039-claim-001#3（命中 4.6%、5.9%、6.1%、6.2%）
    - quote：'2025 年，央企样本企业的有息负\n债增速为4.6%，低于2024 年的5.9%。2025 年，地方国有企业样本企业的有\n息负债增速为6.1%，低于2024 年的6.2%。'

## macro-007（macro，mapped）

- evidence_required：`true`
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001
- `e1` 2026-09-06_cc03f55b page:1 ← macro-039-claim-001#2（命中 2）
    - quote：'2026 年，预计\n两本账支出增速为-0.5%左右，仍低于名义GDP 增速。'
- `e2` 2026-09-06_cc03f55b page:1 ← macro-039-claim-001#3（命中 2）
    - quote：'2025 年，央企样本企业的有息负\n债增速为4.6%，低于2024 年的5.9%。2025 年，地方国有企业样本企业的有\n息负债增速为6.1%，低于2024 年的6.2%。'
- `e3` 2026-09-06_cc03f55b page:1 ← macro-039-claim-001#4（命中 2）
    - quote：'2025 年，中国（使用全\n部A 股）为9.8%，美国（使用标普500 成分股）为20.4%，日本（使用日经\n225 成分股）为14.8%，韩国（使用KOSPI200 成分股）为26.7%。'
- `e4` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#0（命中 2）
    - quote：'1-6 月，本年施工项目计划总投资累计同比\n为-4.3%，本年新开工项目计划总投资增速为-29.4%。'
- `e5` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#1（命中 2）
    - quote：'2025 年，非\n金融企业人均薪酬增速为2.4%，低于2024 年的3.3%，以及2019 年的6.5%。'
- `e6` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#2（命中 2、67.5%、68.6%、70.5%）
    - quote：'从消费倾向（消费/可支配收\n入）来看，2 季度，消费倾向为67.5%，低于2025 年同期的68.6%以及2019\n年同期的70.5%。'
- `e7` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#3（命中 2、80.3%、83.7%、110.3%）
    - quote：'从支出倾向（消费叠加新房购房与可支配收入之比），2 季度\n为80.3%，低于2025 年同期的83.7%以及2019 年同期的110.3%。'

## macro-008（macro，mapped）

- evidence_required：`true`
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001
- `e1` 2026-09-06_cc03f55b page:1 ← macro-039-claim-001#2（命中 6）
    - quote：'2026 年，预计\n两本账支出增速为-0.5%左右，仍低于名义GDP 增速。'
- `e2` 2026-09-06_cc03f55b page:1 ← macro-039-claim-001#3（命中 1、6）
    - quote：'2025 年，央企样本企业的有息负\n债增速为4.6%，低于2024 年的5.9%。2025 年，地方国有企业样本企业的有\n息负债增速为6.1%，低于2024 年的6.2%。'
- `e3` 2026-09-06_cc03f55b page:1 ← macro-039-claim-001#4（命中 1、6）
    - quote：'2025 年，中国（使用全\n部A 股）为9.8%，美国（使用标普500 成分股）为20.4%，日本（使用日经\n225 成分股）为14.8%，韩国（使用KOSPI200 成分股）为26.7%。'
- `e4` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#0（命中 1、6、4.3%、29.4%）
    - quote：'1-6 月，本年施工项目计划总投资累计同比\n为-4.3%，本年新开工项目计划总投资增速为-29.4%。'
- `e5` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#1（命中 1、6）
    - quote：'2025 年，非\n金融企业人均薪酬增速为2.4%，低于2024 年的3.3%，以及2019 年的6.5%。'
- `e6` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#2（命中 1、6）
    - quote：'从消费倾向（消费/可支配收\n入）来看，2 季度，消费倾向为67.5%，低于2025 年同期的68.6%以及2019\n年同期的70.5%。'
- `e7` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#3（命中 1、6）
    - quote：'从支出倾向（消费叠加新房购房与可支配收入之比），2 季度\n为80.3%，低于2025 年同期的83.7%以及2019 年同期的110.3%。'

## macro-009（macro，negative_opt_out）

- evidence_required：`false`
- 说明：负例题：其答案为『库中无答案』，不适用证据目标。按评分器契约显式 evidence_required=false；该例外有独立业务依据（负例任务本身即不得命中）

## macro-010（macro，negative_opt_out）

- evidence_required：`false`
- 说明：负例题：其答案为『库中无答案』，不适用证据目标。按评分器契约显式 evidence_required=false；该例外有独立业务依据（负例任务本身即不得命中）
