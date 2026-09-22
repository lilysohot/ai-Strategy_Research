# c′ 排序信号侧（查询词元口径）只读离线评估

- 日期：2026-09-22；性质：**离线评估，不改任何产品字节**（0 model calls、只读 PG、corpus schema 零写入）
- 脚本：[c3p_eval.py](c3p_eval.py)（由 `audits/20260922-f3b-continuation-fragment/f3b_replay.py` 派生，主体逐行复用）
- 产物：[c3p-eval.json](c3p-eval.json)（write-once，sha256 `e06b0d41eae9…`）
- 议题：company-003 金标文档词法 rank 6 掉出 top-5（issues/10）

## 为什么做这个评估

机制根因（同日查证）：文档名次由**最高分块**决定，`ts_rank`（norm=0）主要计"命中词元个数"；
题面 24 词元中 8 个是虚词/标点 ⇒ **无关正文块（命中 10 个、含虚词）压过真正答题的财务预测表块
（命中 6 个、全实词）**。据此提出候选路径 c′：**查询侧收紧词元口径**。

## 单变量设计

唯一变量 = 送给产品读链的 `or_query` 词元集合；其余（检索 → 选择 → band 聚合 → 评分）
逐行复用 f3b 回放主体。词表判据**全部取自产品既有非金标词表**
（`plugins/corpus/preparation/negative_query.py`），不是为本题现编。

| arm | 口径 | 词元数（company-003） |
|---|---|---|
| `base` | 全 zhcfg 词元 OR（现生产/回测口径） | 24 |
| `minus_function` | 去 `_FUNCTION_WORDS`（保留单字）—— **c′ 主变体** | 22 |
| `content` | `content_lexemes`（去功能词 + 去单字） | 14 |
| `abstain` | `abstain_content_lexemes`（再剔 `_QUESTION_WORDS`）—— 诊断档 | 13 |

**基线锚定**：`base` 臂输出与产品 `svc.search_bands` 逐字段相等（`anchor_base_equals_product=true`）
⇒ 后续 Δ 可归因于词元口径，非脚本漂移。

## 端到端结果（82 目标 / 24 有答案题 / 6 负例）

| arm | EvidencePass | matched | selected_but_match_fail | not_selected | Δ matched | 回退 | SelectedBand 变化题数 | 带宽 |
|---|---|---|---|---|---|---|---|---|
| base | 19/24 | 67 | 6 | 6 | — | — | 0 | 33 |
| **minus_function** | **20/24** | **73** | 6 | 0 | **+6** | **无** | 21/24 | 35 |
| content | 20/24 | 72 | 7 | 0 | +5 | **company-004 ×3** | 24/24 | 34 |
| abstain | 20/24 | 72 | 7 | 0 | +5 | **company-004 ×3** | 24/24 | 34 |

- `minus_function` 的新增 **恰为 company-003 的 e1–e6**，零回退；
- `content`/`abstain`（去单字）开始**回退 company-004 的 a-2/a-3/e2** ⇒ 过犹不及，**甜点在"只去功能词"**；
- 负例：主口径（判定层拒检）6/6 `retrieved_documents=0`；**真检索诊断**（关闭拒检）各臂均为 5，
  **不高于 base** ⇒ 未触碰"负例不回升"红线。

## company-003 专项

| arm | 金标是否被选中 | 在选中集中的位置 | matched |
|---|---|---|---|
| base | 否 | — | 0/6 |
| minus_function | **是** | 2 | **6/6** |
| content | 是 | 1 | 6/6 |
| abstain | 是 | 1 | 6/6 |

## 重要修正：P2「光力无 cell」不成立

先前 c3 归因（issues/10）判定"band 证据只带 `page:`、光力 build `cells=[]` ⇒ P1 单独修复不产生
任何新 matched"。本评估实测**推翻**该 P2 结论：

- 光力 build `dddc7cd0…` 在服务层 **有 381 个 cells**，含 page:20 的财务预测表网格
  （`row=现金及现金等价物/营业收入/应收款项…`、`col=2026E/2027E/2028E`）；
- 一旦文档进 top-5（P1 解除），**e1–e6 直接 matched**，无需任何 reader/表格模型改造。

⇒ 先前判断很可能混淆了「reader 单元级 `cells`（确为空）」与「服务层 `_emit_cells` 派生的 cell 投影」
（非空）。**company-003 的唯一阻断是 P1（排序），P2 不成立。**

## 结论与待裁决点

1. **c′ 有效且是甜点版本**：只去 `_FUNCTION_WORDS` ⇒ EvidencePass **19/24 → 20/24**，
   matched **+6**，**零回退、负例不回升**。
2. **更激进的收紧有害**：`content`/`abstain` 会回退 company-004 三条目标，不采用。
3. **影响面不小**：`minus_function` 使 **21/24 题的 SelectedBand 集合发生变化**。
   端到端零回退已实证，但按 S2 教训仍须：全量语料族回归 + 新冻结修订 + 端到端复验
   （漏斗逐层 Δ、负例、三门）后方可落地。
4. **落地位置需 U 裁决**（两种，收益口径不同）：
   - (i) 只改回测/适配器的查询构造 ⇒ 不改产品字节，但分数口径变化，历史数字不可直接比较；
   - (i i) 改产品正例检索路径的查询归一化 ⇒ 生产真实提升（当前生产 = `base` 口径，
     经 `plainto` AND→OR 兜底得到的词元集合与 base 一致）。
5. **语义复用需具名签认**：`_FUNCTION_WORDS` 当前在产品中只服务于**负例拒检**（F1/B2），
   本评估将其复用到**正例检索降噪**。属查询口径/粒度变更，按 §11 纪律须 U 具名签认。

## 复现

```bash
cd /home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260922-c3-lexical-signal
/home/administrator/FrontierAgent/.venv/bin/python c3p_eval.py            # 落盘（write-once）
/home/administrator/FrontierAgent/.venv/bin/python c3p_eval.py --no-write # 只跑不写
```
