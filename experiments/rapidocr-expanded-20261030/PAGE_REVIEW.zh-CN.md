# RapidOCR small 逐页核对

主指标使用固定摘录和有记录的源文勘误。每页图片为识别前渲染；下列“匹配输出”是半全局编辑距离找到的最佳连续片段，可能含串列插入。非正文对照页不计算正文错误率。

| 页面 | 内容 | 原文类型 | 正文错误率 | 耗时 |
| --- | --- | --- | ---: | ---: |
| d001-p01 | 2026-08-12_2026.08.12-国泰海通-国内研报-国泰海通证券-ipo专题-新股精要-国内领先的电子材料和化工新材料生产企业贝特利-2594e01d.pdf 第1页 | native | 3.57% | 12.45s |
| d001-p03 | 2026-08-12_2026.08.12-国泰海通-国内研报-国泰海通证券-ipo专题-新股精要-国内领先的电子材料和化工新材料生产企业贝特利-2594e01d.pdf 第3页 | native | 0.00% | 12.80s |
| d002-p01 | 2026-08-13_2026.08.13-goldman-sachs-国外研报-高盛-贵州茅台-600519-sh-市场化改革方案六-全国42家直营店四款产品提价-维持-买入-评级-a1454167.pdf 第1页 | scan | 30.84% | 14.24s |
| d002-p02 | 2026-08-13_2026.08.13-goldman-sachs-国外研报-高盛-贵州茅台-600519-sh-市场化改革方案六-全国42家直营店四款产品提价-维持-买入-评级-a1454167.pdf 第2页 | scan | 非正文对照 | 19.66s |
| d002-p03 | 2026-08-13_2026.08.13-goldman-sachs-国外研报-高盛-贵州茅台-600519-sh-市场化改革方案六-全国42家直营店四款产品提价-维持-买入-评级-a1454167.pdf 第3页 | scan | 非正文对照 | 10.27s |
| d002-p04 | 2026-08-13_2026.08.13-goldman-sachs-国外研报-高盛-贵州茅台-600519-sh-市场化改革方案六-全国42家直营店四款产品提价-维持-买入-评级-a1454167.pdf 第4页 | scan | 0.00% | 10.13s |
| d005-p01 | 2026-08-16_2026.08.16-jpmorgan-摩根大通-中国人工智能-glm-5-3和deepseek的重新定价改变了能力成本前沿-raise-智谱minimax目标价-维持增持评级中性-b4d3b59b.pdf 第1页 | native | 9.94% | 12.52s |
| d021-p02 | 2026-09-06_2026.09.06-兴业证券-数据面面观-9月议息会议前的关键周-3e7710e1.pdf 第2页 | native | 0.00% | 9.98s |
| d021-p03 | 2026-09-06_2026.09.06-兴业证券-数据面面观-9月议息会议前的关键周-3e7710e1.pdf 第3页 | native | 0.00% | 8.54s |
| d035-p02 | 2026-09-06_2026.09.06-国联民生证券-宏观周度观察-中国汽车出海的欧洲考验-cac4f407.pdf 第2页 | native | 0.00% | 8.21s |
| d035-p05 | 2026-09-06_2026.09.06-国联民生证券-宏观周度观察-中国汽车出海的欧洲考验-cac4f407.pdf 第5页 | native | 0.00% | 8.44s |
| d035-p13 | 2026-09-06_2026.09.06-国联民生证券-宏观周度观察-中国汽车出海的欧洲考验-cac4f407.pdf 第13页 | native | 0.00% | 7.37s |
| d039-p01 | 2026-09-06_2026.09.06-国金证券-互联网行业研究-gpt-6-astra-fable-5-1正式发布-持续看好ai应用-247dc7fb.pdf 第1页 | native | 0.00% | 9.03s |
| d054-p01 | 2026-09-08_FundaAI_Deep台达电子2H26 重新加速在即VPD 仍被忽视.pdf 第1页 | native | 0.00% | 9.37s |
| d061-p01 | 2026-09-30_2026.09.30-国内研报-长江消费周周谈20260928-5f4db7fb.pdf 第1页 | scan | 0.00% | 8.58s |
| d061-p02 | 2026-09-30_2026.09.30-国内研报-长江消费周周谈20260928-5f4db7fb.pdf 第2页 | scan | 0.00% | 10.07s |
| d061-p03 | 2026-09-30_2026.09.30-国内研报-长江消费周周谈20260928-5f4db7fb.pdf 第3页 | scan | 2.04% | 9.74s |
| d061-p04 | 2026-09-30_2026.09.30-国内研报-长江消费周周谈20260928-5f4db7fb.pdf 第4页 | scan | 0.00% | 10.99s |
| d062-p02 | 2026-10-02_FundaAI_专栏  光通信FCC 光模块规则可能好于悲观预期对中国头部厂商的利好或超想象.pdf 第2页 | native | 2.11% | 14.48s |
| d064-p01 | 2026-10-21_前瞻_NOW_2026财年第三季度：调研反馈稳健，2027年展望.pdf 第1页 | native | 1.98% | 10.31s |
| d065-p03 | 2026-10-21_研究｜光互连：OCP_2026_预示_NPO_落地与替代铜缆带来.pdf 第3页 | native | 4.21% | 9.21s |
| d066-p01 | 【机构调研】这家底层芯片平台供应商业绩创历史同期新高.pdf 第1页 | scan | 0.58% | 9.58s |
| d067-p01 | 【电报解读】格芯与迈威尔共同推进下一代光学连接技术，机构称光.pdf 第1页 | scan | 0.00% | 8.87s |
| d068-p01 | 高盛：GS 贵州茅台：市场化方案五— 2026 年 7 月飞天茅台出厂价与建议零售价意外开启第二轮上调；买入.pdf 第1页 | scan | 34.62% | 13.68s |
| d068-p02 | 高盛：GS 贵州茅台：市场化方案五— 2026 年 7 月飞天茅台出厂价与建议零售价意外开启第二轮上调；买入.pdf 第2页 | scan | 非正文对照 | 18.80s |
| d068-p03 | 高盛：GS 贵州茅台：市场化方案五— 2026 年 7 月飞天茅台出厂价与建议零售价意外开启第二轮上调；买入.pdf 第3页 | scan | 0.00% | 11.28s |

## d001-p01

2026-08-12_2026.08.12-国泰海通-国内研报-国泰海通证券-ipo专题-新股精要-国内领先的电子材料和化工新材料生产企业贝特利-2594e01d.pdf，第1页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d001-p01.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d001-p01.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d001.pdf)

耗时 12.453s；采样峰值 647.1MiB；正文编辑数 4/112；缺失严格词项：无。

### 片段 1

参考：本次公开发行股票数量为6570.00万股，发行后总股本为26270.00万股，公开发行股份数量占公司本次公开发行后总股本的比例为25.01%。

OCR 匹配：本次公开发行股票数量为6570.00万股，发行相关报告后总股本为26270.00万股，公开发行股份数量占公司本次公开发行后总股本的比例为25.01%。

OCR 编辑距离 4；原生提取编辑距离 0。

### 片段 2

参考：2023~2025年公司营收和归母净利润复合增速分别为26.66%和16.42%。

OCR 匹配：2023~2025年公司营收和归母净利润复合增速分别为26.66%和16.42%。

OCR 编辑距离 0；原生提取编辑距离 0。

## d001-p03

2026-08-12_2026.08.12-国泰海通-国内研报-国泰海通证券-ipo专题-新股精要-国内领先的电子材料和化工新材料生产企业贝特利-2594e01d.pdf，第3页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d001-p03.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d001-p03.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d001.pdf)

耗时 12.803s；采样峰值 618.1MiB；正文编辑数 0/101；缺失严格词项：无。

### 片段 1

参考：2024年度，公司主营业务收入同比增长12.04%，主要受益于银价上涨带动的银粉销售收入增加以及2024年新增的HJT浆料收入。

OCR 匹配：2024年度，公司主营业务收入同比增长12.04%，主要受益于银价上涨带动的银粉销售收入增加以及2024年新增的HJT浆料收入。

OCR 编辑距离 0；原生提取编辑距离 0。

### 片段 2

参考：2024年度和2025年度，HJT浆料毛利率为11.47%和16.52%。

OCR 匹配：2024年度和2025年度，HJT浆料毛利率为11.47%和16.52%。

OCR 编辑距离 0；原生提取编辑距离 0。

## d002-p01

2026-08-13_2026.08.13-goldman-sachs-国外研报-高盛-贵州茅台-600519-sh-市场化改革方案六-全国42家直营店四款产品提价-维持-买入-评级-a1454167.pdf，第1页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d002-p01.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d002-p01.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d002.pdf)

耗时 14.244s；采样峰值 651.5MiB；正文编辑数 99/321；缺失严格词项：无。

### 片段 1

参考：Kweichow Moutai’s share price reacted positively on Aug 10 by 3% post the news of raising prices for four products across its 42 self-operating stores across regions on Aug 8:

OCR 匹配：@gs.comGoldmanSachs(Asia)L.L.C.Aug10by3%postthenewsofraisingpricesforfourproductsChristinaLiuacrossits42self-operatingstoresacrossregionsonAug8:

OCR 编辑距离 49；原生提取编辑距离 129。

### 片段 2

参考：More importantly, we expect 2H26 Feitian supply to tighten, making price stabilization rather than volume growth as the key operating focus for Feitian in 2H26 to support wholesale prices into peak seasons.

OCR 匹配：00thimportantly,weexpect2H26Feitiansupplytotighten,makingpricestabilizationratherthanvolumegrowthasthekeyoperatingfocus600519.SSrelativetoAsiaex.

OCR 编辑距离 50；原生提取编辑距离 155。

## d002-p02

2026-08-13_2026.08.13-goldman-sachs-国外研报-高盛-贵州茅台-600519-sh-市场化改革方案六-全国42家直营店四款产品提价-维持-买入-评级-a1454167.pdf，第2页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d002-p02.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d002-p02.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d002.pdf)

耗时 19.656s；采样峰值 649.2MiB；正文编辑数 0/0；缺失严格词项：无。

## d002-p03

2026-08-13_2026.08.13-goldman-sachs-国外研报-高盛-贵州茅台-600519-sh-市场化改革方案六-全国42家直营店四款产品提价-维持-买入-评级-a1454167.pdf，第3页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d002-p03.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d002-p03.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d002.pdf)

耗时 10.271s；采样峰值 634.6MiB；正文编辑数 0/0；缺失严格词项：无。

## d002-p04

2026-08-13_2026.08.13-goldman-sachs-国外研报-高盛-贵州茅台-600519-sh-市场化改革方案六-全国42家直营店四款产品提价-维持-买入-评级-a1454167.pdf，第4页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d002-p04.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d002-p04.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d002.pdf)

耗时 10.127s；采样峰值 660.4MiB；正文编辑数 0/247；缺失严格词项：无。

### 片段 1

参考：Valuation methodology: Our 12m TP of Rmb1,667 is based on a 23.4x 2027E P/E, discounted back to mid-2027 using an 8.5% COE.

OCR 匹配：Valuationmethodology:Our12mTPofRmb1,667isbasedona23.4x2027EP/E,discountedbacktomid-2027usingan8.5%COE.

OCR 编辑距离 0；原生提取编辑距离 95。

### 片段 2

参考：Key downside risks: 1) Potential regulation changes such as a consumption tax rate hike; 2) Environmental pollution; 3) A slower-than-expected macroeconomic recovery;

OCR 匹配：Keydownsiderisks:1)Potentialregulationchangessuchasaconsumptiontaxratehike;2)Environmentalpollution;3)Aslower-than-expectedmacroeconomicrecovery;

OCR 编辑距离 0；原生提取编辑距离 130。

## d005-p01

2026-08-16_2026.08.16-jpmorgan-摩根大通-中国人工智能-glm-5-3和deepseek的重新定价改变了能力成本前沿-raise-智谱minimax目标价-维持增持评级中性-b4d3b59b.pdf，第1页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d005-p01.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d005-p01.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d005.pdf)

耗时 12.522s；采样峰值 642.1MiB；正文编辑数 18/181；缺失严格词项：无。

### 片段 1

参考：We raise our 2026-27 revenue forecasts by 6-9% and 0-11%, respectively, and lift our PTs to HK$1,800 and HK$260.

OCR 匹配：ternet2026-27revenueforecastsby6-9%and0-11%,respectively,andliftourPTsOliviaXuACtoHK$1,800andHK$260.

OCR 编辑距离 17；原生提取编辑距离 0。

### 片段 2

参考：MiniMax’s current M3 has yet to establish a clear advantage on either capability or cost-performance.

OCR 匹配：MiniMax'scurrentM3hasyettoestablishaclearadvantageoneithercapabilityorcost-performance.

OCR 编辑距离 1；原生提取编辑距离 0。

## d021-p02

2026-09-06_2026.09.06-兴业证券-数据面面观-9月议息会议前的关键周-3e7710e1.pdf，第2页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d021-p02.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d021-p02.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d021.pdf)

耗时 9.980s；采样峰值 782.1MiB；正文编辑数 0/86；缺失严格词项：无。

### 片段 1

参考：港股行业层面，银行、计算机和家电行业领涨，轻工制造、电力设备及新能源和汽车行业领跌。

OCR 匹配：港股行业层面，银行、计算机和家电行业领涨，轻工制造、电力设备及新能源和汽车行业领跌。

OCR 编辑距离 0；原生提取编辑距离 41。

### 片段 2

参考：美国企业投资级债券信用利差+2bp至0.80%，高收益债券信用利差+7bp至2.67%。

OCR 匹配：美国企业投资级债券信用利差+2bp至0.80%，高收益债券信用利差+7bp至2.67%。

OCR 编辑距离 0；原生提取编辑距离 26。

## d021-p03

2026-09-06_2026.09.06-兴业证券-数据面面观-9月议息会议前的关键周-3e7710e1.pdf，第3页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d021-p03.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d021-p03.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d021.pdf)

耗时 8.542s；采样峰值 725.3MiB；正文编辑数 0/131；缺失严格词项：无。

### 片段 1

参考：截至9月4日，港股近5日日均卖空成交额为359亿港元，占市场成交总额日均比例为【18.4%】，目前位于近三年【43.7%】分位水平，

OCR 匹配：截至9月4日，港股近5日日均卖空成交额为359亿港元，占市场成交总额日均比例为【18.4%】，目前位于近三年【43.7%】分位水平，

OCR 编辑距离 0；原生提取编辑距离 50。

### 片段 2

参考：截至9月4日，港股市场当周解禁规模120.9亿港元，下周预计解禁12.0亿港元；2026年初至今解禁市值总额达5995.2亿港元。

OCR 匹配：截至9月4日，港股市场当周解禁规模120.9亿港元，下周预计解禁12.0亿港元；2026年初至今解禁市值总额达5995.2亿港元。

OCR 编辑距离 0；原生提取编辑距离 44。

## d035-p02

2026-09-06_2026.09.06-国联民生证券-宏观周度观察-中国汽车出海的欧洲考验-cac4f407.pdf，第2页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d035-p02.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d035-p02.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d035.pdf)

耗时 8.212s；采样峰值 669.0MiB；正文编辑数 0/86；缺失严格词项：无。

### 片段 1

参考：德国对华出口和车企在华份额持续下降，叠加贸易逆差扩大，推动其政策趋硬。

OCR 匹配：德国对华出口和车企在华份额持续下降，叠加贸易逆差扩大，推动其政策趋硬。

OCR 编辑距离 0；原生提取编辑距离 0。

### 片段 2

参考：8月制造业PMI升至49.8%，新订单指数重返扩张区间，需求回暖带动景气修复，但改善仍集中于大型企业；

OCR 匹配：8月制造业PMI升至49.8%，新订单指数重返扩张区间，需求回暖带动景气修复，但改善仍集中于大型企业；

OCR 编辑距离 0；原生提取编辑距离 0。

## d035-p05

2026-09-06_2026.09.06-国联民生证券-宏观周度观察-中国汽车出海的欧洲考验-cac4f407.pdf，第5页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d035-p05.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d035-p05.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d035.pdf)

耗时 8.441s；采样峰值 567.2MiB；正文编辑数 0/84；缺失严格词项：无。

### 片段 1

参考：2023年来，欧盟对华汽车政策工具不断增加，从反补贴调查、加征关税，逐步扩展至价格承诺和企业个案安排；

OCR 匹配：2023年来，欧盟对华汽车政策工具不断增加，从反补贴调查、加征关税，逐步扩展至价格承诺和企业个案安排；

OCR 编辑距离 0；原生提取编辑距离 0。

### 片段 2

参考：但并未新增价格底线和处罚条款，短期内对出口和盈利的直接影响或有限。

OCR 匹配：但并未新增价格底线和处罚条款，短期内对出口和盈利的直接影响或有限。

OCR 编辑距离 0；原生提取编辑距离 0。

## d035-p13

2026-09-06_2026.09.06-国联民生证券-宏观周度观察-中国汽车出海的欧洲考验-cac4f407.pdf，第13页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d035-p13.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d035-p13.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d035.pdf)

耗时 7.368s；采样峰值 519.3MiB；正文编辑数 0/78；缺失严格词项：无。

### 片段 1

参考：8月原材料购进和出厂价格指数分别升至56.6%和50.4%，需求改善带动企业定价能力修复；

OCR 匹配：8月原材料购进和出厂价格指数分别升至56.6%和50.4%，需求改善带动企业定价能力修复；

OCR 编辑距离 0；原生提取编辑距离 0。

### 片段 2

参考：同时非制造业商务活动指数仍为49.0%，表明需求修复尚未广泛扩散。

OCR 匹配：同时非制造业商务活动指数仍为49.0%，表明需求修复尚未广泛扩散。

OCR 编辑距离 0；原生提取编辑距离 0。

## d039-p01

2026-09-06_2026.09.06-国金证券-互联网行业研究-gpt-6-astra-fable-5-1正式发布-持续看好ai应用-247dc7fb.pdf，第1页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d039-p01.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d039-p01.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d039.pdf)

耗时 9.031s；采样峰值 665.9MiB；正文编辑数 0/74；缺失严格词项：无。

### 片段 1

参考：游戏：8月增速预期5-8%，持续稳健增长。

OCR 匹配：游戏：8月增速预期5-8%，持续稳健增长。

OCR 编辑距离 0；原生提取编辑距离 0。

### 片段 2

参考：音乐行业竞争加剧，订阅收入增速放缓，关注非订阅音乐收入开启第二增长曲线。持续关注竞争和AI带来的行业影响。

OCR 匹配：音乐行业竞争加剧，订阅收入增速放缓，关注非订阅音乐收入开启第二增长曲线。持续关注竞争和AI带来的行业影响。

OCR 编辑距离 0；原生提取编辑距离 0。

## d054-p01

2026-09-08_FundaAI_Deep台达电子2H26 重新加速在即VPD 仍被忽视.pdf，第1页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d054-p01.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d054-p01.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d054.pdf)

耗时 9.373s；采样峰值 617.9MiB；正文编辑数 0/149；缺失严格词项：无。

### 片段 1

参考：We initiate coverage of Delta Electronics (2308.TW), the broadest play on AI power spanning the grid-to-core value chain.

OCR 匹配：WeinitiatecoverageofDeltaElectronics(2308.TW),thebroadestplayonAIpowerspanningthegrid-to-corevaluechain.

OCR 编辑距离 0；原生提取编辑距离 0。

### 片段 2

参考：我们预计，受AI电源供应需求增强及VPD模块爆发式增长的推动，2H26营收将重新加速增长；

OCR 匹配：我们预计，受AI电源供应需求增强及VPD模块爆发式增长的推动，2H26营收将重新加速增长；

OCR 编辑距离 0；原生提取编辑距离 0。

## d061-p01

2026-09-30_2026.09.30-国内研报-长江消费周周谈20260928-5f4db7fb.pdf，第1页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d061-p01.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d061-p01.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d061.pdf)

耗时 8.584s；采样峰值 625.8MiB；正文编辑数 0/159；缺失严格词项：无。

### 片段 1

参考：生猪市场进入深度产能出清阶段，仔猪价格跌破130元/公斤，全行业现金流连续亏损超7个月，预计去化延续至2027Q1，累计幅度约15%，支撑未来猪价回升至18元/公斤。

OCR 匹配：生猪市场进入深度产能出清阶段，仔猪价格跌破130元/公斤，全行业现金流连续亏损超7个月，预计去化延续至2027Q1，累计幅度约15%，支撑未来猪价回升至18元/公斤。

OCR 编辑距离 0；原生提取编辑距离 81。

### 片段 2

参考：轻工出口链受中美关税豁免情绪提振，康耐特光学凭借AR眼镜供应链进入第二增长曲线，预计2026Q4放量；乐歌股份受益于非洲及拉美市场红利，估值低于15倍。

OCR 匹配：轻工出口链受中美关税豁免情绪提振，康耐特光学凭借AR眼镜供应链进入第二增长曲线，预计2026Q4放量；乐歌股份受益于非洲及拉美市场红利，估值低于15倍。

OCR 编辑距离 0；原生提取编辑距离 74。

## d061-p02

2026-09-30_2026.09.30-国内研报-长江消费周周谈20260928-5f4db7fb.pdf，第2页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d061-p02.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d061-p02.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d061.pdf)

耗时 10.075s；采样峰值 607.5MiB；正文编辑数 0/86；缺失严格词项：无。

### 片段 1

参考：截至9月18日，根据航班管家的数据，统计区间为9月25日至10月7日的航空口径出行人次同比增长3.1%。

OCR 匹配：截至9月18日，根据航班管家的数据，统计区间为9月25日至10月7日的航空口径出行人次同比增长3.1%。

OCR 编辑距离 0；原生提取编辑距离 51。

### 片段 2

参考：近期，全国近半省份的生猪均价已跌破10元/公斤，呈现二次探底的迹象。

OCR 匹配：近期，全国近半省份的生猪均价已跌破10元/公斤，呈现二次探底的迹象。

OCR 编辑距离 0；原生提取编辑距离 34。

## d061-p03

2026-09-30_2026.09.30-国内研报-长江消费周周谈20260928-5f4db7fb.pdf，第3页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d061-p03.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d061-p03.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d061.pdf)

耗时 9.741s；采样峰值 625.6MiB；正文编辑数 2/98；缺失严格词项：无。

### 片段 1

参考：8月份跌破200元，9月份跌破150元，近期已全面降至130元以内，部分省份甚至跌破100元。全行业断奶仔猪的平均成本约为280元，

OCR 匹配：8月份跌破200元，9月份跌破150元，近期已全面降至130元以内，部分省份甚至跌破100元。全行业断奶仔猪的平均成本约为280元，

OCR 编辑距离 0；原生提取编辑距离 65。

### 片段 2

参考：乐歌股份和康耐特光学是两个具备中长期成长性且当前估值合适的标的。

OCR 匹配：乐歌股份和康耐特光学是两个具备中长期成长性且当前位置合适的标的。

OCR 编辑距离 2；原生提取编辑距离 32。

## d061-p04

2026-09-30_2026.09.30-国内研报-长江消费周周谈20260928-5f4db7fb.pdf，第4页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d061-p04.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d061-p04.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d061.pdf)

耗时 10.990s；采样峰值 625.3MiB；正文编辑数 0/120；缺失严格词项：无。

### 片段 1

参考：具体来看，美国对中国豁免关税的品类中，主要涵盖了轻工行业的不锈钢保温杯、塑料餐厨具、玩具、家纺以及户外用品等子品类。

OCR 匹配：具体来看，美国对中国豁免关税的品类中，主要涵盖了轻工行业的不锈钢保温杯、塑料餐厨具、玩具、家纺以及户外用品等子品类。

OCR 编辑距离 0；原生提取编辑距离 58。

### 片段 2

参考：在华南地区，低温产品的阿尔法效应更为凸显，以君乐宝为代表的全国性低温品牌通过自建工厂突破了本地品牌300公里的运输半径壁垒，

OCR 匹配：在华南地区，低温产品的阿尔法效应更为凸显，以君乐宝为代表的全国性低温品牌通过自建工厂突破了本地品牌300公里的运输半径壁垒，

OCR 编辑距离 0；原生提取编辑距离 62。

## d062-p02

2026-10-02_FundaAI_专栏  光通信FCC 光模块规则可能好于悲观预期对中国头部厂商的利好或超想象.pdf，第2页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d062-p02.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d062-p02.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d062.pdf)

耗时 14.485s；采样峰值 599.0MiB；正文编辑数 4/190；缺失严格词项：无。

### 片段 1

参考：First, there is no public draft of the proposed transceiver rules. The note appears to relay an external senior legal team’s account of discussions with the White House and the FCC.

OCR 匹配：First,thereisnopublicdraftoftheproposedtransceiverrules.Thenoteappearstorelay●anexternalseniorlegalteam'saccountofdiscussionswiththeWhiteHouseandtheFCC.

OCR 编辑距离 2；原生提取编辑距离 0。

### 片段 2

参考：该法案明确点名了中际旭创（InnoLight）和新易盛（Eoptolink）。

OCR 匹配：该法案明确点名了中际旭创（InnoLight)和新易盛（Eoptolink)。

OCR 编辑距离 2；原生提取编辑距离 0。

## d064-p01

2026-10-21_前瞻_NOW_2026财年第三季度：调研反馈稳健，2027年展望.pdf，第1页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d064-p01.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d064-p01.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d064.pdf)

耗时 10.313s；采样峰值 624.1MiB；正文编辑数 2/101；缺失严格词项：31%–35%, 34%–35%。

### 片段 1

参考：我们认为第三季度cRPO增速超预期150-200个基点是合理的，而第四季度cRPO增速指引可能与买方预期基本一致，约为20%。

OCR 匹配：我们认为第三季度cRPO增速超预期150-200个基点是合理的，而第四季度cRPO增速指引可能与买方预期基本一致，约为20%。

OCR 编辑距离 0；原生提取编辑距离 0。

### 片段 2

参考：该专家预计2027年增速区间为31%–35%；若要达到34%–35%的上限，

OCR 匹配：该专家预计2027年增速区间为31%-35%；若要达到34%-35%的上限，

OCR 编辑距离 2；原生提取编辑距离 0。

## d065-p03

2026-10-21_研究｜光互连：OCP_2026_预示_NPO_落地与替代铜缆带来.pdf，第3页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d065-p03.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d065-p03.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d065.pdf)

耗时 9.213s；采样峰值 616.0MiB；正文编辑数 4/95；缺失严格词项：无。

### 片段 1

参考：Credo的ZeroFlap ALC替代的是AEC（有源电缆），而非可插拔光模块或NPO插槽。

OCR 匹配：Credo的ZeroFlapALC替代的是AEC(有源电缆)，而非可插拔光模块或NPO插槽。

OCR 编辑距离 2；原生提取编辑距离 0。

### 片段 2

参考：利用NVLink将576颗GPU互联，面向10万亿以上（10T+）参数模型，并预计于“明年”面世。

OCR 匹配：利用NVLink将576颗GPU互联，面向10万亿以上(10T+)参数模型，并预计于“明年”面世。

OCR 编辑距离 2；原生提取编辑距离 0。

## d066-p01

【机构调研】这家底层芯片平台供应商业绩创历史同期新高.pdf，第1页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d066-p01.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d066-p01.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d066.pdf)

耗时 9.579s；采样峰值 718.6MiB；正文编辑数 1/171；缺失严格词项：6.4TOPS/W@INT8。

### 片段 1

参考：炬芯科技于9月15-16日接待机构调研时表示，今年上半年，公司业绩创下历史同期新高，核心驱动来自端侧AI芯片持续放量

OCR 匹配：炬芯科技于9月15-16日接待机构调研时表示，今年上半年，公司业绩创下历史同期新高，核心驱动来自端侧AI芯片持续放量

OCR 编辑距离 0；原生提取编辑距离 56。

### 片段 2

参考：公司第一代存内计算NPU能效比达到6.4TOPS/W@INT8，第二代存内计算技术将进一步提升至7.8TOPS/W@INT8

OCR 匹配：公司第一代存内计算NPU能效比达到6.4TOPS/WW@INT8，第二代存内计算技术将进一步提升至7.8TOPS/W@INT8

OCR 编辑距离 1；原生提取编辑距离 61。

### 片段 3

参考：当前，端云协同仍然属于早期上升阶段，存量设备AI升级、全新AI硬件带来双重增长机会，长期成长空间广阔。

OCR 匹配：当前，端云协同仍然属于早期上升阶段，存量设备AI升级、全新AI硬件带来双重增长机会，长期成长空间广阔。

OCR 编辑距离 0；原生提取编辑距离 51。

## d067-p01

【电报解读】格芯与迈威尔共同推进下一代光学连接技术，机构称光.pdf，第1页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d067-p01.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d067-p01.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d067.pdf)

耗时 8.866s；采样峰值 641.0MiB；正文编辑数 0/190；缺失严格词项：无。

### 片段 1

参考：财联社9月17日电，格芯与迈威尔科技扩大合作，共同推进下一代光学连接技术。受此提振，格芯股价盘前涨幅扩大至7%。

OCR 匹配：财联社9月17日电，格芯与迈威尔科技扩大合作，共同推进下一代光学连接技术。受此提振，格芯股价盘前涨幅扩大至7%。

OCR 编辑距离 0；原生提取编辑距离 55。

### 片段 2

参考：绿通科技：2025年9月，公司完成对江苏大摩半导体科技有限公司收购。大摩半导体的设备及技术服务全面覆盖6英寸至12英寸晶圆产线，并最高可支持14nm制程工艺。

OCR 匹配：绿通科技：2025年9月，公司完成对江苏大摩半导体科技有限公司收购。大摩半导体的设备及技术服务全面覆盖6英寸至12英寸晶圆产线，并最高可支持14nm制程工艺。

OCR 编辑距离 0；原生提取编辑距离 77。

### 片段 3

参考：广立微：公司全资子公司LUCEDA主营业务涵盖硅光芯片设计成套软件、PDK开发、设计流程优化及专业培训等服务。

OCR 匹配：广立微：公司全资子公司LUCEDA主营业务涵盖硅光芯片设计成套软件、PDK开发、设计流程优化及专业培训等服务。

OCR 编辑距离 0；原生提取编辑距离 53。

## d068-p01

高盛：GS 贵州茅台：市场化方案五— 2026 年 7 月飞天茅台出厂价与建议零售价意外开启第二轮上调；买入.pdf，第1页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d068-p01.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d068-p01.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d068.pdf)

耗时 13.683s；采样峰值 626.5MiB；正文编辑数 99/286；缺失严格词项：无。

### 片段 1

参考：Kweichow Moutai raised the ex-factory price of Feitian Moutai (53% vol, 500ml, 2026 edition) by 7.9% or Rmb100/bottle from Rmb1,269/bottle to Rmb1,369/bottle

OCR 匹配：983|christina.liu@gs.comFeitianMoutai(53%vol,500ml,2026edition)by7.9%orGoldmanSachs(Asia)L.L.C.ValerieZhouRmb100/bottlefromRmb1,269/bottletoRmb1,369/bottle

OCR 编辑距离 66；原生提取编辑距离 128。

### 片段 2

参考：We estimate a 1.2% incremental sales, and 1.6% incremental earnings contribution to 2026 applying a 30% pro-rata to wholesale channels/c.40% pro-rata to Direct sales channels

OCR 匹配：Weestimatea1.2%Integratedincrementalsales,and1.6%incrementalearningscontributionto2026applyinga30%pro-ratatowholesalechannels/c.40%Percentile20th40the

OCR 编辑距离 33；原生提取编辑距离 139。

## d068-p02

高盛：GS 贵州茅台：市场化方案五— 2026 年 7 月飞天茅台出厂价与建议零售价意外开启第二轮上调；买入.pdf，第2页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d068-p02.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d068-p02.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d068.pdf)

耗时 18.800s；采样峰值 645.9MiB；正文编辑数 0/0；缺失严格词项：无。

## d068-p03

高盛：GS 贵州茅台：市场化方案五— 2026 年 7 月飞天茅台出厂价与建议零售价意外开启第二轮上调；买入.pdf，第3页。

[原页预览](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/previews/d068-p03.png) · [OCR 原文](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/d068-p03.txt) · [PDF 副本](C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/samples/d068.pdf)

耗时 11.277s；采样峰值 624.9MiB；正文编辑数 0/195；缺失严格词项：无。

### 片段 1

参考：We also estimate that c. 9,400 tons of Feitian volume sold was already in i-Moutai in 5M26 at a weighted average RSP of Rmb1,512

OCR 匹配：Wealsoestimatethatc.9,400tonsofFeitianvolumesoldwasalreadyini-Moutaiin5M26ataweightedaverageRSPofRmb1,512

OCR 编辑距离 0；原生提取编辑距离 95。

### 片段 2

参考：We now expect 2026 sales/NP growth at 3.9%/3.1% yoy. We expect 2027 sales/NP growth to accelerate to 8%/9%.

OCR 匹配：Wenowexpect2026sales/NPgrowthat3.9%/3.1%yoy.Weexpect2027sales/NPgrowthtoaccelerateto8%/9%.

OCR 编辑距离 0；原生提取编辑距离 80。
