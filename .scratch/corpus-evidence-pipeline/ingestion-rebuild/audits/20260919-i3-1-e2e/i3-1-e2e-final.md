# I3-1 三类开发 E2E —— 真实执行结果（隔离沙箱）

- 生成：2026-09-19T18:48:11+08:00；目标 `postgresql://***@127.0.0.1:543/i2_sandbox_corpus`；守卫 `.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json`（sha256 1c238a62d0d7）
- **范围状态：proposed_pending_ratification** —— 全部来源在 dev-manifest 中仍为 `review_required`（M1 未决），本轮按 Agent 提案 3 类×2 份执行，登记决定作者写明『待 U 追认』
- 真实执行：0 次模型调用；**未复用任何合成分数**；写入仅限隔离库 `i2_sandbox_corpus`

## 一、总览

- 来源 8 份（company/industry/macro 各 2 份 PDF + U 补 DOCX 1 份 + MD 投委会报告 1 份）；**可发布 3（2 PDF + 1 DOCX）/ 阻断 5（4 PDF 缺口 + 1 MD 未过门）**
- 规模：4305 单元 / 767 切块
- 检索命中：{"营业收入": 0, "景气": 0, "非农": 0, "同比": 4}（命中取证核验 4 条，全部通过=True）
- coverage：processing=scoped，query_status=matched；审计冲突：[]

## 二、逐来源门（真实）

| 领域 | 格式 | 来源 | 单元/切块 | check | publish | 阻断缺口 |
|---|---|---|---|---|---|---|
| company | pdf | 2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张 | 778/25 | 4 | 4 | image_region_unreadable(needs_ocr)@2 |
| company | pdf | 2026-09-06_2026.09.06-国信证券-光力科技-3004 | 798/198 | 4 | 4 | image_region_unreadable(needs_ocr)@7 |
| industry | pdf | 2026-08-13_2026.08.13-长江证券-国内研报-长江证券 | 1518/282 | 4 | 4 | image_region_unreadable(needs_ocr)@1；image_region_unreadable(needs_ocr)@2；table_lines_without_extraction(review_required)@12；table_lines_without_extraction(review_required)@13；table_lines_without_extraction(review_required)@17；table_lines_without_extraction(review_required)@18；table_lines_without_extraction(review_required)@21；table_lines_without_extraction(review_required)@22；table_lines_without_extraction(review_required)@24；table_lines_without_extraction(review_required)@3 |
| industry | pdf | 2026-09-06_2026.09.06-华福证券-华福证券-基础化工 | 258/54 | 0 | 0（gen 1） | 无 |
| macro | pdf | 2026-09-06_2026.09.06-光大证券-2026年8月美国 | 695/187 | 4 | 4 | table_lines_without_extraction(review_required)@6 |
| macro | pdf | 2026-09-06_2026.09.06-华创证券-宏观专题-从分化到 | 258/21 | 0 | 0（gen 1） | 无 |

## 三、领域×格式矩阵

| 单元格 | 份数 | 可发布 |
|---|---|---|
| company:pdf | 2 | 0 |
| industry:pdf | 2 | 1 |
| macro:pdf | 2 | 1 |

> 格式覆盖（更新）：**PDF ✓（6 份）**、**DOCX ✓（U 补 1 份，已发布）**、**MD ✗（投委会报告 → `review_required`，格式门未过，需 U 定性）**。

## 四、阻断缺口清单（§7.3 机读分级）

| 代码 | status | disposition | 条数 |
|---|---|---|---|
| table_lines_without_extraction | review_required | blocking | 9 |
| image_region_unreadable | needs_ocr | blocking | 4 |

处置路径（§7.3）：`image_region_unreadable` → 补 OCR；`table_lines_without_extraction` → 换料 / 转 `review_required`。**本轮未擅自降级门**。

## 五、读侧核验（search → fetch → verify）

- 口径：PDF 正文由 PyMuPDF 解析而来：**字节级逐字不适用**；核验口径为『chunk 文本 == 所引单元原文的换行拼接』且『每个单元原文 ⊆ 该文档解析文本』，并核对句柄 active 与页号范围

| 查询 | 命中 | 取证核验 |
|---|---|---|
| 营业收入 | 0 | — |
| 景气 | 0 | — |
| 非农 | 0 | — |
| 同比 | 4 | 全部通过 |

## 六、Findings

- **F1** CLI `plan` 的 stdout 被 PyMuPDF 横幅（『Consider using the pymupdf_layout package…』）污染
  - 影响：严格按 JSON 解析 stdout 的调用方会解析失败；本阶段已改为取首个 `{` 起解析并记录前缀
  - 建议：PyMuPDF 输出应改道 stderr（或 plan 阶段显式抑制）；属 CLI stdout 契约缺陷，建议单列修复
- **F2** 开发范围 73 份来源终态仍为 review_required（M1 未决）
  - 影响：本轮按 Agent 提案 3 类×2 份执行，登记决定作者已写明待追认；I3-1 不能据此宣告完成
  - 建议：U 批准范围后重跑并冻结该清单
- **F3**（**已解决**：U 补入 DOCX → 通过门并发布，见 F6）docx 无开发样本
  - 影响：格式矩阵缺一格 → 现 DOCX ✓；MD 仍缺
  - 建议：MD 需 U 定性
- **F4** 真实开发样本的缺口分布：4/6 份券商研报被门阻断，代码为 `image_region_unreadable`（status=needs_ocr）与 `table_lines_without_extraction`（status=review_required）
  - 影响：隔离库内 6 份来源 build 全成功（4305 单元 / 767 切块），但只有 2 份可发布；阻断项全部由 §7.3 机读分级给出，处置路径 = 补 OCR（图像区域）/ 换料或转 review_required（表格线未抽取）
  - 建议：U 定缺口处置策略（补 OCR / 换料 / 接受为 review_required 并在范围上排除）；本轮不擅自降级门
- **F5** 台账（docs/plan 两份）在本轮未更新
  - 影响：两份台账属 r31 绑定件，改动需新修订；I3-1 尚未冻结，故本轮只在审计目录留真实记录
  - 建议：I3-1 首个冻结修订（范围获批后）一并回填台账

## 七、未作结论（边界）

- I3-1 未宣告完成：开发范围未追认（M1），且 4/6 来源缺口处置策略未定
- 未做 I3-3（检索/切块参数校准）、I3-4（coverage 开发测试）、I3-5（非回归）；结果不得直接放行 I4

- 产物：{"stage1": "i3-1-e2e-record.json", "stage2": "i3-1-e2e-sources.json", "manifest": "dev-scope-manifest.json", "final": "i3-1-e2e-final.json"}

## 八、U 补 DOCX 的真实结果（格式覆盖探针）

- DOCX `9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx`（sha256 48c05895798b）：decision=**in_scope**，44 单元 / 7 切块，**check exit 0、缺口 0、可发布**，publish {"exit_code": 0, "generation": 2}
- MD `仕佳光子_投委会决策报告_20260831.md`：decision=**review_required**（机器检出 `internal_committee_report` → `POLICY_CONFLICT`）→ **格式门未过**
- 沙箱审计计数：{"sources": 8, "admissions": 8, "builds": 14, "units": 8698, "chunks": 1548, "active": 3}；冲突 []


## 九、【已撤回】Agent 自选范围（换料 + U 补料）—— 仅作证据，不得作为 I3-1 范围

来源见 `i3-1-e2e-scope-v2.json`；范围规则：零阻断且非留出（换料，规范口径）+ U 补 DOCX + U 要求接受的 MD；company 类零阻断样本为 0（唯一干净者系留出件）

| 单元格 | 份数 | 已发布 | 单元 |
|---|---|---|---|
| company:pdf | **0** | 0 | —（素材缺口，见 F7） |
| company:md | 2 | 2 | 338 |
| industry:pdf | 6 | 6 | 1268 |
| industry:docx | 1 | 1 | 44 |
| macro:pdf | 2 | 2 | 341 |

- 汇总：**11/11 可发布并已发布**，1991 单元 / 375 切块；`review_required` **0**；
  检索命中 {"营业收入": 1, "景气": 5, "非农": 0, "同比": 5, "光模块": 5, "碳市场": 3}；取证核验全过=True；
  被拒句柄 0；审计冲突 []
- 筛料（只读 plan，41 份券商研报）：零阻断且非留出 **8** 份；阻断代码
  `image_region_unreadable` 93 / `table_lines_without_extraction` 71 / `image_only_page` 8
- coverage：{"requested_scope_ref": "corpus_schema", "effective_scope_ref": "corpus_publications.active_build_id", "publication_snapshot_ref": "corpus_publications@8d6b981f862823c9f1d6ba954f9afd", "processing": "scoped", "query_status": "matched", "availability": "unknown", "reason_codes": "['partial_published', 'gap_regions_present']", "counts": "{'sources': 15, 'published': 11, 'withdrawn': 0, '"}
- 沙箱审计：{"sources": 15, "admissions": 23, "builds": 31, "units": 11782, "chunks": 2124, "active": 11}；冲突 []

### 新增 findings

- **F7** company 域素材缺口（三选一，需 U 定）
- **F8** `review_decision_ids` 必须列**整条取代链**，否则 `conflicting_review`
- **F9** `corpus plan` 的缺口在 `entry.precheck` 层级；整批失败返回 exit 2（解析错层级 → 假阴性）


## 十、纠正后的权威记录（照 U 批准集）

见 `i3-1-e2e-approved-set.md`：可发布 **2/6**（company 0/2、industry 1/2、macro 1/2），
阻断缺口合计 13 处，格式覆盖仅 PDF。
**『三类每类≥2 份』在现行门 + 现行裁定下不可满足**——这是本轮的结构性结论（真问题 1）。
撤回明细见 `i3-1-retraction-record.md`；取样前自检器 `preflight_scope_check.py`
（对自选范围判 FAIL、对批准集判 PASS）。
