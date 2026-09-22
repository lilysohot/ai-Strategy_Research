# 10 company-003 光力科技文档级召回（doc rank 6 掉出 top-5）

Status: completed（2026-09-22 c3 prune_fn_punct 落地解除 P1：company-003 金标 pos1、6/6 matched；冻结 i0c-r4v；M5 已 U 具名签认落盘 i0c-r4w declared）
Type: task
Depends: 无（独立；issues/07 收口时显式移出——"19/24 封口待 company-003 独立议题"）
Layer: 文档级召回 / 词法排序（I-B1 标签注入副作用）
Bound-byte impact: 先归因后定（候选面=排序/选择层或登记不修；S2 判定已否决动注入本身）
Reingest: 否（预期只读归因；若 U 裁决改选择/排序层则不涉重摄入）

## 问题

company-003（光力科技）的金标文档（国信 doc，别名 `dddc7cd0`）在该公司查询的词法排名中
落第 6，被 doc top-5 截断，6 条证据目标 e1–e6 全部 fail。19/24（i0c-r4u 后）之上唯一的
已知封口缺口即本题。

## 已知事实（历史存档，待本轮机读归因复核）

- **归因初判**（i42 `backtest-report.md:72`、议题 B U 决定 2、spec §10.2/§14.4）：
  I-B1 标签注入改变 `ts_rank` ⇒ 光力 doc rank 6、掉出 top-5、6 条证据全丢；
  两变体（global/perdoc）均受影响，与结构排序信号无关。
- **漏斗位置**：`f2-funnel-targets.json`（当前 band 产品口径）e1–e6 均
  `S0_kept=true / S1_candidates=true / S2_doc_topk=false`，bucket=`kept_page_not_selected`
  （金标引文在金标文档 kept 页文本内，但文档未进 doc top-5）。i42 时代口径同层记
  `candidates_no_doc`——两产物桶名不同、语义一致：卡在文档级 top-5 截断。
- **机制**（S2 判定，`audits/20260921-s2-injection-judgment/`）：注入对表格丰富文档是
  净增益（额外匹配词元抬高 `ts_rank`，`norm=0` 不受文本长度稀释），对表格少文档（光力）
  形成相对劣势。注入实现 = 表格行 `search_text = " ".join(label_path) + "\n" + 行文本`
  （`chunk.py::_table_row_label_prefix` + `_table_row_pieces`），标签只进索引不进
  `unit.raw_text`。
- **注入本身不可拆**：S3a/S3b 及修法 a/b/c 全否（去注入 EvidencePass 12/24→2/24）；
  band 只改块内选择、cell 只投影已选带，均在其下游，**不能修文档级截断**。
- **reader 侧**（i33 §1）：光力 reader 单元 `cells=[]`、`element=null`（无结构化网格）——
  e1–e6 为 cell 语义目标（每股收益/经营活动现金流 × 2026E/2027E/2028E），即便文档进
  top-5，cell 投影能否命中需归因确认（目标实际 locator 形态待本轮核实）。
- **当前基线**（i0c-r4u 后）：EvidencePass 19/24、6 负例归零、S1=66/S2=60 不回退。
  company-003 转绿预期 +1（19/24→20/24，以复验为准）。

## 改动面（候选，先归因后定；不得反序）

1. **机读归因（本轮第一步，write-once 落盘 `audits/<date>-company003-doc-recall/`，
   0 model calls，只读 PG）**：复现 company-003 OR 查询的词法排名——金标 doc 的
   distinct-source rank 与 top-5 竞品 best-chunk 分数；按"查询词元命中分解"（
   `search_tsv` 命中 vs `unit.raw_text` body 命中）量化 top-5 竞品的标签词元贡献；
   读取侧虚拟反事实（去标签词元重排）看金标 doc 是否回 top-5，并量化该反事实对全部
   24 题 doc top-5 的扰动面（呼应 S2 判定教训：判定必须看 S2_doc_topk/端到端，
   不得用单层指标下结论）。
2. **候选修复路径（归因后呈 U 裁决，未裁决不得动产品字节）**：
   a. 文档级 top-k 扩容（doc_topk 5→N）：影响全部查询的 S2 截断，需量化对 24 题 +
      6 负例的扰动；
   b. 文档级排序信号（如题面公司名 × 文档标题/元数据匹配先验）：新增信号层，不拆注入；
   c. 登记不修（accept cap）：19/24 为该语料上的既定上限，company-003 归入已知局限。
3. 若 U 裁决改排序/选择层 ⇒ 仿 F1–F4：常驻测试 + 新冻结修订（i0c-r4v 起，
   parent=i0c-r4u）+ archive-first + 三门验证器 exit 0。

## 不变量与反例

- 负例 6 题 `retrieved_documents=0` 不回升（判定层拒检兜底语义不变）。
- S1=66/S2=60、EvidencePass ≥19/24 不回退；band 机制与 I-B3
  `max_chunks_per_document=8` 保持（SelectionPolicy 断言点）。
- 不降 `max_false_positives=0` 门槛；不按金标补取（量尺不得来自金标）。

## 验收

1. 机读归因产物（rank 证据 + 词元分解 + 反事实扰动面）落盘，结论可复核。
2. U 具名裁决修复路径（含"不修"选项）登记在案。
3. 若落地修复：company-003 6 目标达成预设可达桶（以归因结论为准），全量回归绿。

## 冻结影响

只读归因不触字节、无冻结影响。若动 `selection.py`/`service.py` 等 ⇒ 新冻结修订
（archive-first）+ 三门验证器 exit 0。

## 不做

- 不动注入本身（S2 判定已否决全部注入修法）。
- 不改金标/阈值/门槛；不重摄入；不 commit/publish/不写库。

## 归因记录（2026-09-22，`audits/20260922-company003-doc-recall/`，0 model calls 只读）

- **P1 确认**：金标 doc `2026-09-06_dddc7cd0` 词法 distinct-source **rank 6**、产品选择
  不含金标；6 目标 S1 全复现。rank-5→金标差距 **0.35%**（0.03294254 vs 0.032827195）。
- **机制精化（修正历史初判）**：top-6 来源 best chunk 全为 body 块、label_only 词元
  均为空——"竞品 best chunk 靠标签词元抬高"不成立；rank-6 是全池排序环境效应。
  body-only 虚拟反事实金标回 rank 5（末位），但同反事实 **8/24 有答案题 top-5 变化**
  （S2 判定端到端崩塌依旧成立）⇒ 全局去注入仍否。
- **P2 叠加阻断（新确认）**：e1–e6 定位符含 `row:/col:`（page:20），band 证据只带
  `page:` ⇒ P1 修复后至多 `selected_but_match_fail`；`matched` 需 cell 证据，而光力
  build 无结构化网格（i33：cells=[]）⇒ cell 投影无法派生。**P1 单独修复不产生新
  matched，EvidencePass 不变。**
- **候选路径（呈 U 裁决）**：
  a. doc_topk 5→N：修 P1，matched 单调不减、负例不受影响，但 company-003 仍 0/6；
  b. 文档级公司名×标题先验：修 P1，**非单调**（重排回归风险），需端到端复验；
  c. P2 修复（reader/表格模型能力 + 重摄入，issues/04 领地）：唯一能让 e1–e6
     `matched`（19→20）的路径，范围大；
  d. 登记不修：19/24 为该语料既定上限（P1+P2 双阻断）。
  组合（如 a+c）与取舍由 U 具名裁决；未裁决不动产品字节。

## 解决记录（2026-09-22，c3 prune_fn_punct 排序信号落地，冻结 i0c-r4v）

- **执行依据**：U 指令"依据文档落实到执行中"；权威方案 =
  `ingestion-rebuild/audits/20260922-c3-lexical-weight/c3w-rollout-plan.md`（离线评估获胜档
  prune_fn_punct：排序信号剔除功能词+标点，EvidencePass 19/24→21/24、matched 67→75）。
- **落地**（plan §3 四处，archive-first 归档 `audits/20260922-c3w-landing/before-r4v/`）：
  `negative_query.py` 新增 `is_punct_lexeme`/`rank_lexemes`（剔功能词+标点、保单字、
  全剔回退 fail-closed）；`search_pg.py` 双 tsquery——候选池 WHERE 仍 `@@ q.tsq`（全词元，
  **I-1 候选池不收缩**）、score 列改 `ts_rank(search_tsv, q.tsq_rank)`（实词）、ORDER BY
  tie-break 与 `ts_headline` 不变（**I-2 只有 score 变**）；`_rank_query_on` 同游标取词元 +
  `RANK_LEXEME_PRUNE=True` 默认开（False ⇒ 逐字节回 base）。写侧不动、不重摄入。
  注入本身不拆（本议题历史红线保持）；机制上 rank-6 是全池排序环境效应（归因已精化：
  竞品 best chunk 非标签词元抬高），剔功能词/标点重排即让金标回 top-5——非"扩容 top-k"路径。
- **P2 预测修正（实测推翻）**：归因记录曾判"e1–e6 带 row:/col: 定位符 ⇒ 即便进 top-5 至多
  selected_but_match_fail（光力 build cells=[]）"。实测（r4v_replay 直查当前库）当前 published
  build 金标 doc 带 **296 个结构化 cells**（page:20 网格 row/col 齐全，r40/r42 reader-pdf-5
  reshape 产物）——P2 前提已过时，band（page:）+ cell（row:/col:）证据共同承载
  `EvidenceTarget.matches`（quote 码位包含 + 定位符子集），6/6 全 matched。**P2 表格模型
  改造（issues/04 领地）不再需要。**
- **端到端复验**（`audits/20260922-c3w-landing/r4v_replay.py`，11/11 门全绿，
  r4v-replay.json write-once）：EvidencePass **21/24**、82 目标 matched **75**（sbf 4 / ns 0，
  **+8**）、newly 恰为 company-003×6 + company-008/a-2 + industry-008/a-2、**零回退**、
  selection_changed 24、带宽 **33≤49**、company-003 金标 **pos1** 且 **6/6**；G1 机制等价
  （显式 rank_query=臂排序串 ⇒ 产品装配与 c3w 臂重算逐字段相等）；G3 开关回滚 19/24/67/33
  与 anchor 臂逐字段相等；G4 负例 6 题各 5 不回升（拒检兜底语义不变）。
- **常驻测试**：`tests/test_corpus_search_pg.py` 首次入链（I-RANK-1：单元门 6 + 真库门 5）；
  语料族 772 passed / 18 skipped（改前同环境对照 766/13，漂移为既有环境差异）；ruff/pyright 绿。
- **冻结**：`i0c-r4v`（parent=i0c-r4u；binding: search_pg.py=4d1db60c、negative_query.py=
  0f69d33c、test_corpus_search_pg.py 首绑、validate_i0c_freeze.py=45b38930）；r42 对
  calibration-plan-v2.json 的 search_pg 现字节断言按 r4r 先例 supersession 豁免（不改写已关闭
  审计产物）；**三门验证器 exit 0**。manifest sha=9474b85e。
- **待办**：~~M5 独立复核 + U 具名签认~~ → **已完成（2026-09-22，见下）**。
  词元来源口径非门诊断：臂取题面词元、产品默认取收到的查询串（plan §3.2），漏斗逐值等值、
  band 划分可不同（r4v-replay.json diagnostics）。
- **M5 具名签认落盘（2026-09-22，冻结 `i0c-r4w` parent=i0c-r4v）**：U 对 M5 签认流程呈报
  回复"好的，执行吧"= 具名批准。落盘为新签认修订（零运行字节改动，只翻转
  `m5_declaration`：not_declared → **declared**，签认范围=i0c-r4v 落地内容）+ 验证器重绑
  （45b38930 → fdc1f67d，r4w 块语义门：binding 仅 freeze_validator、m5_declaration 须
  declared+U+日期、corrections 须含 m5_sign_off）；manifest sha=cc8fe3e6；**三门验证器
  exit 0**。追加式纪律保持：i0c-r4v.json 已冻结字节未追改。排序信号自此为正式口径；
  一级回滚 `RANK_LEXEME_PRUNE=False` 保留。
