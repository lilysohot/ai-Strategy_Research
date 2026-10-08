# 非表格真实开发金标人工审阅

日期：2026-10-08  
状态：待人工逐条确认；不是冻结金标

本审阅包只使用两份已批准开发材料的正文单元，表格全部排除，未访问留出，也尚未运行本专项候选。
只有审核人对每条记录作出接受/修改/拒绝终态，并另行生成不可变 freeze 后，才可写入正式质量分母。

## 数量

- Claims：20
- material_items：40
- material_relations：20
- 风险/条件记录：51
- 机械校验：valid_draft

## 审核方式

逐条核对引用、主体/期间/单位、事实或预测、观点归属、条件方向和关系方向。请在 JSON 中将
`review_status` 改为 `accepted`、`edited` 或 `rejected`；编辑时保留原值和裁定理由。不要直接修改
旧冻结包。全部完成后，在文末填写审核人、裁定人和日期，再生成新 freeze。

## Claims

### [ ] NT-C01

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:621-855`
- 原文：当日价格 64.04 元
- 语义：factuality=actual；metric=close_price；period=2026-08-28；subject=工业富联；unit=元；value=64.04
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C02

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:146-469`
- 原文：扣非 229.84 亿
- 语义：factuality=actual；metric=adjusted_net_profit；period=2026H1；subject=工业富联；unit=亿元；value=229.84
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C03

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:146-469`
- 原文：归母 237.40 亿
- 语义：factuality=actual；metric=parent_net_profit；period=2026H1；subject=工业富联；unit=亿元；value=237.40
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C04

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:146-469`
- 原文：经营现金流 73.91 亿
- 语义：factuality=actual；metric=operating_cash_flow；period=2026H1；subject=工业富联；unit=亿元；value=73.91
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C05

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:146-469`
- 原文：存货 1921 亿
- 语义：factuality=actual；metric=inventory；period=2026H1；subject=工业富联；unit=亿元；value=1921
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C06

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:146-469`
- 原文：应收 1275 亿
- 语义：factuality=actual；metric=accounts_receivable；period=2026H1；subject=工业富联；unit=亿元；value=1275
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C07

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:146-469`
- 原文：毛利率 7.15%
- 语义：factuality=actual；metric=gross_margin；period=2026H1；subject=工业富联；unit=%；value=7.15
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C08

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:146-469`
- 原文：Q2 还从 Q1 的 7.35% 掉回 6.99%
- 语义：factuality=actual；metric=gross_margin；period=2026Q2；subject=工业富联；unit=%；value=6.99
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C09

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:1393-1655`
- 原文：云计算 +75.7%
- 语义：factuality=actual；metric=cloud_computing_revenue_yoy；period=2026H1；subject=工业富联；unit=%；value=75.7
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C10

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:1393-1655`
- 原文：Q2 营收 3067.83 亿环比 +22%
- 语义：factuality=actual；metric=revenue；period=2026Q2；subject=工业富联；unit=亿元；value=3067.83
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C11

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[1]`
- 原文：29年NPO到10%
- 语义：factuality=forecast；metric=NPO_penetration；period=2029；subject=光模块行业；unit=%；value=10
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C12

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[1]`
- 原文：CPO到30%
- 语义：factuality=forecast；metric=CPO_penetration；period=2029；subject=光模块行业；unit=%；value=30
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C13

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[1]`
- 原文：可插拔主导70%
- 语义：factuality=forecast；metric=pluggable_share；period=2029；subject=光模块行业；unit=%；value=70
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C14

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[3]`
- 原文：27年5万到10万个水平
- 语义：factuality=forecast；metric=CPO_shipments；period=2027；subject=光模块行业；unit=个；value=50000-100000
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C15

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[15]`
- 原文：我们3.2T预计将在27年三季度左右实现批量供应
- 语义：factuality=forecast；metric=3.2T_batch_supply；period=2027Q3；subject=材料所述公司；unit=status；value=batch_supply
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C16

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[15]`
- 原文：预计到28年整个行业的出货量将达到500万只的水平
- 语义：factuality=forecast；metric=3.2T_shipments；period=2028；subject=光模块行业；unit=只；value=5000000
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C17

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[15]`
- 原文：价格方面预计3.2T单价在1800美元左右
- 语义：factuality=forecast；metric=3.2T_unit_price；period=early_stage；subject=光模块行业；unit=美元；value=1800
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C18

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[15]`
- 原文：2.4T 27年的出货量预期在200万只
- 语义：factuality=forecast；metric=2.4T_shipments；period=2027；subject=光模块行业；unit=只；value=2000000
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C19

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[15]`
- 原文：到28年预计增长至300至500万只
- 语义：factuality=forecast；metric=2.4T_shipments；period=2028；subject=光模块行业；unit=只；value=3000000-5000000
- 关键项：true；风险/条件：false
- 人工裁定：pending

### [ ] NT-C20

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[46]`
- 原文：今年下半年预计将有2到3个新客户开始贡献收入
- 语义：factuality=forecast；metric=new_revenue_contributing_customers；period=2026H2；subject=材料所述公司；unit=个；value=2-3
- 关键项：true；风险/条件：false
- 人工裁定：pending


## Material items

### [ ] NT-I01

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:146-469`
- 原文：扣非 229.84 亿同比 +97%
- 语义：attribution=报告作者；polarity=affirmed；proposition=工业富联2026H1扣非净利润229.84亿元、同比增长97%；semantic_type=fact；statement_role=evidence
- 关键项：false；风险/条件：false
- 人工裁定：pending

### [ ] NT-I02

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:146-469`
- 原文：中报的利润几乎是真的
- 语义：attribution=报告作者；polarity=affirmed；proposition=工业富联中报利润质量较真实；semantic_type=opinion；statement_role=claim
- 关键项：false；风险/条件：false
- 人工裁定：pending

### [ ] NT-I03

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:146-469`
- 原文：经营现金流 73.91 亿只盖住扣非的 0.32 倍
- 语义：attribution=报告作者；polarity=affirmed；proposition=经营现金流仅覆盖扣非净利润0.32倍；semantic_type=fact；statement_role=evidence
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I04

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:2405-2625`
- 原文：现金质量相对扣非是差的
- 语义：attribution=报告作者；polarity=affirmed；proposition=工业富联现金质量相对扣非净利润较差；semantic_type=opinion；statement_role=risk
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I05

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:1393-1655`
- 原文：云计算 +75.7%，CSP AI 服务器 +2.3 倍，GPU/ASIC 机柜出货 +3.2 / +3 倍
- 语义：attribution=报告作者；polarity=affirmed；proposition=云计算及AI服务器机柜出货高速增长；semantic_type=fact；statement_role=evidence
- 关键项：false；风险/条件：false
- 人工裁定：pending

### [ ] NT-I06

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:1393-1655`
- 原文：中报验证了量
- 语义：attribution=报告作者；polarity=affirmed；proposition=中报验证了AI相关业务的出货量增长；semantic_type=opinion；statement_role=claim
- 关键项：false；风险/条件：false
- 人工裁定：pending

### [ ] NT-I07

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:1393-1655`
- 原文：Q2 毛利率环比 −0.36pct
- 语义：attribution=报告作者；polarity=affirmed；proposition=2026Q2毛利率环比下降0.36个百分点；semantic_type=fact；statement_role=evidence
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I08

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:1393-1655`
- 原文：并表 7% 的加工费没有变成「系统商」
- 语义：attribution=报告作者；polarity=negated；proposition=当前毛利率没有证明工业富联已从加工费模式转变为系统商；semantic_type=opinion；statement_role=claim
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I09

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:3925-4239`
- 原文：一旦毛利率再掉或 Rubin 延期
- 语义：attribution=报告作者；condition=毛利率继续下降或Rubin延期；polarity=affirmed；proposition=估值风险触发条件；semantic_type=forecast；statement_role=condition
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I10

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:3925-4239`
- 原文：弹性会先打在倍数上
- 语义：attribution=报告作者；polarity=affirmed；proposition=估值倍数会先受到冲击；semantic_type=forecast；statement_role=risk
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I11

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:4659-4907`
- 原文：2025 年前五大 62%，H1 应收前五 68.52%
- 语义：attribution=报告作者；polarity=affirmed；proposition=客户及应收账款集中度较高；semantic_type=fact；statement_role=evidence
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I12

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:4659-4907`
- 原文：客户集中是结构风险
- 语义：attribution=报告作者；polarity=affirmed；proposition=客户集中构成结构性风险；semantic_type=opinion；statement_role=risk
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I13

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:5246-5537`
- 原文：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐
- 语义：attribution=报告作者；condition=Q3现金转换改善或毛利率不再下降；polarity=affirmed；proposition=重新评估观察仓的触发条件之一；semantic_type=forecast；statement_role=condition
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I14

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:5246-5537`
- 原文：等两件事至少中一件再议
- 语义：attribution=报告作者；polarity=affirmed；proposition=至少一个观察条件满足后再考虑建仓；semantic_type=behavior；statement_role=claim
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I15

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:5246-5537`
- 原文：止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5）
- 语义：attribution=报告作者；condition=下季OCF除以扣非净利润低于0.5；polarity=affirmed；proposition=止损触发条件之一；semantic_type=forecast；statement_role=condition
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I16

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:5246-5537`
- 原文：止损看两条硬的
- 语义：attribution=报告作者；polarity=affirmed；proposition=满足硬性恶化条件时执行止损；semantic_type=behavior；statement_role=claim
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I17

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:5246-5537`
- 原文：止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5），或毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期
- 语义：attribution=报告作者；condition=毛利率继续下降且公司确认涨价或产品结构受阻或Rubin延期；polarity=affirmed；proposition=止损触发条件之二；semantic_type=forecast；statement_role=condition
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I18

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:5246-5537`
- 原文：止损看两条硬的
- 语义：attribution=报告作者；polarity=affirmed；proposition=第二项硬性恶化条件同样触发止损；semantic_type=behavior；statement_role=claim
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I19

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:4385-4657`
- 原文：出口管制一旦打到 GPU 系统集成
- 语义：attribution=报告作者；condition=出口管制影响GPU系统集成；polarity=affirmed；proposition=地理对冲失效的外部条件；semantic_type=forecast；statement_role=condition
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I20

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:4385-4657`
- 原文：墨西哥 / 美国厂是地理对冲，救不了出口管制
- 语义：attribution=报告作者；polarity=negated；proposition=墨西哥和美国工厂不能对冲GPU系统集成出口管制风险；semantic_type=opinion；statement_role=risk
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I21

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[3]`
- 原文：CPO主要在交换机侧，市场成熟度不高
- 语义：attribution=未署名讲者；polarity=affirmed；proposition=CPO主要位于交换机侧且市场成熟度不高；semantic_type=opinion；statement_role=evidence
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I22

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[3]`
- 原文：预计26年很少，26年就忽略不计
- 语义：attribution=未署名讲者；polarity=affirmed；proposition=2026年CPO出货很少、可忽略不计；semantic_type=forecast；statement_role=claim
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I23

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[63]`
- 原文：尚无固定的客户
- 语义：attribution=未署名讲者；polarity=negated；proposition=128端口产品尚无固定客户；semantic_type=fact；statement_role=risk
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I24

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[63]`
- 原文：德科立将其视为一个过渡型的产品
- 语义：attribution=材料转述的德科立；polarity=affirmed；proposition=128端口产品被视为过渡产品；semantic_type=opinion；statement_role=claim
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I25

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[72]`
- 原文：128的光波导经过五个批次的流片后，良率仍然不乐观
- 语义：attribution=未署名讲者；polarity=affirmed；proposition=128端口光波导五次流片后良率仍不理想；semantic_type=fact；statement_role=risk
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I26

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[72]`
- 原文：说明设计上仍然存在缺陷，需要进一步调整
- 语义：attribution=未署名讲者；polarity=affirmed；proposition=光波导设计仍有缺陷并需要调整；semantic_type=opinion；statement_role=claim
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I27

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[43]`
- 原文：为期六个月的实验室认证
- 语义：attribution=未署名讲者；polarity=affirmed；proposition=剑桥送样通常需要六个月实验室认证；semantic_type=fact；statement_role=evidence
- 关键项：false；风险/条件：false
- 人工裁定：pending

### [ ] NT-I28

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[43]`
- 原文：最终拿到订单可能需要1年到1年半时间
- 语义：attribution=未署名讲者；polarity=affirmed；proposition=剑桥从送样到获得订单可能需要1年至1.5年；semantic_type=forecast；statement_role=claim
- 关键项：false；风险/条件：false
- 人工裁定：pending

### [ ] NT-I29

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[29]`
- 原文：因为政策原因导致成本的上升
- 语义：attribution=材料转述的公司；condition=政策变化导致成本上升；polarity=affirmed；proposition=启动提价协商的条件；semantic_type=forecast；statement_role=condition
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I30

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[29]`
- 原文：会与客户协商，提价幅度在10%到20%之间
- 语义：attribution=材料转述的公司；polarity=affirmed；proposition=成本上升时计划与客户协商提价10%至20%；semantic_type=behavior；statement_role=claim
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I31

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[37]`
- 原文：北美的这些电力短缺
- 语义：attribution=未署名讲者；polarity=affirmed；proposition=北美数据中心存在电力短缺；semantic_type=fact；statement_role=risk
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I32

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[37]`
- 原文：会影响到公司出货节奏
- 语义：attribution=未署名讲者；polarity=affirmed；proposition=北美电力短缺会影响公司出货节奏；semantic_type=forecast；statement_role=risk
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I33

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[32]`
- 原文：CPO目前可以理解为还没有实际的出货
- 语义：attribution=未署名讲者；polarity=negated；proposition=CPO目前尚无实际出货；semantic_type=fact；statement_role=evidence
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I34

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[37]`
- 原文：预计到29年30年在材料取得重大突破前，可插拔仍然是主流
- 语义：attribution=未署名讲者；condition=材料尚未取得重大突破；polarity=affirmed；proposition=到2029至2030年可插拔方案仍将是主流；semantic_type=forecast；statement_role=claim
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I35

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[115]`
- 原文：如果你所有的都选择相信，公司所有说的话每个公司你都选择相信
- 语义：attribution=未署名讲者；condition=无差别相信所有公司的份额陈述；polarity=affirmed；proposition=行业份额加总失真的前提；semantic_type=opinion；statement_role=condition
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I36

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[115]`
- 原文：像当年机器人份额加起来超过100%
- 语义：attribution=未署名讲者；polarity=affirmed；proposition=公司口径可能导致行业份额加总超过100%；semantic_type=opinion；statement_role=risk
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I37

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[51]`
- 原文：因为1.6T拉胯了
- 语义：attribution=未署名讲者；polarity=affirmed；proposition=1.6T出货不及预期是800G出货超预期的原因；semantic_type=fact；statement_role=evidence
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I38

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[51]`
- 原文：Q2 800G其实是超预期的
- 语义：attribution=未署名讲者；polarity=affirmed；proposition=Q2的800G出货超出预期；semantic_type=fact；statement_role=claim
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I39

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[26]`
- 原文：这里面税率加上去
- 语义：attribution=未署名讲者；condition=海外产能税率增加；polarity=affirmed；proposition=成本转嫁风险的条件；semantic_type=forecast；statement_role=condition
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-I40

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[26]`
- 原文：你转嫁给客户不一定能够很好地转嫁的
- 语义：attribution=未署名讲者；polarity=negated；proposition=新增税负未必能充分转嫁给客户；semantic_type=opinion；statement_role=risk
- 关键项：true；风险/条件：true
- 人工裁定：pending


## Material relations

### [ ] NT-R01

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:146-469`
- 原文：中报的利润几乎是真的：扣非 229.84 亿同比 +97%
- 语义：from_gold_record_id=NT-I01；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I02
- 关键项：false；风险/条件：false
- 人工裁定：pending

### [ ] NT-R02

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:146-469 + char:2405-2625`
- 原文：经营现金流 73.91 亿只盖住扣非的 0.32 倍；现金质量相对扣非是差的
- 语义：from_gold_record_id=NT-I03；provenance=system_inferred；relation=supports；to_gold_record_id=NT-I04
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R03

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:1393-1655`
- 原文：中报验证了量：云计算 +75.7%，CSP AI 服务器 +2.3 倍，GPU/ASIC 机柜出货 +3.2 / +3 倍
- 语义：from_gold_record_id=NT-I05；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I06
- 关键项：false；风险/条件：false
- 人工裁定：pending

### [ ] NT-R04

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:1393-1655`
- 原文：Q2 毛利率环比 −0.36pct，并表 7% 的加工费没有变成「系统商」
- 语义：from_gold_record_id=NT-I07；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I08
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R05

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:3925-4239`
- 原文：一旦毛利率再掉或 Rubin 延期，弹性会先打在倍数上
- 语义：from_gold_record_id=NT-I09；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I10
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R06

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:4659-4907`
- 原文：客户集中是结构风险：2025 年前五大 62%，H1 应收前五 68.52%
- 语义：from_gold_record_id=NT-I11；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I12
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R07

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:5246-5537`
- 原文：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。
- 语义：from_gold_record_id=NT-I13；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I14
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R08

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:5246-5537`
- 原文：止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5）
- 语义：from_gold_record_id=NT-I15；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I16
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R09

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:5246-5537`
- 原文：毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期
- 语义：from_gold_record_id=NT-I17；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I18
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R10

- 来源：`sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb`
- 定位：`char:4385-4657`
- 原文：墨西哥 / 美国厂是地理对冲，救不了出口管制一旦打到 GPU 系统集成
- 语义：from_gold_record_id=NT-I19；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I20
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R11

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[3]`
- 原文：CPO主要在交换机侧，市场成熟度不高，预计26年很少，26年就忽略不计
- 语义：from_gold_record_id=NT-I21；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I22
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R12

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[63]`
- 原文：尚无固定的客户，德科立将其视为一个过渡型的产品
- 语义：from_gold_record_id=NT-I23；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I24
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R13

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[72]`
- 原文：128的光波导经过五个批次的流片后，良率仍然不乐观，尚未达到可以量产的阈值，说明设计上仍然存在缺陷
- 语义：from_gold_record_id=NT-I25；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I26
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R14

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[43]`
- 原文：为期六个月的实验室认证，之后再小批量。整个流程下来最终拿到订单可能需要1年到1年半时间
- 语义：from_gold_record_id=NT-I27；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I28
- 关键项：false；风险/条件：false
- 人工裁定：pending

### [ ] NT-R15

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[29]`
- 原文：因为政策原因导致成本的上升，会与客户协商，提价幅度在10%到20%之间
- 语义：from_gold_record_id=NT-I29；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I30
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R16

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[37]`
- 原文：北美的这些电力短缺的确会影响到公司出货节奏
- 语义：from_gold_record_id=NT-I31；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I32
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R17

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[32] + body[37]`
- 原文：CPO目前可以理解为还没有实际的出货；预计到29年30年在材料取得重大突破前，可插拔仍然是主流
- 语义：from_gold_record_id=NT-I33；provenance=system_inferred；relation=supports；to_gold_record_id=NT-I34
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R18

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[115]`
- 原文：如果你所有的都选择相信，公司所有说的话每个公司你都选择相信。那最后加起来是不是会出现一个状态？什么状态？像当年机器人份额加起来超过100%
- 语义：from_gold_record_id=NT-I35；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I36
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R19

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[51]`
- 原文：Q2 800G其实是超预期的，肯定是超预期的。但这也不叫超预期，就是因为1.6T拉胯了
- 语义：from_gold_record_id=NT-I37；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I38
- 关键项：true；风险/条件：true
- 人工裁定：pending

### [ ] NT-R20

- 来源：`sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f`
- 定位：`body[26]`
- 原文：这里面税率加上去，你转嫁给客户不一定能够很好地转嫁的
- 语义：from_gold_record_id=NT-I39；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I40
- 关键项：true；风险/条件：true
- 人工裁定：pending

## 人工签认（全部逐条裁定后填写）

- 审核人：
- 争议裁定人：
- 签认日期：
- 是否确认本包在候选运行前完成：
- 是否确认未包含表格及留出：
