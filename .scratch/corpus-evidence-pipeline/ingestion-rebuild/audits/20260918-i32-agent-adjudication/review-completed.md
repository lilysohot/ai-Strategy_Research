# I3-2 金标补证与裁决底稿：AI 辅助核验完成，未正式签发

复核者：Codex / AI-assisted source review; not a human signature。人工审核：xyl 通过。时间：2026-09-18T09:45:58.554796+00:00。

## 结论

六份冻结开发 PDF 共89页已按授权只读补证。56条连续原文切片、5组结构对应记录已落盘；40项要件、24道有答案题、6道负例与1项历史状态问题均已有逐项处理建议，无需用户从空白模板重新标注。

本次判断：24道正例所要求的事实在原文中均能找到依据；6道负例在这六份文件范围内仍建议保留无答案。此前几处实质缺证主要是标注未收录完整上下文，不是原文没有对应内容。

但这不是正式金标验收通过：未冒签xyl，未生成正式decisions/approved，未改冻结source/query gold、旧I3守卫或r25快照；未执行I3-3/检索业务评测。署名保留AI辅助核验，最终采纳仍由用户确认。

## 授权与隔离

用户明确授权：‘允许六份开发 PDF 只读补证’。新建独立annotation guard，精确白名单6个原文件路径且逐一核对冻结SHA-256；原I3守卫不放宽。守卫自检24/24。继续隔离3份留出材料；不做OCR、不使用生产清洗/检索结果补答案，不访问网络、外部模型API或PostgreSQL。

使用PDF技能完成双阅读器抽取、全页缩略图筛查及相关原页目视核对。缩略图只用于发现版面和图像遗漏，不代替细表读数；相关财务表、化工表、非农月表、CME概率表、宏观图例已查看原页。

## 补齐的关键内容

| 缺口 | 本次直接依据 |
|---|---|
| macro-003 强就业与加息顾虑的因果判断 | 光大第1页 N-causal，不再从题目反造原句 |
| macro-004 聚焦前四主体、四条路径 | 华创第1页主体段及第1—2页四个路径标题，分别定位 |
| macro-005 财政两个堵点 | 华创第1页 K-bottlenecks，保留旧动能拖累和新动能税负 |
| macro-006 偏头部发债企业样本 | 华创第1页 K-sample，不能用泛化风险提示代替 |
| industry-006 供应链消息归属 | 华福第1页 H-ptfe，包含归属、用途、计划和预计 |
| 公司主体、激励性质、持股方向 | 两份公司首页、茅台第7页‘本公司’定义 |
| 表头、年份、单位、统计窗口 | 原页表格目视记录及独立原文切片，不将裸数字解释为完整证据 |

## 必须随金标保留的质量提示

### Q1

首页/第3/4页前值为修订后2.1万人；第5页将5.6万人写成前值。源内矛盾，非清洗器制造。

保留现有题目目标，但附‘按首页事件段及第3页表’的范围说明和冲突提示；不自动改原文，不把5.6当已核验前值。

依据：[N-event](evidence-appendix.md#n-event)、[N-month-header](evidence-appendix.md#n-month-header)、[N-month-values](evidence-appendix.md#n-month-values)、[N-conflict](evidence-appendix.md#n-conflict)

### Q2

长江正文日期2026-08-10与文件名08-13不同；光大正文9月5日与文件名9月6日不同。

source_id保持不变；正文发布日期与文件身份分开。后续发布时间验收不得以文件名替代正文依据，本轮不改数据库/公共准入规则。

依据：[C-report-date](evidence-appendix.md#c-report-date)、[N-date](evidence-appendix.md#n-date)

### Q3

表格裸数值不足以独立证明行列身份；连续文本和视觉行列对应是不同证据层。

保留本次visual_mappings；正式投影必须携带/联合表头、行名、单位、年份和脚注，不可用同义映射将缺结构视作已证明。

依据：[C-columns](evidence-appendix.md#c-columns)、[C-r32-capacity](evidence-appendix.md#c-r32-capacity)、[G-table-cash-header](evidence-appendix.md#g-table-cash-header)

## 验证结果及未覆盖范围

- 新补证191/191项检查通过：从授权PDF重新抽取并逐条核对页内字符切片、引文哈希、图像绑定、要件身份、来源专属约束、负例覆盖范围和冻结件未变化。它们是字节/结构检查，不是191次语义正确性评测。
- 原有审批/评分器回归88/88通过；r25冻结链校验通过。命令原始输出见regression.txt、freeze-validation.txt。
- 把本AI底稿误传入正式审批器仍为ready=false；没有利用底稿跳过签认。
- 56条引文中，40条在另一阅读器的空白归一文本中连续匹配；16条受双栏/表格读取次序或文字层差异影响不连续匹配，已保留差异清单并结合原页核对，不伪造‘双阅读器全部一致’。
- 未重跑PG、生产入库、全文检索、答案生成或全项目测试；没有业务模型调用，不能由本次结果推算Recall@5或EvidencePass。

## 正式发布前的工程边界

`source-gold-proposed.jsonl` 是**追加全部复核证据的研究提案**，不是可直接覆盖冻结件的发布版本。原始冻结行和签名保持原样；所有新增行均显式标为AI待采纳。冲突片段/负例近似命中也在复核证据库里，正式映射时必须区分支持证据与反证/干扰项。

一次离线机械重映射显示：目标54→85，状态2 blocked→1 blocked（剩macro-004），仍有40项待裁决。四条路径的原文已逐项定位，机器候选仍不能自行联合判为完备，这不意味着原文仍缺四条路径。**不得通过扩大段落、豁免缺词或批量批准强行消除blocked。**

正式转版应保留原必需单元格的行列身份，按本底稿精确改选/补充，去除重复或干扰锚点；按原协议提交anchor_review/lexical_review，并重新检查逐题义务完整性。长段quote、统计单位/公司身份和视觉表格对应不能被简单的字符串覆盖当作机器语义证明。不要直接将85条全部变为必需，也不以目标减少作为成功指标。

## 用户需要确认什么

请审阅Q1及下列逐题建议后，决定是否采纳本次AI辅助核验。建议确认口径：

> 采纳本次AI辅助补证与裁决建议；macro-001按首页事件段和第3页表保留原目标，同时记录第5页前值冲突；以本次复核的新采纳记录处理macro-039历史待复核状态，不冒签或改写旧审核记录。允许另建新金标版本并重新执行批准门。

该确认是采纳AI辅助成果，不应记成用户逐页亲自核验或原审核人的历史笔误证明。用户确认后，剩余版本化、精准映射、校验和冻结由工程侧执行；只有这些门通过才可标记I3-2正式完成。若不同意某题，只需指出题号，不必重填整份模板。

## 24道有答案题：复核与拟定参考答案

### company-001

华创证券对贵州茅台2026—2028年EPS和一年目标价的预测分别是多少，维持什么评级？

冻结要求：必须同时给出EPS 67.74/70.77/73.84元与年度对应、一年目标价2030元、维持强推，并标明是报告预测。

拟采纳答案：报告预测2026/2027/2028年EPS分别67.74/70.77/73.84元；一年目标价2030元，维持强推。

依据：[M-identity](evidence-appendix.md#m-identity)、[M-eps](evidence-appendix.md#m-eps)

### company-002

贵州茅台2026H1与2026Q2的总收入、归母净利润及其同比变化分别是什么？

冻结要求：H1收入922.8亿元/+1.3%、归母445.2亿元/-2.0%；Q2收入375.8亿元/-5.2%、归母172.7亿元/-6.9%；不能混淆半年与单季。

拟采纳答案：2026H1：总收入922.8亿元，同比+1.3%；归母445.2亿元，同比-2.0%。单Q2：总收入375.8亿元，同比-5.2%；归母172.7亿元，同比-6.9%。

依据：[M-h1q2](evidence-appendix.md#m-h1q2)

### company-003

国信证券财务预测表中，光力科技2026E、2027E、2028E的每股收益和经营活动现金流分别是多少？

冻结要求：EPS依次0.36/0.59/0.93元；经营现金流依次-222/-138/-17百万元，括号须解为负数；引用第20页对应行列且标明预测。

拟采纳答案：第20页预测列2026E/2027E/2028E：EPS为0.36/0.59/0.93元；经营活动现金流为-222/-138/-17百万元。括号表示负数，保留年度及两种单位。

依据：[G-table-eps](evidence-appendix.md#g-table-eps)、[G-table-cash](evidence-appendix.md#g-table-cash)、[G-table-cash-header](evidence-appendix.md#g-table-cash-header)

### company-004

光力科技2026—2028年股权激励的营业收入触发值和目标值各是多少？

冻结要求：按年度同时列出触发值8.84/12.06/15.81亿元与目标值9.38/13.40/18.09亿元；不得当作实际收入或券商盈利预测。

拟采纳答案：股权激励2026/2027/2028年营业收入触发值为8.84/12.06/15.81亿元，目标值9.38/13.4/18.09亿元。13.4与题目13.40等值；这些是激励考核口径，不是实际收入或券商盈利预测。

依据：[G-incentive](evidence-appendix.md#g-incentive)

### company-005

光力科技8230、8231、9130、9320的应用与商业化阶段有何区别？

冻结要求：8230先进封装已批量应用；8231支持全切/DBG半切/Edge Trimming且已形成正式订单；9130 Low-k开槽、9320超薄硅/SiC/GaN/MEMS隐切，后两款均在客户验证。

拟采纳答案：8230已在先进封装批量应用；8231支持晶圆全切、DBG半切、Edge Trimming，已形成正式订单。9130用于Low-k晶圆表面开槽；9320用于超薄硅晶圆、碳化硅、氮化镓和MEMS隐切；后二者仍在客户验证。

依据：[G-model-orders](evidence-appendix.md#g-model-orders)、[G-laser](evidence-appendix.md#g-laser)

### company-006

截至2026年6月30日，赵彤宇如何控制光力科技36.60%股份，亲属持股是否计入？

冻结要求：直接32.60%，经全资宁波万丰隆间接4.00%，合计36.60%；陈淑兰1.70%、赵彤亚0.57%不计入。

拟采纳答案：截至2026-06-30，赵彤宇直接持有32.60%，经全资宁波万丰隆间接控制4.00%，合计控制36.60%；亲属陈淑兰1.70%、赵彤亚0.57%未计入。

依据：[G-ownership](evidence-appendix.md#g-ownership)

### company-007

贵州茅台2026年中报点评的声明页披露了茅台集团与华创云信怎样的持股关系？

冻结要求：茅台集团持有华创云信4.06%股份；华创云信为华创证券控股股东，不能误记成华创证券持有茅台集团。

拟采纳答案：茅台集团持有华创云信4.06%；华创云信是报告中的‘本公司’即华创证券的控股股东。不可颠倒为华创证券持有茅台集团。

依据：[M-ownership](evidence-appendix.md#m-ownership)、[M-publisher](evidence-appendix.md#m-publisher)

### company-008

两份公司中报点评分别给贵州茅台和光力科技什么评级，属于维持还是首次覆盖？

冻结要求：必须取得两份材料：贵州茅台为强推（维持），光力科技为优于大市（首次覆盖）；通用评级定义页不能代替具体评级。

拟采纳答案：华创对贵州茅台：强推、维持；国信对光力科技：优于大市、首次覆盖。以两份报告的具体评级和公司身份取证，不以评级定义页代替。

依据：[M-identity](evidence-appendix.md#m-identity)、[M-eps](evidence-appendix.md#m-eps)、[G-identity](evidence-appendix.md#g-identity)、[G-rating](evidence-appendix.md#g-rating)

### industry-001

长江证券化工景气一览表中，纯碱的价格分位、价差分位和开工率分别是多少？

冻结要求：图6续表纯碱行：价格分位0.0%、价差分位0.0%、开工率82.9%；分位不是价格涨幅，开工率是注2所述期间平均。

拟采纳答案：图6续表纯碱：价格分位0.0%、价差分位0.0%、开工率82.9%。前两者是历史分位，不是涨幅；开工率为注2所列两个备选窗口的平均，不擅自确定品种窗口。

依据：[C-table-title](evidence-appendix.md#c-table-title)、[C-columns](evidence-appendix.md#c-columns)、[C-soda](evidence-appendix.md#c-soda)、[C-footnote1](evidence-appendix.md#c-footnote1)、[C-footnote2](evidence-appendix.md#c-footnote2)

### industry-002

图6续表的R32价格分位及2026E产能是多少，制冷剂产能有什么特殊口径？

冻结要求：R32价格分位99.6%，2026E产能28.5万吨/年；按注3属配额，不能解释为实际产量。价格分位窗口2016-01-01至2026-07-27。

拟采纳答案：R32价格分位99.6%，统计窗口2016-01-01至2026-07-27；2026E产能列28.5万吨/年，注3说明为配额，不能改称实际产量。

依据：[C-table-title](evidence-appendix.md#c-table-title)、[C-columns](evidence-appendix.md#c-columns)、[C-years](evidence-appendix.md#c-years)、[C-r32](evidence-appendix.md#c-r32)、[C-r32-capacity](evidence-appendix.md#c-r32-capacity)、[C-footnote1](evidence-appendix.md#c-footnote1)、[C-footnote3](evidence-appendix.md#c-footnote3)

### industry-003

图6续表的尿素开工率和2026E产能分别是多少？

冻结要求：尿素开工率89.9%，2026E产能8068.0万吨/年；区分开工率与产能，2026E为预测列。

拟采纳答案：尿素开工率89.9%；2026E产能8068.0万吨/年。开工率与产能是不同列，E表示预测列，不能混为产量。

依据：[C-table-title](evidence-appendix.md#c-table-title)、[C-columns](evidence-appendix.md#c-columns)、[C-years](evidence-appendix.md#c-years)、[C-urea](evidence-appendix.md#c-urea)、[C-urea-capacity](evidence-appendix.md#c-urea-capacity)

### industry-004

长江化工专题图6中，价格/价差分位与开工率分别使用什么统计窗口？

冻结要求：价格/价差分位为2016-01-01至2026-07-27；开工率为2026-01-01至07-26平均或2026年1—6月平均；不得擅自把二选一窗口分配到各品种。

拟采纳答案：价格/价差分位窗口为2016-01-01至2026-07-27。开工率为2026-01-01至07-26平均，或2026年1—6月平均；原文没有逐品种分配二选一窗口，不作分配。

依据：[C-footnote1](evidence-appendix.md#c-footnote1)、[C-footnote2](evidence-appendix.md#c-footnote2)

### industry-005

2026年9月6日新材料周报所述，氩气价格从5月初到9月2日怎样变化？

冻结要求：从720元/吨升至2459元/吨；约四个月，报告称涨幅超过240%；不是所有电子特气共同涨幅，也不是单日涨幅。

拟采纳答案：氩气价格从2026年5月初720元/吨升至9月2日2459元/吨；约4个月，报告称超过240%。不能泛化为全部特气或单日涨幅。

依据：[H-date](evidence-appendix.md#h-date)、[H-argon](evidence-appendix.md#h-argon)

### industry-006

华福新材料周报如何描述PTFE在英伟达平台的用途与Rubin Ultra的预计推出时间？

冻结要求：报告援引供应链消息：计划用于NVSwitch板卡及Rubin Ultra正交背板主力选材；Rubin Ultra预计2027年推出。须保留消息来源与“计划/预计”限定。

拟采纳答案：报告援引业内供应链消息：英伟达计划在NVSwitch板卡使用PTFE，并将其作为Rubin Ultra正交背板主力选材；Rubin Ultra预计2027年推出。保留消息归属、计划、预计。

依据：[H-ptfe](evidence-appendix.md#h-ptfe)

### industry-007

该周报中Wind新材料指数和申万三级半导体材料指数的收盘点位及周度变化分别是多少？

冻结要求：Wind新材料5611.65点、环比-4.2%；申万三级半导体材料12576.94点、环比-9.12%；保持指数名和数值配对。

拟采纳答案：本周Wind新材料指数5611.65点、环比-4.2%；申万三级半导体材料指数12576.94点、环比-9.12%。指数名、水平值与环比不得错配。

依据：[H-indices1](evidence-appendix.md#h-indices1)、[H-indices2](evidence-appendix.md#h-indices2)

### industry-008

能否把化工景气表中R32的99.6%与新材料周报中氩气“超240%”当成同一种涨幅指标？

冻结要求：不能：R32为历史价格分位（2016-01-01至2026-07-27）；氩气为2026年5月初720至9月2日2459元/吨的价格涨幅。须引用两份材料证明统计含义不同。

拟采纳答案：不能比较为同一涨幅。R32的99.6%是2016-01-01至2026-07-27历史价格分位；氩气超过240%为2026年5月初720至9月2日2459元/吨的区间价格涨幅。两份材料分别取证。

依据：[C-columns](evidence-appendix.md#c-columns)、[C-r32](evidence-appendix.md#c-r32)、[C-footnote1](evidence-appendix.md#c-footnote1)、[H-date](evidence-appendix.md#h-date)、[H-argon](evidence-appendix.md#h-argon)

### macro-001

光大非农点评所述2026年8月美国新增非农、市场预期及7月前值修订分别是什么？

冻结要求：8月16.2万人，预期5.6万人；7月由-2.3万人修正为2.1万人；前值修订与8月数据分开。

拟采纳答案：按首页事件段并结合第3页月度表：2026年8月新增非农16.2万人，预期5.6万人；前月7月由-2.3万人修订为2.1万人。第5页将5.6写为前值，与第1/3/4页不一致，应附来源内部冲突提示，不把错误前值当成另一个正确答案。

依据：[N-event](evidence-appendix.md#n-event)、[N-month-header](evidence-appendix.md#n-month-header)、[N-month-values](evidence-appendix.md#n-month-values)

### macro-002

该非农点评中，8月失业率、劳动参与率、平均时薪同比及对应前值是多少？

冻结要求：失业率4.1%/前值4.1%，劳动参与率61.6%/前值61.4%，平均时薪同比3.1%/前值3.2%；均为报告所述。

拟采纳答案：报告所述2026年8月：失业率4.1%、前值4.1%；劳动参与率61.6%、前值61.4%；平均时薪同比3.1%、前值3.2%。这不是本次对外部统计真实性的认证。

依据：[N-event](evidence-appendix.md#n-event)、[N-participation](evidence-appendix.md#n-participation)

### macro-003

该报告关于美联储9月加息的判断依赖什么通胀条件？报告所述市场概率是否等于政策已落地？

冻结要求：条件是后续通胀下行幅度有限；强就业降低加息顾虑。报告称非农公布后市场预期概率超过60%，必须区分附条件判断、市场预期和正式决定。

拟采纳答案：报告认为强就业减少加息顾虑；若后续通胀下行幅度有限，9月加息可能性难忽视。另称非农公布后市场预期概率超过60%。这是附条件判断与市场预期，不是正式决定。

依据：[N-causal](evidence-appendix.md#n-causal)、[N-condition-probability](evidence-appendix.md#n-condition-probability)

### macro-004

《从分化到收敛》识别哪些需求主体，重点研究的四条收敛路径是什么？

冻结要求：五主体为政府、准财政、企业、居民、海外；本文聚焦前四者；四路径为财政支出增加、缓解城投化债压力、企业投资增加、居民支出增加。

拟采纳答案：五主体：政府、准财政、企业、居民、海外；报告聚焦前四者。四路径：带动财政支出增加、缓解城投化债压力、带动企业投资增加、带动居民支出增加。四个标题分别取证，不伪装为一条连续引文。

依据：[K-subjects](evidence-appendix.md#k-subjects)、[K-path1](evidence-appendix.md#k-path1)、[K-path2](evidence-appendix.md#k-path2)、[K-path3](evidence-appendix.md#k-path3)、[K-path4](evidence-appendix.md#k-path4)

### macro-005

华创宏观专题对2026年两本账支出增速作何预测，并指出财政收入端哪两个堵点？

冻结要求：两本账支出增速预计约-0.5%，低于名义GDP增速；堵点为收入依赖旧动能且受其下行拖累、新动能综合税负偏低。须标注预测。

拟采纳答案：预计2026年两本账支出增速约-0.5%，低于名义GDP增速；财政收入依赖旧动能并受其下行拖累，新动能综合税负偏低。支出数字保留预测属性。

依据：[K-fiscal](evidence-appendix.md#k-fiscal)、[K-bottlenecks](evidence-appendix.md#k-bottlenecks)

### macro-006

报告中2025年央企与地方国企样本有息负债增速分别是多少，相对2024年如何变化？

冻结要求：央企4.6%对5.9%，地方国企6.1%对6.2%，均下降；样本为偏头部发债企业，不等于全国所有国企。

拟采纳答案：偏头部发债企业样本：央企2025年有息负债增速4.6%，低于2024年5.9%；地方国企6.1%，低于6.2%。不能推广为全国所有国企。

依据：[K-sample](evidence-appendix.md#k-sample)、[K-risk](evidence-appendix.md#k-risk)

### macro-007

报告中2026年第二季度居民消费倾向、支出倾向的定义及与2025、2019年同期的比较是什么？

冻结要求：消费倾向=消费/可支配收入，2026/2025/2019Q2为67.5%/68.6%/70.5%；支出倾向=(消费+新房购房)/可支配收入，为80.3%/83.7%/110.3%；不能混用口径。

拟采纳答案：消费倾向=消费/可支配收入，2026/2025/2019年Q2分别67.5%/68.6%/70.5%；支出倾向=(消费+新房购房)/可支配收入，分别80.3%/83.7%/110.3%。当年由报告日期及第11页图例2026共同绑定，不混用两个公式。

依据：[K-date](evidence-appendix.md#k-date)、[K-propensity](evidence-appendix.md#k-propensity)、[K-property-note](evidence-appendix.md#k-property-note)

### macro-008

报告用哪些项目计划投资增速说明固定资产投资偏弱，并提示哪些样本局限？

冻结要求：2026年1—6月本年施工项目计划总投资同比-4.3%，本年新开工项目计划总投资增速-29.4%；上市公司/发债企业样本代表性可能欠佳，结论可能偏差且可能有其他收敛路径。

拟采纳答案：2026年1—6月本年施工项目计划总投资累计同比-4.3%，本年新开工项目计划总投资增速-29.4%；上市公司/发债企业样本代表性可能欠佳、结论可能偏差，也可能存在其他收敛路径。

依据：[K-date](evidence-appendix.md#k-date)、[K-investment](evidence-appendix.md#k-investment)、[K-risk](evidence-appendix.md#k-risk)

## 六道负例：边界与近似命中排除

覆盖六份共89页，不限于原有槽位或检索命中。结论仅限冻结文件，不表示外部世界不存在事实，也不延伸到留出集或新版本。

### company-009

这六份开发材料能否给出光力科技2027年经审计的全年实际归母净利润（不是预测值）？

缺少2027年全年经审计实际归母净利润。第1、13—18、20页涉及未来利润/估值，2.19亿元明确为盈利预测；历史财务截至2026H1，没有对应2027年审计实绩。

近似命中核验：[G-rating](evidence-appendix.md#g-rating)、[G-2027-forecast](evidence-appendix.md#g-2027-forecast)

### company-010

这六份开发材料是否披露光力科技8231的首笔正式订单对应的设备唯一序列号？

缺少首笔8231正式订单所涉设备的唯一序列号。第2—6页型号、产品示意图和特点，第11—14页订单/销量/预测均未把某个唯一编号绑定首单；示意图的8231属于产品型号，不是首单设备serial。

近似命中核验：[G-model-orders](evidence-appendix.md#g-model-orders)

### industry-009

这六份开发材料能否给出2027年全年的氩气实际成交均价？

缺少2027年实际全年氩气均价。第1/7页为2026年5月初和9月2日点价；第3—5、8—9页图表是指数、公司股价涨跌、半导体销售及存储器价格，不是2027年氩气年度均价。

近似命中核验：[H-date](evidence-appendix.md#h-date)、[H-argon](evidence-appendix.md#h-argon)

### industry-010

这六份开发材料是否给出英伟达已签署PTFE采购合同的确切采购吨数？

缺少英伟达已签PTFE采购合同及确切吨数。第1/6页只有供应链选材计划；第6页实际合同为三星电机MLCC且客户未披露，第7页2840t/a是松下环氧模塑料产能，均不能替代英伟达PTFE合同量。

近似命中核验：[H-ptfe](evidence-appendix.md#h-ptfe)、[H-samsung-contract](evidence-appendix.md#h-samsung-contract)、[H-resin-capacity](evidence-appendix.md#h-resin-capacity)

### macro-009

这六份开发材料能否给出美联储2026年9月议息会议已经正式公布的最终利率决定？

缺少已公布的2026年9月美联储最终利率决定。第1/3/4页是判断/预期；第5页CME表标题明确CONDITIONAL MEETING PROBABILITIES，更新截至9月5日，9月16日行60.2%是概率不是决议。全文其他页面未补出最终决定。

近似命中核验：[N-date](evidence-appendix.md#n-date)、[N-condition-probability](evidence-appendix.md#n-condition-probability)、[N-probability-chart](evidence-appendix.md#n-probability-chart)

### macro-010

这六份开发材料能否给出2026Q2中国每户居民的逐户新房购房支出明细？

缺少2026Q2中国居民逐户新房支出明细。第2/10页给宏观比率，第11页图13是季度汇总曲线，购房口径为商品房销售、不含二手房；其他图表是企业/财政/居民汇总分析，不能反推逐户微观数据。

近似命中核验：[K-propensity](evidence-appendix.md#k-propensity)、[K-property-note](evidence-appendix.md#k-property-note)

## 40项要件裁决建议

每一项均为AI建议，待用户采纳。答案侧约束不生成证据目标；其实际执行效果仍在I3-5验收。

### I32-company-001-01 / qualification

报告预测2026/2027/2028年EPS分别67.74/70.77/73.84元；一年目标价2030元，维持强推。

建议：accept_with_source_evidence；依据：[M-eps](evidence-appendix.md#m-eps)

### I32-company-001-02 / answer_constraint

接受此答案侧约束；无需伪造原文说过同样的否定句，不投影证据目标；实际答案合规仍需I3-5验收。

建议：accept_answer_constraint；依据：答案约束，不设置chosen

### I32-company-002-01 / answer_constraint

接受此答案侧约束；无需伪造原文说过同样的否定句，不投影证据目标；实际答案合规仍需I3-5验收。

建议：accept_answer_constraint；依据：答案约束，不设置chosen

### I32-company-003-01 / answer_constraint

接受此答案侧约束；无需伪造原文说过同样的否定句，不投影证据目标；实际答案合规仍需I3-5验收。

建议：accept_answer_constraint；依据：答案约束，不设置chosen

### I32-company-003-02 / answer_constraint

接受此答案侧约束；无需伪造原文说过同样的否定句，不投影证据目标；实际答案合规仍需I3-5验收。

建议：accept_answer_constraint；依据：答案约束，不设置chosen

### I32-company-004-01 / value_equivalence

股权激励2026/2027/2028年营业收入触发值为8.84/12.06/15.81亿元，目标值9.38/13.4/18.09亿元。13.4与题目13.40等值；这些是激励考核口径，不是实际收入或券商盈利预测。

建议：accept_with_source_evidence；依据：[G-incentive](evidence-appendix.md#g-incentive)

### I32-company-004-02 / qualification

股权激励2026/2027/2028年营业收入触发值为8.84/12.06/15.81亿元，目标值9.38/13.4/18.09亿元。13.4与题目13.40等值；这些是激励考核口径，不是实际收入或券商盈利预测。

建议：accept_with_source_evidence；依据：[G-incentive](evidence-appendix.md#g-incentive)

### I32-company-007-01 / answer_constraint

接受此答案侧约束；无需伪造原文说过同样的否定句，不投影证据目标；实际答案合规仍需I3-5验收。

建议：accept_answer_constraint；依据：答案约束，不设置chosen

### I32-company-008-01 / source_coverage

华创对贵州茅台：强推、维持；国信对光力科技：优于大市、首次覆盖。以两份报告的具体评级和公司身份取证，不以评级定义页代替。

建议：accept_with_source_evidence；依据：[M-identity](evidence-appendix.md#m-identity)、[M-eps](evidence-appendix.md#m-eps)、[G-identity](evidence-appendix.md#g-identity)、[G-rating](evidence-appendix.md#g-rating)

### I32-company-008-02 / answer_constraint

接受此答案侧约束；无需伪造原文说过同样的否定句，不投影证据目标；实际答案合规仍需I3-5验收。

建议：accept_answer_constraint；依据：答案约束，不设置chosen

### I32-company-008-03 / source_coverage

华创对贵州茅台：强推、维持；国信对光力科技：优于大市、首次覆盖。以两份报告的具体评级和公司身份取证，不以评级定义页代替。

建议：accept_with_source_evidence；依据：[M-identity](evidence-appendix.md#m-identity)、[M-eps](evidence-appendix.md#m-eps)

### I32-company-008-04 / source_coverage

华创对贵州茅台：强推、维持；国信对光力科技：优于大市、首次覆盖。以两份报告的具体评级和公司身份取证，不以评级定义页代替。

建议：accept_with_source_evidence；依据：[G-identity](evidence-appendix.md#g-identity)、[G-rating](evidence-appendix.md#g-rating)

### I32-industry-001-01 / qualification

图6续表纯碱：价格分位0.0%、价差分位0.0%、开工率82.9%。前两者是历史分位，不是涨幅；开工率为注2所列两个备选窗口的平均，不擅自确定品种窗口。

建议：accept_with_source_evidence；依据：[C-columns](evidence-appendix.md#c-columns)、[C-soda](evidence-appendix.md#c-soda)、[C-footnote1](evidence-appendix.md#c-footnote1)、[C-footnote2](evidence-appendix.md#c-footnote2)

### I32-industry-002-01 / qualification

R32价格分位99.6%，统计窗口2016-01-01至2026-07-27；2026E产能列28.5万吨/年，注3说明为配额，不能改称实际产量。

建议：accept_with_source_evidence；依据：[C-footnote3](evidence-appendix.md#c-footnote3)

### I32-industry-002-02 / qualification

R32价格分位99.6%，统计窗口2016-01-01至2026-07-27；2026E产能列28.5万吨/年，注3说明为配额，不能改称实际产量。

建议：accept_with_source_evidence；依据：[C-footnote1](evidence-appendix.md#c-footnote1)

### I32-industry-003-01 / qualification

尿素开工率89.9%；2026E产能8068.0万吨/年。开工率与产能是不同列，E表示预测列，不能混为产量。

建议：accept_with_source_evidence；依据：[C-columns](evidence-appendix.md#c-columns)、[C-years](evidence-appendix.md#c-years)、[C-urea](evidence-appendix.md#c-urea)、[C-urea-capacity](evidence-appendix.md#c-urea-capacity)

### I32-industry-004-01 / qualification

价格/价差分位窗口为2016-01-01至2026-07-27。开工率为2026-01-01至07-26平均，或2026年1—6月平均；原文没有逐品种分配二选一窗口，不作分配。

建议：accept_with_source_evidence；依据：[C-footnote1](evidence-appendix.md#c-footnote1)

### I32-industry-004-02 / qualification

价格/价差分位窗口为2016-01-01至2026-07-27。开工率为2026-01-01至07-26平均，或2026年1—6月平均；原文没有逐品种分配二选一窗口，不作分配。

建议：accept_with_source_evidence；依据：[C-footnote2](evidence-appendix.md#c-footnote2)

### I32-industry-004-03 / answer_constraint

接受此答案侧约束；无需伪造原文说过同样的否定句，不投影证据目标；实际答案合规仍需I3-5验收。

建议：accept_answer_constraint；依据：答案约束，不设置chosen

### I32-industry-005-01 / answer_constraint

接受此答案侧约束；无需伪造原文说过同样的否定句，不投影证据目标；实际答案合规仍需I3-5验收。

建议：accept_answer_constraint；依据：答案约束，不设置chosen

### I32-industry-006-01 / qualification

报告援引业内供应链消息：英伟达计划在NVSwitch板卡使用PTFE，并将其作为Rubin Ultra正交背板主力选材；Rubin Ultra预计2027年推出。保留消息归属、计划、预计。

建议：accept_with_source_evidence；依据：[H-ptfe](evidence-appendix.md#h-ptfe)

### I32-industry-006-02 / qualification

报告援引业内供应链消息：英伟达计划在NVSwitch板卡使用PTFE，并将其作为Rubin Ultra正交背板主力选材；Rubin Ultra预计2027年推出。保留消息归属、计划、预计。

建议：accept_with_source_evidence；依据：[H-ptfe](evidence-appendix.md#h-ptfe)

### I32-industry-006-03 / qualification

报告援引业内供应链消息：英伟达计划在NVSwitch板卡使用PTFE，并将其作为Rubin Ultra正交背板主力选材；Rubin Ultra预计2027年推出。保留消息归属、计划、预计。

建议：accept_with_source_evidence；依据：[H-ptfe](evidence-appendix.md#h-ptfe)

### I32-industry-007-01 / answer_constraint

接受此答案侧约束；无需伪造原文说过同样的否定句，不投影证据目标；实际答案合规仍需I3-5验收。

建议：accept_answer_constraint；依据：答案约束，不设置chosen

### I32-industry-008-01 / qualification

不能比较为同一涨幅。R32的99.6%是2016-01-01至2026-07-27历史价格分位；氩气超过240%为2026年5月初720至9月2日2459元/吨的区间价格涨幅。两份材料分别取证。

建议：accept_with_source_evidence；依据：[C-columns](evidence-appendix.md#c-columns)、[C-r32](evidence-appendix.md#c-r32)、[C-footnote1](evidence-appendix.md#c-footnote1)

### I32-industry-008-02 / source_coverage

不能比较为同一涨幅。R32的99.6%是2016-01-01至2026-07-27历史价格分位；氩气超过240%为2026年5月初720至9月2日2459元/吨的区间价格涨幅。两份材料分别取证。

建议：accept_with_source_evidence；依据：[C-columns](evidence-appendix.md#c-columns)、[C-r32](evidence-appendix.md#c-r32)、[C-footnote1](evidence-appendix.md#c-footnote1)、[H-date](evidence-appendix.md#h-date)、[H-argon](evidence-appendix.md#h-argon)

### I32-industry-008-03 / source_coverage

不能比较为同一涨幅。R32的99.6%是2016-01-01至2026-07-27历史价格分位；氩气超过240%为2026年5月初720至9月2日2459元/吨的区间价格涨幅。两份材料分别取证。

建议：accept_with_source_evidence；依据：[C-columns](evidence-appendix.md#c-columns)、[C-r32](evidence-appendix.md#c-r32)、[C-footnote1](evidence-appendix.md#c-footnote1)

### I32-macro-001-01 / qualification

按首页事件段并结合第3页月度表：2026年8月新增非农16.2万人，预期5.6万人；前月7月由-2.3万人修订为2.1万人。第5页将5.6写为前值，与第1/3/4页不一致，应附来源内部冲突提示，不把错误前值当成另一个正确答案。

建议：accept_with_source_evidence；依据：[N-event](evidence-appendix.md#n-event)、[N-month-header](evidence-appendix.md#n-month-header)、[N-month-values](evidence-appendix.md#n-month-values)

### I32-macro-002-01 / answer_constraint

接受此答案侧约束；无需伪造原文说过同样的否定句，不投影证据目标；实际答案合规仍需I3-5验收。

建议：accept_answer_constraint；依据：答案约束，不设置chosen

### I32-macro-003-01 / qualification

报告认为强就业减少加息顾虑；若后续通胀下行幅度有限，9月加息可能性难忽视。另称非农公布后市场预期概率超过60%。这是附条件判断与市场预期，不是正式决定。

建议：accept_with_source_evidence；依据：[N-condition-probability](evidence-appendix.md#n-condition-probability)

### I32-macro-003-02 / qualification

报告认为强就业减少加息顾虑；若后续通胀下行幅度有限，9月加息可能性难忽视。另称非农公布后市场预期概率超过60%。这是附条件判断与市场预期，不是正式决定。

建议：accept_with_source_evidence；依据：[N-causal](evidence-appendix.md#n-causal)

### I32-macro-003-03 / qualification

报告认为强就业减少加息顾虑；若后续通胀下行幅度有限，9月加息可能性难忽视。另称非农公布后市场预期概率超过60%。这是附条件判断与市场预期，不是正式决定。

建议：accept_with_source_evidence；依据：[N-condition-probability](evidence-appendix.md#n-condition-probability)

### I32-macro-004-01 / qualification

五主体：政府、准财政、企业、居民、海外；报告聚焦前四者。四路径：带动财政支出增加、缓解城投化债压力、带动企业投资增加、带动居民支出增加。四个标题分别取证，不伪装为一条连续引文。

建议：accept_with_source_evidence；依据：[K-subjects](evidence-appendix.md#k-subjects)

### I32-macro-004-02 / qualification

五主体：政府、准财政、企业、居民、海外；报告聚焦前四者。四路径：带动财政支出增加、缓解城投化债压力、带动企业投资增加、带动居民支出增加。四个标题分别取证，不伪装为一条连续引文。

建议：accept_with_source_evidence；依据：[K-subjects](evidence-appendix.md#k-subjects)

### I32-macro-004-03 / qualification

五主体：政府、准财政、企业、居民、海外；报告聚焦前四者。四路径：带动财政支出增加、缓解城投化债压力、带动企业投资增加、带动居民支出增加。四个标题分别取证，不伪装为一条连续引文。

建议：accept_with_source_evidence；依据：[K-path1](evidence-appendix.md#k-path1)、[K-path2](evidence-appendix.md#k-path2)、[K-path3](evidence-appendix.md#k-path3)、[K-path4](evidence-appendix.md#k-path4)

### I32-macro-005-01 / qualification

预计2026年两本账支出增速约-0.5%，低于名义GDP增速；财政收入依赖旧动能并受其下行拖累，新动能综合税负偏低。支出数字保留预测属性。

建议：accept_with_source_evidence；依据：[K-bottlenecks](evidence-appendix.md#k-bottlenecks)

### I32-macro-005-02 / answer_constraint

接受此答案侧约束；无需伪造原文说过同样的否定句，不投影证据目标；实际答案合规仍需I3-5验收。

建议：accept_answer_constraint；依据：答案约束，不设置chosen

### I32-macro-006-01 / qualification

偏头部发债企业样本：央企2025年有息负债增速4.6%，低于2024年5.9%；地方国企6.1%，低于6.2%。不能推广为全国所有国企。

建议：accept_with_source_evidence；依据：[K-sample](evidence-appendix.md#k-sample)、[K-risk](evidence-appendix.md#k-risk)

### I32-macro-007-01 / answer_constraint

接受此答案侧约束；无需伪造原文说过同样的否定句，不投影证据目标；实际答案合规仍需I3-5验收。

建议：accept_answer_constraint；依据：答案约束，不设置chosen

### I32-macro-008-01 / qualification

2026年1—6月本年施工项目计划总投资累计同比-4.3%，本年新开工项目计划总投资增速-29.4%；上市公司/发债企业样本代表性可能欠佳、结论可能偏差，也可能存在其他收敛路径。

建议：accept_with_source_evidence；依据：[K-risk](evidence-appendix.md#k-risk)

## 历史状态澄清

原记录human_basis称待真人复核但有xyl签名。本次可核验内容，不可替原签名人证明此前只是笔误。原记录不删改，新版本须明确用户采纳与AI贡献。

## 文件导航

- adjudication-reviewed.json：40+24+6+1逐项建议和完整来源范围。
- source-gold-supplements-proposed.json：56条精确原文、拟定slot/item位置和5组视觉映射。
- evidence-appendix.md：可读原文附录及页面图片链接。
- verification.json：191项核对明细和双阅读器差异清单。
- candidate-remap-diagnostic.json：一次离线机械追加试映射，非业务验收。
- protected-artifacts-check.json：原冻结件与正式门状态未被改变。
- annotation-guard*.json、source-read-audit.json：授权范围、自检和源文件哈希。
