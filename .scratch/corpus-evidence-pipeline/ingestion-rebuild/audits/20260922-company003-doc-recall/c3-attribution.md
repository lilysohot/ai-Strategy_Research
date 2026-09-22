# c3 归因报告：company-003 文档级召回（issues/10）

- 产物：`c3-attribution.json`（write-once，机读）；脚本 `c3_attribution.py`
- 口径：0 model calls、只读 PG（SELECT + 会话级 TEMP TABLE，corpus schema 零写入）、
  DSN 经 `20260920-i31-region-review/release.py::connect()`、gold 经
  `i3s2_scoring_input`（与 f3b_replay 同口径）。

## 结论（机器可复核，见 JSON self_check）

1. **P1（文档级截断）确认**：金标 doc `2026-09-06_dddc7cd0`（国信·光力科技）在
   company-003 OR 查询下 distinct-source 词法 **rank 6**，产品选择（band，top_k=5）
   不含金标（`gold_excluded=true`）——复现 f2 桶（S0/S1=true、S2_doc_topk=false）。
   6 目标 e1–e6 S1 全复现（引文在金标命中块文本内）。
2. **差距极薄**：rank-5（`2026-08-13_174b6462`，162 hits）best chunk
   `0.03294254` vs 金标（174 hits）`0.032827195`，**Δ≈0.000115（0.35%）**。
3. **机制精化（对历史初判的修正）**：top-6 来源的 best chunk **全部是 body 块，
   `matched_label_only_lexemes` 均为空**——"竞品 best chunk 靠标签词元抬高"在
   best-chunk 粒度**不成立**。rank-6 是全池排序环境效应：去标签 body-only 虚拟重排下
   金标回 **rank 5**（末位进圈），但同一反事实 **8/24 有答案题 top-5 集合变化**
   （且 S2 判定已证去注入端到端崩塌 12/24→2/24）——全局去注入依旧不可行。
   残差 1 处（cc03f55b best chunk 的「财务」）来自块标题/上下文前缀，非标签注入。
4. **P2（叠加阻断，本轮新确认）**：e1–e6 定位符为
   `page:20 + row:每股收益|经营活动现金流 + col:2026E|2027E|2028E`——
   `EvidenceTarget.matches` 要求证据 locator **包含全部 token**，band 证据只携带
   `page:` ⇒ 即便 P1 修复（文档进 top-5），目标至多 `selected_but_match_fail`；
   `matched` 需要 cell 证据，而光力 build 无结构化 cell 网格（i33 §1：reader 单元
   `cells=[]`、`element=null`）⇒ cell 投影无法派生。**P1 修复单独不产生任何新
   matched 目标。**

## 候选路径（呈 U 裁决；未裁决不动产品字节）

| 路径 | 修什么 | 效果上限 | 风险/成本 |
|---|---|---|---|
| a. doc_topk 5→6（或 N） | P1 | 金标进选择（S2_doc_topk +6 目标），**EvidencePass 不变**（matched 仍 0） | 对 matched 单调不减（只加证据不减），负例走判定层拒检不受影响；需全量复验 + 新冻结 |
| b. 文档级先验（题面公司名 × 标题匹配） | P1 | 同 a（**不改 matched**） | **非单调**（重排可把现 matched 文档挤出 top-5）⇒ 回归风险，需端到端复验；S2 教训适用 |
| c. P2 修复：reader/表格模型能力（光力财务预测表网格）+ 重摄入 | P2 | e1–e6 才可能 `matched`（EvidencePass 19→20 唯一路径） | 大范围：reader/TableModel 升级 + 重摄入 + 新冻结链；属 issues/04 表格模型领地 |
| d. 登记不修 | — | 19/24 成为该语料既定上限 | company-003 归入已知局限（P1+P2 双阻断） |

> 组合注记：a/b 只解决"进不了门"；c 才是"进门后拿分"。d 与 a/b/c 互斥度由 U 定
> （可 a+c 组合，也可整体 d）。

## 红线

- 注入本身不动（S2 判定 S3a/S3b/a/b/c 全否）。
- 不降 `max_false_positives=0`；不改 `EvidenceTarget.matches` 口径（量尺不得来自金标）；
  I-B3 `max_chunks_per_document=8` 保持。
- 负例 6 题 `retrieved_documents=0` 不回升；S1=66/S2=60/EvidencePass ≥19/24 不回退。
