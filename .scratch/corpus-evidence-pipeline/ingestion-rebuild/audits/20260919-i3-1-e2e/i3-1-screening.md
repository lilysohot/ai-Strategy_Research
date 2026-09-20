# I3-1 筛料（只读预检：从 43 份研报挑无 blocking 缺口的样本）

- 生成：2026-09-19T19:07:07+08:00；方法：corpus plan（只读可发布性预检；同一缺口分级实现；未装守卫、无 PG 写入）
- 筛了 41 份：**干净 9 / 有 blocking 缺口 32**
- 阻断代码分布：{"image_region_unreadable": 93, "table_lines_without_extraction": 71, "image_only_page": 8}

## 各类可用的干净样本（按体量升序，题名已截断）

### company（1 份）

| 来源 | blocking | acknowledged |
|---|---|---|
| 2026-08-17_2026.08.17-国信证券-张向伟-王新雨-公司研究-业绩点评-贵州茅台-600519-202 | 0 | 6 |

### macro（2 份）

| 来源 | blocking | acknowledged |
|---|---|---|
| 2026-09-07_2026.09.07-国盛证券-宏观点评-这次不一样-3600亿增资银行保险的信号-08d0451 | 0 | 5 |
| 2026-09-06_2026.09.06-华创证券-宏观专题-从分化到收敛-可能的路径与挑战-投石问-k-系列八-81 | 0 | 16 |

### industry（6 份）

| 来源 | blocking | acknowledged |
|---|---|---|
| 2026-09-06_2026.09.06-华源证券-环保行业周报-碳市场四行业配额方案落地-节能降碳赛道有望受益-80 | 0 | 2 |
| 2026-09-06_2026.09.06-国金证券-地产专题分析报告-二手房成交热度仍高-6906d4ad.pdf | 0 | 4 |
| 2026-09-06_2026.09.06-国泰海通-国泰海通证券-机器人行业周报-figure斥35亿美元加码heli | 0 | 11 |
| 2026-09-06_2026.09.06-国金证券-电力设备与新能源行业研究-中报全览-锂电验景气-aidc信号密-光 | 0 | 13 |
| 2026-09-06_2026.09.06-华福证券-华福证券-基础化工行业新材料周报-英伟达带火-新材料-电子特气涨幅 | 0 | 11 |
| 2026-09-06_2026.09.06-国泰海通-国泰海通证券-农业-超强厄尔尼诺将至-关注农业板块-29ebd03 | 0 | 8 |

## 有阻断的样本

| 来源 | 领域提示 | 阻断代码 |
|---|---|---|
| 2026-08-13_2026.08.13-长江证券-国内研报-长江证券-化工专题-景气投资-十问十答- | industry | {"image_region_unreadable": 2, "table_lines_without_extraction": 8} |
| 2026-08-16_2026.08.16-jpmorgan-摩根大通-中国人工智能-glm-5-3和d | company | {"table_lines_without_extraction": 2} |
| 2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张慧-公司研究-业绩点评-贵州茅台 | company | {"image_region_unreadable": 1} |
| 2026-09-05_2026.09.05-中信建投-行业数据周报9月第1期-市场普遍下跌-机构低配板块 | industry | {"image_region_unreadable": 27, "table_lines_without_extraction": 8} |
| 2026-09-06_2026.09.06-中银国际-中银证券-策略周报-外部加息扰动未消-短期以守为攻 | macro | {"table_lines_without_extraction": 1} |
| 2026-09-06_2026.09.06-光大证券-2026年8月美国非农数据点评-强非农降低了年内加 | macro | {"table_lines_without_extraction": 1} |
| 2026-09-06_2026.09.06-光大证券-金属行业周期品高频数据周报-焦煤期货收盘价周内下跌 | macro | {"table_lines_without_extraction": 6} |
| 2026-09-06_2026.09.06-兴业证券-数据面面观-9月议息会议前的关键周-3e7710e | macro | {"image_region_unreadable": 33, "table_lines_without_extraction": 10} |
| 2026-09-06_2026.09.06-兴业证券-极致轮动如何收敛-探讨几个契机-733fc399. | macro | {"table_lines_without_extraction": 1} |
| 2026-09-06_2026.09.06-华泰证券-宏观海外周报-联储加息悬念白热化-d571f138 | macro | {"table_lines_without_extraction": 5, "image_region_unreadable": 1} |
| 2026-09-06_2026.09.06-华福证券-华福证券-周观点-美联储加息扩表可能性或已浮现-看 | macro | {"image_region_unreadable": 1} |
| 2026-09-06_2026.09.06-国信证券-光力科技-300480-2026年中报点评-半导体 | company | {"image_region_unreadable": 1} |
| 2026-09-06_2026.09.06-国投证券-独立行情周报-地产与文旅中报尾部冲击主导走阔-68 | industry | {"image_region_unreadable": 7} |
| 2026-09-06_2026.09.06-国投证券-策略定期报告-有转机-在何时-5e03dd1c.p | macro | {"image_region_unreadable": 4, "table_lines_without_extraction": 1} |
| 2026-09-06_2026.09.06-国泰海通-国泰海通证券-传媒行业双周报-后西游记-上线-ai | industry | {"image_region_unreadable": 2} |
| 2026-09-06_2026.09.06-国联民生证券-医药行业周报-cxo中报我们看到了什么-c1e | industry | {"table_lines_without_extraction": 2, "image_region_unreadable": 1} |
| 2026-09-06_2026.09.06-国联民生证券-宏观周度观察-中国汽车出海的欧洲考验-cac4 | macro | {"image_region_unreadable": 7, "table_lines_without_extraction": 3} |
| 2026-09-06_2026.09.06-国联民生证券-通信行业周报-2026-cioe中国光博会前瞻 | industry | {"table_lines_without_extraction": 1} |
| 2026-09-06_2026.09.06-国金证券-ai行业周观察-7月手机市场大幅下滑-多家旗舰模型 | industry | {"image_region_unreadable": 1} |
| 2026-09-06_2026.09.06-国金证券-a股策略周报-迷雾与罗盘-fb9b3c67.pdf | macro | {"table_lines_without_extraction": 1} |
| 2026-09-06_2026.09.06-国金证券-互联网行业研究-gpt-6-astra-fable | industry | {"table_lines_without_extraction": 1} |
| 2026-09-06_2026.09.06-国金证券-有色金属行业小金属双周谈-钽价有望启动上行-关注锑 | industry | {"table_lines_without_extraction": 11, "image_region_unreadable": 1} |
| 2026-09-06_2026.09.06-国金证券-电子行业研究-韬定律-与业绩斜率-ai-pcb及半 | industry | {"table_lines_without_extraction": 3} |
| 2026-09-06_2026.09.06-国金证券-通信行业研究-hbm市场极度紧缺-字节获296亿美 | industry | {"table_lines_without_extraction": 2} |
| 2026-09-06_2026.09.06-天风证券-a股策略周报-非农大超预期-加息预期升温-5e67 | macro | {"image_region_unreadable": 1} |
