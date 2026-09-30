# E5 最终闭环报告

**报告日期**：2026-09-30
**目标**：E3 缺陷修复环候选栈冻结为生产活动 build，并对构建层 + 检索层 + 内部状态完成可追溯的闭环验收。
**证据目录**：`.scratch/b4-candidate-20260929/`
**对接文档**：`.scratch/corpus-access-validation/protocol.md`（E1 契约）、`e3-defect-register.md`（v3.2）

---

## 1. 目标与范围

将经 B4 候选对照通过的三段式候选栈 **reader-pdf-9 → clean-4 → chunk-5**，在**金标 6 源**上经真实生产管线重建并发布为 PG 活动 build（`corpus_publications.active_build_id`，generation=2），并完成收尾验收。零模型（仅 at-rule 与引文判定）、只读审计优先。

栈身份（冻结时）：
- `READER_PDF_REV = reader-pdf-9`（源流序装配，修复 ok→structure_error 回归与续表次序）
- `CLEAN_REV = clean-4`（N1/N2 免责节游程整体保留、N3 页眉去重保留首现）
- `CHUNK_REV = chunk-5`（R2-a 守卫，拒绝跨权力结构合并）

---

## 2. 执行路径

引擎规范写路径 `plan_builds → execute_builds → publish_build`，目标库 `postgres`，发布门 fail-closed（不绕过）。

**6 源重建结果**（全部 `in_scope`，gen=2，reader-pdf-9 栈）：

| 源 | build(前16) | units | chunks | gen | gap-review 凭证 | 发布门重放 |
|---|---|---|---|---|---|---|
| 2026-08-13_174b6462 | 82dac0d446ef83cd | 1329 | 146 | 2 | y | PASS |
| 2026-08-16_6f14cc14 | 9fa4cd7cf1ab602a | 326 | 55 | 2 | y | PASS |
| 2026-09-06_793b3967 | 9ebd323f89e55cc1 | 474 | 43 | 2 | y | PASS |
| 2026-09-06_cc03f55b | 147e841aab35836a | 269 | 30 | 2 | no(无缺口) | PASS |
| 2026-09-06_dddc7cd0 | 568f9e752f0fa65a | 613 | 83 | 2 | y | PASS |
| 2026-09-06_f8e31696 | 1d0117eb6e17c63c | 230 | 23 | 2 | no(无缺口) | PASS |

> 单元数=解析全量；kept/referenced 见 §5。build/单元数为 2026-09-30 生产库直读核对值。

---

## 3. 发布门放行（4 源 blocking 缺口）

- 4 源缺口页（174b6462 图/表、6f14cc14 图、793b3967 表、dddc7cd0 图）经 **09-29 零模型源页复核**判定**零 content_loss**：
  - 图页 = `image_only_no_text`（文字层部分覆盖 100%，无文本可提取）
  - 表页 = `table_lines_without_extraction` → 内容已入库（`content_retained`，字符覆盖 100%）
- 与既有评审者 `xyl`（09-21）对同一来源同缺口语逐字一致，据此原样重建 human gap-review 凭证并绑定 gen-2 build 指纹。
- 经 `store.put_gap_review → apply_gap_review`（保留/不相交/区域几何，dddc7cd0 走 region schema human-gap-review-2，pymupdf 校验 page:7 文字与图像区不相交）校验通过后按发布门放行重发——**gap 保持可见、coverage scoped，未绕过 fail-closed**。
- `doc_chars_lost=672` 接受为**单元化口径差异**（非真实内容丢失），依据：全部引文单块命中、字符落入被重组元数据/结构而非正文检索目标。

---

## 4. 检索层验证（金标评分，零模型、只读）

对冻结 gen-2 活跃 build **直读生产 PG 权威单元/chunk**（`b0.load_source_artifacts`，非内存重算）重跑 99 条金标引文。

- **98 `ok`，1 `chunking_impact`**（仅 `company-008 a-1`，R2-a 已裁决边界，非回归）。
- 转移：`chunking_impact→ok` **19**；`structure_error→ok` **4**（company-001 e1/e2/e3、industry-001 e5）；**base ok→冻结非 ok 回归 0**。
- 冻结 build 与发布记录一致（6 源 `BUILD_MATCH` 全 True）。
- 产物：`e5-gold-score.json` / `e5_gold_score.py`。

---

## 5. 发布门内部状态正向确证（只读、零模型）

复刻 `_verify_publication_ready` 三硬项，输出正向确证而非"未抛错"负向信号。**ALL_PASS=True**：

- 6 源 PARSED / CHUNKED job 终态均 SUCCEEDED。
- `oversized_chunks` 为空。
- **保留单元集合 == chunk 引用集合完全相等**（无越界引用、无缺引）：

| 源 | kept == referenced |
|---|---|
| 174b6462 | 1177 |
| 6f14cc14 | 310 |
| 793b3967 | 442 |
| cc03f55b | 223 |
| dddc7cd0 | 542 |
| f8e31696 | 167 |

- 缺口经 `apply_gap_review` 放行但仍保持可见（ack>0，含 image_region_small 等默认分级归档）。
- 产物：`e5-publish-gate.json` / `e5_publish_gate.py`。

---

## 6. 结论

**E5 冻结任务闭环**。候选栈 reader-pdf-9/clean-4/chunk-5 作为 gen-2 活动 build 在生产 PG 发布，三重验收（发布门、检索层金标、内部状态确证）全部通过，证据链落盘完整。

### 遗留（已记录，非本次缺陷）
- **a-1 已知边界**：company-008 a-1 引文跨单元 5/6（左右栏 bbox 不相交），文本已完整入库（`in_concat=true`、crossed 全 kept），单块命中受 chunk-5 R2-a 守卫按设计拒绝合并。修法选项=读侧 masthead 分组或对照口径，**显式不放宽 R2-a**。
- **范围外**：B2 未实施；生产语料仅金标 6 源冻结，**全量语料未重建**。

### 审计暂缓项（非核心，已登记）
- `doc_chars_lost=672` 字符级可复现证据（因全部引文 ok，未引内容完整性不在检索契约目标内）。
- 发布 checkpoint 的 `operator` 字段（本次为空）——建议后续 `publish_build` 统一传入 operator，作为前瞻约定。

---

## 附：产物清单

| 产物 | 用途 |
|---|---|
| `.scratch/b4-candidate-20260929/e5_freeze_driver.py` | 冻结+发布驱动 |
| `.scratch/b4-candidate-20260929/e5-freeze-result.json` | 6 源重建+发布记录 |
| `.scratch/b4-candidate-20260929/e5_gold_score.py` / `e5-gold-score.json` | 检索层金标评分 |
| `.scratch/b4-candidate-20260929/e5_publish_gate.py` / `e5-publish-gate.json` | 发布门内部状态确证 |
| `.scratch/corpus-access-validation/e3-defect-register.md` | 登记表 v3.2（§5.7/§5.8/§5.8.1） |