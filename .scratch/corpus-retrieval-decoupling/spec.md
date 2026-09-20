# 语料检索链：诊断 · 归因 · 层内解耦方案（汇总）

Status: needs-triage — 待 U 审阅
Baseline: 最新冻结修订 `i0c-r40`；诊断输入 i33 / i35 / i36 / i37 / i38
日期: 2026-09-20
性质: **本文档为方案文本。未动任何代码、未动冻结链、未动金标。**
自包含: 本文件是完整汇总，可独立阅读；可跟踪的工单视图见 `issues/00`–`issues/05`。

---

## 0. 一页速览

**现象**：I3-3 连续五轮在同一批失败目标上打转，54 → 43 → 21 → 10 → 11，数字一直在动，被重分类的始终是同一批对象。

**三条根因**：

| 编号 | 根因 | 一句话 |
|---|---|---|
| R1 | 同一个上游缺陷在下游三层轮流露脸 | 表格结构信息缺失，在 read/chunk/search 各表现为不同症状，每轮只修看得见的那面 |
| R2 | 验收信号只挂在链尾 | 判据只有端到端 EvidencePass，层内成功无法被确认，层内失败无法被定位 |
| R3 | 证据选择策略没有产品落点 | `group_hits`/`per_document=8` 只在评测脚本里；改它不沉淀产品行为 |
| — | 分母污染 | 18 条金标改写/重建永不可命中，却每轮计入分母 |

**结论**：分层没有失效。i38 的消融已经证明分层能**可归因**（13→14→16→20/24 逐层分配、4 条残留逐条点名）。失效的是「分层 → 层内可证伪判据」这一步没有落地。**分层的价值是让失败可定位，不是让改动免联动；后者是数据依赖链的固有性质，设计消不掉。**

**方案**：6 票，依赖 `00 → 01 → 02 → 03 → (04 ∥ 05)`。
排序原则：**从不动被绑字节的改动开始，把"要全量重摄入"的压到最后，一次做完。**

---

## 1. 现象与时间线

| 轮次 | 动作 | 结果 |
|---|---|---|
| i33 | 54 条缺失目标根因分类 | 20 kept + 2 清洗剔除 + **18 金标改写/重建** + 6 坐标不可映射；只改评分器匹配口径，+7 |
| i35 | 读序修复（reader-pdf-2 → reader-pdf-5）全量重摄入 | 8/8 built，4 published |
| i36 | 单一回归（唯一变量=重摄入） | `evidence_target_missing` **54→43**，但 EvidencePass 仅 **5→7/24**；并发现全链 `i0c-current` **red 8 条** |
| i37 | 全链回测 cap=8 | EvidencePass **13/24**、负例 6；桶 matched 49 / match_fail 7 / **kept_page_not_selected 21** / clean_loss 2 |
| i38 | 分层消融 | base 13 → +S3 14 → +S2 16 → **+S3b 20/24**、负例 0、剩 4 条 |

i37 的桶定义（`20260920-i37-fullchain-backtest/backtest-report.md`）：

```20:26:.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i37-fullchain-backtest/backtest-report.md
| matched | 49 | 评分命中 |
| selected_but_match_fail | 7 | 引文在选中证据里但匹配失败（locator/verified） |
| kept_page_not_selected | 21 | 引文在 kept 声明页内但未进 top-k 选中块（检索/切块丢失） |
| kept_elsewhere_page_mismatch | 0 | 引文在 kept 但不在声明页（跨页/定位差异） |
| doc_not_kept_clean_stage_loss | 2 | 引文只在非 kept 单元（清洗剔除/NOISE） |
| not_in_doc_unreachable | 0 | 全文任意处不逐字出现（金标改写/重建，检索层不可达） |
```

---

## 2. 根因

### R1 —— 同一个上游缺陷在下游三层轮流露脸

i33 §1 记录：company-003 与 industry 表格目标的 reader 单元 **`cells=[]`、`element=null`**，无结构化 cell 网格。i37 议题 B §6 自述：

```69:69:.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i37-fullchain-backtest/topic-b-structured-retrieval-ranking.md
- 依赖：I2 的 `row/col` 元数据（已完成）＋表格结构重建（合并单元格/多级表头）。**没有表头层级，行/列标签本身就不完整** ⇒ 本议题与"表格结构重建"是同一批工作。
```

这个缺失的三种下游表象：

| 下游层 | 表象 | i37 归属 |
|---|---|---|
| read | kept 页文本缺 | i36：`evidence_target_missing` 54→43 的恢复项 |
| chunk | 跨块 / 单块装不下 | 议题 A 11 条 |
| search | 排名 11–62 | 议题 B 10 条 |

### R2 —— 验收信号只挂在链尾

所有轮次的判据都是端到端 EvidencePass。i35 层内是成功的（i35 取证 34 条 kept 页内命中 32 条，i36 复算 54→43），但链尾分数不动 → 被读成"阅读层又坏了"。分层只被用于**事后解释**，没有用于**事前拦截**。

解药其实在 i37 §5 就已经写出来了（`I-A1/A2/A3`、`I-B1/B2/B3` 这些层内可测、不依赖金标的不变量），但一直只是"测试草案"，没有变成常驻测试。

### R3 —— 证据选择策略没有产品落点（制度性硬伤）

```37:50:.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/calibrate.py
def group_hits(hits, top_k, per_document):
    """First occurrence follows maximum chunk score; never duplicate a source rank."""
    grouped = {}
    for hit in hits:
        if hit.source_id not in grouped:
            if len(grouped) >= top_k:
                continue
            grouped[hit.source_id] = []
        selected = grouped[hit.source_id]
```

这一整套（含 `observations_for` 的按页聚合）**只存在于评测脚本**：

- `audits/20260920-i33-calibration/calibrate.py:37-74`
- `audits/20260920-i37-fullchain-backtest/*.py`
- `audits/20260920-i38-reshape/reshape.py`

`plugins/corpus/` 全仓搜不到 `group_hits` / `max_chunks_per_top_document`。产品侧 `service.py` 只有 `search_with_coverage` + `fetch_verbatim` 两个原语，**没有任何选择策略**。

⇒ 每轮"修证据选择层"改的是一份一次性脚本副本，产品行为零变化；下一轮换目录再抄一份。**这是"打转"最直接的放大器，比技术耦合更致命。**

### 分母污染

i33 已用全文 LCS 证实 18 条 `absent_in_extraction` 为金标改写/重建（如金标「预测值67.74」原文为「预测值**为**67.74」）。管线无论怎么修都不可能命中，却每轮计入分母，压住 EvidencePass。

---

## 3. 精确归因（失败桶 → 层 → 代码位置）

| i37 桶 | 条数 | 归属层 | 具体位置 | 为什么这层没拦住 |
|---|---|---|---|---|
| `selected_but_match_fail` | 7 | 评分器 | `scoring.py` `EvidenceTarget.matches()` | 空白规约未采纳（工作树改了，r39 绑定仍是严格码位 `bf9c8b80`） |
| `kept_page_not_selected` 议题 A | 11 | **chunk** | `chunk.py:280-351 emit_run` | 只产出单块，**没有"连续块区间"概念**，引文跨块永不可承载 |
| `kept_page_not_selected` 议题 B | 10 | **search** | `search_pg.py:41-65` + `:68-83` | 单一 `ts_rank` 排序；`SearchHit` 无结构字段，下游拿不到信号 |
| `doc_not_kept_clean_stage_loss` | 2 | **clean** | `clean.py:384-421` | 噪声判定与投影同一循环，只能看"被剔"，看不到"为什么" |
| `absent_in_extraction` | 18 | 金标侧 | — | 管线不可达，不该进管线分母 |

议题 A 的三种子机制（i37 topic-a）：③ 引文跨块 4 条、④ 只有一半在池内 4 条、⑤ 长引文块内不连续 3 条。
议题 B 的关键事实：10 条的引文**全部在候选池内**，排名落在 **11/12/13/18/48/62**——**不是 cap 问题，是排名信号问题**。

---

## 4. 六个层内解耦点

**共同判断：六处都是"接口太浅"或"职责错位"，不是"耦合太紧"。**

### 4.1 ① 证据选择策略落产品

现状见 §2 R3。目标形态：新增 `plugins/corpus/preparation/selection.py`。

```python
@dataclass(frozen=True)
class SelectionPolicy:
    top_k: int = 5
    max_chunks_per_document: int = 8     # 默认锁死 8，不得改
    expand: str = "page"                 # "chunk" | "page"
    per_source_unique_build: bool = True

def select(hits: tuple[SearchHit, ...], policy: SelectionPolicy) -> tuple[SelectedDocument, ...]:
    """按 policy 从检索命中选出证据；不做 IO，只做选择。"""
```

- 默认 policy 行为必须与 `calibrate.py` 现状**逐字节等价**
- `expand="chunk"` 是 i38 S3/S3b 已验证的候选策略，**只作为可选项，不得成为默认**
- 现在恰好有两个消费者（评测脚本 + 生产 `service.py`）⇒ **这是真 seam，不是假设的 seam**

### 4.2 ② SearchHit 加深

```68:84:plugins/corpus/preparation/search_pg.py
@dataclass(frozen=True)
class SearchHit:
    """读侧检索命中：定位 chunk 并回接活动来源（消费侧证据起点）。"""

    source_id: str
    build_id: str
    chunk_id: str
    kind: str
    title_text: str | None
    section_path: tuple[str, ...]
    unit_refs: tuple[str, ...]
    score: float
```

没有 `page`/`cells`/标签路径，于是下游只能回捞全文自己聚合：

```66:71:.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/calibrate.py
            # Pages are obtained from actual units, never copied from expected locators.
            pages = {}
            for unit in result.units:
                pages.setdefault(unit.page, []).append(unit.raw_text)
            for page, texts in pages.items():
                evidences.append(FetchedEvidence("\n".join(texts),
                    locator=(f"page:{page}",) if page is not None else (), verified=True))
```

**这就是"块选择退化成页覆盖选择"的机械原因。** 加深接口（补 `page` / `cells` / `label_path`，均带默认值）不改任何参数，只是让下游不用猜。
约束：不得 SQL N+1；须在调用方同一游标/快照内取 `corpus_units.location`。

### 4.3 ③ search 拆 recall / rank

```41:49:plugins/corpus/preparation/search_pg.py
_SEARCH_SQL = """
SELECT p.source_id,
       c.build_id,
       c.chunk_id,
       c.kind,
       c.title_text,
       c.section_path,
       c.unit_refs,
       ts_rank(c.search_tsv, q.tsq) AS score,
```

GIN 召回 + `ts_rank` 打分 + `LIMIT` 焊在一条语句里，排序策略无注入口。

```python
def recall(dsn, query, *, domain=None, ..., limit=2000) -> tuple[SearchHit, ...]   # 只筛范围 + GIN 命中
def rank(hits, *, signals: tuple[str, ...] = ("lexical",)) -> tuple[SearchHit, ...] # 排序可插信号
```

默认 `signals=("lexical",)` ⇒ 与现状逐字节一致。结构信号（`kind == "table"` + `label_path` 命中）为**可选**信号。
**注意：这改的是信号不是阈值，不违反 r39 的 `No tuning after scores`。**

### 4.4 ④ chunk 的连续块区间

```80:96:plugins/corpus/preparation/chunk.py
@dataclass(frozen=True)
class ChunkCandidate:
    """一个检索块候选（契约 ``Chunk`` 的前置投影，id 由引擎装配）。"""

    key: str
    kind: str
    unit_ordinals: tuple[int, ...]
    search_text: str
```

`search_text` 是给 `ts_rank` 打分的（要小、要纯），`unit_ordinals` 是给证据匹配的（要大到装下整条引文）。**两者方向相反却共用一个输出**——为了检索分高必须切小，切成小段就装不下引文。议题 A 的 ③④⑤ 是直接产物。

```python
def cover(self, quote: str) -> tuple[int, int] | None:
    """返回承载 quote 的最小连续块区间 [i, j]（按块序拼接、去空白后包含）。

    无区间可承载时返回 None（不得返回"最接近"的近似区间）。
    """
```

### 4.5 ⑤ 表格结构模型下沉 reader

```169:180:plugins/corpus/preparation/chunk.py
def _table_group_key(
    unit_by_ordinal: dict[int, CandidateUnit], ordinal: int, region: CleanRegion
) -> tuple[str, str]:
    """表格行分组键（页码/元素, 表序）：页界即分组边界，跨页不猜接。"""
```

加上 `chunk.py:416` 的 `context = pieces[0]`（只有首行当列头），以及：

```296:303:plugins/corpus/preparation/contract.py
class UnitLocation:
    """原文单元坐标（page/element/char/bbox/cells，架构 §4.1）。"""

    page: int | None = None
    element: str | None = None
    char_span: CharSpan | None = None
    bbox: tuple[float, float, float, float] | None = None
    cells: tuple[tuple[int, int], ...] = ()
```

`cells` **只有 `(row, col)` 数字，没有标签文本**。⇒ 议题 B 的 8 条。

目标形态（做在 reader 层，因为只有它有网格 + `native_pos` + bbox）：

```python
@dataclass(frozen=True)
class TableModel:
    page: int
    table_index: int
    header_rows: tuple[int, ...]
    def label_path(self, row: int, col: int) -> tuple[str, ...]:
        """(行标签, 列标签, 列标签父级, ...)——多级表头按层级展开。"""
    def cell_text(self, row: int, col: int) -> str: ...
```

- 表头识别必须**确定性**（不得用模型）
- 合并单元格（`table.extract()` 的 `None`）须显式处理
- `UnitLocation` 只**新增** `label_path`，不改 `cells` 语义

### 4.6 ⑥ 清洗判定依据可机读

```384:421:plugins/corpus/preparation/clean.py
def clean_reader_result(result: ReaderResult) -> CleanResult:
    """对读取结果做保真清洗：噪声判定 + 空白投影 + 全量区域台账。"""
```

噪声判定与空白投影在同一循环里完成，`CleanRegion.reasons` 只有**码**（`header_repeated_geometric`），没有**依据值**（重复几页、带边界在哪、命中哪一行）。⇒ `doc_not_kept_clean_stage_loss` 2 条无法回答"是判错了，还是本来就该剔"。

目标形态：新增 `CleanRegion.verdicts: tuple[NoiseVerdict, ...] = ()`，`NoiseVerdict(code, rule, observed, threshold)`。
**不改 `reasons` 的形状**（被多处冻结测试断言）。

---

## 5. 不该动的三处（防过度设计）

1. **`pdf_reader.py:333-345 _row_text` 的"只用换行 + 按 `native_pos` 排序"** 是**刻意的保真约束**，不是耦合（插 `" | "` / 按网格重排是历史 bug，注释已点名）。i35 的 reader-pdf-5 正是靠它修好读序。
2. **`clean.py:26-28` 的分级职责划分**：缺口是否阻断发布由 `gaps.py` 裁决，clean 只保证"每个缺口都在台账里、带坐标"。这是正确的 seam 纪律。
3. **`verify_chunk_result` / `verify_clean_region` / `contract.py` 的 `__post_init__`**：这是**现成的层内不变式门**，是白捡的 leverage。不用新建，只需要接进常驻测试，让它们从"构造时顺手跑"升级为"层的验收判据"。

---

## 6. 方案：任务清单与排序理由

### 6.1 任务清单

| 票 | 层 | 依赖 | 动被绑字节 | 触发全量重摄入 | 验收 |
|---|---|---|---|---|---|
| [00 冻结链归位](issues/00-freeze-realign.md) | 流程 | — | 是（重绑/还原） | 否 | `validate_i0c_freeze.py` exit 0 |
| [01 证据选择策略落产品](issues/01-selection-module.md) | 证据选择 | 00 | **否**（纯新增） | 否 | 与现行评测输出**逐字节等价**；默认 policy 不变 |
| [02 SearchHit 加深](issues/02-search-hit-interface.md) | search 接口 | 01 | 是（`search_pg.py`） | 否（索引未变） | 新字段与 `fetch_verbatim` 回捞结果逐条一致 |
| [03 chunk 连续块区间 + recall/rank](issues/03-chunk-cover.md) | chunk + search 排序 | 02 | 是（`chunk.py`、`search_pg.py`） | **是** | I-A1/A2/A3 + 议题 A 11 条 → matched |
| [04 表格结构模型](issues/04-table-model.md) | reader | 03 | 是（reader + contract） | **是**（与 03 合并） | I-B1/B2/B3 + 议题 B 8 条 → matched |
| [05 清洗判定依据](issues/05-clean-evidence.md) | clean | 03 | 是（`clean.py`） | **是**（与 03 合并） | 2 条 clean_loss 可机读归因 |

依赖链：`00 → 01 → 02 → 03 → (04 ∥ 05)`。

### 6.2 排序理由

原则：**从不动被绑字节的改动开始，把"要全量重摄入"的压到最后。**

- **00 先做**：i36 §5 报告全链 `i0c-current` 为 red（8 条未冻结漂移）。**基线红着跑分，任何修复增益都读不准。**
- **01 最先做**：纯新增文件，零算法改动，只是把审计脚本搬成产品 module + 参数注入。成本最低、收益最大——此后所有轮次结论可复现、可比较。
- **02 次之**：纯接口加深，不改行为、不动索引。
- **03/04/05 合并成一次冻结**：三者都改 reader/chunk 层字节 ⇒ 一次全量重摄入 + 一次双门复跑，避免"改一次 reader 就打回一轮"。
- **04 最贵**：动 reader 与 contract，必须与 03 同批。

现在的实际做法恰好相反——每轮都在改最贵的 reader/search，改一次就打回一轮。本方案把顺序倒过来。

---

## 7. 票详情

### 7.0 票 00：冻结链归位（先于一切）

i36 §5 的 8 条 red：

| # | 路径 | 漂移内容 |
|---|---|---|
| 1 | `plugins/corpus/scoring.py` | 工作树 whitespace-norm `f61573d7` vs r19/r21/r39 绑定严格码位 `bf9c8b80` |
| 2 | `plugins/corpus/preparation/readers/pdf_reader.py` | reader-pdf-5 实现（i1-r4 绑定的是 reader-pdf-2） |
| 3 | `plugins/corpus/preparation/readers/base.py` | 缺口码词表文档同步 |
| 4 | `tests/test_corpus_preparation_clean.py` | 随 reader-pdf-5 演进 |
| 5 | `tests/test_corpus_preparation_readers.py` | 同上 |
| 6 | `tests/test_corpus_scoring.py` | 随 whitespace-norm 新增用例 |
| 7 | `docs/plan/corpus-ingestion-rebuild-tasks.md` | 文档演进 |
| 8 | `docs/plan/claims-market-closed-loop-plan.md` | 同上 |

**这不是"重绑一下就完事"**，内含一个决策（见 §10）。

验收：`validate_i0c_freeze.py` exit 0（判定须用 `text.rstrip().endswith("exit=0")`，**不得用 `"exit=0" in 日志`**——失败文案会自身命中）+ `validate_i3_2_completion.py` 的 `i3_2_complete=true`。
另需单列跟踪（不在本票内解决）：M5 F3，`validate_i1_freeze.py` 对工作区 13 项失配 = i1-r3 绑定未随 I2 合法改动更新，建议随 `i1-r5` 重绑。

### 7.1 票 01：证据选择策略落产品

改动面：**新增** `plugins/corpus/preparation/selection.py`（唯一新增，无删除）。

不变量 **I-C1（策略可注入且默认不变）**：
- 正例：`select(hits, SelectionPolicy())` 输出 == 现行 `group_hits` + `observations_for` 输出
- 反例：传 `max_chunks_per_document=48` 时输出必须变化（证明参数真被使用，不是死参数）
- 反向断言：`SelectionPolicy().max_chunks_per_document == 8`

关键验收——**等价性证明**：在新目录复制 `calibrate.py`，把 `group_hits`/`observations_for` 换成 `selection.select`，与 `audits/20260920-i33-calibration/candidate_question_lexemes_or-observations.json` **逐字节比对相同**。

> ⚠ `calibrate.py` 是 write-once（`calibration-summary.json` 存在即 `RuntimeError("This bounded experiment is already complete")`）⇒ **不可原地复跑，必须新目录**。

不做：不改默认 policy 的任何数值；不把 selection 接进 `service.py` 生产路径（那是 02 之后的事）。

### 7.2 票 02：SearchHit 加深

新增字段（均带默认值，不改已有字段语义）：

```python
    page: int | None = None                        # 命中块内首个带页单元的页
    cells: tuple[tuple[int, int], ...] = ()        # 块内单元格网格坐标并集
    label_path: tuple[str, ...] = ()               # 依赖票 04，04 前恒空
```

不变量 **I-D1**：对任一 hit，`hit.page` / `hit.cells` == 由 `fetch_verbatim(hit)` 的 `units` 推导的同名字段，**逐条一致**。
反例：构造 `unit_refs` 跨两页的块，断言 `page` 取首单元页、`cells` 是并集（不取交集、不取第一单元）。
约束：不得把 `page` 从 expected locator 抄来；`snippet` 维持"非权威展示"语义。

### 7.3 票 03：chunk 连续块区间 + recall/rank 拆分

不变量：

- **I-A1（句内不切）**：块边界不得落在句子内部。近似判定：边界左端不以句末标点结束 **且** 右端不是新段落/标题起点 ⇒ 违规候选
- **I-A2（连续块可承载引文）**：对任意引文，存在连续块序列拼接后（去空白）包含它。用伪引文抽样测试（不依赖金标）
- **I-A3（超长引文）**：超单块上限时由相邻块并集承载
- **I-B3（不调 cap）**：显式断言 `max_chunks_per_top_document == 8`

反例样本：`company-008 a-2`（42 字被切在 36/37 块）、648 字长引文（macro-002 e4）。
常驻测试四条（i37 §5 草案）：`test_chunk_never_splits_inside_sentence`、`test_any_quote_within_page_is_coverable_by_consecutive_chunks`、`test_long_quote_requires_consecutive_chunk_union`、`test_cap_unchanged_by_this_work`。

目标级：议题 A 的 **11 条** → matched。

### 7.4 票 04：表格结构模型下沉 reader

不变量：

- **I-B1**：任一单元格的索引文本必须同时包含其列标签路径与行标签
- **I-B2**：问题含行/列标签词时，对应 cell 块必须进入该文档前 N 块
- **I-B3**：`max_chunks_per_top_document` 保持 8，显式断言
- **保真反例（必须同时守）**：`_row_text` 仍只用换行连接、仍按 `native_pos` 排序

回归样本：长江证券《化工专题：景气投资"十问十答"》p10 图 6 的 10 条引文，断言排名从 11–62 进入选择范围。
目标级：议题 B 的 **8 条** → matched。

不做：不用模型识别表头；不在 chunk/search 层做表格结构补偿；不改 `cells` 既有语义。

### 7.5 票 05：清洗判定依据可机读

新增字段（不改 `reasons` 形状）：

```python
@dataclass(frozen=True)
class NoiseVerdict:
    code: str                     # 与 reasons 中的码一致
    rule: str                     # 命中的具体规则名
    observed: dict[str, object]   # 依据值：重复页数 / 带边界 / 命中行 / 占比
    threshold: dict[str, object]  # 当时生效的阈值

# CleanRegion 新增
verdicts: tuple[NoiseVerdict, ...] = ()
```

不变量：

- **I-E1**：任一 `status is NOISE` 的区域，`verdicts` 非空且每条 `code` 都在 `reasons` 中
- **I-E2**：`verdicts[i].observed` 必须含至少一个可复核的数值/坐标（不得是空 dict）
- 反例：构造"重复 2 页"的页眉（低于 `_REPEAT_MIN_PAGES=3`），断言**不产生** `header_repeated_geometric`，且 `observed["repeat_pages"] == 2`

目标级：`company-007/e1`、`company-008/a-1` 给出机读归因，据此判定是"规则过宽"还是"本就该剔"。
不做：不在本票内调整任何噪声阈值（调阈值须单独立项 + 具名签认）；不改 `reasons` 形状。

---

## 8. 总验收判据

### 8.1 层内不变量（主判据，必须先绿）

| 编号 | 内容 | 归属票 |
|---|---|---|
| I-A1 | 句内不切 | 03 |
| I-A2 | 连续块可承载引文 | 03 |
| I-A3 | 超长引文由块并集承载 | 03 |
| I-B1 | 单元格索引文本含行列标签 | 04 |
| I-B2 | 结构命中进入选择范围 | 04 |
| I-B3 | `max_chunks_per_top_document` 仍为 8 | 03 / 04 |
| I-C1 | 策略可注入且默认不变 | 01 |
| I-D1 | 检索命中自带结构坐标 | 02 |
| I-E1 | 噪声判定可归因 | 05 |
| I-E2 | 依据值非空 | 05 |

### 8.2 系统级（次判据，只读诊断）

- DocRecall 不降（保持 1.0）
- 负例误报数不增加（i38 基线为 0，**不得回升**）
- `uv run pytest tests/test_corpus_*.py -q` 基线 **651 passed / 12 skipped** 不回退
- 静态门：`uv run ruff check <CI 范围>`（全仓既有告警不计）、`uv run pyright`（仅 `server/store.py` 既有缺依赖）、`python tools/import_smoke.py --stage 1|2`、`python tools/check_symbols.py`

### 8.3 分母分层（口径修正，不动门槛）

回测报告须把"管线可达"与"金标改写不可达"分列。**这不是降低门槛**，是把两类问题分开计账。18 条 `absent_in_extraction` 单列，并标注"本项不由管线修复"。

---

## 9. 风险与停止条件

| 风险 | 缓解 |
|---|---|
| 块粒度放宽导致单块过大、检索变粗 | 以 I-A2（覆盖优先）为主判据，I-A1 为质量约束；附带"块大小分布"回归 |
| 结构信号入排序改变检索语义 | 须预先声明 + 跑负例回归（6 题误报不得从 0 回升） |
| 一次性合并三处改动导致归因困难 | 每处独立产出层内不变量报告；回测按层做消融（沿用 i38 的 base/+S3/+S2/+S3b 表格形式） |
| `SearchHit` 加深后生产路径行为偏移 | 票 02 验收要求新字段与回捞结果逐条一致，冲突即失败 |

**停止条件**：任一票若需要改金标、改门槛、或改 `max_chunks_per_top_document` 默认值才能通过，则**停止并上报，不得就地调参**。

---

## 10. 需 U 决策的岔口（票 00 内含）

票 00 不是"重绑一下就完事"，它内含一个决定基线取值的决策：

| 选项 | 动作 | 后果 |
|---|---|---|
| **采纳** | 新建 `i0c-r41` 绑定 reader-pdf-5 + whitespace-norm scorer 的新字节 | 需**另起新冻结修订重建 `scoring-input-manifest.json` 血缘**（i36 §4：不得在单一回归里混入空白 scorer） |
| **不采纳** | 按 `git show HEAD:<path>` 逐字节还原工作树 | 核对 sha256 与 r39 绑定相等；`selected_but_match_fail` 7 条继续保持现状 |

这个岔口决定 02–05 的基线取值，**必须先定**。

---

## 11. 明确不做

- **不改 `max_chunks_per_top_document` 默认值 8**（r39 预先声明的实验边界；i37 议题 A §4 / 议题 B §3 双重写死）
- **不按金标词/页/行列补取证据**（评测量尺不得来自金标）
- **不改金标**（18 条改写项须走人工裁决另立项）
- **不在 chunk/search 层打表格结构的补丁**（含 `_row_text` 的字符/顺序保真约束）
- **不动 `clean.py` 与 `gaps.py` 的分级职责划分**
- **不引入第二个 widget 框架或新的存储层**
- **不以本方案放行 M6 / I4**（放行只能由独立复核 + U 具名签认给出）

---

## 12. 交付物

- 每票：层内不变量测试（常驻，入 `tests/`）+ 该票报告（落 `audits/<日期>-<票名>/`）
- 合并冻结：新修订 `i0c-r41` + `validate_i0c_freeze.py` / `validate_i3_2_completion.py` 双门复跑日志
- 回测：**新目录**产出分母分层后的报告（`calibrate.py` write-once，不可原地复跑）

---

## 附录 A：证据索引

| 主题 | 路径 |
|---|---|
| I3-3 分步根因（54 条重分类、cells=[]） | `audits/20260920-i33-calibration/i33-rootcause.md` |
| 读序修复重摄入（reader-pdf-5） | `audits/20260920-i35-reingest-pdf5/reingest-report.md` |
| 单一回归 + 8 条 red | `audits/20260920-i36-i33-reread-pdf5/i33-reread-audit.md` |
| 全链回测（桶定义） | `audits/20260920-i37-fullchain-backtest/backtest-report.md` |
| 议题 A 切块粒度（11 条） | `audits/20260920-i37-fullchain-backtest/topic-a-chunk-evidence-granularity.md` |
| 议题 B 结构化排序（10 条） | `audits/20260920-i37-fullchain-backtest/topic-b-structured-retrieval-ranking.md` |
| 分层消融（13→20/24） | `audits/20260920-i38-reshape/reshape-report.md`、`reshape-score.md` |
| 评测侧选择策略实现 | `audits/20260920-i33-calibration/calibrate.py:37-74` |
| 冻结链 | `freezes/i0c-r40.json`、`freezes/validate_i0c_freeze.py` |

## 附录 B：关键代码位置速查

| 位置 | 内容 |
|---|---|
| `plugins/corpus/preparation/search_pg.py:41-65` | `_SEARCH_SQL`：召回 + `ts_rank` + LIMIT 焊死处 |
| `plugins/corpus/preparation/search_pg.py:68-84` | `SearchHit` 接口（缺 page/cells） |
| `plugins/corpus/preparation/chunk.py:80-96` | `ChunkCandidate` 接口（检索/证据双职责冲突） |
| `plugins/corpus/preparation/chunk.py:169-180` | `_table_group_key`（只有表序） |
| `plugins/corpus/preparation/chunk.py:280-351` | `emit_run`（只产单块，无区间概念） |
| `plugins/corpus/preparation/chunk.py:408-424` | 表格分组与 `context = pieces[0]` |
| `plugins/corpus/preparation/clean.py:384-421` | `clean_reader_result`（判定与投影同循环） |
| `plugins/corpus/preparation/contract.py:296-303` | `UnitLocation.cells`（只有 `(row,col)`） |
| `plugins/corpus/preparation/readers/pdf_reader.py:333-345` | `_row_text`（保真约束，**勿动**） |
| `plugins/corpus/preparation/readers/pdf_reader.py:213-278` | `_extract_tables`（网格 + native_pos 来源） |
