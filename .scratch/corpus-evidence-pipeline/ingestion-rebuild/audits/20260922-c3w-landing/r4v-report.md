# r4v 落地复验报告：prune_fn_punct（排序信号剔除功能词+标点）

**日期**：2026-09-22
**执行依据**：`audits/20260922-c3-lexical-weight/c3w-rollout-plan.md`（M2→M4）+ `c3w-eval.json`（权威期望值）
**性质**：只读 PG 复验（corpus schema 零写入）、0 model calls、不 commit/publish/重摄入/写库
**产物**：`r4v-replay.json`（write-once）、`r4v_replay.py`（可复跑，`--no-write` 支持）、`before-r4v/`（archive-first 归档）

## 1. 落地内容（plan §3 四处，全部实现）

| 位置 | 改动 | 落地后 sha256（前 8） | 改前归档 sha（前 8） |
|---|---|---|---|
| `plugins/corpus/preparation/negative_query.py` | 新增 `is_punct_lexeme` / `rank_lexemes`（剔功能词+标点、保单字、全剔回退 fail-closed）；docstring 修正（删除过时"不触 search_pg"表述） | `0f69d33c` | `6db6876c`（=r4t 绑定） |
| `plugins/corpus/preparation/search_pg.py` | `RANK_LEXEME_PRUNE=True` 常量；`_SEARCH_SQL` 双 tsquery（`tsq` 全词元供 WHERE/ts_headline、`tsq_rank` 实词供 score）；`_rank_query_on`（同一游标取词元）；`build_search_params` 可选 `rank_query` 键；`search_chunks_on` 注入 | `4d1db60c` | `04bc7d61`（=r42 绑定） |
| `tests/test_corpus_search_pg.py` | 新建 I-RANK-1：单元门 6 + 真库门 5（PG 门控 skipif） | （首绑） | — |

不变式落实：**I-1 候选池不收缩**（WHERE 仍 `@@ q.tsq` 全词元）；**I-2 只有 score 变**（ORDER BY tie-break `score DESC, build_id, chunk_id` 与 `ts_headline` 全词元不变）。

## 2. 质量门（M2）

- py_compile / `ruff check` / `ruff format`（新文件）：绿；pyright：0 errors
- `tests/test_corpus_search_pg.py`：29 passed（带 DSN）；无 DSN 时 24 passed + 5 skipped
- 语料族回归：**772 passed / 18 skipped**（含新文件）。改前同环境对照（还原 before-r4v 字节）= 766/13 ⇒ 净贡献 +6/+5，其余漂移为既有环境差异（hf-space 等缺失依赖的 skip、test_web_* 集合错误），与本改动无关（对照实验已证）

## 3. 端到端复验（M4，r4v_replay.py，11/11 门全绿）

| 指标 | 记录值（c3w-eval.json） | 产品实测 | 门 |
|---|---|---|---|
| EvidencePass | 21/24 | **21/24** | G2 ✅ |
| 82 目标 matched | 75（sbf=4、ns=0） | **75/4/0** | G2 ✅ |
| newly_matched | 恰 8 条 | **company-003×6 + company-008/a-2 + industry-008/a-2** | G2 ✅ |
| regressed | [] | **[]** | G2 ✅ |
| selection_changed | 24 | **24** | G2 ✅ |
| 带宽 max | 33 | **33 ≤ 49** | G2 ✅ |
| company-003 | 金标 pos1、6 目标 | **pos1、6/6** | G2 ✅ |
| 开关回滚 | anchor 记录：19/24、67、33 | **19/24、6/6/6 桶、33，且 == anchor 臂逐字段** | G3 ✅ |
| 负例真检索 | 各 5 且 ≤ anchor | **6 题各 5** | G4 ✅ |
| 机制等价 | — | 显式 `rank_query=臂排序串` ⇒ 产品装配 == 臂重算**逐字段**（24/24） | G1 ✅ |

## 4. 词元来源口径（已记录的非门诊断）

评估臂的排序词元取自**题面** zhcfg 词元；产品默认路径按 rollout-plan §3.2 从**收到的查询串**提取（harness 传入题面词元的 OR 串，再分词产生 'or' 操作符词元/再切分差异）。两口径在 82 目标漏斗上**逐值等值**（G2 全绿），但 band 划分可不同——诊断项 `default_vs_arm_doc_mismatch` 记录 24/24 题均有文档集差异（`r4v-replay.json`）。需要与臂逐字段一致时用 `build_search_params(rank_query=…)` 显式指定（G1 即此路径，已证机制等价）。

## 5. 待办与边界

- **M5 未完成**：`_FUNCTION_WORDS` 复用到正例排序属口径/粒度变更，须冻结 notes 写明并 **U 具名签认**（plan §7）；签认前本改动不生效于正式口径。
- 冻结修订 `i0c-r4v`（parent=i0c-r4u）随后执行（见 freeze-manifest / validate_i0c_freeze.py）；r42 对 search_pg 的 current-bytes 断言按 r4r 先例以 supersession 豁免承接（calibration-plan-v2.json 不可改写）。
- 显式范围外（plan §4）：不改写侧、不动选择/band 聚合、不动负例判定与 scoring.py、不改 `EvidenceTarget.matches`、`max_chunks_per_document=8` 保持。
- 回滚（plan §8）：一级 `RANK_LEXEME_PRUNE=False`；二级按修订哈希 revert 字节。
