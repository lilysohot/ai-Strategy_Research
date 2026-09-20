# I3-3 单一回归复核审计（reader-pdf-5 重摄入，r39 冻结 scorer）

- 审计目录：`audits/20260920-i36-i33-reread-pdf5/`
- 生成：2026-09-20
- 复核性质：**冻结链重绑 + 单一回归**（同一 scorer，唯一变量 = reader-pdf-5 重摄入 active corpus）
- Decisión: **I3-3 放 行 ❌ 未通过**（负例误报 0 未达成；EvidencePass 未达 95%）

## 1. 复核口径（单一回归）

- 基线：`i33-calibration` 十 r39 冻结值（reader-pdf-2 的 active corpus）。
- 变量仅 1：corpus 换成 i35 在 teardown 重建沙箱上以 **reader-pdf-5** 全量重摄入、
  4 份含阻断缺口经人工 gap-review 重签后 publish 的 8 份 active builds。
- scorer 固定为 **r39 冻结字节** `bf9c8b80`（严格码位包含，`EvidenceTarget.matches()` 无空白规约）；
  重跑前临时还原 r39 字节、跑完恢复工作树 whitespace-norm 版本（`f61573d7`）——两次 sha 均在审计档案留存。
- 只跑 `candidate_question_lexemes_or` variant（baseline 在 r39 已证 0 命中，无意义）。
- 评分输入 `i3-2/query-gold-scoring-v1.jsonl` 经 `i3s2_scoring_input` manifest 校验（通过）；
  scorer/search_pg/read_pg/chunk/守卫与 r39 绑定字节逐条核对（全部通过）。
- 检索读取 **实时** active builds（`corpus.corpus_publications`，8 条 active），gold alias 唯一解析。
- bounds：top_k=5、min_rate=19/20、max_chunk_candidates=2000、max_当前8/doc、model_calls=0。
- 不改金标、不改 scorer、不做参数调参。

## 2. 结果（与 r39 OR variant 严格同口径对比）

| 类 | r39 DocRecall | r40 DocRecall | r39 QuestionPass | r40 QuestionPass | r39 EvidencePass | r40 EvidencePass |
|---|---|---|---|---|---|---|
| company | 100%(8/8) | 100%(8/8) | 8/8 | 8/8 | 1/8 | 1/8 |
| industry | 100%(8/8) | 100%(8/8) | 8/8 | 8/8 | 2/8 | **3/8** |
| macro | 100%(8/8) | 100%(8/8) | 8/8 | 8/8 | 2/8 | **3/8** |
| 合计观测 | 100% | 100% | 24/24 | 24/24 | 5/24 | **7/24** |

- `evidence_target_missing`：r39 54 → r40 **43**（reader-pdf-5 重摄入恢复 11 条必需证据命中）。
- 负例误报 / 伪造引用：**6/6 全部未消除**（company-009/010、industry-009/010、macro-009/010），
  与 r39 相同——这是 I3-3 放行的硬阻断。
- I3-3 门槛：EvidencePass ≥95%（19/20）❌（当前 7/24）、关键引用 100% ❌、负例误报 = 0 ❌（当前 6/6）。

## 3. 判定

**I3-3 无法放行。** reader-pdf-5 解决了「引文 kept 页内缺失」方向的部分证据召回
（i35 取证 34 条 kept 页内 32 命中，同口径重跑 evidence_target_missing 54→43），
但 (1) EvidencePass 仍 7/24，远低于 19/20；(2) 关键题 company 维度仅 1/8；
(3) 六条无答案负例全部持续误报并伪造引用，0 不可达成。三者任一即阻断放行。

按计划中止条件：指标未达 95% 或负例误报 > 0 ⇒ 不能放行，如实上报，不改金标、不改预期换分数。
`i33_complete` 保持 **false**，`m6_released` 保持 **false**（M6 属 I3-6/I3-7 范畴，本轮不判）。

## 4. 需留意的独立发现（不在本轮放行范围内）

- `i3s2_scoring_input.py --check` 报告 `lineage.scorer.sha256` 与工作树 `scoring.py` 不符：
  工作树存在**未冻结**的 `EvidenceTarget.matches()` 空白规约改动（`f61573d7`），而 manifest 与 r39
  冻结的仍是严格码位包含 scorer（`bf9c8b80`）。若后续要采用空白规约语义，须另起新冻结修订（重建 manifest
  血缘 + 新 freeze），不在本单一回归中用空白 scorer 混入。
- 本 r40 仅绑定「重摄入 + 取证 + 单一回归」产物；不改变金标、评分器、检索实现、守卫字节。

## 5. 冻结链校验状态（`validate_i0c_freeze.py`）

- **r40 自身校验全过**：parent=i0c-r39（文件字节/哈希一致）、binding 组 =
  `{reingest_evidence, regression_rerun, guards, freeze_validator}`、单 OR variant、
  model_calls=0、questions=30、`passed=false`、`i33_released=false`/`i33_complete=false`。
- **全链 i0c-current 现为 red（8 条失败），全部为**本次会话开始前已存在的**工作树未冻结漂移**：
  - `plugins/corpus/scoring.py`（工作树 whitespace-norm `f61573d7` vs r19/r21/r39 实现绑定严格 `bf9c8b80`）；
  - reader-pdf-5 的 `plugins/corpus/preparation/readers/pdf_reader.py`、`readers/base.py`（i1-r4 绑定）；
  - 更新后的 `tests/test_corpus_preparation_clean.py`、`tests/test_corpus_preparation_readers.py`、
    `tests/test_corpus_scoring.py`；
  - `docs/plan/corpus-ingestion-rebuild-tasks.md`、`docs/plan/claims-market-closed-loop-plan.md`。
- 这些漂移的本体是 i35 之前已引入的 reader-pdf-5 实现与文档演进，**不在单一回归/重绑产物范围**，
  且 whitespace-norm scorer 尚未被采纳。要恢复全链绿色需单独冻结决策（整体采纳 reader-pdf-5 代码与
  doc/test 演进），**未在本轮未授权范围内执行**。r40 冻结件保持 scoped，不做超越性重绑。