# 语料检索链：诊断 · 归因 · 层内解耦方案（汇总）

Status: needs-triage — 待 U 审阅
Baseline: 最新冻结修订 **`i0c-r41`**（scoped：仅绑空白规约 scorer + i40/i41 诊断证据；其余漂移登记为 t6）
诊断输入: i33 / i35 / i36 / i37 / i38 / **i40 / i41 / i42**
基线漏斗: 见 §13（79 目标嵌套累计，2026-09-21 实测；方案后须**同口径**对比）
总体目标: **M6 放行**（`docs/plan/corpus-ingestion-rebuild-tasks.md`:260）；本方案定位见 §6.0
日期: 2026-09-20 起，**2026-09-21 更正**
性质: 本文档为方案文本。**未动任何代码、未动冻结链、未动金标。**
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

> **最新状态（2026-09-21 更正，详见 §14）**
>
> 1. **票 01 / 02 / 04 已被提前实现**；票 03 只实现了 `rank_hits`（`chunk.cover` 未做）；**票 05 已实现**（2026-09-21，§7.5）。
> 2. **出现了本方案没有的 band 路线**：i40（17/24）、i41（**19/24**，topic A 11/11 全中），
>    只存在于诊断脚本、**未落产品**；产品路径（i42）为 **12/24**。详见 §10.5。
> 3. **冻结链已推进到 `i0c-r41`**（scoped）：17 处红 → **14 处**；剩余登记为 **t6 待办**；
>    第二道门（I3-2）**仍红**（`scoring-input-manifest.json` 血缘未重建）。
> 4. 复测结论：**代码门 6/6 全绿、冻结门 2/2 全红**——问题不在代码质量，在"入链"。
> 5. **本方案全部落在 EvidencePass 侧**；按 M6 对账，**唯一零进展的是负例（恒 6）**，不在本方案范围内（§6.0）。

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

## 6. 方案：在总体目标中的位置、执行清单与启动条件

### 6.0 本方案在总体目标中的位置（先对账，再动手）

总体目标 = **M6 放行**（`docs/plan/corpus-ingestion-rebuild-tasks.md`:260）。逐条对账：

| M6 判据 | 现状 | 状态 | 归属 |
|---|---|---|---|
| 逐类三指标达冻结目标 | 最好 19/24（band，未落产品）；产品 12/24；门槛 23/24 | **有进展**（13→19） | 本方案票 03/04/05 |
| 关键引用题 100% | 未达 | 进行中 | 同上 |
| **已知伪引用负例为 0** | **恒 6**（i33→i42 五轮不变） | **零进展** | **不在本方案范围，须另立** |
| 旧检索/财务基线不退化 | 未验 | 未开始 | 超出范围 |
| 格式覆盖 PDF/DOCX/MD | 已达标（r34/r37） | ✅ 完成 | — |
| I3-7 对 I3-6 冻结版本重验 | I3-6 未定版 | 未开始 | 依赖本方案完成 |

**两条结论**：

1. **本方案只覆盖 EvidencePass 侧**（票 03/04/05）。它不改善负例，也不改善旧基线非回归。
2. **按"补短板"原则，负例（唯一零进展）应优先。** 本方案的 **票 04-S2 可并行启动**（一行成本、只消除已知回归），
   但 **票 03/05 不应挤占负例的资源**。

> 排除项说明：**t6 重绑与 I3-2 门属"记账"，不是能力**——它们不改善任何一项 M6 判据，应随能力改动合并执行，
> 不单独立项。`r41` 的定位是"恢复对账能力"，不是目标达成。

### 6.1 执行清单（含启动条件）

> 原方案按"从零开始"编写；票 01 / 02 / 04 主体已被提前实现，故以**当前状态**为起点重排。

| 步骤 | 内容 | 对应票 | 启动条件 | 阻塞 |
|---|---|---|---|---|
| **S1** | 清账：绑定当前字节 + **12/24 失败结果**；重建 `scoring-input-manifest.json` 血缘 | 00 | ✅ `r41` 已建（scoped），可作基线锚点 | 剩 14 处 t6 + I3-2 门 |
| **S2** | ✅ **已完成**（2026-09-21，`audits/20260921-s2-injection-judgment/`）：注入对召回零贡献（S1 66→66），但**承载排名价值**（去注入 EvidencePass 12/24→2/24） | 04 副作用 | ✅ 已执行（`self_check_reproduces_i42: true`） | 无 |
| **S3a** | ❌ **否决**（S2 判定）：label_tsv 隔离后排名机制不变，标签词元退出 `ts_rank` ⇒ 同崩至 ~2/24 | 04 | 已判定 | §10.2 |
| **S3b** | ❌ **否决**（S2 判定）：删除注入摧毁排名，EvidencePass 12/24→2/24 | 04 | 已判定 | §10.2 |
| **S4** | ~~`chunk.cover`（议题 A 的 11 条）~~ | 03 后半 | **已闭合**：归属裁决选 A，band 落产品承载"连续区间"，`cover` 作废（§10.5） | 无 |
| **S5** | 清洗判定依据（**已完成**，2026-09-21，`audits/20260921-s5-noise-verdict/`）：`NoiseVerdict` + `CleanRegion.verdicts` 落产品，I-E1/I-E2 常驻测试；目标级归因：**e1→`disclaimer_section` 规则过宽（粒度）**、**a-1→页眉本就该剔、损失归引文边界（另立议题）**；不调阈值 | 05 | ✅ 已解除阻塞：i37 成立，票 05 有活干；**e1→`disclaimer_section` 粒度、a-1→表头/正文边界（另立议题）** | 无（已完成） |
| **S6** | band 落产品回测 | 01 后半 | ✅ **已完成**（2026-09-21，`audits/20260921-band-product/`）：EvidencePass 12/24→**17/24**，负例 6 不回升，`self_check` 全绿 | 无 |

> **新增待立议题**（S2 判定派生）：**company-003 光力科技**——文档级召回问题，注入改法与 band **均不能修复**（§10.2）。

**已完成的票**（不再执行，仅作复核基线）：

| 内容 | 对应票 | 证据 |
|---|---|---|
| `selection.py` 落产品（含 `select_structural`） | 01 | `selection.py:54`、`:85` |
| `SearchHit` 加深（`page`/`cells`/`label_path` + `_enrich_hits`） | 02 | `search_pg.py:94`、`:105` |
| 表格结构模型下沉 reader（`TableModel.label_path`） | 04 主体 | `pdf_reader.py:146`、`:519-533`、`contract.py:309` |
| `rank_hits` 拆分（global 变体已弃用） | 03 前半 | `search_pg.py:162` |

### 6.2 启动结论（S2 完成后更新）

**S2 已完成，结论是"改道"**：S3a / S3b **双否**（§10.2）⇒ **票 04 的副作用分支闭合**，
改道 **band 落产品（§10.5 选项 A）**。原判据"注入价值可疑"被证伪——注入在**排名侧是必需的**（去注入 12/24 → 2/24）。

**当前可启动的只剩 band**：i41 已在注入存在的池上验证 **19/24**，且不改 schema、不重摄入、不删注入。
**S4 与 S5 各有前置阻塞**（§10.4 归因未定 / §10.5 band 归属须 U 定）。

**更新（2026-09-21，band 落地后）**：band **已完成**（§10.5 / §6.1 S6，17/24）；S4 随归属裁决**闭合**；
S5 前置归因**已定**（§10.4：i37 成立，票 05 有活干）——当前清单只剩 **S5（票 05 清洗判定依据）** 与 **S1（清账，堵在 t6 + I3-2 门）** 两项待办。

**再更新（2026-09-21，票 05 落地后）**：**S5 已完成**（§7.5 / §6.1，`audits/20260921-s5-noise-verdict/`）——
`NoiseVerdict`/`verdicts` 落产品 + I-E1/I-E2 常驻测试；目标级归因 e1=规则过宽（`disclaimer_section` 粒度）、
a-1=页眉本就该剔（损失归引文边界，另立议题）。**当前待办只剩 S1（清账，堵在 t6 + I3-2 门）。**

**再更新（2026-09-21，S1 清账落地后）**：**S1 已完成**（票 00，`audits/20260921-s1-freeze-realign/`）——
U 确认整体采纳工作树为权威版本，新建 **`i0c-r42`** 完成 t6 重绑（I3-3 重塑 + reader-pdf-5 + 随行测试 +
回归脚本 + docs 全部钉当前字节，`i1-r4` readers 经 supersession 覆盖）；
`scoring-input-manifest.json` **血缘重建**（`lineage.scorer.sha256`=空白规约 `f61573d7`、`status`=frozen）；
两道门全绿：`validate_i0c_freeze.py` exit=0、`validate_i3_2_completion.py` **`i3_2_complete=true`**（10/10 pass）；
语料族回归 **731 passed / 12 skipped** 不回退。**当前方案全部待办已清零。**

**按 M6 判据**：负例（6 → 0）是唯一"无论怎么优化 EvidencePass 都绕不过"的硬阻断
（`scoring.py:279` `max_false_positives = 0`），应优先。**若以本方案为主线，等于把负例继续推后**——
两者都要做，但有先后，须 U 明确。

**再更新（2026-09-21，R3 闭环 / r43 后，U 指令"先解耦、后负例"落地）**：**R3 闭环完成**
（§4.1 seam + §14.4 判断 4，`freezes/i0c-r43.json`）——生产 `service.py` 新链（`search` /
`search_with_coverage`）接入 `selection.select_structural`（**perdoc**，i42 产品路径逐字节一致）：
候选池 `max(limit, 40)` → `query_lexemes`（只依赖查询文本）→ 选择 → 截断到 `limit`；`selection.py`
首次入链（此前 UNBOUND），`_RankedHit` 协议只读化后 pyright 全绿。按 U 2026-09-21 决策，生产默认形态为
**perdoc select_structural**；band（`select_band`）保持产品代码与测试、**未接入生产默认**。
回归 731 passed / 12 skipped；`validate_i0c_freeze.py` exit=0。**解耦主线收尾**；负例议题
（M6 负例 6→0，§6.0）按 U 2026-09-21 二次复核指令**重新立项**（已解除此前推迟，见 §14.5 / `issues/06`）。

### 6.3 排序理由（修正版）

原原则"从不动被绑字节的改动开始"已失效（改动既成事实）。当前原则：

> **先还账、再花钱判定、最后才付大成本；同时不与 M6 短板抢资源。**

- **S1**：账实不符时，任何"变好/变坏"都读不准；新改动还会叠加在未登记的旧改动之上。
- **S2（已完成）**：把"要不要付 schema 改造 + 全量重摄入的代价"压缩成**一次一行实验**。结论：注入对召回零贡献（S1 66→66），但**承载排名价值**（去注入 EvidencePass 12/24→2/24）——原"注入价值可疑"的猜测只对了一半（召回侧成立，排名侧错误）。
- **S3a/S3b 均已否决**（§10.2）：两条路都让标签词元退出 `ts_rank`，摧毁排名。改道 **band 落产品（§10.5 选项 A）**——注入存在池上已验证 19/24，不改 schema、不重摄入。
- **S4/S5 最后**：两者都触发全量重摄入，且与 `ts_rank` 副作用无关，可合并成一次重摄入。

对照另两条路：**直接删注入**（可能损失表格召回，是赌）；**直接改 schema**（若注入本就无效则白付一次重摄入）。
本方案用一行成本先消除这个不确定性。

---

## 7. 票详情

> **实现现状（2026-09-21 实测，详见 §14.3）**：票 01 / 02 / 04 **已落地**；票 03 **部分落地**
> （`search_pg.rank_hits` 已实现且 global 变体已被 i42 弃用，`chunk.cover` **未实现**）；**票 05 已落地**（§7.5）。
> 以下各票的"验收"按方案原文保留：对**未落地**部分是待办判据，对**已落地**部分是复核基线。

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

> ⚠️ **启动前必读**：本票与 i40/i41 的 **band 路线重复**（同一问题的两个落点）。
> **须先按 §10.5 定归属**——若选 A（band 落产品），本票的 `cover` 部分**作废**；
> 只有选 B 才照下面实施。`rank_hits` 部分**已完成**，不受影响。

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

**实现情况（2026-09-21 已完成，`audits/20260921-s5-noise-verdict/`）**：

- 产品：`clean.py` 新增 `NoiseVerdict`（`code`/`rule`/`observed`/`threshold`）与
  `CleanRegion.verdicts`；各 NOISE 分支（页眉/页脚带、目录、免责声明标题/整节/前缀、
  分析师名单、合成缺口 `image_region_small`）填充机读依据；`verify_noise_verdicts`
  构造后 fail-closed 校验 I-E1/I-E2。不改 `reasons` 形状、不调任何阈值。
- 判定语义：NOISE 区只保留已触发（`code ∈ reasons`）的 verdict（I-E1）；KEPT 区可含
  "评估过但未越阈值"的近似命中（如页眉只重复 2 页，`observed["repeat_pages"] == 2`）。
- 测试：`tests/test_corpus_preparation_clean.py` 新增 3 条（I-E1/I-E2 全规则遍历 +
  `verify_noise_verdicts` 拒绝破坏 + 2 页页眉反例）；`tests/test_corpus_*.py` 731 passed / 12 skipped。
- 目标级归因（§10.4 目标重放，8 个命中单元 `status_match` 全真）：
  **e1 = 规则过宽（`disclaimer_section` 粒度）**——ord=717 整段分析师声明被剔，
  但同一单元含实质事实句（华创云信 4.06% 持股）；
  **a-1 = 页眉本就该剔**——标题跨 p1–p7 重复 7 次 ≥ `_REPEAT_MIN_PAGES=3` 且处页顶带，
  规则按定义正确触发；损失来自引文横跨 NOISE/kept 边界，另立议题。
- 价值口径：票 05 只加机读记账，**不提升 EvidencePass**；价值在归因与后续阈值立项的依据。

---

## 8. 总验收判据

**同口径总判据见 §13 的漏斗对比**（逐层存活 + 桶分布双表）。

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
| I-E1 | 噪声判定可归因 | 05 ✅（`verify_noise_verdicts` + 常驻测试） |
| I-E2 | 依据值非空 | 05 ✅（同上） |

### 8.2 系统级（次判据，只读诊断）

- DocRecall 不降（保持 1.0）
- 负例误报数不增加（i38 基线为 0，**不得回升**）
- `uv run pytest tests/test_corpus_*.py -q` 基线 **716 passed / 12 skipped**（2026-09-21 复测；旧记录 651 / 12）不回退
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

## 10. 需 U 决策的岔口

**原岔口（"采纳 vs 还原"）已不适用**——票 01/02/04 已被提前实现并跑出结果（§14.3），不再是"未验证的漂移"。当前实际决策如下。

### 10.1 顺序：先锚定再修，还是先修再绑？

| 选项 | 动作 | 代价 |
|---|---|---|
| **A（推荐）** | 先绑 `r41`（记录 reader-pdf-6 / chunk-3 / index-4 / `selection.py` **+ 失败结果 EvidencePass 12/24**）→ 链条转绿、现状可复现 → 再修副作用出 `r42` | 多一次冻结成本（生成器 + 归档 + 双门） |
| B | 先修 `ts_rank` 副作用，修完一次性绑 | 修的过程中**无可比基线**（12/24 来自不可复现字节），且 17 处红里混着 6 类来源不同的改动，无法判责 |

依据：冻结链**允许失败修订入链**（r40 自身即 `passed=false`、`i33_released=false`）——它是"字节 ↔ 结果"对应表，不是成功登记簿。

### 10.2 `ts_rank` 副作用的修法形态（**已由 S2 判定：原前提证伪，S3a/S3b 双否**）

**原前提（已证伪）**：`chunk._table_row_pieces` 把结构标签前缀**无条件拼进 `search_text`** ⇒ 进 GENERATED 列 `search_tsv` ⇒ 改变 `ts_rank`。原假设是标签**稀释**正文词频、压低 `ts_rank`。

**S2 判定实验**（`audits/20260921-s2-injection-judgment/`，读侧虚拟重建，0 model calls，`self_check_reproduces_i42: true`）：

| 侧 | 结论 |
|---|---|
| 召回（S1_candidates） | 注入**零贡献**：66 → 66，0 条目标掉失（§6.3 对召回侧的怀疑成立） |
| 排名（S2→S4 / EvidencePass） | 注入**承载排名价值**：去注入后 S2 60→30、S3 51→18、S4 44→13，EvidencePass **12/24 → 2/24**（31 条 matched → kept_page_not_selected） |
| 机制 | 标签不是稀释，而是给表格块**注入额外匹配词元抬高 ts_rank**（norm=0 不受文本长度稀释） |
| 负例误报 | 6 → 6，不回升（符合约束） |

**决策（S3a/S3b 双否，改道 band 落产品）**：

| 修法 | 判定 | 依据 |
|---|---|---|
| a（label_tsv 隔离、`ts_rank` 只看 `search_tsv`） | **否决** | 排名机制不变（标签词元退出 `ts_rank`），与直接去注入等价 ⇒ 同崩至 ~2/24 |
| b（标签不进索引文本，查询侧独立通道） | **否决** | 同样让标签词元退出 `ts_rank`，排名侧崩塌同 a |
| c（保留注入但 `setweight(..., 'D')` 降权） | **否决** | 排序仍被改变，且 S2 显示排序依赖注入词元 ⇒ 引入新回归风险 |
| **S3b（直接删除注入）** | **否决** | S1 保持（66→66）但 EvidencePass 12/24→2/24，摧毁排名 |

**改道**：`ts_rank` 副作用不再单独修。**band 落产品（§10.5 选项 A）为现成路径**——在注入存在的池上已验证 19/24，不删除注入、不改 schema、不重摄入，顺带规避本副作用议题。

**三条路线实测对照**（同一 79 目标口径）：

| 配置 | EvidencePass | 说明 |
|---|---|---|
| 无注入 + perdoc 选择 | **2/24** | ≈ S3a/S3b 实施后的等价状态 |
| 有注入 + perdoc 选择（i42，**现状产品**） | **12/24** | 当前产品路径 |
| 有注入 + band 选择（i41，**未落产品**） | **19/24** | §10.5 选项 A |

⇒ **注入贡献 +10、band 贡献 +7，两者互补、都要**。这也从数据上支持"不改注入、改选择层"的改道。

**判据教训（须作为后续实验规范）**：本次实验方法规范（读侧虚拟重建 + `self_check_reproduces_i42: true` 自检），
但**初版判定只看 `S1_candidates` 就得出"支持删除注入"**，与 S2 起三层的暴跌方向相反。
根因：**S1 是集合语义（引文在/不在候选集），而注入的作用在排序语义**。
⇒ 判定"某改动是否有价值"**必须看 `S2_doc_topk` / `S4_matched`（端到端）**，**不得用单层指标下结论**。

**company-003（光力科技）须单独立题**：注入对**有表格的文档**是净增益（额外匹配词元抬高 `ts_rank`；
`norm=0` 不受文本长度稀释），对**表格少/无表格的文档**（如光力）形成**相对劣势** ⇒ doc rank 6、掉出 top-5、6 条证据全丢。
该问题属**文档级召回**，**band 无法修复**（band 只改块内选择），须另立议题。

> **I-B1 表述修订**（a、b 均否决后不再强制）：原约定"a、b 会让标签不在索引文本里，须把表述改为'可被结构信号召回'"——该约定随 a/b 否决而作废，I-B1 维持现状（索引文本含标签）。

### 10.3 空白规约 scorer 的口径

`validate_i3_2_completion.py` 当前红，根因即此项：`scoring-input-manifest.json` 的 `lineage.scorer.sha256`
与实际 `scoring.py` 不符（§14.2）。若采纳空白规约语义，须**另起新冻结修订重建 manifest 血缘**（i36 §4）。

### 10.4 `company-007/e1`、`company-008/a-1` 的归因（**已裁定：i37 成立，i42 为误标**）

| 来源 | 判定 | 含义 |
|---|---|---|
| i37 `backtest-report.md` | `doc_not_kept_clean_stage_loss` | 引文只在**非 kept 单元**（清洗剔除） |
| i42 `backtest-report.md` | `not_in_doc_unreachable` | 全文任意处**不逐字出现**（金标改写/重建） |

两个相反结论。**若是后者，方案票 05（清洗判定依据）就是白做**——必须先定。

**裁定（2026-09-21，当前活动语料 index-4-zhcfg-2 实测，`audits/20260921-2targets-attribution/`）**：
**i37 成立，i42 为误标**——i42 漏斗只检查 kept 单元（`in_kept_any`），从未检查全文（含非 kept 单元），
故 `not_in_doc_unreachable` 命名失真。两条引文都**逐字存在于全文的非 kept（NOISE）单元**：

| 目标 | 命中单元 | status / reasons | 判定 |
|---|---|---|---|
| company-007/e1 | 1 个：ord=717 p7 | `noise` / `disclaimer_section` | 整段免责声明被 NOISE，但其中含实质内容（华创云信 4.06% 持股事实） |
| company-008/a-1 | 7 个：标题"贵州茅台（600519）2026 年中报点评"跨 p1–p7 | `noise` / `header_repeated_geometric`（+`heading_by_font_size` p1） | 引文前半在 NOISE 表头、后半"强推（维持）"在 **kept** 单元 ord=6 p1 ⇒ 引文横跨 NOISE/kept 边界 |

**结论**：票 05 不白做——**e1 的 lever 是 `disclaimer_section` 判定粒度**（整段免责声明一锅端，吞掉实质事实句）；
**a-1 的 lever 是表头 NOISE 与正文评级的边界**（更接近引文粒度/表归属问题，可能须另立议题，见 §13.1 note）。
i42 `recall-funnel.json` 的 `not_in_doc_unreachable: 2` 应读作 **`doc_not_kept_clean_stage_loss: 2`**（该产物已关闭，不就地改写，以本裁定为准）。

---

### 10.5 band 路线与票 03 的重复（**归属已定：选项 A 落地**）

**事实**：i40/i41 的 band 路线（选中块周围的"连续区间"，`gap=1`/`expand=1`/`band_cap=8`/`pool_cap=24`/可证带宽上界 49）
与票 03 的 `chunk.cover(quote) -> (i,j)`（在 chunk 层承载"连续块区间"）**是同一件事的两个落点**：

| | 落点 | 现状 | 成绩 |
|---|---|---|---|
| **band** | **选择层**（`selection.select_band`，产品代码） | **已落产品**（`BandPolicy`/`SelectedBand`，12 条常驻测试） | 回测 **17/24**（band 单独；注入存在池），实测带宽 33 ≤ 49 |
| **票 03 `cover`** | **chunk 层**（产品代码） | 未实现 | — |

**若照票 03 直接启动，等于把 band 已验证的成果在另一处重做一遍。** 归属裁决（2026-09-21，与 S2 判定同日落地）：

| 选项 | 动作 | 代价 |
|---|---|---|
| **A（已选定并落地）** | band 落产品：把"连续区间"做进 `selection`，chunk 层不动 | 小；已有 19/24 验证；**不需改 schema/索引文本，顺带规避 `ts_rank` 副作用** |
| B | 票 03 的 `cover`：在 chunk 层实现区间承载，band 作废 | 须重新验证；动 chunk ⇒ 全量重摄入 |
| C | 两者都留 | 须说明职责边界，否则出现两套区间逻辑 |

**裁决：选 A，已落地**。`selection.select_band`（`BandPolicy gap=1/expand=1/band_cap=8/pool_cap=24`，`provable_width_bound=49`）承载"连续区间选择"；chunk 层职责仍为"把文本切成块"，票 03 的 `cover` 部分**作废**。回测产物：`audits/20260921-band-product/`（EvidencePass 12/24 → **17/24**，负例误报 6 不回升，漏斗 S0/S1/S2 与 i42 逐字节一致，`self_check` 全绿）。

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

## 13. 基线漏斗与方案后对比

### 13.1 基线（2026-09-21 实测 **i42**，79 目标，嵌套累计）

数据来源：`audits/20260920-i42-topic-b-reingest/recall-funnel.md`（链路 = `search_chunks → selection.select_structural(perdoc)
→ fetch_verbatim → scoring`；scorer = 工作树空白规约，**NOT frozen**）。

| 层 | 含义 | 存活 | 累计存活率 | 本层损失 |
|---|---|---|---|---|
| S0_kept | 引文在 kept 单元内 | 77/79 | 97.5% | — |
| S1_candidates | 在候选块内（search 可召回） | 66/79 | 83.5% | **11** |
| S2_doc_topk | 文档进 top-5（DocRecall） | 60/79 | 75.9% | **6** |
| S3_chunk_top8 | 引文块进该文档选中 top-8（I-B2） | 51/79 | 64.6% | **9** |
| S4_matched | `EvidenceTarget.matches` 逐字命中 | 44/79 | 55.7% | **7** |

桶分布（首个断点，合计 79）：

| 桶 | 条数 |
|---|---|
| `matched` | 44 |
| `selected_but_match_fail` | 7 |
| `doc_topk_no_chunk` | 9 |
| `candidates_no_doc` | 6 |
| `kept_not_candidate` | 11 |
| `not_in_doc_unreachable` | 2 |

**自洽性核算**（已校验）：77−11=66，66−6=60，60−9=51，51−7=44；44+7+9+6+11+2=79。

**可修上限 = 33 条**（11+6+9+7）；`not_in_doc_unreachable` 2 条属金标侧，不由管线修复。

#### 两个必须先钉死的口径问题

1. **S4 的匹配口径未注明**：`EvidenceTarget.matches` 用的是严格码位（r39 冻结 `bf9c8b80`）还是工作树空白规约（`f61573d7`）？这直接决定 `selected_but_match_fail 7` 中有多少属于票 00 的决策范围。**复跑对比前必须先声明。**
2. **本漏斗与 i38 消融不可相减**：i38 的 `matched 75/79` 是**实验增强后**（+S2/S3/S3b）且用未冻结的空白规约 scorer；本漏斗的 `44/79` 是**生产口径基线**。二者是"当前实际"与"策略上限"的关系——i38 已证明策略侧存在到 75/79 的路径，本方案负责把该路径沉淀为产品行为并逐层留痕。

### 13.2 层 → 票 映射（哪层损失由哪票负责）

| 层损失 | 条数 | 归属票 | 机制 |
|---|---|---|---|
| S0→S1 `kept_not_candidate` | 11 | **03** | 引文在 kept 但连候选池都没进 ⇒ 召回信号问题（词法未命中 / 索引文本缺结构标签） |
| S1→S2 `candidates_no_doc` | 6 | **03** | 文档未进 top-5 ⇒ 文档级排名信号 |
| S2→S3 `doc_topk_no_chunk` | 9 | **03 + 04** | 引文块未进 top-8 ⇒ 块区间覆盖（03）+ 结构标签进排序（04） |
| S3→S4 `selected_but_match_fail` | 7 | **00（决策）** | 匹配口径：严格码位 vs 空白规约 |
| `not_in_doc_unreachable` | 2 | 不修 | 金标改写/重建，管线不可达 |

> **与 i37/i38 的口径差异（待确认，勿强行对齐）**：
> - `matched`：本漏斗 44 / i37 49 / i38 75（实验增强）——三个数分属不同口径，对比前须逐一声明 scorer 字节与语料版本
> - `not_in_doc_unreachable`：本漏斗 2，而 i37 该桶为 **0**（i37 的 2 条落在 `doc_not_kept_clean_stage_loss` 清洗剔除）⇒ **同一桶名在两处含义可能不同，须确认**
> - 本漏斗 `kept_not_candidate 11` + `doc_topk_no_chunk 9` 疑似对应 i37 的 `kept_page_not_selected 21`（差 1 条，须确认归属）
>
> 这三组差异必须先对齐到同一口径，否则方案后对比会产出**假 Δ**。

### 13.3 方案后对比（band 落产品已回测，2026-09-21）

数据来源：`audits/20260921-band-product/band-summary.json`（产品 `selection.select_band`，79 目标、index-4-zhcfg-2、0 model calls；scorer = 工作树空白规约，NOT frozen，与 §13.1 同口径）。

**逐层对比**

| 层 | 基线 | 方案后（band） | Δ | 期望方向 |
|---|---|---|---|---|
| S0_kept | 77/79 (97.5%) | 77/79 | 0 | **不降**（保真约束，票 04 不得回退） |
| S1_candidates | 66/79 (83.5%) | 66/79 | 0 | ↑，上限 77 |
| S2_doc_topk | 60/79 (75.9%) | 60/79 | 0 | ↑，上限 66 |
| S3_chunk_top8 → S3_band_cover | 51/79 (64.6%) | **59/79 (74.7%)** | **+8** | ↑，上限 60 |
| S4_matched | 44/79 (55.7%) | **50/79 (63.3%)** | **+6** | ↑，上限见票 00 决策 |

> S1/S2 与基线一致是**自检成立**（band 不碰 search 召回与文档 top-5 选择；`self_check.S0_S1_S2_match_i42 = true`）。
> S3 层改名：band 语义为「引文在选中带文本内」而非「引文块进 top-8」，层含义变宽，故单独给行。

**桶分布对比**（band 按漏斗层分解，与 i42 同口径可减）

| 桶 | 基线 | 方案后（band） | Δ |
|---|---|---|---|
| `matched` | 44 | **50** | +6 |
| `selected_but_match_fail` | 7 | **9** | +2 |
| `doc_topk_no_chunk` → `doc_topk_no_band` | 9 | **1** | −8 |
| `candidates_no_doc` | 6 | 6 | 0（company-003 全在此层，另立议题） |
| `kept_not_candidate` | 11 | 11 | 0 |
| `not_in_doc_unreachable` | 2 | 2 | 应恒为 2（不由管线修复） |

> band-summary.json 的 `target_buckets` 用 s2 位置桶口径（`matched 60 / selected_but_match_fail 9 / kept_page_not_selected 8 / not_in_doc_unreachable 2`），与上表漏斗层分解不同，勿混用。

**负例误报**（同步记录，不得缺失）

| 指标 | 基线 | 方案后 |
|---|---|---|
| 负例误报（i42 OR 检索路径） | 6 | **6（不回升）** |

> §13.3 早期模板写「0（i38 口径）」：i38 为实验增强口径，与当前 i42/band 的 OR 检索路径不同；band 回测沿用 i42 路径，误报 6 与基线一致。

### 13.4 对比纪律

1. **同口径**：79 目标、嵌套累计、同一 scorer 字节、同一 active corpus（8 builds）
2. **单变量**：一次对比只改一票（或一次合并冻结 `i0c-r41`），不得同时改口径
3. **先钉 §13.1 的 S4 口径**，否则 `selected_but_match_fail` 不可比
4. **每层都报 Δ**：不得以上层的提升掩盖下层的下降；任一层下降必须给出解释
5. **负例误报同步报**：目标存活率上升但负例误报回升 = 无效
6. **数据必须来自落盘产物**（脚本 + 输出文件），不得口述填入
7. 在 §13.1 口径下 `not_in_doc_unreachable` 恒为 2（注意：**i37 口径下该桶为 0**，其 2 条落在 `doc_not_kept_clean_stage_loss`，见 §10.4）；若变化，须先确认是否换了桶定义，再判定是否金标/语料被改动

---

## 14. 2026-09-21 全面复测

### 14.1 八道门结果

| 门 | 命令 | 结果 | 判定 |
|---|---|---|---|
| 语料族回归 | `uv run pytest tests/test_corpus_*.py -q` | **716 passed / 12 skipped**（42.32s） | ✅ 绿（旧基线 651，+65） |
| Ruff | `uv run ruff check frontier_agent/ apodex/ benchmarks/ workflows/ plugins/ deploy/ tools/ scripts/` | `All checks passed!` | ✅ 绿 |
| Pyright | `uv run pyright` | 19 errors / 7 文件 | ✅ 既有缺依赖（非回归） |
| 导入冒烟 stage 1 | `uv run python tools/import_smoke.py --stage 1` | `[framework] 363/363`，exit 0 | ✅ 绿 |
| 导入冒烟 stage 2 | `uv run python tools/import_smoke.py --stage 2` | `[eval] 412/412`，exit 0 | ✅ 绿 |
| 符号闭包 | `uv run python tools/check_symbols.py` | `OK: 0 missing-symbol import(s) across 462 file(s)` | ✅ 绿 |
| 冻结链门 | `uv run python .scratch/.../freezes/validate_i0c_freeze.py` | `FAILED: 17 error(s)`，exit 1 | ❌ **红** |
| I3-2 完成门 | `uv run python .scratch/.../freezes/validate_i3_2_completion.py` | `i3_2_complete=false`，exit 1 | ❌ **红** |

> **结论：代码门 6/6 全绿，冻结门 2/2 全红。问题不在代码质量，在"未入链"。**

Pyright 的 19 errors 分布：`deploy/huggingface/app.py`、`scripts/migrate_sqlite_to_pg.py`、`server/alembic/env.py`、
`server/alembic/versions/0001_initial.py`、`server/alembic/versions/0002_run_usage.py`、`server/security.py`、
`server/store.py`——全部为 `sqlalchemy` / `argon2` 未安装所致，与本次改动无关。
（记录中旧称"仅 `server/store.py` 既有缺依赖"，实际范围更宽，须以本次为准。）

### 14.2 I3-2 完成门红的原因（新发现）

```
"manifest.status='frozen_r28'（**仍标 pending**，未随冻结更新）"
"manifest.lineage.scorer.sha256 与当前字节不符（上游已变）"
```

根因：`plugins/corpus/scoring.py` 改为空白规约版后，**未重建 `i3-2/scoring-input-manifest.json` 的血缘**。
这正是 i36 §4 预警的事项 ⇒ 与 §10.3 是同一件事，**不是新问题**。

其余 9 项检查全为 `pass`：P2 阈值/关键题/负例与冻结物一致、旧基线身份/范围闭环（含"无未冻结指针"）、
唯一初始实验 manifest、全部必要资产哈希入链、阶段签认（具名 + 入链）、留出隔离覆盖、
旧锚点映射规则级复核关闭、尾巴收口记录（无 open 项 + 入链）。

### 14.3 实现现状 vs 方案票

| 票 | 方案内容 | 实现状态 | 证据 |
|---|---|---|---|
| 01 | `selection.py` 落产品 | ✅ **已实现**（超出方案：含 `select_structural`） | `plugins/corpus/preparation/selection.py:54`（`select`）、`:85`（`select_structural`）；`SelectionPolicy` 默认 `top_k=5` / `max_chunks_per_document=8`；**生产接入（r43）**：`service.py::_apply_selection`（`search`/`search_with_coverage` 新链，候选池 `max(limit,40)` → `select_structural` → 截断） |
| 02 | `SearchHit` 加深 | ✅ **已实现** | `search_pg.py:94`（`label_path` 字段）、`:105`（`_enrich_hits`，同游标批量加深） |
| 03 | `chunk.cover` + recall/rank 拆分 | ⚠️ **部分**：`rank_hits` 已实现（`search_pg.py:162`），global 变体已被 i42 弃用；**`cover` 未实现** | `chunk.py` 函数全表中无 `cover` |
| 04 | 表格结构模型下沉 reader | ✅ **已实现**（但 `ts_rank` 副作用未清） | `readers/pdf_reader.py:146`（`TableModel.label_path`）、`:519-533`（填入 `UnitLocation.label_path`）；`contract.py:309`；`chunk.py:169`（`_table_row_label_prefix`） |
| 05 | 清洗判定依据可机读 | ✅ **已实现**（2026-09-21，S5 / §7.5） | `clean.py`：`NoiseVerdict` + `CleanRegion.verdicts`（NOISE 分支机器可读判定依据）；`audits/20260921-s5-noise-verdict/` |
| — | **band 路线**（本方案之外） | ✅ **已落产品代码**（`selection.select_band`，i40 17/24、i41 **19/24**、band 回测 17/24），**未接生产默认**（U 决策：生产默认 perdoc） | `selection.py::select_band`；`audits/20260920-i40-topic-a-tighten/i40_band.py`、`audits/20260920-i41-topic-a-cell/i41_band_cell.py`、`audits/20260921-band-product/`（§10.5 选项 A 落点） |
| — | 冻结链 | **`i0c-r43` 已建（R3 闭环）**：`selection.py` 入链（此前 UNBOUND）、`service.py` 重绑（r13 → r43）、随行测试、validator 扩展；supersession 区间扩至 r2..r43 | `freezes/i0c-r43.json`（`production_selection`/`freeze_validator` 两组绑定）；`freezes/validate_i0c_freeze.py`（exit=0） |

**常驻测试**：`tests/test_corpus_selection.py`（12 条）已覆盖 I-B2 / I-B3（含 `test_cap_unchanged_by_this_work`
显式断言 cap=8），但 **I-B1、I-A1/A2/A3、I-E1/E2 仍无常驻测试**；band 的 topic A 11/11 亦无常驻测试。
**生产路径测试（r43）**：`tests/test_corpus_consumers_pg.py::test_service_search_applies_selection_policy`
（PG 门控：6 来源 × 2 块 → 选择后 top_k=5 来源 10 条、每源 ≤8 块）。

### 14.4 由复测得出的四条判断

1. **票 00 的前提失效**：票 01/02/04 已落地 ⇒ 不是"未验证漂移"，而是"已裁决、已实现、结果低于基线"。见 §10.1。
2. **负收益的根因单一且已定位**：`ts_rank` 被标签注入稀释 → company-003 光力科技 doc rank 6
   （i42 `backtest-report.md:72`，且"两变体均受影响，与结构排序信号无关"）。修法见 §10.2。
3. **入链是唯一缺口**：代码门全绿 + 冻结门全红 ⇒ 当前唯一的系统性问题是"17 处改动未登记 + manifest 血缘未重建"，
   属流程而非代码。这也再次印证 §2 R2/R3：**判据挂在链尾，层内的对错无法被独立确认**。
4. **最好成绩不在产品里**（**已由 R3 闭环关闭**）：band 路线 **19/24**（i41）原只存在于诊断脚本，产品路径 **12/24**（i42）。
   **r43 后生产检索路径已接入 perdoc `select_structural`**（i42 产品路径逐字节一致），"未落产品"缺口关闭；
   band（17/24）与 perdoc（12/24）的差异仍在，但生产默认形态按 U 决策取 perdoc，band 切换生产默认留待后续
   （§10.5 归属已定：选项 A 落产品代码，未接默认）。**负例误报历轮恒 6**（i33→i42 五轮不变）仍为唯一零进展项，
   属 M6 硬判据（§6.0、§10.5）——按 U 2026-09-21 二次复核指令**重新立项**（§14.5 / `issues/06`，解除 §6.0 推迟）。

### 14.5 二次复核：接线判定 + 四笔立项（2026-09-21，U 已确认）

> 本节为方案总文本的**复核结论**，记录对三类问题的判定与修复方案初稿。
> U 已确认（2026-09-21）。四笔已转为正式工单：`issues/06`–`issues/09`
> （均 `needs-triage`，待逐笔进入实施）。

#### 判定 5：band 接线是"有意分步"，非"漏接" → 17/24 尚未生产生效

存档证据 `freezes/i0c-r43.json` notes：
"band 路线（select_band）保持产品代码与测试，**未接入生产默认**（按 U 2026-09-21 决策，生产默认 perdoc）。"

| 形态 | 落点 | 生产默认？ | 成绩 |
|---|---|---|---|
| perdoc（i42 产品路径） | `service.py::_apply_selection`（r43 接线） | **是** | 12/24 |
| band | `selection.select_band`（产品代码 + 常驻测试） | 否 | 17/24 |
| band + cell（i41 S2 投影） | 诊断脚本 `i41_band_cell.py` | 否 | 19/24 |

**结论**：band/cell 属"已验证、未上线"增量，**不算已拿到**；存在真实缺口（生产默认仍是 12/24），
升级路径是"把已通过的能力推进为生产默认 + 新冻结修订 + U 签认"，**不是修错**。

#### 四笔修复方案（初稿，均待 U 立项）

| 编号 | 议题 | 目标 | 依赖 | 阻塞条件 |
|---|---|---|---|---|
| F1 | 负例误报 6→0（M6 硬判据） | 6 题 `retrieved_documents` 0、`max_false_positives=0`，不扰动有答案题 S1 | 无（独立） | ✅ **已完成**（2026-09-21，`audits/20260921-f1-negative/`） |
| F2 | band 接生产 + 补 cell 投影 | 2a 17/24 生产生效；2b 当前语料 18/24（19/24 封口待 company-003 独立议题） | 新冻结 `i0c-r4n` + U 开关 | 2a（band）→ 2b（cell）顺序；U 已签收口口径 |
| F3 | e1 `disclaimer_section` 判定粒度过宽 | company-007/e1 转绿 | 重摄入 + 新修订 + 阈值具名签认 | 独立 |
| F4 | a-1 表头/正文边界（表归属） | company-008/a-1 归因转绿 | 与 F2 同批评估 | 弱耦合 F2 |

**F1：负例 6→0（M6 硬阻断，优先，独立）——✅ 实施完成（2026-09-21，`audits/20260921-f1-negative/`）**
- 现状：6 条 no-answer 题（company/industry/macro-009/-010）走同一 OR 词元检索各命中 5 篇 → 每题误报
  （证据 `i41/negative-cases.json`；`scoring.py:279 max_false_positives=0`）。
- 根因：no-answer 题单 token 命中即拉回候选文档（"2027 实际成交均价"命中任意含"2027/均价"文档、议息 vs 非农），FP 判定只看"是否有文档被检索"。
- 动作：① 固化 6 张 FP 归因表（token→命中块，`f1-attribution.*`）；② 机读归因证明纯"多词元共现/实体门"无法闭环 6→0 ⇒ 采用**判定层拒检兜底（收紧查询 + 拒检谓词）**，新增 `plugins/corpus/preparation/negative_query.py`（`tighten_no_answer_query` 内容词元 websearch AND + `is_relevant_candidate` 同单元全词元谓词）；③ 只作用于 no-answer 观测构造、不触 `search_pg.py`/`scoring.py` 字节，与有答案题 S1 命中池完全独立。
- 验收达成：6 题 `retrieved_documents` 0、`false_positives=[]`（I-M6-1 true）；S1_candidates=66 / S2=60 逐字节不回退（I-M6-2 true）；EvidencePass 12/24 不回归；`max_false_positives=0` 通过。回归 `tests/test_corpus_*.py` 742 passed / 12 skipped。

**F2：band 接生产（2a，17/24）+ 补 cell 投影（2b，17→19/24）**
- 2a：`service.py::_apply_selection` perdoc→`select_band`；需在 `read_pg.search_with_coverage` **同快照**内按 build 装配该 source 原文序全量块清单（`chunk_order_by_source`，沿用 `_enrich_hits` 同游标，禁 N+1）；返回类型 `SearchHit`→`SelectedBand`，`fetch_verbatim` 需支持按区间取回带内全部块。验收＝复现 `band-summary.json` 17/24 + `self_check.S0_S1_S2_match_i42=true` + 带宽 ≤49 断言。
- 2b：对命中带内 `cells` 非空 table 单元，用 `TableModel.label_path` 派生 `(page,row,col)` 并经 `service.py:1142 fetch_cell`（I2-6 权威）**发射 cell 证据**（只派生不改写、不再排一次序）。验收＝i41 的 13 个 `row:/col:` 目标 11 条转绿；industry-002 e2 / industry-003 e2（金标合成列标签）确认不可派生、保持 fail 不强行补取。
- 新冻结 `i0c-r4n` 捆绑 U 签认 + archive-first。

**F2 实施完成（2026-09-21，`audits/20260922-f2-band-prod-cell/`）——U 已签收口口径：17→18/24（当前语料），19/24 封口待 company-003 独立议题**
- 2a（band 接生产）：产品新增 band 读取路径并只读回测复现 17/24——`read_pg.search_with_coverage_bands`（同一 REPEATABLE READ 快照内 命中+覆盖+`chunk_order_by_source`，`_chunk_order_by_source_on` 按 build 批量装配原文序全量块清单，禁 N+1）、`read_pg.fetch_bands`（批量取回带内逐字块，禁 N+1）、`service.search_bands`/`_apply_selection_bands`/`_assemble_band_documents`。漏斗 S0=77/S1=66/S2=60/S3_band_cover=59/S4_matched=50 与 i42 逐字节一致；实测最大带宽 33 ≤ 可证上界 49；负例 6→0；回归 corpus 家族 **748 passed / 12 skipped**，ruff/pyright 全绿。生产默认仍 perdoc，band 为并行路径（切换默认归 `i0c-r4n` + U 签认）。
- 2b（cell 投影）：`_emit_cells` 对命中带内对齐 table 单元派生 `(page,row,col)` 并经 `fetch_cell` 权威路径发射 cell 证据（只派生、不改变选择）。当前语料 **band+cell = 18/24**、row:/col: **5/13** matched；industry-002 e2 / industry-003 e2（金标合成列标签）确认不可派生、保持 fail。**6 个 company-003 cell 目标**（每股收益/经营活动现金流 × 2026E/2027E/2028E）所在国信 doc 在**当前语料** rank-6 落出 top-5，非 cell 机制问题（i41 的 19/24 测于更早 reader-pdf-5 语料；当前 index-4-zhcfg-2 上 cell 无法触及该文档）——归并至既有 company-003 独立议题（§10.2 文档级召回，band/cell 均不修），F2 收口 18/24。
- 自检：band 层 17/24 与 `audits/20260921-band-product/` 逐层一致（`self_check.S0_S1_S2_match_i42=true`、`width_le_provable=true`、`fp_not_increased=true`）；band_s2 层如实标 `19=false`（不虚报 19/24）。新常驻测试覆盖 I-BAND-1（同快照全量原文序清单 + select_band 文档集与 select 一致）、I-BAND-2（带宽 ≤ 可证上界）、I-CELL-1（仅选中带对齐表单元派生、不改变选择）。

**F2 冻结落定：`i0c-r4n`（生产默认 perdoc→band + 启用 cell，2026-09-21）**
- 新冻结修订 `i0c-r4n` 已创建（archive-first 归档上一绑定字节至 `audits/20260922-r4n-band-prod-default/before-r4n/`；`freeze-manifest.json` 追加条目）。U 具名决策：生产默认 perdoc→band、启用 cell 投影；机制=band 选 chunk、保持 chunk 取证（不改 `corpus_search/corpus_fetch` 工具契约，硬闸①不破坏）。
- 绑定字节：`service.py=54ef53b8`、`read_pg.py=52b182f7`（首次入链，`search_with_coverage_bands`/`fetch_bands`）、`selection.py=9bd0a416`、`test_corpus_selection.py=a1b654ec`、`test_corpus_consumers_pg.py=c6bf0015`、`validate_i0c_freeze.py=f148ad36`。
- 校验：`validate_i0c_freeze.py` 增 r4n 块（parent/边界/语义门），r4n 全部自检通过；服务/实现组漂移（service.py、read_pg.py）清零。剩余 3 项已知待办漂移均非 r4n 引入、记录在案：① `r39` calibration-plan 历史 `read_pg.py` 绑旧哈希（已关闭轮次审计产物，不就地改写，待独立校准修订）；②③ `clean.py`（pre-F3 绑定）与 `test_corpus_preparation_clean.py`——**F3 重摄入另立 `i0c-r4p` 承接**（U 决策：F2 与 F3 分修订，不并入）。
- 回归：`tests/test_corpus_selection.py` 27 passed；corpus 家族 `tests/test_corpus_*.py` **748 passed / 12 skipped**（12 skip 为 I2 沙箱演练旧库监守）；ruff/pyright 全绿（r4n 触及字节 pyright 0 errors）。

**F3：e1 `disclaimer_section` 判定粒度过宽** ✅ 已完成（2026-09-21）
- 事实：company-007 ord=717 整段免责声明 NOISE，但同单元含实质事实句（华创云信 4.06% 持股）。
- 动作：`disclaimer_section` 从"整段一锅端"改**句粒度**（仅整段均为免责措辞时剔；含数字事实句降 KEPT/保留实质句）。⚠ 改 `clean.py` 噪声判定 ⇒ 影响 kept ⇒ 触发重摄入 + 新修订；阈值调整须具名签认（§11 纪律）。
- 落地：`plugins/corpus/preparation/clean.py` 新增三类『可复核数字事实句』机器可读谓词（持股百分比 `持有…X%…股份/股权`、6 位证券代码、带量词货币金额 `X元`），免责节单元命中即**整段降 KEPT** 并留 `disclaimer_section_numeric_fact_keep` verdict（I-E3）。谓词刻意不认评级规则阈值句（裸百分比，如『买入指…高于20%』），故不误降、既有 742 基线的 `评级说明` 阈值句仍 NOISE。
- 阈值签认（§11，U 已签名）：谓词=三类命中；粒度=单元级整体降 KEPT（非句级切分）。
- 机读复核（`audits/20260921-f3-disclaimer-granularity/`）：整库 8 build 回放，免责节中**仅 ord717 一单元** NOISE→KEPT，其余（716/718/719/720）仍 NOISE——变化范围单一且被归因；e1 事实句现落在 kept 单元；未达任何生产写库（重摄入随 F2 同批）。
- 回归：全语料族 **745 passed / 12 skipped**（742 基线未回退，新增 3 条 I-E3 永驻测试）；ruff/pyright 全绿。

**F4：a-1 表头 NOISE 与正文评级边界（表归属）**
- 事实：company-008 引文前半"贵州茅台…点评"在 NOISE 表头（跨 p1–p7）、后半"强推（维持）"在 kept 单元 ⇒ 引文横跨 NOISE/kept 边界。
- 动作：立为表归属/引文粒度议题（§10.4 已提示"更接近引文粒度/表归属，可能须另立"）；提供"跨 NOISE/kept 联合取证"或把承载真实评级的表头行降 kept 的判定路径，**先机读归因后定是否调阈值**；与 F2 同批评估（都动 table）。

#### 优先级与原则
- 补短板优先：**F1 并行启动、第一资源**（唯一零进展的 M6 硬判据）；F3 → F2a → F2b；F4 与 F2 同批。
- 每笔：不做"先调阈值再验归因"；不触金标；不调 `max_chunks_per_top_document=8`；负例误报不得回升。

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
| 冻结链 | `freezes/i0c-r41.json`（最新，scoped）、`freezes/validate_i0c_freeze.py` |
| i40 band 收紧诊断 | `audits/20260920-i40-topic-a-tighten/i40-summary.json`、`i40-report.md`、`i40_band.py` |
| i41 band+cell 诊断（19/24） | `audits/20260920-i41-topic-a-cell/i41-summary.json`、`i41-report.md`、`i41_band_cell.py` |
| i42 议题 B 产品路径回测（12/24） | `audits/20260920-i42-topic-b-reingest/backtest-report.md`、`recall-funnel.md`、`recal-score.md` |

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
