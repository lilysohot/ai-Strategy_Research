# B4 分项对照（对照设施 + B1-only）—— 具体实施方案

> 依据：docs/data_clean_dos/02-fragment-chunking.md §B4；B0 F1：company-004 五行正文 = 同一段硬换行，
> 因 `_merge_lines` 未并段 → 一行一个 paragraph unit → chunk 判为 heading（`chunking_impact` 20 条，
> heading 13）。
> 范围（用户裁决）：对照设施 + B1-only；落地 = reader 模块内升 revision（gate 切换）。
> 硬约束：不重建生产语料、不切发布指针、不混读旧 build、对照通过才保留 `reader-pdf-7`。

---

## 前置条件（实施第 1 步核对，不满足则重建步降级为「交付就绪命令」）

1. **源归档可用性**：6 个受影响源 `corpus_sources.archive_path` 是否解析到 `data/corpus-archive/…`。
   SQL：`SELECT source_id, archive_path FROM corpus.corpus_sources
   WHERE source_id LIKE '%dddc7cd0' OR source_id LIKE '%6f14cc14' OR source_id LIKE '%793b3967'
   OR source_id LIKE '%174b6462' OR source_id LIKE '%3f0c0f1e' OR source_id LIKE '%...（第6源SQL查实）';`
   再核对文件存在。现状：`data/corpus-archive` 仅 3 个 .md，58 个 PDF 在 `data/corpus/`。
2. `i2_sandbox_corpus` 可写（`repository_pg.py` L239 唯一写入目标，不碰生产）。
3. pymupdf 1.28.2 可用（已确认）。

---

## 阶段 A — 对照设施

### A1. 参数化 b0_attribution.py 支持按 build_id 打分
文件 `.scratch/b0-attribution-20260928/b0_attribution.py`

- 新增签名（抽 `main()` 后半段 L325–L478）：
  ```python
  async def run_attribution(build_map: dict[str, str] | None = None) -> dict:
  ```
  `build_map` = `{gold_source_id: build_id}`。
- `resolve_sources`（L95）改为：查活动 build 后，若 `build_map` 命中该 gid，则用其值覆盖返回的 `build_id`。
- CLI 增参 `--build-map PATH`（json `{gid: build_id}`）→ 传给 `run_attribution`；缺省 `build_map=None` 走基线（行为不变）。
- 复用（不改）：`norm/hash8/load_gold/load_source_artifacts/attr_target/crossed_units`、`DenyModels` 零模型陷阱、
  `PGOPTIONS=default_transaction_read_only=on` + 断言。

### A2. 薄对照脚本 —— 新建 `.scratch/b4-compare/b4_compare.py`
- 调用 `run_attribution({})`（baseline）+ `run_attribution(build_map)`（candidate），写 `b4_compare.json`。
- 输出表（判定口径与 b0 一致）：
  | 组 | 指标 | 通过判据 |
  |---|---|---|
  | 准备层 | 非空白字符覆盖 / 阅读序连续 / chunk kind 分布 / 短块比例 | 覆盖不降、结构 kind 说明来源 |
  | 端到端 | `ok` 数 / `chunking_impact` 数 | `ok`↑、`chunking_impact`↓ |
  | 负向 | `source_text_missing` / `structure_error` | **必须 ==0 / 不增长** |
- `main()` 读 `--baseline-json --candidate-json` 或直接两次 `run_attribution`。

---

## 阶段 B — B1-only 候选（plugins/corpus/preparation/readers/pdf_reader.py）

### B1. `_Line` 保留 block 身份
```python
@dataclass
class _Line:                       # L44-51
    text: str
    bbox: BBox
    size: float
    block: int = -1                # NEW：PDF 原生 block 序号，仅 _page_lines 填
```
`_page_lines`（L262-287）：`for bi, block in enumerate(payload.get("blocks", [])):`，`_Line(..., block=bi)`。
其余 `_Line(...)` 构造点不变（默认 -1）。

### B2. gate 感知合并 —— `_can_merge`
把 `_merge_lines`（L315-334）的内联判定抽为：
```python
_PDF_READER_GATE = os.environ.get("PDF_READER_GATE", "baseline")   # 模块级

def _can_merge(prev: _Line, line: _Line) -> bool:
    prev_height = prev.bbox[3] - prev.bbox[1]
    gap = line.bbox[1] - prev.bbox[3]
    horizontal = min(prev.bbox[2], line.bbox[2]) - max(prev.bbox[0], line.bbox[0])
    geom = prev_height > 0 and gap < prev_height * 0.8 and horizontal > 0
    if _PDF_READER_GATE == "baseline":
        return geom
    # candidate：同 block 是强正向信号；style 近似防把价格框/脚注并入正文
    same_block = prev.block >= 0 and prev.block == line.block
    style_ok = abs(prev.size - line.size) <= max(0.5, prev.size * 0.1)
    return geom and same_block and style_ok
```
`_merge_lines` 内换成 `if merged and _can_merge(prev, line): merged[-1].append(line)`。
> 说明：candidate 比 baseline **更保守**——当正文五行同 block 时几何已触发，直接并段，避免逐行成 heading；
> 不同 block 的相邻行仍各成段，守住「不跨 block 无条件并段」（B1.1）。该门限以 company-004 fixture 校准。

### B3. revision gate
- 常量改为按 gate 选：`_REV_BY_GATE = {"baseline": "reader-pdf-6", "candidate": "reader-pdf-7"}`；
  `_extractor_rev()`（L229-231）当前读 `READER_PDF_REV`，改为 `f"{_REV_BY_GATE[_PDF_READER_GATE]}+pymupdf-{pymupdf.__version__}"`。
  `README_PDF_REV` 常亮保留为 `reader-pdf-6`（向后兼容引用）。
- 因 build_id 绑定 parse_rev，候选/基线 build 天然不同，隔离。

---

## 阶段 C — 候选构建与对照运行（隔离库）

- 入口：`engine._build_and_stage`（L788）/`_execute_one`（L903）；读取 `archive_root/source.archive_path`（L969）。
- 候选：`PDF_READER_GATE=candidate` + 受影响源 list + `--archive-root data/corpus-archive` → 写入 `i2_sandbox_corpus`，
  得候选 build_id（rev=`reader-pdf-7`）。
- 基线：`PDF_READER_GATE=baseline` 同源重放 → 基线 build_id（rev=`reader-pdf-6`）。
- 具体命令与 manifest 复用 .scratch/corpus-evidence-pipeline 既有的引擎调用方式（实施时按现有 ingest 入口拼接）。

---

## 阶段 D — 验证

- **新建单测** `plugins/corpus/tests/test_pdf_reader_merge.py`：
  - fixture = company-004 五行正文（同 block，字号≈中位数的硬换行序列）。
  - `_PDF_READER_GATE="baseline"` 时：断言五行仍各成段（旧行为，防回归）。
  - `_PDF_READER_GATE="candidate"` 时：断言并成 1 段（`kind=paragraph`），`_is_heading` 不对整段误判。
  - 用例：不同 block 的两行在 candidate 下仍不并段（守住「不跨 block 无条件并段」）。
- **复用不变量**：`verify_clean_region`（clean.py L161）非空白覆盖；A4 replay 四集合指标。
- **金标 before/after**：`b4_compare.py` 确认 `chunking_impact` 20→降，`ok` 升，`source_text_missing`==0、
  `structure_error` 不增，非空白字符覆盖不降。

---

## 阶段 E — 版本 / 发布约束

- build_id 绑定 parse_rev → 按 build_id 读取新旧不混读；候选仅存 `i2_sandbox_corpus`。
- 对照通过：保留 `reader-pdf-7` 候选供后续发布决策（不进发布指针）；未通过：gate 归 baseline，候选不保留。
- **本轮不重建生产语料、不切指针、不设 `A4_ENFORCE`**；仅产出对照证据（B4.2/B4.3 语义）。

---

## 端到端验证命令

1. `uv run ruff check . && uv run ruff format .`
2. `uv run pyright`
3. `uv run pytest plugins/corpus/tests/test_pdf_reader_merge.py -q`
4. 基线复跑：`uv run python -m b0_attribution`（`--build-map` 缺省）应复现 75/20/4/0/0。
5. 候选对照：`uv run python .scratch/b4-compare/b4_compare.py --candidate-map <json>` 输出量表并满足阶段 D 判据。
6. **若前置条件 1 不满足**：交付 A1/A2 + B1/B2/B3(gate) + D 单测 + 就绪命令，重建步标「待归档环境」。