# I3-3 栏重建（FIX-1）：只读复现验证 —— 先证后重摄入

## Context（为什么做）

修正先前错误结论：I3-3 首轮 54 条缺失证据，此前被我误判为「18 条金标改写/重建、检索层不可达」。
`remediation-guide-quote-reconstruction.md`（U 提供版面截图 + bbox 实锤）证伪该判断：**原 PDF 内容完整**，
是**摄入侧阅读顺序**把 PDF 双栏/浮动的右栏块（如 company-001 p1 的 `相关研究报告` 盒子，bbox x≈394–468、
y≈611–621）按 y 坐标夹进了左栏句子中间，导致 34 条中 25 条（B 类）引文被插断、7 条（A 类）因 CJK↔拉丁
空格被吞而不逐字。只读复算已确认 **A=7 / B=25 / C=2**。

修复必须走**摄入侧**（不动金标、不放松评分判据）。主因 FIX-1 = 页内阅读顺序重建（栏聚类 + 浮块隔离）。
这是**重摄入级**改动（bump `READER_PDF_REV` → 全量重摄入 → 重建块 → 重新冻结重绑 → 两门复跑）。

用户已裁决：**本轮首步先做"只读复现验证"，证明确能使 25 条 B 类转绿后，再谈重摄入。**

## 现状（代码定位）

- [pdf_reader.py:117-139](file:///home/administrator/FrontierAgent/plugins/corpus/preparation/readers/pdf_reader.py#L117-L139) `_split_columns`：
  只有「左右两栏纵向并排且纵向重叠 ≥50% + 横向空隙足够宽（`page_width*_COLUMN_GAP_RATIO`）」才判定分栏。
  → 窄/短的右侧浮盒（`相关研究报告`）判定为 None → [L360-361](file:///home/administrator/FrontierAgent/plugins/corpus/preparation/readers/pdf_reader.py#L360-L366) 回退单栏，
  按 `(bbox[1], bbox[0])` y 排序 → 浮盒被夹进左栏正文句内。→ 存储后的单位顺序保存了该错误阅读顺序
  （[read_pg.py:184-189](file:///home/administrator/FrontierAgent/plugins/corpus/preparation/read_pg.py#L184-L189)）。
- 空白被吞（A 类）：[pdf_reader.py:73-87](file:///home/administrator/FrontierAgent/plugins/corpus/preparation/readers/pdf_reader.py#L73-L87) `_join_spans`
  仅当两侧均 ASCII 字母数字才补空格 → CJK↔数字/拉丁边界空格被吞（`26-28 年`→`26-28年`）。属 FIX-2。

## 本阶段目标（只读复现验证，交付物）

不改生产、不 bump 版本、不写 PG、不增删单元、不做文档级硬编码。只产出：
1. **复现路径校准**：用当前 `_page_lines`+`_split_columns`（现版逻辑）重跑 company-001 p1，确认单元序列
   （`相关研究报告` 夹在 `…EPS预测值` / `67.74/70.77…` 之间）与 `evidence-diagnosis.json` 现场一致
   （证明 repro 脚本与真实入库结果吻合，后续"A→B"可比对）。
2. **改良栏重建原型（只在 scratch 脚本内）**：对 25 条 B 类 + 2 条 C 类的 8 个目标页，实现并应用：
   - **自适应 x 中心一维聚类**分栏（不写死 `390`；用可解释阈值，如页内 x 中心 gap 的核密度/分位）；
   - **跨栏/通栏单元（标题、通栏表格、页眉页脚）作为分栏边界**，不划入任一栏；
   - **窄/短浮盒（右栏小盒、图注、水印）标记为侧栏/浮块**，与正文流分离或独立成段。
   对每页给出「现状列序 vs 改良后列序」的前后 unit 序列。
3. **逐条命中表**：对每条 B 类判定 `norm(quote)` 在改良后 kept 页文本中是否连续逐字（并可复现），
   计数 25 条预期转绿数。C 类 2 条按 guide FIX-4 仅诊断（company-007/e1 是否 works 在场景/非 kept；
   company-008/a-1 属 FIX-3 页眉）。
4. **回归对冲样本**：单栏文档（docx/md/普通单栏 PDF）与通栏表格页须与现状**逐字节一致**，列作对照样本，
   作为后续 FIX-1 正式落地的回归基线。
5. 产物：`remediation-repro.json`（逐条 before/after + 命中判定）+ `remediation-repro.md`（结论 + go/no-go）。

## 不做什么（红线，照 guide §10）

- 不改金标/评分器/locator；不为了命中而硬编码某文档某页；
- 不改单元集合（增删/status/quality_report 形状）；
- 不写回 `evidence-diagnosis.json`（write-once）；不 bump 版本、不重摄入（重摄入是 Stage-1 另立项）；
- 不宣称 I3-3/M6 由此放行。

## 执行步骤

1. **资源核对**：确认 sandbox 中源 PDF 文件在位（corpus data 目录哈希文件名）且 `read_pdf` 可只读重放；
   若缺，退而用库里 kept 单元按 bbox 排序重演现状列序（仍只读）。
2. 写 `repro_column_reconstruction.py`（scratch，只读）：复用 `read_pdf`/`_page_lines`/`_split_columns`
   与 `_merge_lines`；输入目标页清单；输出每页 lines(bbox+text) → 现状序列 vs 改良序列 → 命中判定。
3. 跑脚本，产出 `remediation-repro.json`；核对 company-001 p1 现场一致，统计 25 条转绿数、C 类诊断结论。
4. 汇总 `remediation-repro.md`，给出 FIX-1 go/no-go。

## 验证门（本阶段）

- company-001 p1 复现序列与 `evidence-diagnosis.json`/§2.1 bbox 现场一致。
- 25 条 B 类中 `norm(quote)` 转绿数 ≥ 23（预留少数页因页眉/跨栏边界/deep 难页留待 FIX-3），逐条列出。
- 单栏/通栏对照样本序列逐字节不变。
- 全程只读：无 PG 写、无版本 bump、无冻结件改写。

## 后续（本阶段验收后再立项，不在本轮）

Stage-1：按复现验证的改良列序落地 FIX-1 到 `pdf_reader.py`（含 `_COLUMN_GAP_RATIO` 替换为自适应聚类、
浮块隔离、跨栏边界），bump `READER_PDF_REV` → 全量重摄入 → 重建块 → 重新冻结重绑 → 两门
（`validate_i0c_freeze.py`、`validate_i3_2_completion.py`）复跑 → 重诊断 34→≤2 → 语料族回归
`uv run pytest tests/test_corpus_*.py -q`（651 passed / 12 skipped）。独立于本轮，另行授权。