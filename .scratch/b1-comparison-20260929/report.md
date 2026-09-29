# B4 · B1-only 分项对照（reader-pdf-7 vs 基线 reader-pdf-6）

> 生成：2026-09-29 · 脚本 [`b1_comparison.py`](b1_comparison.py) · 产物
> [`b1_comparison.json`](b1_comparison.json) · 驱动：
> [`docs/data_clean_dos/02-fragment-chunking.md`](../../docs/data_clean_dos/02-fragment-chunking.md)
> §B4.1（B1-only 行）、[B0 归因](../b0-attribution-20260928/report.md) §4

## 1. 目的与隔离保证

B4 的 B1-only 行回答两个问题：**分组是否改善**、**是否出现字符或阅读序损伤**。
仅 reader 候选逻辑变化（`_is_heading` 新增 `uniform_multiline_block`），clean-3 /
chunk-3 不变。

- **零模型**：沿用 B0 的 import 陷阱（拒绝 `openai`／`anthropic`）。
- **只读 PG**：旧 artifacts 从活动 build 只读 SELECT；新 artifacts 由归档副本
  （`audits/20260919-i3-1-e2e/archive/`）经 reader-pdf-7 → clean → chunk 纯内存重建。
- **不发布**：无 PG 写入、无索引构建、无指针切换——符合 B4.3「只读源和新的产物位置」。
- **固定样本**：同 B0（30 题／99 target／6 来源），金标仅作固定样本，非盲测。

**冻结的候选规则**（B1 规则，仍以代码常量表达，本次对照后冻结验证）：

> `uniform_multiline_block`：PDF 原生多行文本块（`block_line_count > 1`）内字号一致
> （`block_max_size − block_min_size ≤ max(0.5, block_max_size × 0.05)`）时，该行
> **不判为标题**（按正文进入段落装配），无论行字号是否高于页中位数。原因：研报页
> 混排大量小字号表格/页脚会拉低页中位数，连续正文每行都「高于中位数」而被误拆为
> heading。块内存在明显字号层次时仍走原字号规则。

## 2. 结果总览（99 target）

| 转移 | 数量 | 含义 |
|---|---|---|
| `chunking_impact → ok` | **11** | F1 正文被拆进 heading 块的证据恢复为单块可取 |
| `chunking_impact → chunking_impact` | 9 | 仍跨块（宏观/表格边界类，非 reader 分组问题） |
| `ok → ok` | **75** | 基线全部 `ok` 无回归 |
| `ok → *非 ok*` | **0** | 无回归 |
| `structure_error → structure_error` | 4 | F2/F3 未变化（cells 保留/续表阅读序非 B1 范围） |

**B1.3 原文保护核验（6 来源全过）**：

- 字符覆盖：`chars_lost_vs_old = 0`、`chars_gained_vs_old = 0`（全部来源）。
- 旧单元连续子串：`old_unit_not_contiguous_in_new = []`（旧单元逐字仍是新文档连续子串）。
- 阅读序：旧单元序列在新文档中为**有序子序列**（6/6 来源 `ordered_subsequence_ok`），
  无跨单元重排。
- `old_chunks_broken_any=98` 属**块重分组**（单元合并改变块边界），已由
  「单元级有序子序列 + 零字符丢失」排除真实阅读序损伤，非内容重排。

## 3. 改善明细（11 个 target）

全部来自 **2026-09-06_dddc7cd0**（B0 F1 的 company-004/005/008 标题误判缺陷本体）：

- company-004：e1/e2/a-2/a-3（原「正文拆成 5 个 heading 块」示例逐字复原）
- company-005：e1–e5
- company-008：a-3/a-5

这正是 reader-pdf-7 的预期作用面：**标题字号误判 → 正文段落还原**。

## 4. 残留 chunking_impact（9 个）与 B3 证据

| 来源 | target |
|---|---|
| 2026-08-16_6f14cc14 | company-007 e1/e2、company-008 a-1 |
| 2026-09-06_dddc7cd0 | company-008 a-2 |
| 2026-09-06_793b3967 | macro-001 e3、macro-002 e4、macro-003 a-2/a-4/e2 |

残留样本跨 `body`/`table` 边界（B0 F1 的 macro 段），与标题误判不同源：**非 reader
分组问题，属 chunk 边界（B3）证据**。B1 单独通过不解决这些；是否实施 B3 由 B4
组合对照决定。

## 5. 结论与限制

- **B1 单独通过**：分组改善（11/20 F1 目标恢复单块），零字符丢失、零阅读序损伤，
  75 个 `ok` 零回归。满足 §B1.3「对照修改前初始提取 + 字符覆盖 + 阅读序」的门槛。
- **structure_error 4 条不变**（F2 逐表 cells 不稳定、F3 续表阅读序）不在 B1 作用面，
  应分别归入 B3（表格边界）与表格结构通道，不因此否决 B1。
- **限制**：offered 判定复用 B0 保存的检索命中，按「来源命中 → offered 覆盖其全部
  新块」等价重现（B0 已证实该结构结论）；未对新 build 建 GIN 索引做真实检索——若
  需发布级判定，须在隔离目标库完成候选 build 的索引与检索回放。
- 本次为**对照验证**，未构建可发布 build、未重建语料、未切换指针；B4.3 的隔离
  build 验证与发布/回滚演练仍属后续发布决策事项。
