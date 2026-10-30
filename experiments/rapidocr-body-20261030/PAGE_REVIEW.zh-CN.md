# 正文组件逐页复核索引

页码均为 PDF 物理页码（从 1 开始）。指标为固定抽样片段，控制页不计正文错误率；`needs_review` 为待核验提示。

| 页面 | 新增 | 来源 | 状态 | 片段错误/字数 | 关键内容命中 | 秒 | 自动分栏 | 异常规则 |
|---|---|---|---|---:|---:|---:|---|---|
| [d001-p01](outputs/d001-p01.txt) | 否 | native | ok | 0/112 | 5/5 | 0.387 | 否 | 无 |
| [d001-p03](outputs/d001-p03.txt) | 否 | native | ok | 0/101 | 4/4 | 0.265 | 否 | 无 |
| [d002-p01](outputs/d002-p01.txt) | 否 | ocr | needs_review | 1/321 | 6/6 | 14.377 | 是 | ambiguous_numeric_token×1 |
| [d002-p02](outputs/d002-p02.txt) | 否 | ocr | needs_review | 控制页 | 0/0 | 19.460 | 否 | low_confidence_line×1 |
| [d002-p03](outputs/d002-p03.txt) | 否 | ocr | needs_review | 控制页 | 0/0 | 9.940 | 否 | low_confidence_line×2 |
| [d002-p04](outputs/d002-p04.txt) | 否 | ocr | ok | 0/247 | 5/5 | 9.649 | 否 | 无 |
| [d005-p01](outputs/d005-p01.txt) | 否 | native | ok | 0/181 | 5/5 | 0.204 | 否 | 无 |
| [d021-p02](outputs/d021-p02.txt) | 否 | ocr | ok | 0/86 | 5/5 | 9.824 | 否 | 无 |
| [d021-p03](outputs/d021-p03.txt) | 否 | ocr | ok | 0/131 | 6/6 | 8.271 | 否 | 无 |
| [d035-p02](outputs/d035-p02.txt) | 否 | native | ok | 0/86 | 5/5 | 0.224 | 否 | 无 |
| [d035-p05](outputs/d035-p05.txt) | 否 | native | ok | 0/84 | 4/4 | 0.224 | 否 | 无 |
| [d035-p13](outputs/d035-p13.txt) | 否 | native | ok | 0/78 | 4/4 | 0.224 | 否 | 无 |
| [d039-p01](outputs/d039-p01.txt) | 否 | native | ok | 0/74 | 4/4 | 0.244 | 否 | 无 |
| [d054-p01](outputs/d054-p01.txt) | 否 | native | ok | 0/149 | 5/5 | 0.326 | 否 | 无 |
| [d061-p01](outputs/d061-p01.txt) | 否 | ocr | ok | 0/159 | 7/7 | 8.759 | 否 | 无 |
| [d061-p02](outputs/d061-p02.txt) | 否 | ocr | ok | 0/86 | 6/6 | 10.100 | 否 | 无 |
| [d061-p03](outputs/d061-p03.txt) | 否 | ocr | ok | 2/98 | 6/6 | 9.784 | 否 | 无 |
| [d061-p04](outputs/d061-p04.txt) | 否 | ocr | ok | 0/120 | 5/5 | 10.850 | 否 | 无 |
| [d062-p02](outputs/d062-p02.txt) | 否 | native | ok | 0/190 | 5/5 | 0.265 | 否 | 无 |
| [d064-p01](outputs/d064-p01.txt) | 否 | native | ok | 0/101 | 6/6 | 0.286 | 否 | 无 |
| [d065-p03](outputs/d065-p03.txt) | 否 | native | ok | 0/95 | 6/6 | 0.285 | 否 | 无 |
| [d066-p01](outputs/d066-p01.txt) | 否 | ocr | needs_review | 1/171 | 4/5 | 9.450 | 否 | suspicious_repeated_unit×1 |
| [d067-p01](outputs/d067-p01.txt) | 否 | ocr | ok | 0/190 | 12/12 | 8.554 | 否 | 无 |
| [d068-p01](outputs/d068-p01.txt) | 否 | ocr | needs_review | 0/286 | 6/6 | 13.480 | 是 | low_confidence_line×1 |
| [d068-p02](outputs/d068-p02.txt) | 否 | ocr | needs_review | 控制页 | 0/0 | 17.496 | 否 | low_confidence_line×3 |
| [d068-p03](outputs/d068-p03.txt) | 否 | ocr | needs_review | 0/195 | 5/5 | 10.350 | 否 | low_confidence_line×4, fragmented_line×1, ambiguous_numeric_token×1 |
| [d061-p05](outputs/d061-p05.txt) | 是 | ocr | ok | 0/67 | 4/4 | 9.788 | 否 | 无 |
| [d068-p04](outputs/d068-p04.txt) | 是 | ocr | ok | 控制页 | 0/0 | 11.951 | 否 | 无 |
| [d021-p05](outputs/d021-p05.txt) | 是 | ocr | ok | 控制页 | 1/1 | 4.614 | 否 | 无 |
| [d065-p04](outputs/d065-p04.txt) | 是 | native | ok | 0/81 | 5/5 | 0.244 | 否 | 无 |

原冻结参考 d065-p04 为 1/81；表中使用源图复核后的参考（0/81），详见 reference-errata.json。

## 样本文件对应

- `d001`：2026-08-12_2026.08.12-国泰海通-国内研报-国泰海通证券-ipo专题-新股精要-国内领先的电子材料和化工新材料生产企业贝特利-2594e01d.pdf；SHA-256 `f0e67b732b3f6d7b8e59329fdb769b33ffcb05709521a42d1f7d441241d0f71f`。
- `d002`：2026-08-13_2026.08.13-goldman-sachs-国外研报-高盛-贵州茅台-600519-sh-市场化改革方案六-全国42家直营店四款产品提价-维持-买入-评级-a1454167.pdf；SHA-256 `8935e5291a43a0251b35b7c82e6a228d86f41929f9c19acda8f3d8cf168defb1`。
- `d005`：2026-08-16_2026.08.16-jpmorgan-摩根大通-中国人工智能-glm-5-3和deepseek的重新定价改变了能力成本前沿-raise-智谱minimax目标价-维持增持评级中性-b4d3b59b.pdf；SHA-256 `7d3ca3b90deaafe68f4eae4de6013bcc7a924d59a9e3d7e4b02e4b4d68d428c8`。
- `d021`：2026-09-06_2026.09.06-兴业证券-数据面面观-9月议息会议前的关键周-3e7710e1.pdf；SHA-256 `c27ec5c878b92f5ec735afdd152e2d1b69c01863bebe57212888c991db8e58d6`。
- `d035`：2026-09-06_2026.09.06-国联民生证券-宏观周度观察-中国汽车出海的欧洲考验-cac4f407.pdf；SHA-256 `d0668d5a77f9f71385b63d3555136425a62624c86f288df22664211dc3b4f8ae`。
- `d039`：2026-09-06_2026.09.06-国金证券-互联网行业研究-gpt-6-astra-fable-5-1正式发布-持续看好ai应用-247dc7fb.pdf；SHA-256 `987d9f69f96235ba00b599fda44ae441a25c1aa99f6d6f56b3c8a6b96daf0f8a`。
- `d054`：2026-09-08_FundaAI_Deep台达电子2H26 重新加速在即VPD 仍被忽视.pdf；SHA-256 `1ccf5074e6ee188a2e1c6ed9644a69c934d547413630dac856a91d675f05ec0b`。
- `d061`：2026-09-30_2026.09.30-国内研报-长江消费周周谈20260928-5f4db7fb.pdf；SHA-256 `004303e2ff4f9acd4f315c909c098ebe0af5d2d1b7f537dc701b5e1fc02caa7e`。
- `d062`：2026-10-02_FundaAI_专栏  光通信FCC 光模块规则可能好于悲观预期对中国头部厂商的利好或超想象.pdf；SHA-256 `8b11fbdd67b1d0a215c39c3155799e12cb9c259d6a7b40066d6efa557434ed39`。
- `d064`：2026-10-21_前瞻_NOW_2026财年第三季度：调研反馈稳健，2027年展望.pdf；SHA-256 `373c75e2a67817622a143c7a508e6f5465ad14808fe4151186facdf0d26be0e7`。
- `d065`：2026-10-21_研究｜光互连：OCP_2026_预示_NPO_落地与替代铜缆带来.pdf；SHA-256 `cb2648e1099427785d08edeff449d26d7b75c1e114bec2508f76dfe2b9f7ccb7`。
- `d066`：【机构调研】这家底层芯片平台供应商业绩创历史同期新高.pdf；SHA-256 `b279daa0bc90403376daddbc40f2d42a5c90c8c479c74ef63c3346ae30b58fad`。
- `d067`：【电报解读】格芯与迈威尔共同推进下一代光学连接技术，机构称光.pdf；SHA-256 `c06a68fa3f1f2d87f90953286d34354286be659764077df181e22645401a41dd`。
- `d068`：高盛：GS 贵州茅台：市场化方案五— 2026 年 7 月飞天茅台出厂价与建议零售价意外开启第二轮上调；买入.pdf；SHA-256 `3738c927c6fb11b8f795d6d76ebf33294e8aef88ed7c98d16e55c56cf80c6c49`。

原始路径见 outputs/manifest.json；源文件未修改。原 26 页预览位于 ../rapidocr-expanded-20261030/outputs/previews，新增 4 页预览位于本实验 outputs。

原始 OCR、识别框、置信度、原生文字和完整异常证据位于 outputs/runs/<页面>.json。
