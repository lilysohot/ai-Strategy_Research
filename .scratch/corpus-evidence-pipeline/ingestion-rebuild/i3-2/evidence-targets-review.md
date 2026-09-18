# I3-2 补料：证据目标候选（待 U 裁决）

- 生成时间：2026-09-18T15:04:04+08:00；规则版本：`evidence-mapping-3`
- 输入：`query-gold-frozen.jsonl` sha256=6f6c5a25d55b…、`source-gold-frozen.jsonl` sha256=c360a132ad63…
- 统计：mapped **20** ／ partial **1** ／ needs_human **3** ／ 负例显式不做证据评分 **6**；候选证据目标合计 **60** 条（30 题）

> 本文件是**机器建议**：证据来源全部是 I0A-4 人工标注槽位（reviewer=xyl），quote 为原文逐字子串；
> 未命中/无法判别一律登记不猜，交人工裁决；匹配过宽超护栏时显式降级为 needs_human。
> **裁决点**：EvidencePass 分母口径（逐 item 严／槽位聚合宽）由 U 在 I3-2 冻结时选定，本脚本不代决。

> 版本记录：v1（`evidence-mapping-1`）子串匹配致短 token 误命中（`20` 命中 `2026`，company-003 达 28 条）；v2（`evidence-mapping-2`）用连续汉字串当关键词（整句当词）；本版 v3 用数字边界匹配 + 无强 token 时显式交人工，历史产物保留为 `-v1`/`-v2` 后缀。

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
- 槽位聚合视图（宽口径）：company-001-claim-001×3、company-008-claim-001×1

## company-002（company，mapped）

- evidence_required：`true`
- 候选槽位：company-001-claim-001、company-008-claim-001、company-013-claim-001
- `e1` 2026-08-16_6f14cc14 page:1 ← company-008-claim-001#0（命中 922.8、1.3%、445.2、2.0%）
    - quote：'26H1 实现总收入922.8 亿元，同增1.3%，归母净利润\n445.2 亿元，同降2.0%。'
- `e2` 2026-08-16_6f14cc14 page:1 ← company-008-claim-001#1（命中 375.8、5.2%、172.7、6.9%）
    - quote：'单Q2 总收入375.8 亿元，同降5.2%，归母净利润\n172.7 亿元，同降6.9%。'
- 槽位聚合视图（宽口径）：company-008-claim-001×2

## company-003（company，mapped）

- evidence_required：`true`
- 候选槽位：company-003-claim-001、company-018-claim-001、company-024-claim-001、company-028-claim-001、company-032-claim-001、company-036-claim-001、company-040-claim-001、company-044-claim-001、company-048-claim-001、company-052-claim-001、company-056-claim-001、company-060-claim-001
- 页码提示（不参与匹配）：page:20
- `e1` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#0（命中 0.36）
    - quote：'0.36'
- `e2` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#2（命中 222）
    - quote：'(222)'
- `e3` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#3（命中 0.59）
    - quote：'0.59'
- `e4` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#5（命中 138）
    - quote：'(138)'
- `e5` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#6（命中 0.93）
    - quote：'0.93'
- `e6` 2026-09-06_dddc7cd0 page:20 ← company-003-claim-001#8（命中 17）
    - quote：'(17)'
- 槽位聚合视图（宽口径）：company-003-claim-001×6

## company-004（company，partial）

- evidence_required：`true`
- 候选槽位：company-003-claim-001、company-018-claim-001、company-024-claim-001、company-028-claim-001、company-032-claim-001、company-036-claim-001、company-040-claim-001、company-044-claim-001、company-048-claim-001、company-052-claim-001、company-056-claim-001、company-060-claim-001
- 说明：部分 token 未在人工标注槽位中找到承载 item（缺标注或需人工指定），补齐前该题证据分母不完整
- `e1` 2026-09-06_dddc7cd0 page:1 ← company-018-claim-001#2（命中 8.84、12.06、15.81、9.38、18.09）
    - quote：'其设定的2026—2028 年的营业收入触发\n值和目标值分别为8.84/12.06/15.81 亿元（26-28 年同比增速为\n32%/36%/31% ）和9.38/13.4/18.09 亿元'
- 槽位聚合视图（宽口径）：company-018-claim-001×1
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
- 槽位聚合视图（宽口径）：company-024-claim-001×1、company-028-claim-001×2、company-060-claim-001×1

## company-006（company，mapped）

- evidence_required：`true`
- 候选槽位：company-003-claim-001、company-018-claim-001、company-024-claim-001、company-028-claim-001、company-032-claim-001、company-036-claim-001、company-040-claim-001、company-044-claim-001、company-048-claim-001、company-052-claim-001、company-056-claim-001、company-060-claim-001
- `e1` 2026-09-06_dddc7cd0 page:7 ← company-044-claim-001#0（命中 32.60%、4.00%、36.60%）
    - quote：'赵彤宇直接持有公司32.60%股份，并通过其持股100%的宁波万丰隆贸\n易有限公司间接控制公司4.00%股份，合计控制公司36.60%股份。'
- `e2` 2026-09-06_dddc7cd0 page:7 ← company-044-claim-001#1（命中 36.60%、1.70%、0.57%）
    - quote：'陈淑兰和赵彤\n亚分别持有公司1.70%和0.57%股份，虽与赵彤宇存在亲属关系，但未计入上述实\n际控制人控制比例。'
- 槽位聚合视图（宽口径）：company-044-claim-001×2

## company-007（company，mapped）

- evidence_required：`true`
- 候选槽位：company-001-claim-001、company-008-claim-001、company-013-claim-001
- `e1` 2026-08-16_6f14cc14 page:7 ← company-013-claim-001#0（命中 4.06%）
    - quote：'贵州茅台的控股股东茅台集团持有本公司的控股股东华创云信4.06%的股\n份。'
- 槽位聚合视图（宽口径）：company-013-claim-001×1

## company-008（company，needs_human）

- evidence_required：`true`
- 候选槽位：company-001-claim-001、company-003-claim-001、company-008-claim-001、company-013-claim-001、company-018-claim-001、company-024-claim-001、company-028-claim-001、company-032-claim-001、company-036-claim-001、company-040-claim-001、company-044-claim-001、company-048-claim-001、company-052-claim-001、company-056-claim-001、company-060-claim-001
- 说明：evidence_requirement 中没有可判别的强数字 token（也没有弱 token）：纯定性题不猜，请人工从下方候选 item 预览中指定证据目标
- 候选 item 预览（供人工指定目标）：
    - company-001-claim-001#0（table_cell） '178,657'
    - company-001-claim-001#1（table_cell） '84,679'
    - company-001-claim-001#2（table_cell） '67.74'
    - company-001-claim-001#3（table_cell） '25,756'
    - company-001-claim-001#4（table_cell） '186,196'
    - company-001-claim-001#5（table_cell） '88,470'
    - company-001-claim-001#6（table_cell） '70.77'
    - company-001-claim-001#7（table_cell） '30,089'
    - company-001-claim-001#8（table_cell） '194,063'
    - company-001-claim-001#9（table_cell） '92,302'
    - company-001-claim-001#10（table_cell） '73.84'
    - company-001-claim-001#11（table_cell） '35,014'

## company-009（company，negative_opt_out）

- evidence_required：`false`
- 说明：负例题：答案为『库中无答案』，不适用证据目标，按评分器契约显式 evidence_required=false（该例外有独立业务依据，不得用于规避证据缺口）

## company-010（company，negative_opt_out）

- evidence_required：`false`
- 说明：负例题：答案为『库中无答案』，不适用证据目标，按评分器契约显式 evidence_required=false（该例外有独立业务依据，不得用于规避证据缺口）

## industry-001（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-009-claim-001、industry-020-claim-001
- `e1` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#0（命中 0.0%）
    - quote：'0.0%'
- `e2` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#1（命中 0.0%）
    - quote：'0.0%'
- `e3` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#2（命中 82.9%）
    - quote：'82.9%'
- 槽位聚合视图（宽口径）：industry-009-claim-001×3

## industry-002（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-009-claim-001、industry-020-claim-001
- `e1` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#0（命中 01、07、27）
    - quote：'0.0%'
- `e2` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#1（命中 01、07、27）
    - quote：'0.0%'
- `e3` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#3（命中 32、99.6%、01、07、27）
    - quote：'99.6%'
- `e4` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#4（命中 32、28.5）
    - quote：'28.5'
- `e5` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#5（命中 01、07、27）
    - quote：'98.8%'
- `e6` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#8（命中 01、07、27）
    - quote：'注1：价格、价差分位为2016 年1 月1 日至2026 年7 月27 日'
- `e7` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#10（命中 32）
    - quote：'注3：制冷剂R22、R32、R134a 的产能为配额'
- 槽位聚合视图（宽口径）：industry-009-claim-001×7

## industry-003（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-009-claim-001、industry-020-claim-001
- `e1` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#6（命中 89.9%）
    - quote：'89.9%'
- `e2` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#7（命中 8068.0）
    - quote：'8068.0'
- 槽位聚合视图（宽口径）：industry-009-claim-001×2

## industry-004（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-009-claim-001、industry-020-claim-001
- `e1` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#0（命中 01、07、27）
    - quote：'0.0%'
- `e2` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#1（命中 01、07、27）
    - quote：'0.0%'
- `e3` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#2（命中 26）
    - quote：'82.9%'
- `e4` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#3（命中 01、07、27）
    - quote：'99.6%'
- `e5` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#5（命中 01、07、27）
    - quote：'98.8%'
- `e6` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#6（命中 26）
    - quote：'89.9%'
- `e7` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#8（命中 01、07、27）
    - quote：'注1：价格、价差分位为2016 年1 月1 日至2026 年7 月27 日'
- `e8` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#9（命中 26）
    - quote：'注2：开工率数据为2026 年1 月1 日至2026 年7 月26 日取平均，或2026 年1 月至2026 年6 月取平均'
- 槽位聚合视图（宽口径）：industry-009-claim-001×8

## industry-005（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-057-claim-001
- `e1` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#4（命中 720、2459、240%）
    - quote：'截至9\n月2 日，氩气价格报2459 元/吨，相比5 月初的720 元/吨，在4 个月时间里涨\n幅超过240%'
- 槽位聚合视图（宽口径）：industry-057-claim-001×1

## industry-006（industry，needs_human）

- evidence_required：`true`
- 候选槽位：industry-057-claim-001
- 说明：evidence_requirement 中没有可判别的强数字 token（仅弱 token：2027）：纯定性题不猜，请人工从下方候选 item 预览中指定证据目标
- 候选 item 预览（供人工指定目标）：
    - industry-057-claim-001#0（value） 'Wind 新材料指数收报5611.65 点，环比下跌4.2%'
    - industry-057-claim-001#1（value） '申万三级行业半导体材料指数收报12576.94 点，环比下跌\n9.12%'
    - industry-057-claim-001#2（condition） '英伟达计划在NVSwitch\n板卡中使用PTFE 材料，并将该材料作为英伟达新一代服务器平台Rubin Ultra\n正交'
    - industry-057-claim-001#3（condition） '10GHz 条件下介电常数Dk=2.1，介质损耗Dk 低至0.0004'
    - industry-057-claim-001#4（value） '截至9\n月2 日，氩气价格报2459 元/吨，相比5 月初的720 元/吨，在4 个月时间里涨\n幅超过240%'
    - industry-057-claim-001#5（rating） '强于大市（维持评级）'

## industry-007（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-057-claim-001
- `e1` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#0（命中 5611.65、4.2%）
    - quote：'Wind 新材料指数收报5611.65 点，环比下跌4.2%'
- `e2` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#1（命中 12576.94、9.12%）
    - quote：'申万三级行业半导体材料指数收报12576.94 点，环比下跌\n9.12%'
- 槽位聚合视图（宽口径）：industry-057-claim-001×2

## industry-008（industry，mapped）

- evidence_required：`true`
- 候选槽位：industry-009-claim-001、industry-020-claim-001、industry-057-claim-001
- `e1` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#0（命中 01、07、27）
    - quote：'0.0%'
- `e2` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#1（命中 01、07、27）
    - quote：'0.0%'
- `e3` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#3（命中 32、01、07、27）
    - quote：'99.6%'
- `e4` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#4（命中 32）
    - quote：'28.5'
- `e5` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#5（命中 01、07、27）
    - quote：'98.8%'
- `e6` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#8（命中 01、07、27）
    - quote：'注1：价格、价差分位为2016 年1 月1 日至2026 年7 月27 日'
- `e7` 2026-08-13_174b6462 page:10 ← industry-009-claim-001#10（命中 32）
    - quote：'注3：制冷剂R22、R32、R134a 的产能为配额'
- `e8` 2026-09-06_f8e31696 page:1 ← industry-057-claim-001#4（命中 720、2459）
    - quote：'截至9\n月2 日，氩气价格报2459 元/吨，相比5 月初的720 元/吨，在4 个月时间里涨\n幅超过240%'
- 槽位聚合视图（宽口径）：industry-009-claim-001×7、industry-057-claim-001×1

## industry-009（industry，negative_opt_out）

- evidence_required：`false`
- 说明：负例题：答案为『库中无答案』，不适用证据目标，按评分器契约显式 evidence_required=false（该例外有独立业务依据，不得用于规避证据缺口）

## industry-010（industry，negative_opt_out）

- evidence_required：`false`
- 说明：负例题：答案为『库中无答案』，不适用证据目标，按评分器契约显式 evidence_required=false（该例外有独立业务依据，不得用于规避证据缺口）

## macro-001（macro，mapped）

- evidence_required：`true`
- 候选槽位：macro-019-claim-001、macro-038-claim-001
- `e1` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#0（命中 16.2、5.6、2.3、2.1）
    - quote：'新增非农就业16.2\n万人，预期5.6 万人，前值由-2.3 万人修正为2.1 万人'
- 槽位聚合视图（宽口径）：macro-038-claim-001×1

## macro-002（macro，mapped）

- evidence_required：`true`
- 候选槽位：macro-019-claim-001、macro-038-claim-001
- `e1` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#1（命中 4.1%、3.1%、3.2%）
    - quote：'8 月失业率4.1%，预期\n4.1%，前值4.1%；平均时薪同比升3.1%，预期升3.0%，前值升3.2%。'
- `e2` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#2（命中 61.6%、61.4%）
    - quote：'8 月劳动参与率为61.6%，高于上月的61.4%'
- 槽位聚合视图（宽口径）：macro-038-claim-001×2

## macro-003（macro，mapped）

- evidence_required：`true`
- 候选槽位：macro-019-claim-001、macro-038-claim-001
- `e1` 2026-09-06_793b3967 page:1 ← macro-038-claim-001#4（命中 60%）
    - quote：'在非农数据公布后，市场预期9 月加息的概\n率已经超过60%。'
- 槽位聚合视图（宽口径）：macro-038-claim-001×1

## macro-004（macro，needs_human）

- evidence_required：`true`
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001
- 说明：evidence_requirement 中没有可判别的强数字 token（也没有弱 token）：纯定性题不猜，请人工从下方候选 item 预览中指定证据目标
- 候选 item 预览（供人工指定目标）：
    - macro-039-claim-001#0（condition） '新动\n能（包括装备制造业、信息业、租赁和商务服务业），旧动能（地产、建筑、\n上游材料制造业）'
    - macro-039-claim-001#1（condition） '这五个主体分别是政府、准财政（如城投等）、企业、居民、海\n外。'
    - macro-039-claim-001#2（value） '2026 年，预计\n两本账支出增速为-0.5%左右，仍低于名义GDP 增速。'
    - macro-039-claim-001#3（value） '2025 年，央企样本企业的有息负\n债增速为4.6%，低于2024 年的5.9%。2025 年，地方国有企业样本企业的有'
    - macro-039-claim-001#4（value） '2025 年，中国（使用全\n部A 股）为9.8%，美国（使用标普500 成分股）为20.4%，日本（使用日经\n225 成'
    - macro-060-claim-001#0（value） '1-6 月，本年施工项目计划总投资累计同比\n为-4.3%，本年新开工项目计划总投资增速为-29.4%。'
    - macro-060-claim-001#1（value） '2025 年，非\n金融企业人均薪酬增速为2.4%，低于2024 年的3.3%，以及2019 年的6.5%。'
    - macro-060-claim-001#2（value） '从消费倾向（消费/可支配收\n入）来看，2 季度，消费倾向为67.5%，低于2025 年同期的68.6%以及2019\n年同'
    - macro-060-claim-001#3（value） '从支出倾向（消费叠加新房购房与可支配收入之比），2 季度\n为80.3%，低于2025 年同期的83.7%以及2019 年'
    - macro-060-claim-001#4（condition） '使用上市公司或者发债企业的数据代表性可能欠佳，获得的结论有\n一定的偏差。可能存在其他收敛路径。'

## macro-005（macro，mapped）

- evidence_required：`true`
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001
- `e1` 2026-09-06_cc03f55b page:1 ← macro-039-claim-001#2（命中 0.5%）
    - quote：'2026 年，预计\n两本账支出增速为-0.5%左右，仍低于名义GDP 增速。'
- 槽位聚合视图（宽口径）：macro-039-claim-001×1

## macro-006（macro，mapped）

- evidence_required：`true`
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001
- `e1` 2026-09-06_cc03f55b page:1 ← macro-039-claim-001#3（命中 4.6%、5.9%、6.1%、6.2%）
    - quote：'2025 年，央企样本企业的有息负\n债增速为4.6%，低于2024 年的5.9%。2025 年，地方国有企业样本企业的有\n息负债增速为6.1%，低于2024 年的6.2%。'
- 槽位聚合视图（宽口径）：macro-039-claim-001×1

## macro-007（macro，mapped）

- evidence_required：`true`
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001
- `e1` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#2（命中 67.5%、68.6%、70.5%）
    - quote：'从消费倾向（消费/可支配收\n入）来看，2 季度，消费倾向为67.5%，低于2025 年同期的68.6%以及2019\n年同期的70.5%。'
- `e2` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#3（命中 80.3%、83.7%、110.3%）
    - quote：'从支出倾向（消费叠加新房购房与可支配收入之比），2 季度\n为80.3%，低于2025 年同期的83.7%以及2019 年同期的110.3%。'
- 槽位聚合视图（宽口径）：macro-060-claim-001×2

## macro-008（macro，mapped）

- evidence_required：`true`
- 候选槽位：macro-020-claim-001、macro-039-claim-001、macro-060-claim-001
- `e1` 2026-09-06_cc03f55b page:2 ← macro-060-claim-001#0（命中 4.3%、29.4%）
    - quote：'1-6 月，本年施工项目计划总投资累计同比\n为-4.3%，本年新开工项目计划总投资增速为-29.4%。'
- 槽位聚合视图（宽口径）：macro-060-claim-001×1

## macro-009（macro，negative_opt_out）

- evidence_required：`false`
- 说明：负例题：答案为『库中无答案』，不适用证据目标，按评分器契约显式 evidence_required=false（该例外有独立业务依据，不得用于规避证据缺口）

## macro-010（macro，negative_opt_out）

- evidence_required：`false`
- 说明：负例题：答案为『库中无答案』，不适用证据目标，按评分器契约显式 evidence_required=false（该例外有独立业务依据，不得用于规避证据缺口）
