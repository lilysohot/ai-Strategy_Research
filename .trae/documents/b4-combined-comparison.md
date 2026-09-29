# B4 组合对照：B3 候选切块规则（chunk-4）与 B1+B3 组合验证

## Context

B1-only 对照已出结论：reader-pdf-7 单独通过（11 改善／0 回归／零字符丢失），但仍有 **9 条 `chunking_impact` 残留**。新 build（reader-pdf-7 重建）下的机制探查已确认，9 条分三类：

| 类别 | 目标 | 机制 | 能否 chunk 层修复 |
|---|---|---|---|
| 单格表行误判 | macro-001 e3、macro-002 e4、macro-003 a-2/a-4/e2（同一 699 字引文，793b3967） | cells=1 的 prose 行被判 `table_row`，正文句子被腰斩进 table 块 | **可修**（并入正文 run，模拟验证合并后 < TARGET_MAX） |
| 连续标题拆块 | company-008 a-2（dddc7cd0） | 标题拆两行成两个 KEPT heading 块，引文跨两块 | **可修**（合并为一个 heading 块） |
| 跨 NOISE 单元 | company-007 e1/e2、company-008 a-1（6f14cc14） | 跨点含 NOISE 单元（clean_view 空，文本按设计不进任何块） | 不可修（根因在 clean 层：running-header 去重误伤标题首行、免责节 fact-keep 切句），归 B2/clean 层证据 |

本任务执行 B4 组合对照（[02-fragment-chunking.md](file:///home/administrator/FrontierAgent/docs/data_clean_dos/02-fragment-chunking.md) §B4.1「通过项的组合」行）：实现 B3 候选切块规则（chunk-4），跑 **B3-only** 与 **B1+B3** 两个变体对比同一基线，回答「B3 是否有必要实施」与「组合是否引入新错误、综合成本是否值得」。3 条 NOISE 残留不作为 B3 失败，记录为 clean 层证据。

## B3 候选规则（改 `plugins/corpus/preparation/chunk.py`，CHUNK_REV → `chunk-4`）

**R1 单格 prose 表行并入正文**：`kind == _TABLE_KIND` 且对应单元 `len(u.location.cells) == 1` 时不走表格分组，落入正文 run 装配（kind="body"）。正文 run 的 break 条件改为「`table_row` 且 cells>1」才 break。判定必须 `== 1` 而非 `<=1`（cells=() 是 MD/docx 行与合成用例常态，`<=1` 会误伤真实表格行）。

**R2 连续 heading 合并**：连续 heading 单元（无正文隔开）收集成一个 run，合并为单一 heading 块（文本 `"\n".join`），不再各成独立块；后文存在时合并文本作标题关联，末尾 pending flush 语义保留。

不变式约束：`verify_chunk_result` 不改动即通过（单格行是 KEPT 区，并入正文后覆盖检查自动满足）；`oversized_unsplittable`、`context_refs`、title 关联语义保留。

## 变体矩阵（全部相对基线 base_code，即 b0_attribution.json）

| 变体 | reader | chunk | 数据来源 |
|---|---|---|---|
| 基线 | reader-pdf-6 | chunk-3 | b0_attribution.json（已存） |
| B1-only | reader-pdf-7 | chunk-3 | b1_comparison.json（已存，复用 `targets[].new_code`） |
| B3-only | 旧 PG units 反投影 | chunk-4 | 扩展 SQL 读 kind/status/clean_view/reasons |
| B1+B3 | reader-pdf-7 | chunk-4 | 归档重建（b1.build_new_artifacts）+ 当前 chunk |

隔离保证沿用 B4.3：零模型（import 陷阱）、只读 PG、新产物纯内存、不写库不建索引不发布。

## 实施步骤

1. **chunk.py 实现 R1/R2**，CHUNK_REV 升 chunk-4；新增 helper `_is_single_cell_row`。
2. **新增对照脚本** `.scratch/b4-combined-20260929/b4_combined.py`：
   - importlib 装载 b0_attribution（环境/attr_target/norm/load_gold/resolve_sources）与 b1_comparison（复用 `build_new_artifacts`/`offered_hits_for_new`，不重构 b1 本体）。
   - `load_source_artifacts_ext(conn, build_id)`：复制 b0 L118-180 并增加 `kind/status/clean_view/reasons` 四列（corpus_units 表已有）。
   - `build_b3only_artifacts`：旧 units 反投影成伪 ReaderResult（kind←u.kind、status←u.status、clean_view←u.clean_view）→ `chunk_clean_result`（自动用 chunk-4）→ B0 形状 artifacts。
   - target 级用 `b0.attr_target` 计算 B3-only 与 B1+B3 的 new_code；文档级做字符覆盖与单元连续性核验。
   - 输出 `b4-combined-comparison.json`（三种变体 transitions + doc_level + 逐 target 明细 + cost 统计：chunk 数/kind 分布/字节变化）。
3. **新增回归测试**（`tests/test_corpus_preparation_chunk.py`）：
   - R1：单格行（`cells=((0,0),)`）夹在正文段间 → 无 table 块、行文本入 body 块、verify 过；多格行仍成 table 组。
   - R2：`[heading, heading, body]` → 单一 heading 块文本含 `\n` 合并、后文标题关联正确、verify 过；连续 heading 收尾不重复发布。
4. **对照报告** `.scratch/b4-combined-20260929/report.md`：变体结果、冻结规则、B1.3 核验、成本对照、残留 3 条 clean 层证据、结论与限制。
5. **文档更新**：`02-fragment-chunking.md`（§B4.1 增补「组合对照执行」小节、头部状态 v6、CHUNK_REV 提及）与 `README.md`（头部 v9、§5 执行状态、§6 验收记录增补组合对照行）。

## 验证

- `uv run pytest tests/test_corpus_preparation_chunk.py -q` 全绿（新增 R1/R2 用例 + 既有 16 用例不回归）。
- `uv run pytest tests -q` 关键子集不回归；`uv run ruff check plugins/corpus/preparation/chunk.py && uv run pyright` 预检通过。
- `uv run python -m .scratch.b4-combined-20260929.b4_combined.py` 产出 JSON：B3-only 与 B1+B3 均 **0 回归（ok→非ok=0）**、零字符丢失；B1+B3 恢复 6 条可修残留（5 macro + a-2），3 条 NOISE 残留记录为 clean 层。
- 判定：若 B1+B3 0 回归且 6 条恢复 → B3 值得实施（chunk-4 冻结）；cost 维度（chunk 数/kind 分布）如实报告，不构成否决条件时采纳。

## 决策输出

对照结论回答：B3 是否有必要（是/否 + 证据）、组合成本是否值得；3 条 clean 层残留作为 B2 候选方向证据记录，不在本次实施。B4.3 隔离 build 验证与发布／回滚演练仍属发布级后续事项。
