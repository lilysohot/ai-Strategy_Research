# B4 组合对照（B3-only + B1+B3）报告

- 日期：2026-09-29
- 依据：[02-fragment-chunking.md §B4.1「通过项的组合」](../../docs/data_clean_dos/02-fragment-chunking.md)
- 脚本：`b4_combined.py`；产物：`b4-combined-comparison.json`
- 隔离保证：零模型（import 陷阱拒绝 openai/anthropic）、PG 只读（`transaction_read_only=on` 已断言）、新产物纯内存、不写库不建索引不发布。

## 1. 变体矩阵

| 变体 | 含义 | 来源 |
|---|---|---|
| `base` | B0 活动 build（reader-pdf-6 时代，chunk-3）归因 | `b0_attribution.json` 的 `primary_code` |
| `b1` | B1-only：reader-pdf-7 + chunk-3 | `b1_comparison.json` 保存值（其生成时 `CHUNK_REV=chunk-3`，恰为 B1-only） |
| `b3` | B3-only：旧 PG 单元反投影 + chunk-4（R1/R2） | 本脚本 `build_b3only_artifacts` |
| `b1b3` | B1+B3：归档副本重读 reader-pdf-7 → clean → chunk-4 | 复用 `b1.build_new_artifacts` |

B3 候选规则（chunk-4，已在 `chunk.py` 以代码实现）：

- **R1**：`table_row` 且 `len(location.cells)==1` 时按正文 run 装配（判定 `==1` 而非 `<=1`，`cells=()` 的 MD/docx 行不误伤）。
- **R2**：连续 heading 单元合并为单一 heading 块（文本 `"\n"` 拼接），单行标题维持既有行为。

offered 判定沿用 B0 保存的检索命中，按「来源命中 → 该变体全部新块」等价重现（与 B1 相同的受控假设，B0 已证实命中文档 offered 覆盖其全部块）。

## 2. 结果（99 target / 30 题 / 6 来源）

### 2.1 target 级转移

| 转移（相对 base） | `b1` | `b3` | `b1b3` |
|---|---|---|---|
| `chunking_impact → ok` | 11 | **17** | **17** |
| `chunking_impact → chunking_impact` | 9 | 3 | 3 |
| `ok → ok` | 75 | 75 | 75 |
| `ok → 非 ok` | **0 回归** | **0 回归** | **0 回归** |
| `structure_error → structure_error` | 4 | 4 | 4 |

`b1 → b1b3`：6 条 `chunking_impact → ok`，其余全部不变（`ok→ok` 86、`structure_error→structure_error` 4、3 条残留），**无 `ok → 非 ok`**。

### 2.2 恢复目标集合关系

- `b1` 恢复 11 条 ⊂ `b3` 恢复 17 条（B3 是超集）；`b3` 恢复集 == `b1b3` 恢复集（完全相同）。
- `b3 − b1` 恰为预测的 6 条可修残留：macro-001 e3、macro-002 e4、macro-003 a-2/a-4/e2（`793b3967`，单格表行误判，R1）+ company-008 a-2（`dddc7cd0`，标题拆两行，R2）。
- 结论：**17 条可修残留的根因都在 chunk 装配层**，R1/R2 单独（B3-only，不换 reader）即可全部恢复；B1 的 11 条在 B3 下同样恢复（同一批目标），故 B1 分组修复与 B3 装配修复对恢复维度不构成「增量叠加」，而是 B3 覆盖 B1。

### 2.3 残留 3 条（chunk 层不可修，归 clean 层证据）

company-007 e1/e2、company-008 a-1（`2026-08-16_6f14cc14`）。flags 证实 `in_concat=True`、`in_single_chunk_any=False`：引文在全文归一拼接中存在，但文本位于 **NOISE 单元**（clean_view 为空、按设计不进块）——running-header 去重误伤标题首行、免责节 fact-keep 切句。切块层无法使其进入任何块，根因在 clean 层（B2/clean 层证据）。

### 2.4 文档级核验（相对基线，0 字符丢失）

| 核验项 | `b3` | `b1b3` |
|---|---|---|
| `chars_lost` 合计 | 0 | 0 |
| `old_unit_not_contiguous_in_new` 合计 | 0 | 0 |
| `old_chunks_broken` 合计 | 98 | 98 |

`old_chunks_broken=98` 与 B1-only **逐来源完全一致**（30/17/4/19/19/9）——块重分组（单元合并改变块边界）的既有测量特性，chunk-4 未新增任何块断裂；结合零字符丢失与单元级有序子序列（`old_units_broken=0`）排除真实阅读序损伤。

### 2.5 成本（chunk 数与 kind 分布，相对基线）

| 来源 | base chunks | `b3` | `b1b3` |
|---|---|---|---|
| 174b6462 | 291 | 109 | 101 |
| 6f14cc14 | 36 | 35 | 33 |
| 793b3967 | 187 | 37 | 39 |
| cc03f55b | 32 | 31 | 30 |
| dddc7cd0 | 206 | 81 | 74 |
| f8e31696 | 55 | 29 | 22 |
| **合计** | **807** | **322（−485）** | **299（−508）** |

主要降幅来自 heading 碎片块消除（R2 合并连续标题，如 dddc7cd0 的 heading 由大块碎片收敛）与单格表行回正文（R1，body 块合并、table 块只保留真实多格行）。块更少且覆盖不变（0 回归）→ 索引/检索成本净下降；块平均变大使检索粒度变粗，是本规则的唯一权衡，未造成命中覆盖损失。

## 3. 结论与决策建议

1. **B3 有必要实施**：chunk-4 的 R1/R2 单独即可恢复全部 17 条可修 `chunking_impact`（含 B1 的 11 条），0 回归、0 字符丢失、0 新增块断裂。
2. **组合不引入新错误、成本净下降**：B1+B3 与 B3-only 恢复集相同、`ok→非ok` 为 0、chunk 合计 −508（−63%）。B1 与 B3 不冲突；B1 保留（reader 分组语义独立成立）或由 B3 覆盖均可，发布时一并冻结。
3. **残留 3 条不在切块作用面**：记入 B2/clean 层证据（running-header 去重、免责 fact-keep），不否决 B3。

## 4. 限制

- `b1` 变体为保存值（chunk-3 时代），未用 chunk-4 重算 B1-only；因 `b3`/`b1b3` 已分别隔离 reader 与 chunk 维度，该取舍不改变结论。
- B3-only 用占位 `cells`（`(i,0)` 序列）保证 `len` 语义正确；单格/多格判定与真实路径等价，但 `label_path` 缺失时表格行标签前缀为空（对本对照无影响）。
- offered 判定为受控等价重现，非对新 build 索引重新检索。
