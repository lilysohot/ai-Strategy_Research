# c′ 第二半：实词加权 / 虚词标点降权 —— 只读离线评估

- 日期：2026-09-22；性质：**离线评估，不改任何产品字节**（0 model calls、只读 PG、corpus schema 零写入）
- 脚本：[c3w_eval.py](c3w_eval.py)；产物：[c3w-eval.json](c3w-eval.json)（write-once，sha256 `de6ee340991a…`）
- 姊妹篇：`audits/20260922-c3-lexical-signal/`（c′ 第一半：直接改查询串剔除词元）

## C 方案原文

> 查询侧剔除虚词/标点词元，**或**给实词（年度列、公司名、指标名）加权。

第一半已在姊妹篇评估（有效，但"去单字"会回退）。本稿评估第二半。

## 关键流程（7 步）

```
1. 题面 → normalize_search_text → to_tsvector('zhcfg') → 词元列表（24 个）
2. 词元分组（判据全部取自产品既有非金标词表 / 结构判定）：
     content   = 实词（公司名、年度列 2026E/2027E/2028E、指标名 每股/收益/现金流…）
     function  = _FUNCTION_WORDS 命中的虚词（是 / 的 / …）
     punct     = 标点词元（结构判定：词元内不含字母/数字/汉字）
3. 候选池 = 产品 base 池（全词元 OR、limit=2000）—— **不收缩候选**，这是与姊妹篇的关键区别
4. 重新打分（唯一改动）：
     score = 1.0 * ts_rank(search_tsv, tsq_content) + w_f * ts_rank(search_tsv, tsq_function)
5. 按 (score DESC, build_id, chunk_id) 重排 hits（与产品 _SEARCH_SQL 的 ORDER BY 同 tie-break）
   —— chunk_order 是"来源全量原文序"，与命中顺序无关 ⇒ 无需重建
6. 交回产品：_apply_selection_bands → fetch_bands → aggregate_band_chunks(stitch=True) → _assemble_band_documents
7. 端到端判定：82 目标三桶 + EvidencePass(24) + 负例（主口径拒检 / 真检索诊断）+ 带宽
```

**为什么不用 PG 的权重语法**：写侧 `to_tsvector('zhcfg', search_text)` **未 `setweight`** ⇒ 所有词元同权重类，
`ts_rank(weights, …)` 与 `tsquery` 的 `:A/:B` 标记都没有区分效果。故在**排序调用侧**用双 tsquery 加权和实现。

**锚定**：`anchor` 档（content=全词元、function=∅）退化成 base，其输出与产品 `svc.search_bands`
逐字段相等（`anchor_equals_product=true`）⇒ Δ 可归因于排序信号，非脚本漂移。

## 结果（w_c 恒为 1.0，扫 w_f）

| arm | content / function | w_f | EvidencePass | matched | Δ | 回退 | c′003 | 选择变化 | 带宽 |
|---|---|---|---|---|---|---|---|---|---|
| anchor（=base） | 24 / 0 | 0 | 19/24 | 67 | — | — | 0/6 | 0 | 33 |
| prune_fn | 22 / 2 | 0 | 20/24 | 73 | +6 | 无 | **6/6** | 21 | 33 |
| **prune_fn_punct** | **19 / 5** | **0** | **21/24** | **75** | **+8** | **无** | **6/6**（pos 1） | 24 | 33 |
| w0.2 | 22 / 2 | 0.2 | 20/24 | 73 | +6 | 无 | 6/6（pos 5） | 21 | 33 |
| w0.5 | 22 / 2 | 0.5 | **17/24** | 57 | **−10** | **10 个目标** | 0/6 | 21 | 34 |
| prune_content | 14 / 10 | 0 | 21/24 | 75 | +8 | 无 | 6/6（pos 1） | 24 | 33 |

- 负例：主口径 6/6 `retrieved_documents=0`；**真检索诊断各档均为 5**（不高于 anchor）⇒ 未触红线。
- `prune_fn_punct` 与 `prune_content` **结果完全相同**（新增同为 company-003×6 + company-008/a-2 + industry-008/a-2，零回退）。

## 三点结论

1. **最优是"从排序信号里剔除"（w_f=0），不是"降权"**：w_f 从 0 → 0.2 → 0.5 单调变差，
   0.5 直接崩（−10、10 个目标回退）。即"实词权重 1、虚词权重 0"＝极端加权，是最优点。
2. **标点也要剔**：`prune_fn`（只去功能词）+6，`prune_fn_punct`（再去标点）+8 —— 多赚
   company-008/a-2 与 industry-008/a-2 两条。
3. **推荐档 = `prune_fn_punct`**（content=去 `_FUNCTION_WORDS` + 去标点，**保留单字**）：
   剔除更少却与 `prune_content` 同分，风险更低。
   ⇒ **EvidencePass 19/24 → 21/24，matched 67 → 75（+8），零回退，负例不回升，带宽 33 ≤ 49。**

## 与姊妹篇的方法论差异（重要）

| | 姊妹篇 c3p（改查询串） | 本稿 c3w（改排序权重） |
|---|---|---|
| 候选池 | **随词元收缩**（只含保留词元的块才进池） | **固定为 base 全池** |
| 同"去单字"档结果 | `content`：20/24、**回退 company-004 ×3** | `prune_content`：**21/24、零回退、+8** |

⇒ **删词必须发生在排序信号侧，不能发生在查询串侧**：一旦查询串被收紧，候选池先掉块，
后面的排序再准也找不回来。这是两稿之间最有工程价值的一条。

## 待裁决

1. 是否按 `prune_fn_punct` 落地（19 → 21/24，零回退）。
2. 落地位置需改产品排序表达式（`search_pg._SEARCH_SQL` 的 `score`）⇒ 新冻结修订 + 全量语料族回归
   + 端到端复验（漏斗逐层 Δ、6 负例、三门）+ **U 具名签认**（排序/粒度类变更）。
3. 影响面：24/24 题的 SelectedBand 集合发生变化（端到端零回退已实证，但须全量回归确认）。

## 复现

```bash
cd /home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260922-c3-lexical-weight
/home/administrator/FrontierAgent/.venv/bin/python c3w_eval.py            # 落盘（write-once，约 90s）
/home/administrator/FrontierAgent/.venv/bin/python c3w_eval.py --no-write # 只跑不写
```
