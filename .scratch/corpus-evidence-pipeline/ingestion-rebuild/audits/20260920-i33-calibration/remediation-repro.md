# FIX-1 只读复现验证结论（Stage-0）

- 生成：2026-09-20（只读；不改金标/库/版本；未写回 `evidence-diagnosis.json`）
- 脚本：`repro_column_reconstruction.py` + `remediation-repro.json`
- 结论：**单元级（后处理）栏重建不足以修复 25 条 B 类**；根因沉在 reader 行级。**FIX-1 必须走 reader 改动 + 全量重摄入（Stage-1）。**

## 1. 复核 A/B/C 分型（确认 guide）

对 34 条按 kept 页文本做 A（去空白逐字命中）/B（子句全在但被插断）/C（待核）复核：

```
A=7  B=25  C=2   （含 \n 的引文 34/34）
```
与 `remediation-guide-quote-reconstruction.md` §3 完全一致。

## 2. 单元级栏重建原型（repro 结果）

用**冻结 stored kept 单元 + 真实 bbox**，实施「全宽单元(spanner)分离 + x 中心 gap 聚类分栏 + 栏内按 y + 栏间左→右拼接」：

- 25 条 B 类中，仅 **5 条**在 `after` 文本下 `norm(quote)` 连续（A 7→12）；
- **20 条 B 类仍不连续**，部分页还出现栏顺序/反向等乱序 → **不满足「≥23」门**。

**判定**：后处理单元级重排**不足以**复现正确阅读顺序，无法作为免重摄入的替代方案。

## 3. 定位到真实行级根因（pdf_reader.py）

对 company-001 p1（华创贵州茅台双栏+右侧浮盒）实测 bbox：左栏正文段落 x≈41–381、右侧 `相关研究报告` 盒 x≈394–468（单行、短）：

1. `_split_columns`（[pdf_reader.py:117-139](file:///home/administrator/FrontierAgent/plugins/corpus/preparation/readers/pdf_reader.py#L117-L139)）要求「两栏纵向并排且重叠≥50%+超宽空隙」——**单行浮盒判不出右栏** → 返回 `None`。
2. 于是 `ordered_columns=[lines]`（单栏流），按 `(y,x)` 排序后逐行入 `prose`（[pdf_reader.py:403-465](file:///home/administrator/FrontierAgent/plugins/corpus/preparation/readers/pdf_reader.py#L403-L465)）。
3. 右栏浮盒行 `相关研究报告` 因字号较大被 `_is_heading` 判为标题 → **flush 当前 `prose`**，把左栏 `我们维持26-28年EPS预测值`（前半）与 `67.74/70.77/73.84 元…`（后半）**拆成两个 paragraph 单元**，浮盒夹在中间。
4. 到入库阶段句子已被拆开，故单元级重排无可补救。

**结论**：修复正确落点是 `_split_columns` 对「浮动侧栏/短右栏」的识别 + `_merge_lines`/prose 的**栏内合并**（使同栏上下行不因异栏行插断）。这是 reader 行级改动。

## 4. A 类（空白）归属 FIX-2

`_join_spans`（[pdf_reader.py:73-87](file:///home/administrator/FrontierAgent/plugins/corpus/preparation/readers/pdf_reader.py#L73-L87)）「两侧均 ASCII 才补空格」吞掉 CJK↔数字/拉丁空格（`26-28 年`→`26-28年`）。属 FIX-2，与栏无关；匹配侧空白等价（Step-2 已实现）只能作配套账，不能代替摄入侧保留。

## 5. go / no-go

- **no-go（单元级免重摄入路径）**：数据不支持，5/25。
- **go（reader 级 FIX-1 + 重摄入）**：确认需 bump `READER_PDF_REV` → 全量重摄入 → 重建块 → 重新冻结重绑 → 两门复跑 → 重诊断 34→≤2。
- C 类 2 条：company-008/a-1 归 FIX-3（页眉区）；company-007/e1 待单独诊断（页 7 披露句是否被清洗/跨块拆分）——按 guide FIX-4 先取证。

## 6. 红线遵守

本次全程只读：未改金标/评分器/locator、未改单元集合、未写 PG、未 bump 版本、未就地改 `evidence-diagnosis.json`。不因此声明 I3-3/M6 放行。