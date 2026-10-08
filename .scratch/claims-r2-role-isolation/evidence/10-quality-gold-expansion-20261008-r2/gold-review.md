# 非表格真实开发金标审阅 r2

状态：待人工语义裁定；尚未冻结。

本包评估指定目标的召回，并非两份材料的穷尽金标。额外正确输出须单独裁定，不自动计 FP。

数量：{"claims": 20, "material_items": 48, "material_relations": 24}

风险/条件按角色计数：{"claims": 0, "material_items": 21, "material_relations": 12}

这些记录存在关联，不代表独立风险场景数量。机械校验仅检查引文、字段和已声明规则，不能证明全部语义正确。

逐条在 JSON 的 review_status/adjudication 中填写终态、审核人、理由；修改附 before/after/reason。Markdown 由 JSON 生成。

I17 保留公司改口子项的原文歧义，不猜测内部 AND/OR。

## 条件组合

- opening_watch_position: ANY(NT-I42, NT-I13, NT-I43) → NT-I14
- stop_loss: ANY(NT-I15, NT-I17) → NT-I16

## claims

### NT-C01 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:621-855`

原文：当日价格 64.04 元

预期字段：factuality=actual；metric=close_price；period=2026-08-28；subject=工业富联；unit=元；value=64.04；attribution=报告作者引述的行情或中报数据；perspective=quoted_other；source_stance=reported；estimate_status=not_applicable；qualifier=exact_as_reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:621-855`：【实时数据层】mx-xuangu，行情日 2026-08-28
当日价格 64.04 元；涨跌 +0.28%；成交额 103.15 亿元；换手 0.80%；量比 1.66。52 周（2025.09.01–2026.08.28）高 84.95 / 低 46.70，相对位置约 45.3%。融资余额 79.81 亿。近 5 日收盘 60.40 → 60.15 → 60.57 → 63.86 → 64.04。8/27 英伟达财报次日约 +5.43%，8/28 把溢价吐掉。

`char:25-134`：基准：2026-08-28 收盘 64.04 元（mx-xuangu）。中报口径来自 2026-08-11 上交所半年报全文及 8/12 摘要（新浪指定披露镜像交叉）。本报告只对标的本身做独立判断，不针对任何已有仓位。

</details>

### NT-C02 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:146-469`

原文：扣非 229.84 亿

预期字段：factuality=actual；metric=adjusted_net_profit；period=2026H1；subject=工业富联；unit=亿元；value=229.84；attribution=报告作者引述的行情或中报数据；perspective=quoted_other；source_stance=reported；estimate_status=not_applicable；qualifier=exact_as_reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:146-469`：**持有 + 观望。** 中报的利润几乎是真的：扣非 229.84 亿同比 +97%，与归母 237.40 亿只差 7.56 亿非经常，不是「公允价值把标题顶起来」。但经营现金流 73.91 亿只盖住扣非的 0.32 倍，存货 1921 亿、应收 1275 亿，高营收已经变成营运资本。毛利率 7.15% 同比只加 0.55 个百分点，Q2 还从 Q1 的 7.35% 掉回 6.99%。现价 64.04 已从 6 月 84.95 回了约 25%，动 PE 26.76 在定价约 475 亿 26E——几乎是 H1 线性年化，没有把卖方 560–667 亿吃进去。不按 93–101 去追，也不因为一天没涨就把 AI 机柜出货 +3 倍写成证伪。

`char:25-134`：基准：2026-08-28 收盘 64.04 元（mx-xuangu）。中报口径来自 2026-08-11 上交所半年报全文及 8/12 摘要（新浪指定披露镜像交叉）。本报告只对标的本身做独立判断，不针对任何已有仓位。

</details>

### NT-C03 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:146-469`

原文：归母 237.40 亿

预期字段：factuality=actual；metric=parent_net_profit；period=2026H1；subject=工业富联；unit=亿元；value=237.4；attribution=报告作者引述的行情或中报数据；perspective=quoted_other；source_stance=reported；estimate_status=not_applicable；qualifier=exact_as_reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:146-469`：**持有 + 观望。** 中报的利润几乎是真的：扣非 229.84 亿同比 +97%，与归母 237.40 亿只差 7.56 亿非经常，不是「公允价值把标题顶起来」。但经营现金流 73.91 亿只盖住扣非的 0.32 倍，存货 1921 亿、应收 1275 亿，高营收已经变成营运资本。毛利率 7.15% 同比只加 0.55 个百分点，Q2 还从 Q1 的 7.35% 掉回 6.99%。现价 64.04 已从 6 月 84.95 回了约 25%，动 PE 26.76 在定价约 475 亿 26E——几乎是 H1 线性年化，没有把卖方 560–667 亿吃进去。不按 93–101 去追，也不因为一天没涨就把 AI 机柜出货 +3 倍写成证伪。

`char:25-134`：基准：2026-08-28 收盘 64.04 元（mx-xuangu）。中报口径来自 2026-08-11 上交所半年报全文及 8/12 摘要（新浪指定披露镜像交叉）。本报告只对标的本身做独立判断，不针对任何已有仓位。

</details>

### NT-C04 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:146-469`

原文：经营现金流 73.91 亿

预期字段：factuality=actual；metric=operating_cash_flow；period=2026H1；subject=工业富联；unit=亿元；value=73.91；attribution=报告作者引述的行情或中报数据；perspective=quoted_other；source_stance=reported；estimate_status=not_applicable；qualifier=exact_as_reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:146-469`：**持有 + 观望。** 中报的利润几乎是真的：扣非 229.84 亿同比 +97%，与归母 237.40 亿只差 7.56 亿非经常，不是「公允价值把标题顶起来」。但经营现金流 73.91 亿只盖住扣非的 0.32 倍，存货 1921 亿、应收 1275 亿，高营收已经变成营运资本。毛利率 7.15% 同比只加 0.55 个百分点，Q2 还从 Q1 的 7.35% 掉回 6.99%。现价 64.04 已从 6 月 84.95 回了约 25%，动 PE 26.76 在定价约 475 亿 26E——几乎是 H1 线性年化，没有把卖方 560–667 亿吃进去。不按 93–101 去追，也不因为一天没涨就把 AI 机柜出货 +3 倍写成证伪。

`char:25-134`：基准：2026-08-28 收盘 64.04 元（mx-xuangu）。中报口径来自 2026-08-11 上交所半年报全文及 8/12 摘要（新浪指定披露镜像交叉）。本报告只对标的本身做独立判断，不针对任何已有仓位。

</details>

### NT-C05 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:146-469`

原文：存货 1921 亿

预期字段：factuality=actual；metric=inventory；period=2026H1；subject=工业富联；unit=亿元；value=1921；attribution=报告作者引述的行情或中报数据；perspective=quoted_other；source_stance=reported；estimate_status=not_applicable；qualifier=exact_as_reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:146-469`：**持有 + 观望。** 中报的利润几乎是真的：扣非 229.84 亿同比 +97%，与归母 237.40 亿只差 7.56 亿非经常，不是「公允价值把标题顶起来」。但经营现金流 73.91 亿只盖住扣非的 0.32 倍，存货 1921 亿、应收 1275 亿，高营收已经变成营运资本。毛利率 7.15% 同比只加 0.55 个百分点，Q2 还从 Q1 的 7.35% 掉回 6.99%。现价 64.04 已从 6 月 84.95 回了约 25%，动 PE 26.76 在定价约 475 亿 26E——几乎是 H1 线性年化，没有把卖方 560–667 亿吃进去。不按 93–101 去追，也不因为一天没涨就把 AI 机柜出货 +3 倍写成证伪。

`char:25-134`：基准：2026-08-28 收盘 64.04 元（mx-xuangu）。中报口径来自 2026-08-11 上交所半年报全文及 8/12 摘要（新浪指定披露镜像交叉）。本报告只对标的本身做独立判断，不针对任何已有仓位。

</details>

### NT-C06 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:146-469`

原文：应收 1275 亿

预期字段：factuality=actual；metric=accounts_receivable；period=2026H1；subject=工业富联；unit=亿元；value=1275；attribution=报告作者引述的行情或中报数据；perspective=quoted_other；source_stance=reported；estimate_status=not_applicable；qualifier=exact_as_reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:146-469`：**持有 + 观望。** 中报的利润几乎是真的：扣非 229.84 亿同比 +97%，与归母 237.40 亿只差 7.56 亿非经常，不是「公允价值把标题顶起来」。但经营现金流 73.91 亿只盖住扣非的 0.32 倍，存货 1921 亿、应收 1275 亿，高营收已经变成营运资本。毛利率 7.15% 同比只加 0.55 个百分点，Q2 还从 Q1 的 7.35% 掉回 6.99%。现价 64.04 已从 6 月 84.95 回了约 25%，动 PE 26.76 在定价约 475 亿 26E——几乎是 H1 线性年化，没有把卖方 560–667 亿吃进去。不按 93–101 去追，也不因为一天没涨就把 AI 机柜出货 +3 倍写成证伪。

`char:25-134`：基准：2026-08-28 收盘 64.04 元（mx-xuangu）。中报口径来自 2026-08-11 上交所半年报全文及 8/12 摘要（新浪指定披露镜像交叉）。本报告只对标的本身做独立判断，不针对任何已有仓位。

</details>

### NT-C07 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:146-469`

原文：毛利率 7.15%

预期字段：factuality=actual；metric=gross_margin；period=2026H1；subject=工业富联；unit=%；value=7.15；attribution=报告作者引述的行情或中报数据；perspective=quoted_other；source_stance=reported；estimate_status=not_applicable；qualifier=exact_as_reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:146-469`：**持有 + 观望。** 中报的利润几乎是真的：扣非 229.84 亿同比 +97%，与归母 237.40 亿只差 7.56 亿非经常，不是「公允价值把标题顶起来」。但经营现金流 73.91 亿只盖住扣非的 0.32 倍，存货 1921 亿、应收 1275 亿，高营收已经变成营运资本。毛利率 7.15% 同比只加 0.55 个百分点，Q2 还从 Q1 的 7.35% 掉回 6.99%。现价 64.04 已从 6 月 84.95 回了约 25%，动 PE 26.76 在定价约 475 亿 26E——几乎是 H1 线性年化，没有把卖方 560–667 亿吃进去。不按 93–101 去追，也不因为一天没涨就把 AI 机柜出货 +3 倍写成证伪。

`char:25-134`：基准：2026-08-28 收盘 64.04 元（mx-xuangu）。中报口径来自 2026-08-11 上交所半年报全文及 8/12 摘要（新浪指定披露镜像交叉）。本报告只对标的本身做独立判断，不针对任何已有仓位。

</details>

### NT-C08 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:146-469`

原文：Q2 还从 Q1 的 7.35% 掉回 6.99%

预期字段：factuality=actual；metric=gross_margin；period=2026Q2；subject=工业富联；unit=%；value=6.99；attribution=报告作者引述的行情或中报数据；perspective=quoted_other；source_stance=reported；estimate_status=not_applicable；qualifier=exact_as_reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:146-469`：**持有 + 观望。** 中报的利润几乎是真的：扣非 229.84 亿同比 +97%，与归母 237.40 亿只差 7.56 亿非经常，不是「公允价值把标题顶起来」。但经营现金流 73.91 亿只盖住扣非的 0.32 倍，存货 1921 亿、应收 1275 亿，高营收已经变成营运资本。毛利率 7.15% 同比只加 0.55 个百分点，Q2 还从 Q1 的 7.35% 掉回 6.99%。现价 64.04 已从 6 月 84.95 回了约 25%，动 PE 26.76 在定价约 475 亿 26E——几乎是 H1 线性年化，没有把卖方 560–667 亿吃进去。不按 93–101 去追，也不因为一天没涨就把 AI 机柜出货 +3 倍写成证伪。

`char:25-134`：基准：2026-08-28 收盘 64.04 元（mx-xuangu）。中报口径来自 2026-08-11 上交所半年报全文及 8/12 摘要（新浪指定披露镜像交叉）。本报告只对标的本身做独立判断，不针对任何已有仓位。

</details>

### NT-C09 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:1393-1655`

原文：云计算 +75.7%

预期字段：factuality=actual；metric=cloud_computing_revenue_yoy；period=2026H1；subject=工业富联；unit=%；value=75.7；attribution=报告作者引述的行情或中报数据；perspective=quoted_other；source_stance=reported；estimate_status=not_applicable；qualifier=exact_as_reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:1393-1655`：【研报核心发现】卖方讲三条：CSP/GPU 机柜量、Rubin 卡位、CPO/高速网络。中报验证了量：云计算 +75.7%，CSP AI 服务器 +2.3 倍，GPU/ASIC 机柜出货 +3.2 / +3 倍，Q2 营收 3067.83 亿环比 +22%。冲突点：卖方爱用归母 +96% 和 26E 600 亿+，中报扣非虽然同步，但 OCF 只有 73.91 亿；Q2 毛利率环比 −0.36pct，并表 7% 的加工费没有变成「系统商」。框架站扣非、OCF 和毛利率，不站归母标题，也不站 90 元共识当明天的地板价。

`char:25-134`：基准：2026-08-28 收盘 64.04 元（mx-xuangu）。中报口径来自 2026-08-11 上交所半年报全文及 8/12 摘要（新浪指定披露镜像交叉）。本报告只对标的本身做独立判断，不针对任何已有仓位。

</details>

### NT-C10 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:1393-1655`

原文：Q2 营收 3067.83 亿环比 +22%

预期字段：factuality=actual；metric=revenue；period=2026Q2；subject=工业富联；unit=亿元；value=3067.83；attribution=报告作者引述的行情或中报数据；perspective=quoted_other；source_stance=reported；estimate_status=not_applicable；qualifier=exact_as_reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:1393-1655`：【研报核心发现】卖方讲三条：CSP/GPU 机柜量、Rubin 卡位、CPO/高速网络。中报验证了量：云计算 +75.7%，CSP AI 服务器 +2.3 倍，GPU/ASIC 机柜出货 +3.2 / +3 倍，Q2 营收 3067.83 亿环比 +22%。冲突点：卖方爱用归母 +96% 和 26E 600 亿+，中报扣非虽然同步，但 OCF 只有 73.91 亿；Q2 毛利率环比 −0.36pct，并表 7% 的加工费没有变成「系统商」。框架站扣非、OCF 和毛利率，不站归母标题，也不站 90 元共识当明天的地板价。

`char:25-134`：基准：2026-08-28 收盘 64.04 元（mx-xuangu）。中报口径来自 2026-08-11 上交所半年报全文及 8/12 摘要（新浪指定披露镜像交叉）。本报告只对标的本身做独立判断，不针对任何已有仓位。

</details>

### NT-C11 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[1]`

原文：29年NPO到10%

预期字段：factuality=forecast；metric=NPO_penetration；period=2029；subject=光模块行业；unit=%；value=10；attribution=讲者转述的未明确来源；perspective=quoted_other；source_stance=challenged；estimate_status=uncertain；qualifier=exact_as_reported

关键项：True；原因：必须同时保留预测数值与讲者质疑，避免把被质疑口径作为认可结论

<details><summary>完整必要语境</summary>

`body[1]`：有个OCS的快速看一下，渗透率反正都是吹牛的，都没准数的。29年NPO到10%，CPO到30%，可插拔主导70%。

</details>

### NT-C12 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[1]`

原文：CPO到30%

预期字段：factuality=forecast；metric=CPO_penetration；period=2029；subject=光模块行业；unit=%；value=30；attribution=讲者转述的未明确来源；perspective=quoted_other；source_stance=challenged；estimate_status=uncertain；qualifier=exact_as_reported

关键项：True；原因：必须同时保留预测数值与讲者质疑，避免把被质疑口径作为认可结论

<details><summary>完整必要语境</summary>

`body[1]`：有个OCS的快速看一下，渗透率反正都是吹牛的，都没准数的。29年NPO到10%，CPO到30%，可插拔主导70%。

</details>

### NT-C13 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[1]`

原文：可插拔主导70%

预期字段：factuality=forecast；metric=pluggable_share；period=2029；subject=光模块行业；unit=%；value=70；attribution=讲者转述的未明确来源；perspective=quoted_other；source_stance=challenged；estimate_status=uncertain；qualifier=exact_as_reported

关键项：True；原因：必须同时保留预测数值与讲者质疑，避免把被质疑口径作为认可结论

<details><summary>完整必要语境</summary>

`body[1]`：有个OCS的快速看一下，渗透率反正都是吹牛的，都没准数的。29年NPO到10%，CPO到30%，可插拔主导70%。

</details>

### NT-C14 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[3]`

原文：27年5万到10万个水平

预期字段：factuality=forecast；metric=CPO_shipments；period=2027；subject=光模块行业；unit=个；value=50000-100000；attribution=未署名材料中的预测；perspective=unknown；source_stance=reported；estimate_status=forecast；qualifier=exact_as_reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[3]`：互补关系非完全替代，然后这个东西也是反正也是吹牛的。27年合计的高速光模块两个是1.5亿只，这是需求得出的需求量，需求量没用，要交付量才有用。CPO主要在交换机侧，市场成熟度不高，预计26年很少，26年就忽略不计，27年5万到10万个水平，这是合理的。

</details>

### NT-C15 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[15]`

原文：我们3.2T预计将在27年三季度左右实现批量供应

预期字段：factuality=forecast；metric=3.2T_batch_supply；period=2027Q3；subject=材料所述公司；unit=status；value=batch_supply；attribution=未署名材料中的预测；perspective=unknown；source_stance=reported；estimate_status=forecast；qualifier=approximately

裁定提示：预测来源身份未可靠消歧；不得擅自归给旭创或其他具体企业。

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[15]`：二季度800G出货量未达市场预期的原因是什么？实际上这出货量主要原因是1.6T影响了800G，谁说的？这个不太对，那反正不是旭创的数字。3.2T看看行业，我们3.2T预计将在27年三季度左右实现批量供应，这是个预计的，预计到28年整个行业的出货量将达到500万只的水平。价格方面预计3.2T单价在1800美元左右，这是个比较早期的一些预计，可以先看看2.4T未来如何。2.4T 27年的出货量预期在200万只，这个是之前传的，也是200万只，这是可能的。到28年预计增长至300至500万只，这个就是金像电的这个产品。然后EML和硅光26年初是4比6，预计到年底是规划到65%比35%。

</details>

### NT-C16 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[15]`

原文：预计到28年整个行业的出货量将达到500万只的水平

预期字段：factuality=forecast；metric=3.2T_shipments；period=2028；subject=光模块行业；unit=只；value=5000000；attribution=未署名材料中的预测；perspective=unknown；source_stance=reported；estimate_status=forecast；qualifier=exact_as_reported

裁定提示：预测来源身份未可靠消歧；不得擅自归给旭创或其他具体企业。

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[15]`：二季度800G出货量未达市场预期的原因是什么？实际上这出货量主要原因是1.6T影响了800G，谁说的？这个不太对，那反正不是旭创的数字。3.2T看看行业，我们3.2T预计将在27年三季度左右实现批量供应，这是个预计的，预计到28年整个行业的出货量将达到500万只的水平。价格方面预计3.2T单价在1800美元左右，这是个比较早期的一些预计，可以先看看2.4T未来如何。2.4T 27年的出货量预期在200万只，这个是之前传的，也是200万只，这是可能的。到28年预计增长至300至500万只，这个就是金像电的这个产品。然后EML和硅光26年初是4比6，预计到年底是规划到65%比35%。

</details>

### NT-C17 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[15]`

原文：价格方面预计3.2T单价在1800美元左右

预期字段：factuality=forecast；metric=3.2T_unit_price；period=early_stage；subject=光模块行业；unit=美元；value=1800；attribution=未署名材料中的预测；perspective=unknown；source_stance=reported；estimate_status=early_estimate；qualifier=approximately

裁定提示：预测来源身份未可靠消歧；不得擅自归给旭创或其他具体企业。

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[15]`：二季度800G出货量未达市场预期的原因是什么？实际上这出货量主要原因是1.6T影响了800G，谁说的？这个不太对，那反正不是旭创的数字。3.2T看看行业，我们3.2T预计将在27年三季度左右实现批量供应，这是个预计的，预计到28年整个行业的出货量将达到500万只的水平。价格方面预计3.2T单价在1800美元左右，这是个比较早期的一些预计，可以先看看2.4T未来如何。2.4T 27年的出货量预期在200万只，这个是之前传的，也是200万只，这是可能的。到28年预计增长至300至500万只，这个就是金像电的这个产品。然后EML和硅光26年初是4比6，预计到年底是规划到65%比35%。

</details>

### NT-C18 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[15]`

原文：2.4T 27年的出货量预期在200万只

预期字段：factuality=forecast；metric=2.4T_shipments；period=2027；subject=2.4T产品（厂商口径不明）；unit=只；value=2000000；attribution=未署名材料中的预测；perspective=unknown；source_stance=reported；estimate_status=reported_rumor；qualifier=exact_as_reported

裁定提示：预测来源身份未可靠消歧；不得擅自归给旭创或其他具体企业。

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[15]`：二季度800G出货量未达市场预期的原因是什么？实际上这出货量主要原因是1.6T影响了800G，谁说的？这个不太对，那反正不是旭创的数字。3.2T看看行业，我们3.2T预计将在27年三季度左右实现批量供应，这是个预计的，预计到28年整个行业的出货量将达到500万只的水平。价格方面预计3.2T单价在1800美元左右，这是个比较早期的一些预计，可以先看看2.4T未来如何。2.4T 27年的出货量预期在200万只，这个是之前传的，也是200万只，这是可能的。到28年预计增长至300至500万只，这个就是金像电的这个产品。然后EML和硅光26年初是4比6，预计到年底是规划到65%比35%。

</details>

### NT-C19 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[15]`

原文：到28年预计增长至300至500万只

预期字段：factuality=forecast；metric=2.4T_shipments；period=2028；subject=2.4T产品（厂商口径不明）；unit=只；value=3000000-5000000；attribution=未署名材料中的预测；perspective=unknown；source_stance=reported；estimate_status=forecast；qualifier=exact_as_reported

裁定提示：预测来源身份未可靠消歧；不得擅自归给旭创或其他具体企业。

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[15]`：二季度800G出货量未达市场预期的原因是什么？实际上这出货量主要原因是1.6T影响了800G，谁说的？这个不太对，那反正不是旭创的数字。3.2T看看行业，我们3.2T预计将在27年三季度左右实现批量供应，这是个预计的，预计到28年整个行业的出货量将达到500万只的水平。价格方面预计3.2T单价在1800美元左右，这是个比较早期的一些预计，可以先看看2.4T未来如何。2.4T 27年的出货量预期在200万只，这个是之前传的，也是200万只，这是可能的。到28年预计增长至300至500万只，这个就是金像电的这个产品。然后EML和硅光26年初是4比6，预计到年底是规划到65%比35%。

</details>

### NT-C20 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[46]`

原文：今年下半年预计将有2到3个新客户开始贡献收入

预期字段：factuality=forecast；metric=new_revenue_contributing_customers；period=2026H2；subject=材料所述公司；unit=个；value=2-3；attribution=未署名材料中的预测；perspective=unknown；source_stance=reported；estimate_status=forecast；qualifier=exact_as_reported

裁定提示：预测来源身份未可靠消歧；不得擅自归给旭创或其他具体企业。

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[46]`：北美客户今年定位非常明确，就服务于顶级客户。今年下半年预计将有2到3个新客户开始贡献收入，这些主要是第二梯队。这里的相当于是一些新云，或者一些莫名其妙新增长出来的，就莫名其妙是那个奥特曼说的，对吧？他他说了你们这些莫名其妙新出来的这些客户，这些云，对不对？自己都还没搞清楚赚钱模式，什么应用也没有，就来投入云。你们莫名其妙，说的就是这些新客户。他那个采访反正他是有立场的，对吧？

`body[49]`：但是的确有一些可能性，这些前沿东西得关注，那些才是更重要的东西。目前反正是有新客户了，这些新的云不知道是什么原因。目前公司与这些新客户开展顺利，进入了小批量测试。到26年底这些新客户开始供应，供应占比合计能达到15%左右，那是一个比较有意义的体量了，不限于那四大了，还有四大加上NVIDIA，不限于这五家了。加上现有核心客户的业务，预计北美市场收入占比将达到85%左右。今年85%左右，还有15%是国内。

</details>


## material_items

### NT-I01 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:146-469`

原文：扣非 229.84 亿同比 +97%

预期字段：attribution=报告作者；polarity=affirmed；proposition=工业富联2026H1扣非净利润229.84亿元、同比增长97%；semantic_type=fact；statement_role=evidence；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:146-469`：**持有 + 观望。** 中报的利润几乎是真的：扣非 229.84 亿同比 +97%，与归母 237.40 亿只差 7.56 亿非经常，不是「公允价值把标题顶起来」。但经营现金流 73.91 亿只盖住扣非的 0.32 倍，存货 1921 亿、应收 1275 亿，高营收已经变成营运资本。毛利率 7.15% 同比只加 0.55 个百分点，Q2 还从 Q1 的 7.35% 掉回 6.99%。现价 64.04 已从 6 月 84.95 回了约 25%，动 PE 26.76 在定价约 475 亿 26E——几乎是 H1 线性年化，没有把卖方 560–667 亿吃进去。不按 93–101 去追，也不因为一天没涨就把 AI 机柜出货 +3 倍写成证伪。

</details>

### NT-I02 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:146-469`

原文：中报的利润几乎是真的

预期字段：attribution=报告作者；polarity=affirmed；proposition=工业富联中报利润质量较真实；semantic_type=opinion；statement_role=claim；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:146-469`：**持有 + 观望。** 中报的利润几乎是真的：扣非 229.84 亿同比 +97%，与归母 237.40 亿只差 7.56 亿非经常，不是「公允价值把标题顶起来」。但经营现金流 73.91 亿只盖住扣非的 0.32 倍，存货 1921 亿、应收 1275 亿，高营收已经变成营运资本。毛利率 7.15% 同比只加 0.55 个百分点，Q2 还从 Q1 的 7.35% 掉回 6.99%。现价 64.04 已从 6 月 84.95 回了约 25%，动 PE 26.76 在定价约 475 亿 26E——几乎是 H1 线性年化，没有把卖方 560–667 亿吃进去。不按 93–101 去追，也不因为一天没涨就把 AI 机柜出货 +3 倍写成证伪。

</details>

### NT-I03 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:146-469`

原文：经营现金流 73.91 亿只盖住扣非的 0.32 倍

预期字段：attribution=报告作者；polarity=affirmed；proposition=经营现金流仅覆盖扣非净利润0.32倍；semantic_type=fact；statement_role=evidence；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:146-469`：**持有 + 观望。** 中报的利润几乎是真的：扣非 229.84 亿同比 +97%，与归母 237.40 亿只差 7.56 亿非经常，不是「公允价值把标题顶起来」。但经营现金流 73.91 亿只盖住扣非的 0.32 倍，存货 1921 亿、应收 1275 亿，高营收已经变成营运资本。毛利率 7.15% 同比只加 0.55 个百分点，Q2 还从 Q1 的 7.35% 掉回 6.99%。现价 64.04 已从 6 月 84.95 回了约 25%，动 PE 26.76 在定价约 475 亿 26E——几乎是 H1 线性年化，没有把卖方 560–667 亿吃进去。不按 93–101 去追，也不因为一天没涨就把 AI 机柜出货 +3 倍写成证伪。

</details>

### NT-I04 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:2405-2625`

原文：现金质量相对扣非是差的

预期字段：attribution=报告作者；polarity=affirmed；proposition=工业富联现金质量相对扣非净利润较差；semantic_type=opinion；statement_role=risk；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:2405-2625`：少数股东 0.086 亿，几乎可忽略，所以「净利润 237.49 亿」和「归母 237.40 亿」不必像生益那样拆并表子公司。中期不分红、应付股利 130.52 亿是上年股利落账；筹资现金流 −86.61 亿里分配股利/利息 84.39 亿，现金在往外走的同时短贷在滚动（借 960 亿、还 951 亿）。审计结论：「利润质量相对扣非是干净的，现金质量相对扣非是差的；AI 放量把资产负债表做成了服务器厂的标准形状——存贷双高、保理托底。」

</details>

### NT-I05 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:1393-1655`

原文：云计算 +75.7%

预期字段：attribution=报告作者；polarity=affirmed；proposition=云计算业务增长75.7%；semantic_type=fact；statement_role=evidence；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:1393-1655`：【研报核心发现】卖方讲三条：CSP/GPU 机柜量、Rubin 卡位、CPO/高速网络。中报验证了量：云计算 +75.7%，CSP AI 服务器 +2.3 倍，GPU/ASIC 机柜出货 +3.2 / +3 倍，Q2 营收 3067.83 亿环比 +22%。冲突点：卖方爱用归母 +96% 和 26E 600 亿+，中报扣非虽然同步，但 OCF 只有 73.91 亿；Q2 毛利率环比 −0.36pct，并表 7% 的加工费没有变成「系统商」。框架站扣非、OCF 和毛利率，不站归母标题，也不站 90 元共识当明天的地板价。

</details>

### NT-I06 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:1393-1655`

原文：中报验证了量

预期字段：attribution=报告作者；polarity=affirmed；proposition=中报验证了AI相关业务的出货量增长；semantic_type=opinion；statement_role=claim；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:1393-1655`：【研报核心发现】卖方讲三条：CSP/GPU 机柜量、Rubin 卡位、CPO/高速网络。中报验证了量：云计算 +75.7%，CSP AI 服务器 +2.3 倍，GPU/ASIC 机柜出货 +3.2 / +3 倍，Q2 营收 3067.83 亿环比 +22%。冲突点：卖方爱用归母 +96% 和 26E 600 亿+，中报扣非虽然同步，但 OCF 只有 73.91 亿；Q2 毛利率环比 −0.36pct，并表 7% 的加工费没有变成「系统商」。框架站扣非、OCF 和毛利率，不站归母标题，也不站 90 元共识当明天的地板价。

</details>

### NT-I07 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:1393-1655`

原文：Q2 毛利率环比 −0.36pct

预期字段：attribution=报告作者；polarity=affirmed；proposition=2026Q2毛利率环比下降0.36个百分点；semantic_type=fact；statement_role=evidence；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:1393-1655`：【研报核心发现】卖方讲三条：CSP/GPU 机柜量、Rubin 卡位、CPO/高速网络。中报验证了量：云计算 +75.7%，CSP AI 服务器 +2.3 倍，GPU/ASIC 机柜出货 +3.2 / +3 倍，Q2 营收 3067.83 亿环比 +22%。冲突点：卖方爱用归母 +96% 和 26E 600 亿+，中报扣非虽然同步，但 OCF 只有 73.91 亿；Q2 毛利率环比 −0.36pct，并表 7% 的加工费没有变成「系统商」。框架站扣非、OCF 和毛利率，不站归母标题，也不站 90 元共识当明天的地板价。

</details>

### NT-I08 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:1393-1655`

原文：并表 7% 的加工费没有变成「系统商」

预期字段：attribution=报告作者；polarity=negated；proposition=当前毛利率没有证明工业富联已从加工费模式转变为系统商；semantic_type=opinion；statement_role=claim；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:1393-1655`：【研报核心发现】卖方讲三条：CSP/GPU 机柜量、Rubin 卡位、CPO/高速网络。中报验证了量：云计算 +75.7%，CSP AI 服务器 +2.3 倍，GPU/ASIC 机柜出货 +3.2 / +3 倍，Q2 营收 3067.83 亿环比 +22%。冲突点：卖方爱用归母 +96% 和 26E 600 亿+，中报扣非虽然同步，但 OCF 只有 73.91 亿；Q2 毛利率环比 −0.36pct，并表 7% 的加工费没有变成「系统商」。框架站扣非、OCF 和毛利率，不站归母标题，也不站 90 元共识当明天的地板价。

</details>

### NT-I09 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:3925-4239`

原文：一旦毛利率再掉或 Rubin 延期

预期字段：attribution=报告作者；condition=毛利率继续下降或Rubin延期；polarity=affirmed；proposition=估值风险触发条件；semantic_type=forecast；statement_role=condition；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:3925-4239`：看空：TTM 27 倍对 7% 毛利率的 EMS 并不便宜到「必须买」；贵的是「A 股唯一 NVIDIA 整柜代理」的叙事溢价，一旦毛利率再掉或 Rubin 延期，弹性会先打在倍数上。OCF/扣非 0.32 是已经发生的证伪，不是担心。Q2 毛利率环比已经为负。动 PE 隐含的 475 亿看起来「没给卖方 600」，但 475 本身就是把 H1 的 237 再做一次——如果 H2 只是季节性、Rubin 放量后移，475 不是地板。北向 H1 减持 8180 万股。目标价 93–101 用的是 2026 年 24–35 倍或 2027 年利润，不是 8 月能兑现的地板。高盛 121 是 IMA 标题，更不能当明天的价格。

</details>

### NT-I10 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:3925-4239`

原文：弹性会先打在倍数上

预期字段：attribution=报告作者；polarity=affirmed；proposition=估值倍数会先受到冲击；semantic_type=forecast；statement_role=risk；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:3925-4239`：看空：TTM 27 倍对 7% 毛利率的 EMS 并不便宜到「必须买」；贵的是「A 股唯一 NVIDIA 整柜代理」的叙事溢价，一旦毛利率再掉或 Rubin 延期，弹性会先打在倍数上。OCF/扣非 0.32 是已经发生的证伪，不是担心。Q2 毛利率环比已经为负。动 PE 隐含的 475 亿看起来「没给卖方 600」，但 475 本身就是把 H1 的 237 再做一次——如果 H2 只是季节性、Rubin 放量后移，475 不是地板。北向 H1 减持 8180 万股。目标价 93–101 用的是 2026 年 24–35 倍或 2027 年利润，不是 8 月能兑现的地板。高盛 121 是 IMA 标题，更不能当明天的价格。

</details>

### NT-I11 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:4659-4907`

原文：2025 年前五大 62%

预期字段：attribution=报告作者；polarity=affirmed；proposition=2025年前五大客户占比62%；semantic_type=fact；statement_role=evidence；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:4659-4907`：客户集中是结构风险：2025 年前五大 62%，H1 应收前五 68.52%。GPU 线绑英伟达节奏，ASIC 线绑少数 CSP。双供一旦发生，伤口不是「份额从叙事里的 50% 降到 45%」，而是整柜良率认证被别人拿走、自己变成备援。研发费用 −1.91%、费用率从约 1.41% 降到 0.90%（界面），利润改善来自规模和 mix 形容词，不是研发变现。中期不分红、回购上限只有年分红的一个量级零头（腾讯「十问」的评论口径），治理上要接受「鸿海体系的现金调度优先于 A 股自由现金流故事」。

</details>

### NT-I12 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:4659-4907`

原文：客户集中是结构风险

预期字段：attribution=报告作者；polarity=affirmed；proposition=客户集中构成结构性风险；semantic_type=opinion；statement_role=risk；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:4659-4907`：客户集中是结构风险：2025 年前五大 62%，H1 应收前五 68.52%。GPU 线绑英伟达节奏，ASIC 线绑少数 CSP。双供一旦发生，伤口不是「份额从叙事里的 50% 降到 45%」，而是整柜良率认证被别人拿走、自己变成备援。研发费用 −1.91%、费用率从约 1.41% 降到 0.90%（界面），利润改善来自规模和 mix 形容词，不是研发变现。中期不分红、回购上限只有年分红的一个量级零头（腾讯「十问」的评论口径），治理上要接受「鸿海体系的现金调度优先于 A 股自由现金流故事」。

</details>

### NT-I13 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:5246-5537`

原文：Q3 OCF/扣非回到 0.6 以上

预期字段：attribution=报告作者；condition=Q3 OCF/扣非净利润 >= 0.6；polarity=affirmed；proposition=Q3经营现金流与扣非净利润之比达到0.6以上，是重新讨论观察仓的条件之一；semantic_type=forecast；statement_role=condition；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

条件逻辑：`{"op": "compare", "metric": "OCF_to_adjusted_profit", "period": "Q3", "comparator": ">=", "value": "0.6", "unit": "ratio"}`

关键项：True；原因：遗漏会丢失关键条件、限制、行为意向或否定立场

<details><summary>完整必要语境</summary>

`char:5246-5537`：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。单票不超过组合的合理上限。止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5），或毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期。目标价不把 121、100.8 当锚；中性路径就是 55–75 消化中报和英伟达 β，乐观才靠近中金 77.68 / 华泰 93。

</details>

### NT-I14 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:5246-5537`

原文：若从零开一个观察仓：等两件事至少中一件再议

预期字段：attribution=报告作者；polarity=affirmed；proposition=从零开观察仓须等待至少一个指定条件满足后再讨论，并非立即建仓承诺；semantic_type=behavior；statement_role=claim；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported；behavior_status=intent；temporal_frame=contemporaneous

关键项：True；原因：遗漏会丢失关键条件、限制、行为意向或否定立场

<details><summary>完整必要语境</summary>

`char:5246-5537`：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。单票不超过组合的合理上限。止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5），或毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期。目标价不把 121、100.8 当锚；中性路径就是 55–75 消化中报和英伟达 β，乐观才靠近中金 77.68 / 华泰 93。

</details>

### NT-I15 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:5246-5537`

原文：止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5）

预期字段：attribution=报告作者；condition=下季 OCF/扣非净利润 < 0.5；polarity=affirmed；proposition=止损触发条件之一；semantic_type=forecast；statement_role=condition；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

条件逻辑：`{"op": "compare", "metric": "OCF_to_adjusted_profit", "period": "next_quarter", "comparator": "<", "value": "0.5", "unit": "ratio"}`

关键项：True；原因：遗漏会丢失关键条件、限制、行为意向或否定立场

<details><summary>完整必要语境</summary>

`char:5246-5537`：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。单票不超过组合的合理上限。止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5），或毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期。目标价不把 121、100.8 当锚；中性路径就是 55–75 消化中报和英伟达 β，乐观才靠近中金 77.68 / 华泰 93。

</details>

### NT-I16 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:5246-5537`

原文：止损看两条硬的

预期字段：attribution=报告作者；polarity=affirmed；proposition=若任一指定硬性恶化条件触发，考虑执行止损；这是意向而非已执行行为；semantic_type=behavior；statement_role=claim；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported；behavior_status=intent；temporal_frame=contemporaneous

关键项：True；原因：遗漏会丢失关键条件、限制、行为意向或否定立场

<details><summary>完整必要语境</summary>

`char:5246-5537`：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。单票不超过组合的合理上限。止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5），或毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期。目标价不把 121、100.8 当锚；中性路径就是 55–75 消化中报和英伟达 β，乐观才靠近中金 77.68 / 华泰 93。

</details>

### NT-I17 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:5246-5537`

原文：毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期

预期字段：attribution=报告作者；condition=毛利率相对6.99%下降>1个百分点 AND 公司改口“涨价/mix受阻、Rubin延期”（并列项内部逻辑未明）；polarity=affirmed；proposition=毛利率较6.99%再降超过1个百分点，且公司改口涨价/mix受阻、Rubin延期，是另一止损条件；semantic_type=forecast；statement_role=condition；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

条件逻辑：`{"op": "all", "args": [{"op": "compare", "metric": "gross_margin_change_from_baseline", "baseline": "6.99", "comparator": "<", "value": "-1", "unit": "percentage_points"}, {"op": "source_clause", "text": "公司改口说涨价/mix 受阻、Rubin 延期", "inner_operator": "unknown"}]}`

裁定提示：原文顿号未明确公司改口子项是 AND 还是 OR。保留原文，不将其中任一子项擅自作为充分条件。

明确未知：condition_inner_boolean

关键项：True；原因：遗漏会丢失关键条件、限制、行为意向或否定立场

<details><summary>完整必要语境</summary>

`char:5246-5537`：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。单票不超过组合的合理上限。止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5），或毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期。目标价不把 121、100.8 当锚；中性路径就是 55–75 消化中报和英伟达 β，乐观才靠近中金 77.68 / 华泰 93。

</details>

### NT-I19 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:4385-4657`

原文：出口管制一旦打到 GPU 系统集成

预期字段：attribution=报告作者；condition=出口管制影响GPU系统集成；polarity=affirmed；proposition=地理对冲失效的外部条件；semantic_type=forecast；statement_role=condition；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：True；原因：遗漏会丢失关键条件、限制、行为意向或否定立场

<details><summary>完整必要语境</summary>

`char:4385-4657`：最坏情景：Rubin / GB300 爬坡再延，CSP 把增量柜双供给广达 / 纬颖，FII 只能靠传统板和机构件填收入，毛利率从 7% 回到 6% 以下，存货继续堆，OCF 转负。次坏：云资本开支从「训练」切到「推理效率」，整柜需求还在但 ASP 不再上、Consignment 切换慢于申万假设，利润增速回到收入增速。再坏：美元短贷 + 汇兑再来一刀，或保理额度收紧，现金缺口被融资费用放大。实体清单本次没有 sourced 命中，但不能把「没搜到」当成「不会发生」；墨西哥 / 美国厂是地理对冲，救不了出口管制一旦打到 GPU 系统集成。

</details>

### NT-I20 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:4385-4657`

原文：墨西哥 / 美国厂是地理对冲，救不了出口管制

预期字段：attribution=报告作者；polarity=negated；proposition=墨西哥和美国工厂不能对冲GPU系统集成出口管制风险；semantic_type=opinion；statement_role=risk；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：True；原因：遗漏会丢失关键条件、限制、行为意向或否定立场

<details><summary>完整必要语境</summary>

`char:4385-4657`：最坏情景：Rubin / GB300 爬坡再延，CSP 把增量柜双供给广达 / 纬颖，FII 只能靠传统板和机构件填收入，毛利率从 7% 回到 6% 以下，存货继续堆，OCF 转负。次坏：云资本开支从「训练」切到「推理效率」，整柜需求还在但 ASP 不再上、Consignment 切换慢于申万假设，利润增速回到收入增速。再坏：美元短贷 + 汇兑再来一刀，或保理额度收紧，现金缺口被融资费用放大。实体清单本次没有 sourced 命中，但不能把「没搜到」当成「不会发生」；墨西哥 / 美国厂是地理对冲，救不了出口管制一旦打到 GPU 系统集成。

</details>

### NT-I21 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[3]`

原文：市场成熟度不高

预期字段：attribution=未署名讲者；polarity=affirmed；proposition=CPO市场成熟度不高；semantic_type=opinion；statement_role=evidence；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[3]`：互补关系非完全替代，然后这个东西也是反正也是吹牛的。27年合计的高速光模块两个是1.5亿只，这是需求得出的需求量，需求量没用，要交付量才有用。CPO主要在交换机侧，市场成熟度不高，预计26年很少，26年就忽略不计，27年5万到10万个水平，这是合理的。

</details>

### NT-I22 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[3]`

原文：预计26年很少，26年就忽略不计

预期字段：attribution=未署名讲者；polarity=affirmed；proposition=2026年CPO出货很少、可忽略不计；semantic_type=forecast；statement_role=claim；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[3]`：互补关系非完全替代，然后这个东西也是反正也是吹牛的。27年合计的高速光模块两个是1.5亿只，这是需求得出的需求量，需求量没用，要交付量才有用。CPO主要在交换机侧，市场成熟度不高，预计26年很少，26年就忽略不计，27年5万到10万个水平，这是合理的。

</details>

### NT-I23 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[63]`

原文：尚无固定的客户

预期字段：attribution=未署名讲者；polarity=negated；proposition=128端口产品尚无固定客户；semantic_type=fact；statement_role=risk；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[63]`：128是刚刚推出的，正在中心进行验证，对吧？中心是它的客户，尚无固定的客户，德科立将其视为一个过渡型的产品。因为mems主要是要用300，对吧？为什么用300？为什么要多？以前给你们讲特氟龙的时候都说过这个问题，对吧？就是要多。虽然NVIDIA可能对128有需求，但谷歌已经明确表示，如果要mems的话就要300以上。

</details>

### NT-I24 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[63]`

原文：德科立将其视为一个过渡型的产品

预期字段：attribution=材料转述的德科立；polarity=affirmed；proposition=128端口产品被视为过渡产品；semantic_type=opinion；statement_role=claim；perspective=quoted_other；speaker_ref=doc_dekeli；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[63]`：128是刚刚推出的，正在中心进行验证，对吧？中心是它的客户，尚无固定的客户，德科立将其视为一个过渡型的产品。因为mems主要是要用300，对吧？为什么用300？为什么要多？以前给你们讲特氟龙的时候都说过这个问题，对吧？就是要多。虽然NVIDIA可能对128有需求，但谷歌已经明确表示，如果要mems的话就要300以上。

</details>

### NT-I25 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[72]`

原文：128的光波导经过五个批次的流片后，良率仍然不乐观

预期字段：attribution=未署名讲者；polarity=affirmed；proposition=128端口光波导五次流片后良率仍不理想；semantic_type=fact；statement_role=risk；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[72]`：Mems相比光波导优势，这个以前都解释过，就稍微看看时延、功耗等等这些。既然光波导的方案优势明显，为何300还是要用mems？因为光波导还没做出来。他自称在全球上处于领先地位，理论仿真已经跑通了256端口的设计。在实际研发当中，128的光波导经过五个批次的流片后，良率仍然不乐观，尚未达到可以量产的阈值，说明设计上仍然存在缺陷，需要进一步调整，就是没进展。希望谷歌，希望德科立加快这个速度，以匹配其V8I的需求，这个需求是非常紧急的了。所以就要看你跑不跑得过，你自己如果跑不过，但是芯片是不能等你的，因为这里面不光有芯片，有博通，有台积电，你还有PCB，还有7788的所有的供应链，没法等你这一个。如果你这个出来就出来了，出不来只能用替代方案了。

</details>

### NT-I26 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[72]`

原文：说明设计上仍然存在缺陷

预期字段：attribution=未署名讲者；polarity=affirmed；proposition=128端口光波导设计仍有缺陷；semantic_type=opinion；statement_role=claim；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[72]`：Mems相比光波导优势，这个以前都解释过，就稍微看看时延、功耗等等这些。既然光波导的方案优势明显，为何300还是要用mems？因为光波导还没做出来。他自称在全球上处于领先地位，理论仿真已经跑通了256端口的设计。在实际研发当中，128的光波导经过五个批次的流片后，良率仍然不乐观，尚未达到可以量产的阈值，说明设计上仍然存在缺陷，需要进一步调整，就是没进展。希望谷歌，希望德科立加快这个速度，以匹配其V8I的需求，这个需求是非常紧急的了。所以就要看你跑不跑得过，你自己如果跑不过，但是芯片是不能等你的，因为这里面不光有芯片，有博通，有台积电，你还有PCB，还有7788的所有的供应链，没法等你这一个。如果你这个出来就出来了，出不来只能用替代方案了。

</details>

### NT-I27 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[43]`

原文：为期六个月的实验室认证

预期字段：attribution=未署名讲者；polarity=affirmed；proposition=剑桥送样通常需要六个月实验室认证；semantic_type=fact；statement_role=evidence；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[43]`：剑桥呢在送样方面，他们通常会经历一个为期六个月的实验室认证，之后再小批量。整个流程下来最终拿到订单可能需要1年到1年半时间。

</details>

### NT-I28 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[43]`

原文：最终拿到订单可能需要1年到1年半时间

预期字段：attribution=未署名讲者；polarity=affirmed；proposition=剑桥从送样到获得订单可能需要1年至1.5年；semantic_type=forecast；statement_role=claim；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[43]`：剑桥呢在送样方面，他们通常会经历一个为期六个月的实验室认证，之后再小批量。整个流程下来最终拿到订单可能需要1年到1年半时间。

</details>

### NT-I29 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[29]`

原文：因为政策原因导致成本的上升

预期字段：attribution=材料转述的公司；condition=政策变化导致成本上升；polarity=affirmed；proposition=启动提价协商的条件；semantic_type=forecast；statement_role=condition；perspective=quoted_other；speaker_ref=doc_quoted_company；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[29]`：面对潜在的政策变动，是否准备了涨价预案？有相应的预案，因为政策原因导致成本的上升，会与客户协商，提价幅度在10%到20%之间。为保障供应链的稳定和产能持续供应对客户而言至关重要，因此他们愿意承担部分增加的成本，对吧？部分肯定是可能的，大家谈一谈做生意都是这样。公司预计到27年市占率达到什么水平？这个也是那个协会的。但是这个肯定不是指的高速，高速显然不是这个比例，肯定是所有的光模块全算进去的。好的，27年公司的市占率将有显著提升。

</details>

### NT-I30 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[29]`

原文：会与客户协商，提价幅度在10%到20%之间

预期字段：attribution=材料转述的公司；polarity=affirmed；proposition=成本上升时计划与客户协商提价10%至20%；semantic_type=behavior；statement_role=claim；perspective=quoted_other；speaker_ref=doc_quoted_company；speech_role=statement；source_stance=reported；behavior_status=intent；temporal_frame=contemporaneous

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[29]`：面对潜在的政策变动，是否准备了涨价预案？有相应的预案，因为政策原因导致成本的上升，会与客户协商，提价幅度在10%到20%之间。为保障供应链的稳定和产能持续供应对客户而言至关重要，因此他们愿意承担部分增加的成本，对吧？部分肯定是可能的，大家谈一谈做生意都是这样。公司预计到27年市占率达到什么水平？这个也是那个协会的。但是这个肯定不是指的高速，高速显然不是这个比例，肯定是所有的光模块全算进去的。好的，27年公司的市占率将有显著提升。

</details>

### NT-I31 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[37]`

原文：北美的这些电力短缺

预期字段：attribution=未署名讲者；polarity=affirmed；proposition=北美数据中心存在电力短缺；semantic_type=fact；statement_role=risk；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[37]`：在CPO领域，探索目前尚未形成明确的结论方向，可插拔并没有成为主流，就是提出了可插拔CPO没有成为主流。长远的来看，可插拔仍有生命周期，预计到29年30年在材料取得重大突破前，可插拔仍然是主流，并且速度还有提升空间。主要群体北美的这些电力短缺的确会影响到公司出货节奏，所有的出货节奏都是环环相扣的。不可忽视的是，对数据中心客户来说，通过网络的提升远比服务器芯片、存储这些提升要来得大，对吧？这个是从去年开始就跟大家反复说了，网络这个点提升的性价比是最高的。资本开支受限的情况下，网络提升需求依然存在。这一定程度上可以对冲数据中心如果是放缓假设放缓的情况下带来的负面影响。这个观点我觉得是认可的。

</details>

### NT-I32 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[37]`

原文：会影响到公司出货节奏

预期字段：attribution=未署名讲者；polarity=affirmed；proposition=北美电力短缺会影响公司出货节奏；semantic_type=forecast；statement_role=risk；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[37]`：在CPO领域，探索目前尚未形成明确的结论方向，可插拔并没有成为主流，就是提出了可插拔CPO没有成为主流。长远的来看，可插拔仍有生命周期，预计到29年30年在材料取得重大突破前，可插拔仍然是主流，并且速度还有提升空间。主要群体北美的这些电力短缺的确会影响到公司出货节奏，所有的出货节奏都是环环相扣的。不可忽视的是，对数据中心客户来说，通过网络的提升远比服务器芯片、存储这些提升要来得大，对吧？这个是从去年开始就跟大家反复说了，网络这个点提升的性价比是最高的。资本开支受限的情况下，网络提升需求依然存在。这一定程度上可以对冲数据中心如果是放缓假设放缓的情况下带来的负面影响。这个观点我觉得是认可的。

</details>

### NT-I33 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[32]`

原文：CPO目前可以理解为还没有实际的出货

预期字段：attribution=未署名讲者；polarity=negated；proposition=CPO目前尚无实际出货；semantic_type=fact；statement_role=evidence；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[32]`：然后网络架构中scale out、scale up分别有哪些产品？200G scale up领域主要用NPO，NPO可以理解为一种没有外壳的可插拔光模块。2.4T产品用于scale up领域，3.2T则在scale out外面就是普通的光模块。CPO目前可以理解为还没有实际的出货，这个是真实情况。在CPO里面90%以上的价值由交换机芯片厂商，就是NVIDIA、台积电来主导。

</details>

### NT-I34 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[37]`

原文：预计到29年30年在材料取得重大突破前，可插拔仍然是主流

预期字段：attribution=未署名讲者；condition=材料尚未取得重大突破；polarity=affirmed；proposition=到2029至2030年可插拔方案仍将是主流；semantic_type=forecast；statement_role=claim；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：True；原因：遗漏会丢失关键条件、限制、行为意向或否定立场

<details><summary>完整必要语境</summary>

`body[37]`：在CPO领域，探索目前尚未形成明确的结论方向，可插拔并没有成为主流，就是提出了可插拔CPO没有成为主流。长远的来看，可插拔仍有生命周期，预计到29年30年在材料取得重大突破前，可插拔仍然是主流，并且速度还有提升空间。主要群体北美的这些电力短缺的确会影响到公司出货节奏，所有的出货节奏都是环环相扣的。不可忽视的是，对数据中心客户来说，通过网络的提升远比服务器芯片、存储这些提升要来得大，对吧？这个是从去年开始就跟大家反复说了，网络这个点提升的性价比是最高的。资本开支受限的情况下，网络提升需求依然存在。这一定程度上可以对冲数据中心如果是放缓假设放缓的情况下带来的负面影响。这个观点我觉得是认可的。

</details>

### NT-I35 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[115]`

原文：如果你所有的都选择相信，公司所有说的话每个公司你都选择相信

预期字段：attribution=未署名讲者；condition=无差别相信所有公司的份额陈述；polarity=affirmed；proposition=行业份额加总失真的前提；semantic_type=opinion；statement_role=condition；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[115]`：如果你所有的都选择相信，公司所有说的话每个公司你都选择相信。那最后加起来是不是会出现一个状态？什么状态？像当年机器人份额加起来超过100%，会不会出现这个状态？是不是一个罗生门，总是有人说得不对的了，不管他是主观的还是被动的，对不对？你说的加起来总不能超过100%。

</details>

### NT-I36 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[115]`

原文：像当年机器人份额加起来超过100%

预期字段：attribution=未署名讲者；polarity=affirmed；proposition=公司口径可能导致行业份额加总超过100%；semantic_type=opinion；statement_role=risk；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[115]`：如果你所有的都选择相信，公司所有说的话每个公司你都选择相信。那最后加起来是不是会出现一个状态？什么状态？像当年机器人份额加起来超过100%，会不会出现这个状态？是不是一个罗生门，总是有人说得不对的了，不管他是主观的还是被动的，对不对？你说的加起来总不能超过100%。

</details>

### NT-I37 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[51]`

原文：因为1.6T拉胯了

预期字段：attribution=未署名讲者；polarity=affirmed；proposition=讲者以1.6T出货不及预期解释800G的出货表现；semantic_type=opinion；statement_role=evidence；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[51]`：Q2 800G其实是超预期的，肯定是超预期的。但这也不叫超预期，就是因为1.6T拉胯了，不是DSP拉胯了，然后800G就明显比那个800G肯定不止。他说什么半年这个肯定数字不对，二季度就有超过300万个了。

</details>

### NT-I38 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[51]`

原文：Q2 800G其实是超预期的，肯定是超预期的。但这也不叫超预期

预期字段：attribution=未署名讲者；polarity=mixed；proposition=讲者先称800G超预期，随后限定这并非通常意义的超预期；semantic_type=opinion；statement_role=claim；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

裁定提示：保留同一讲者的自我修正，不能只取前半句判为无条件事实。

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[51]`：Q2 800G其实是超预期的，肯定是超预期的。但这也不叫超预期，就是因为1.6T拉胯了，不是DSP拉胯了，然后800G就明显比那个800G肯定不止。他说什么半年这个肯定数字不对，二季度就有超过300万个了。

</details>

### NT-I39 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[26]`

原文：这里面税率加上去

预期字段：attribution=未署名讲者；condition=海外产能税率增加；polarity=affirmed；proposition=成本转嫁风险的条件；semantic_type=forecast；statement_role=condition；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[26]`：长期来看，为规避风险，都在泰国布局产能，未来60%以上的将通过泰国或者台湾生产，由于台湾海鸥基地有免税政策，这部分会转嫁给客户，因此对竞争力和毛利影响不大。这句话是不对的，是电话会还是什么忘了。这个已经是免税，应该是最后的事情了，以后再往下就不免税了，你免了税还要按15%税率给你补上，以前都是零，前几年没有说是几年，可能是三年，反正之前几年是零，但是后面都是要算了，对吧？这个事情当时已经说过了，以后都是要算的，所以这部分是在强掰。然后这里面税率加上去，你转嫁给客户不一定能够很好地转嫁的。这个是你公司自己的供应商自己的问题，你不可能全部转嫁给客户的，只是要谈，没有说得这么容易。你如果转嫁了，对你的竞争力就会有影响，对不对？这是二者取其一的事情。

</details>

### NT-I40 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[26]`

原文：你转嫁给客户不一定能够很好地转嫁的

预期字段：attribution=未署名讲者；polarity=negated；proposition=新增税负未必能充分转嫁给客户；semantic_type=opinion；statement_role=risk；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：True；原因：遗漏会丢失关键条件、限制、行为意向或否定立场

<details><summary>完整必要语境</summary>

`body[26]`：长期来看，为规避风险，都在泰国布局产能，未来60%以上的将通过泰国或者台湾生产，由于台湾海鸥基地有免税政策，这部分会转嫁给客户，因此对竞争力和毛利影响不大。这句话是不对的，是电话会还是什么忘了。这个已经是免税，应该是最后的事情了，以后再往下就不免税了，你免了税还要按15%税率给你补上，以前都是零，前几年没有说是几年，可能是三年，反正之前几年是零，但是后面都是要算了，对吧？这个事情当时已经说过了，以后都是要算的，所以这部分是在强掰。然后这里面税率加上去，你转嫁给客户不一定能够很好地转嫁的。这个是你公司自己的供应商自己的问题，你不可能全部转嫁给客户的，只是要谈，没有说得这么容易。你如果转嫁了，对你的竞争力就会有影响，对不对？这是二者取其一的事情。

</details>

### NT-I41 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:5055-5071`

原文：持有 + 观望

预期字段：attribution=报告作者；polarity=affirmed；proposition=报告作者对工业富联的总体建议是持有加观望；semantic_type=opinion；statement_role=claim；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:5055-5071`：四选一：**持有 + 观望。**

</details>

### NT-I42 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:5246-5537`

原文：回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）

预期字段：attribution=报告作者；polarity=affirmed；proposition=股价回撤至52—58元且无新的大额负面管制公告，是重新讨论观察仓的条件之一；semantic_type=forecast；statement_role=condition；condition=52 <= 股价（元） <= 58 AND 无新的大额负面管制公告；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

条件逻辑：`{"op": "all", "args": [{"op": "range", "metric": "share_price", "lower": "52", "upper": "58", "bounds": "inclusive", "unit": "CNY"}, {"op": "source_clause", "text": "无新的大额负面管制公告"}]}`

裁定提示：原文“约低于回购均价61、动PE到24附近”保留为解释性背景，不新增独立硬门槛。

关键项：True；原因：遗漏会丢失关键条件、限制、行为意向或否定立场

<details><summary>完整必要语境</summary>

`char:5246-5537`：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。单票不超过组合的合理上限。止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5），或毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期。目标价不把 121、100.8 当锚；中性路径就是 55–75 消化中报和英伟达 β，乐观才靠近中金 77.68 / 华泰 93。

</details>

### NT-I43 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:5246-5537`

原文：毛利率较 Q2 的 6.99% 不再回吐

预期字段：attribution=报告作者；polarity=affirmed；proposition=毛利率不再低于Q2的6.99%，是重新讨论观察仓的条件之一；semantic_type=forecast；statement_role=condition；condition=毛利率 >= 6.99%；perspective=unknown；speaker_ref=md_author；speech_role=statement；source_stance=reported

条件逻辑：`{"op": "compare", "metric": "gross_margin", "comparator": ">=", "value": "6.99", "unit": "percent"}`

关键项：True；原因：遗漏会丢失关键条件、限制、行为意向或否定立场

<details><summary>完整必要语境</summary>

`char:5246-5537`：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。单票不超过组合的合理上限。止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5），或毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期。目标价不把 121、100.8 当锚；中性路径就是 55–75 消化中报和英伟达 β，乐观才靠近中金 77.68 / 华泰 93。

</details>

### NT-I44 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[1]`

原文：渗透率反正都是吹牛的，都没准数的

预期字段：attribution=未署名讲者；polarity=negated；proposition=讲者质疑所转述的渗透率预测，认为没有可靠数字；semantic_type=opinion；statement_role=claim；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：True；原因：遗漏会丢失关键条件、限制、行为意向或否定立场

<details><summary>完整必要语境</summary>

`body[1]`：有个OCS的快速看一下，渗透率反正都是吹牛的，都没准数的。29年NPO到10%，CPO到30%，可插拔主导70%。

</details>

### NT-I45 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[1]`

原文：29年NPO到10%

预期字段：attribution=讲者转述的未明确来源；polarity=affirmed；proposition=被转述预测称2029年NPO渗透率为10%；semantic_type=forecast；statement_role=claim；perspective=quoted_other；source_stance=challenged；estimate_status=uncertain；speaker_ref=doc_quoted_unknown；speech_role=statement

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[1]`：有个OCS的快速看一下，渗透率反正都是吹牛的，都没准数的。29年NPO到10%，CPO到30%，可插拔主导70%。

</details>

### NT-I46 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[1]`

原文：CPO到30%

预期字段：attribution=讲者转述的未明确来源；polarity=affirmed；proposition=被转述预测称2029年CPO渗透率为30%；semantic_type=forecast；statement_role=claim；perspective=quoted_other；source_stance=challenged；estimate_status=uncertain；speaker_ref=doc_quoted_unknown；speech_role=statement

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[1]`：有个OCS的快速看一下，渗透率反正都是吹牛的，都没准数的。29年NPO到10%，CPO到30%，可插拔主导70%。

</details>

### NT-I47 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[1]`

原文：可插拔主导70%

预期字段：attribution=讲者转述的未明确来源；polarity=affirmed；proposition=被转述预测称2029年可插拔份额为70%；semantic_type=forecast；statement_role=claim；perspective=quoted_other；source_stance=challenged；estimate_status=uncertain；speaker_ref=doc_quoted_unknown；speech_role=statement

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[1]`：有个OCS的快速看一下，渗透率反正都是吹牛的，都没准数的。29年NPO到10%，CPO到30%，可插拔主导70%。

</details>

### NT-I48 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[26]`

原文：由于台湾海鸥基地有免税政策，这部分会转嫁给客户，因此对竞争力和毛利影响不大

预期字段：attribution=讲者转述的未明确来源；polarity=affirmed；proposition=被转述观点认为税负可转嫁，对竞争力和毛利影响不大；semantic_type=opinion；statement_role=claim；perspective=quoted_other；source_stance=challenged；speaker_ref=doc_quoted_unknown；speech_role=statement

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[26]`：长期来看，为规避风险，都在泰国布局产能，未来60%以上的将通过泰国或者台湾生产，由于台湾海鸥基地有免税政策，这部分会转嫁给客户，因此对竞争力和毛利影响不大。这句话是不对的，是电话会还是什么忘了。这个已经是免税，应该是最后的事情了，以后再往下就不免税了，你免了税还要按15%税率给你补上，以前都是零，前几年没有说是几年，可能是三年，反正之前几年是零，但是后面都是要算了，对吧？这个事情当时已经说过了，以后都是要算的，所以这部分是在强掰。然后这里面税率加上去，你转嫁给客户不一定能够很好地转嫁的。这个是你公司自己的供应商自己的问题，你不可能全部转嫁给客户的，只是要谈，没有说得这么容易。你如果转嫁了，对你的竞争力就会有影响，对不对？这是二者取其一的事情。

</details>

### NT-I49 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[63]`

原文：因为mems主要是要用300

预期字段：attribution=未署名讲者；polarity=affirmed；proposition=讲者认为MEMS主要需要300端口；semantic_type=opinion；statement_role=evidence；perspective=unknown；speaker_ref=doc_narrator；speech_role=statement；source_stance=reported

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[63]`：128是刚刚推出的，正在中心进行验证，对吧？中心是它的客户，尚无固定的客户，德科立将其视为一个过渡型的产品。因为mems主要是要用300，对吧？为什么用300？为什么要多？以前给你们讲特氟龙的时候都说过这个问题，对吧？就是要多。虽然NVIDIA可能对128有需求，但谷歌已经明确表示，如果要mems的话就要300以上。

</details>


## material_relations

### NT-R01 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:146-469`

原文：中报的利润几乎是真的：扣非 229.84 亿同比 +97%

预期字段：from_gold_record_id=NT-I01；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I02

端点：工业富联2026H1扣非净利润229.84亿元、同比增长97% → 工业富联中报利润质量较真实

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:146-469`：**持有 + 观望。** 中报的利润几乎是真的：扣非 229.84 亿同比 +97%，与归母 237.40 亿只差 7.56 亿非经常，不是「公允价值把标题顶起来」。但经营现金流 73.91 亿只盖住扣非的 0.32 倍，存货 1921 亿、应收 1275 亿，高营收已经变成营运资本。毛利率 7.15% 同比只加 0.55 个百分点，Q2 还从 Q1 的 7.35% 掉回 6.99%。现价 64.04 已从 6 月 84.95 回了约 25%，动 PE 26.76 在定价约 475 亿 26E——几乎是 H1 线性年化，没有把卖方 560–667 亿吃进去。不按 93–101 去追，也不因为一天没涨就把 AI 机柜出货 +3 倍写成证伪。

</details>

### NT-R03 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:1393-1655`

原文：中报验证了量：云计算 +75.7%，CSP AI 服务器 +2.3 倍，GPU/ASIC 机柜出货 +3.2 / +3 倍

预期字段：from_gold_record_id=NT-I05；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I06

端点：云计算业务增长75.7% → 中报验证了AI相关业务的出货量增长

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:1393-1655`：【研报核心发现】卖方讲三条：CSP/GPU 机柜量、Rubin 卡位、CPO/高速网络。中报验证了量：云计算 +75.7%，CSP AI 服务器 +2.3 倍，GPU/ASIC 机柜出货 +3.2 / +3 倍，Q2 营收 3067.83 亿环比 +22%。冲突点：卖方爱用归母 +96% 和 26E 600 亿+，中报扣非虽然同步，但 OCF 只有 73.91 亿；Q2 毛利率环比 −0.36pct，并表 7% 的加工费没有变成「系统商」。框架站扣非、OCF 和毛利率，不站归母标题，也不站 90 元共识当明天的地板价。

</details>

### NT-R04 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:1393-1655`

原文：Q2 毛利率环比 −0.36pct，并表 7% 的加工费没有变成「系统商」

预期字段：from_gold_record_id=NT-I07；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I08

端点：2026Q2毛利率环比下降0.36个百分点 → 当前毛利率没有证明工业富联已从加工费模式转变为系统商

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:1393-1655`：【研报核心发现】卖方讲三条：CSP/GPU 机柜量、Rubin 卡位、CPO/高速网络。中报验证了量：云计算 +75.7%，CSP AI 服务器 +2.3 倍，GPU/ASIC 机柜出货 +3.2 / +3 倍，Q2 营收 3067.83 亿环比 +22%。冲突点：卖方爱用归母 +96% 和 26E 600 亿+，中报扣非虽然同步，但 OCF 只有 73.91 亿；Q2 毛利率环比 −0.36pct，并表 7% 的加工费没有变成「系统商」。框架站扣非、OCF 和毛利率，不站归母标题，也不站 90 元共识当明天的地板价。

</details>

### NT-R05 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:3925-4239`

原文：一旦毛利率再掉或 Rubin 延期，弹性会先打在倍数上

预期字段：from_gold_record_id=NT-I09；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I10

端点：估值风险触发条件 → 估值倍数会先受到冲击

关键项：True；原因：关系丢失会改变条件或讲者立场

<details><summary>完整必要语境</summary>

`char:3925-4239`：看空：TTM 27 倍对 7% 毛利率的 EMS 并不便宜到「必须买」；贵的是「A 股唯一 NVIDIA 整柜代理」的叙事溢价，一旦毛利率再掉或 Rubin 延期，弹性会先打在倍数上。OCF/扣非 0.32 是已经发生的证伪，不是担心。Q2 毛利率环比已经为负。动 PE 隐含的 475 亿看起来「没给卖方 600」，但 475 本身就是把 H1 的 237 再做一次——如果 H2 只是季节性、Rubin 放量后移，475 不是地板。北向 H1 减持 8180 万股。目标价 93–101 用的是 2026 年 24–35 倍或 2027 年利润，不是 8 月能兑现的地板。高盛 121 是 IMA 标题，更不能当明天的价格。

</details>

### NT-R06 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:4659-4907`

原文：客户集中是结构风险：2025 年前五大 62%，H1 应收前五 68.52%

预期字段：from_gold_record_id=NT-I11；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I12

端点：2025年前五大客户占比62% → 客户集中构成结构性风险

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`char:4659-4907`：客户集中是结构风险：2025 年前五大 62%，H1 应收前五 68.52%。GPU 线绑英伟达节奏，ASIC 线绑少数 CSP。双供一旦发生，伤口不是「份额从叙事里的 50% 降到 45%」，而是整柜良率认证被别人拿走、自己变成备援。研发费用 −1.91%、费用率从约 1.41% 降到 0.90%（界面），利润改善来自规模和 mix 形容词，不是研发变现。中期不分红、回购上限只有年分红的一个量级零头（腾讯「十问」的评论口径），治理上要接受「鸿海体系的现金调度优先于 A 股自由现金流故事」。

</details>

### NT-R07 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:5246-5537`

原文：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。

预期字段：from_gold_record_id=NT-I13；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I14

端点：Q3经营现金流与扣非净利润之比达到0.6以上，是重新讨论观察仓的条件之一 → 从零开观察仓须等待至少一个指定条件满足后再讨论，并非立即建仓承诺

关键项：True；原因：关系丢失会改变条件或讲者立场

<details><summary>完整必要语境</summary>

`char:5246-5537`：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。单票不超过组合的合理上限。止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5），或毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期。目标价不把 121、100.8 当锚；中性路径就是 55–75 消化中报和英伟达 β，乐观才靠近中金 77.68 / 华泰 93。

</details>

### NT-R08 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:5246-5537`

原文：止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5）

预期字段：from_gold_record_id=NT-I15；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I16

端点：止损触发条件之一 → 若任一指定硬性恶化条件触发，考虑执行止损；这是意向而非已执行行为

关键项：True；原因：关系丢失会改变条件或讲者立场

<details><summary>完整必要语境</summary>

`char:5246-5537`：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。单票不超过组合的合理上限。止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5），或毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期。目标价不把 121、100.8 当锚；中性路径就是 55–75 消化中报和英伟达 β，乐观才靠近中金 77.68 / 华泰 93。

</details>

### NT-R09 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:5246-5537`

原文：毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期

预期字段：from_gold_record_id=NT-I17；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I16

端点：毛利率较6.99%再降超过1个百分点，且公司改口涨价/mix受阻、Rubin延期，是另一止损条件 → 若任一指定硬性恶化条件触发，考虑执行止损；这是意向而非已执行行为

关键项：True；原因：关系丢失会改变条件或讲者立场

<details><summary>完整必要语境</summary>

`char:5246-5537`：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。单票不超过组合的合理上限。止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5），或毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期。目标价不把 121、100.8 当锚；中性路径就是 55–75 消化中报和英伟达 β，乐观才靠近中金 77.68 / 华泰 93。

</details>

### NT-R10 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:4385-4657`

原文：墨西哥 / 美国厂是地理对冲，救不了出口管制一旦打到 GPU 系统集成

预期字段：from_gold_record_id=NT-I19；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I20

端点：地理对冲失效的外部条件 → 墨西哥和美国工厂不能对冲GPU系统集成出口管制风险

关键项：True；原因：关系丢失会改变条件或讲者立场

<details><summary>完整必要语境</summary>

`char:4385-4657`：最坏情景：Rubin / GB300 爬坡再延，CSP 把增量柜双供给广达 / 纬颖，FII 只能靠传统板和机构件填收入，毛利率从 7% 回到 6% 以下，存货继续堆，OCF 转负。次坏：云资本开支从「训练」切到「推理效率」，整柜需求还在但 ASP 不再上、Consignment 切换慢于申万假设，利润增速回到收入增速。再坏：美元短贷 + 汇兑再来一刀，或保理额度收紧，现金缺口被融资费用放大。实体清单本次没有 sourced 命中，但不能把「没搜到」当成「不会发生」；墨西哥 / 美国厂是地理对冲，救不了出口管制一旦打到 GPU 系统集成。

</details>

### NT-R11 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[3]`

原文：CPO主要在交换机侧，市场成熟度不高，预计26年很少，26年就忽略不计

预期字段：from_gold_record_id=NT-I21；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I22

端点：CPO市场成熟度不高 → 2026年CPO出货很少、可忽略不计

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[3]`：互补关系非完全替代，然后这个东西也是反正也是吹牛的。27年合计的高速光模块两个是1.5亿只，这是需求得出的需求量，需求量没用，要交付量才有用。CPO主要在交换机侧，市场成熟度不高，预计26年很少，26年就忽略不计，27年5万到10万个水平，这是合理的。

</details>

### NT-R12 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[63]`

原文：德科立将其视为一个过渡型的产品。因为mems主要是要用300

预期字段：from_gold_record_id=NT-I49；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I24

端点：讲者认为MEMS主要需要300端口 → 128端口产品被视为过渡产品

裁定提示：原 R12 由相邻“尚无固定客户”推断支持关系不够明确；改用原文“因为MEMS主要要用300”的显式理由。

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[63]`：128是刚刚推出的，正在中心进行验证，对吧？中心是它的客户，尚无固定的客户，德科立将其视为一个过渡型的产品。因为mems主要是要用300，对吧？为什么用300？为什么要多？以前给你们讲特氟龙的时候都说过这个问题，对吧？就是要多。虽然NVIDIA可能对128有需求，但谷歌已经明确表示，如果要mems的话就要300以上。

</details>

### NT-R13 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[72]`

原文：128的光波导经过五个批次的流片后，良率仍然不乐观，尚未达到可以量产的阈值，说明设计上仍然存在缺陷

预期字段：from_gold_record_id=NT-I25；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I26

端点：128端口光波导五次流片后良率仍不理想 → 128端口光波导设计仍有缺陷

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[72]`：Mems相比光波导优势，这个以前都解释过，就稍微看看时延、功耗等等这些。既然光波导的方案优势明显，为何300还是要用mems？因为光波导还没做出来。他自称在全球上处于领先地位，理论仿真已经跑通了256端口的设计。在实际研发当中，128的光波导经过五个批次的流片后，良率仍然不乐观，尚未达到可以量产的阈值，说明设计上仍然存在缺陷，需要进一步调整，就是没进展。希望谷歌，希望德科立加快这个速度，以匹配其V8I的需求，这个需求是非常紧急的了。所以就要看你跑不跑得过，你自己如果跑不过，但是芯片是不能等你的，因为这里面不光有芯片，有博通，有台积电，你还有PCB，还有7788的所有的供应链，没法等你这一个。如果你这个出来就出来了，出不来只能用替代方案了。

</details>

### NT-R14 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[43]`

原文：为期六个月的实验室认证，之后再小批量。整个流程下来最终拿到订单可能需要1年到1年半时间

预期字段：from_gold_record_id=NT-I27；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I28

端点：剑桥送样通常需要六个月实验室认证 → 剑桥从送样到获得订单可能需要1年至1.5年

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[43]`：剑桥呢在送样方面，他们通常会经历一个为期六个月的实验室认证，之后再小批量。整个流程下来最终拿到订单可能需要1年到1年半时间。

</details>

### NT-R15 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[29]`

原文：因为政策原因导致成本的上升，会与客户协商，提价幅度在10%到20%之间

预期字段：from_gold_record_id=NT-I29；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I30

端点：启动提价协商的条件 → 成本上升时计划与客户协商提价10%至20%

关键项：True；原因：关系丢失会改变条件或讲者立场

<details><summary>完整必要语境</summary>

`body[29]`：面对潜在的政策变动，是否准备了涨价预案？有相应的预案，因为政策原因导致成本的上升，会与客户协商，提价幅度在10%到20%之间。为保障供应链的稳定和产能持续供应对客户而言至关重要，因此他们愿意承担部分增加的成本，对吧？部分肯定是可能的，大家谈一谈做生意都是这样。公司预计到27年市占率达到什么水平？这个也是那个协会的。但是这个肯定不是指的高速，高速显然不是这个比例，肯定是所有的光模块全算进去的。好的，27年公司的市占率将有显著提升。

</details>

### NT-R16 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[37]`

原文：北美的这些电力短缺的确会影响到公司出货节奏

预期字段：from_gold_record_id=NT-I31；provenance=source_explicit；relation=supports；to_gold_record_id=NT-I32

端点：北美数据中心存在电力短缺 → 北美电力短缺会影响公司出货节奏

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[37]`：在CPO领域，探索目前尚未形成明确的结论方向，可插拔并没有成为主流，就是提出了可插拔CPO没有成为主流。长远的来看，可插拔仍有生命周期，预计到29年30年在材料取得重大突破前，可插拔仍然是主流，并且速度还有提升空间。主要群体北美的这些电力短缺的确会影响到公司出货节奏，所有的出货节奏都是环环相扣的。不可忽视的是，对数据中心客户来说，通过网络的提升远比服务器芯片、存储这些提升要来得大，对吧？这个是从去年开始就跟大家反复说了，网络这个点提升的性价比是最高的。资本开支受限的情况下，网络提升需求依然存在。这一定程度上可以对冲数据中心如果是放缓假设放缓的情况下带来的负面影响。这个观点我觉得是认可的。

</details>

### NT-R18 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[115]`

原文：如果你所有的都选择相信，公司所有说的话每个公司你都选择相信。那最后加起来是不是会出现一个状态？什么状态？像当年机器人份额加起来超过100%

预期字段：from_gold_record_id=NT-I35；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I36

端点：行业份额加总失真的前提 → 公司口径可能导致行业份额加总超过100%

关键项：True；原因：关系丢失会改变条件或讲者立场

<details><summary>完整必要语境</summary>

`body[115]`：如果你所有的都选择相信，公司所有说的话每个公司你都选择相信。那最后加起来是不是会出现一个状态？什么状态？像当年机器人份额加起来超过100%，会不会出现这个状态？是不是一个罗生门，总是有人说得不对的了，不管他是主观的还是被动的，对不对？你说的加起来总不能超过100%。

</details>

### NT-R19 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[51]`

原文：Q2 800G其实是超预期的，肯定是超预期的。但这也不叫超预期，就是因为1.6T拉胯了

预期字段：from_gold_record_id=NT-I37；provenance=source_explicit；relation=elaborates；to_gold_record_id=NT-I38

端点：讲者以1.6T出货不及预期解释800G的出货表现 → 讲者先称800G超预期，随后限定这并非通常意义的超预期

关键项：False；原因：无

<details><summary>完整必要语境</summary>

`body[51]`：Q2 800G其实是超预期的，肯定是超预期的。但这也不叫超预期，就是因为1.6T拉胯了，不是DSP拉胯了，然后800G就明显比那个800G肯定不止。他说什么半年这个肯定数字不对，二季度就有超过300万个了。

</details>

### NT-R20 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[26]`

原文：这里面税率加上去，你转嫁给客户不一定能够很好地转嫁的

预期字段：from_gold_record_id=NT-I39；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I40

端点：成本转嫁风险的条件 → 新增税负未必能充分转嫁给客户

关键项：True；原因：关系丢失会改变条件或讲者立场

<details><summary>完整必要语境</summary>

`body[26]`：长期来看，为规避风险，都在泰国布局产能，未来60%以上的将通过泰国或者台湾生产，由于台湾海鸥基地有免税政策，这部分会转嫁给客户，因此对竞争力和毛利影响不大。这句话是不对的，是电话会还是什么忘了。这个已经是免税，应该是最后的事情了，以后再往下就不免税了，你免了税还要按15%税率给你补上，以前都是零，前几年没有说是几年，可能是三年，反正之前几年是零，但是后面都是要算了，对吧？这个事情当时已经说过了，以后都是要算的，所以这部分是在强掰。然后这里面税率加上去，你转嫁给客户不一定能够很好地转嫁的。这个是你公司自己的供应商自己的问题，你不可能全部转嫁给客户的，只是要谈，没有说得这么容易。你如果转嫁了，对你的竞争力就会有影响，对不对？这是二者取其一的事情。

</details>

### NT-R21 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:5246-5537`

原文：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。

预期字段：from_gold_record_id=NT-I42；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I14

端点：股价回撤至52—58元且无新的大额负面管制公告，是重新讨论观察仓的条件之一 → 从零开观察仓须等待至少一个指定条件满足后再讨论，并非立即建仓承诺

关键项：True；原因：关系丢失会改变条件或讲者立场

<details><summary>完整必要语境</summary>

`char:5246-5537`：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。单票不超过组合的合理上限。止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5），或毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期。目标价不把 121、100.8 当锚；中性路径就是 55–75 消化中报和英伟达 β，乐观才靠近中金 77.68 / 华泰 93。

</details>

### NT-R22 · pending

来源：data/corpus/工业富联_投委会决策报告_20260829.md；定位：`char:5246-5537`

原文：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。

预期字段：from_gold_record_id=NT-I43；provenance=source_explicit；relation=conditions；to_gold_record_id=NT-I14

端点：毛利率不再低于Q2的6.99%，是重新讨论观察仓的条件之一 → 从零开观察仓须等待至少一个指定条件满足后再讨论，并非立即建仓承诺

关键项：True；原因：关系丢失会改变条件或讲者立场

<details><summary>完整必要语境</summary>

`char:5246-5537`：若从零开一个观察仓：等两件事至少中一件再议——（1）回撤到 52–58（大约回到 7 月回购均价 61 之下、动 PE 降到 24 附近，且无新的大额负面管制公告）；（2）Q3 OCF/扣非回到 0.6 以上，或毛利率较 Q2 的 6.99% 不再回吐。单票不超过组合的合理上限。止损看两条硬的：下季 OCF 盖不住扣非的一半（OCF/扣非 < 0.5），或毛利率较 6.99% 再掉超过 1 个百分点且公司改口说涨价/mix 受阻、Rubin 延期。目标价不把 121、100.8 当锚；中性路径就是 55–75 消化中报和英伟达 β，乐观才靠近中金 77.68 / 华泰 93。

</details>

### NT-R23 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[1]`

原文：有个OCS的快速看一下，渗透率反正都是吹牛的，都没准数的。29年NPO到10%，CPO到30%，可插拔主导70%。

预期字段：from_gold_record_id=NT-I44；provenance=source_explicit；relation=challenges；to_gold_record_id=NT-I45

端点：讲者质疑所转述的渗透率预测，认为没有可靠数字 → 被转述预测称2029年NPO渗透率为10%

关键项：True；原因：关系丢失会改变条件或讲者立场

<details><summary>完整必要语境</summary>

`body[1]`：有个OCS的快速看一下，渗透率反正都是吹牛的，都没准数的。29年NPO到10%，CPO到30%，可插拔主导70%。

</details>

### NT-R24 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[1]`

原文：有个OCS的快速看一下，渗透率反正都是吹牛的，都没准数的。29年NPO到10%，CPO到30%，可插拔主导70%。

预期字段：from_gold_record_id=NT-I44；provenance=source_explicit；relation=challenges；to_gold_record_id=NT-I46

端点：讲者质疑所转述的渗透率预测，认为没有可靠数字 → 被转述预测称2029年CPO渗透率为30%

关键项：True；原因：关系丢失会改变条件或讲者立场

<details><summary>完整必要语境</summary>

`body[1]`：有个OCS的快速看一下，渗透率反正都是吹牛的，都没准数的。29年NPO到10%，CPO到30%，可插拔主导70%。

</details>

### NT-R25 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[1]`

原文：有个OCS的快速看一下，渗透率反正都是吹牛的，都没准数的。29年NPO到10%，CPO到30%，可插拔主导70%。

预期字段：from_gold_record_id=NT-I44；provenance=source_explicit；relation=challenges；to_gold_record_id=NT-I47

端点：讲者质疑所转述的渗透率预测，认为没有可靠数字 → 被转述预测称2029年可插拔份额为70%

关键项：True；原因：关系丢失会改变条件或讲者立场

<details><summary>完整必要语境</summary>

`body[1]`：有个OCS的快速看一下，渗透率反正都是吹牛的，都没准数的。29年NPO到10%，CPO到30%，可插拔主导70%。

</details>

### NT-R26 · pending

来源：data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx；定位：`body[26]`

原文：长期来看，为规避风险，都在泰国布局产能，未来60%以上的将通过泰国或者台湾生产，由于台湾海鸥基地有免税政策，这部分会转嫁给客户，因此对竞争力和毛利影响不大。这句话是不对的，是电话会还是什么忘了。这个已经是免税，应该是最后的事情了，以后再往下就不免税了，你免了税还要按15%税率给你补上，以前都是零，前几年没有说是几年，可能是三年，反正之前几年是零，但是后面都是要算了，对吧？这个事情当时已经说过了，以后都是要算的，所以这部分是在强掰。然后这里面税率加上去，你转嫁给客户不一定能够很好地转嫁的。这个是你公司自己的供应商自己的问题，你不可能全部转嫁给客户的，只是要谈，没有说得这么容易。你如果转嫁了，对你的竞争力就会有影响，对不对？这是二者取其一的事情。

预期字段：from_gold_record_id=NT-I40；provenance=source_explicit；relation=challenges；to_gold_record_id=NT-I48

端点：新增税负未必能充分转嫁给客户 → 被转述观点认为税负可转嫁，对竞争力和毛利影响不大

关键项：True；原因：关系丢失会改变条件或讲者立场

<details><summary>完整必要语境</summary>

`body[26]`：长期来看，为规避风险，都在泰国布局产能，未来60%以上的将通过泰国或者台湾生产，由于台湾海鸥基地有免税政策，这部分会转嫁给客户，因此对竞争力和毛利影响不大。这句话是不对的，是电话会还是什么忘了。这个已经是免税，应该是最后的事情了，以后再往下就不免税了，你免了税还要按15%税率给你补上，以前都是零，前几年没有说是几年，可能是三年，反正之前几年是零，但是后面都是要算了，对吧？这个事情当时已经说过了，以后都是要算的，所以这部分是在强掰。然后这里面税率加上去，你转嫁给客户不一定能够很好地转嫁的。这个是你公司自己的供应商自己的问题，你不可能全部转嫁给客户的，只是要谈，没有说得这么容易。你如果转嫁了，对你的竞争力就会有影响，对不对？这是二者取其一的事情。

</details>

## 已退出必答分母的 r1 记录

- NT-R02：system_inferred 不属于当前原文明示关系抽取契约；不进入必答分母。
- NT-R17：跨段系统推断不属于当前抽取契约；不进入必答分母。
- NT-I18：同一止损动作去重；R09 改为指向 I16。

## 人工签认

审核人：xyl
裁定人：xyl

签认对象包含 scoring-contract.json 的范围和匹配规则；签认后另建冻结包，本文件不自动冻结。
