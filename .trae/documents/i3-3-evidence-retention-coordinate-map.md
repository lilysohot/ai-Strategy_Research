# I3-3 证据保留与坐标映射：分步根因定位与修复收口

## Context（为什么做）

I3-3 检索校准首轮（i0c-r39）实测：整句基线全无命中；问题词元 OR 候选 DocRecall/QuestionPass 均
100%，但 EvidencePass 仅 1/8、2/8、2/8，六个无答案负例全误报，**I3-3 未过、M6 未放行**。
54 条缺失证据目标分类：34 逐字未命中、14 保留但未进选中块、6 缺所需坐标。

本机会的定位是**生产管线修复**（超出已闭合的『两轮限定校准』），交付框架为：
**生产修复 ＋ 只读重验**。不宣称在限定校准轮内“通过 I3-3”；最终放行仍由 I3-6 冻结与 M6 承担。

用户明确要求：**先确定、一步一步排除、查究失败的根本原因**。因此本计划以「根因取证 → 分步验证
→ 命中后再启用修复」为门，不一次性触碰多层，避免把表象当根因、也避免未经验证的改动进入生产。

## 已确认的三个根因假设（待取证证实）

1. **34 逐字未命中 ≈ 空白/换行表征差异，非内容缺失。**
   金标 quote 自带换行与空格（如 `company-001/e4` `"…EPS 预测值\n67.74/70.77/73.84 元…"`、
   `company-002/e3` `"…归母净利润\n172.7 亿元…"`）。金标自身的 `exact()`（
   [annotate_working.py](file:///home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/annotate_working.py#L17-L23)）
   以**全空白剥离**求 raw 切片，即金标本意就是空白容忍；而评分器
   `EvidenceTarget.matches()` 与诊断 `diagnose_evidence.py` 均做**字节精确** `quote in text`。
   据此多数应属表征差异，正文实际保留。
2. **14 保留但未进选中块 ≈ 块预算/选择覆盖不足。** `group_hits`（
   [calibrate.py](file:///home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/calibrate.py#L37-L50)）
   每文档只取前 8 块；被评到第 9+ 块或未被 OR 命中的块不参与取证。
3. **6 缺坐标 ≈ 证据只发原生 page，未映射行列。** `observations_for`（
   [calibrate.py](file:///home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/calibrate.py#L53-L74)）
   只发 `page:`；金标要求 `row:每股收益`/`col:2026E` 这类**表头标签**。`UnitEvidence.cells`
   （[read_pg.py](file:///home/administrator/FrontierAgent/plugins/corpus/preparation/read_pg.py#L66-L76)）
   已携带 `(row,col)` 数值坐标，但行/列表头标签需从**真实表格结构**解析，不能直接贴金标标签。

## 约束（不得逾越）

- 金标、来源、阈值、索引、生产查询均**不改**；gold 只读。
- 引文权威仍是 `unit.raw_text`；`clean_view` 仅空白投影，不作引用权威。
- 有效性的核心锚点：评分器匹配口径与金标 `exact()` 语义一致（空白归一化）。
- 每步改动先经该层根因取证证实，命中后再启用；取证产物须固化留档。
- M6 只读最终冻结版本结果。

## 分步执行（每步含【取证 / 改动 / 验证门】）

### Step 1 — 只读取证：把 54 条根因精盘（不改生产）
产出并固化一份分类取证报告，作为后续每层的证据。

- 脚本（只读，不改 PG）：对冻结 30 题 + 54 目标，按页取 kept 单元做**空白归一化**（剥离
  `isspace()`）的 quote 包含核算，区分三类：
  - `present_after_whitespace_norm`：空白归一化后保留 ⇒ 属 ⱡ 评分器口径（35 层主杠杆）。
  - `truly_absent`：内含不在 kept 正文（图像/清洗丢弃/跨结构）⇒ 需逐条说明，**不授权改 gold**。
  - 对 6 条坐标：验证「从 `cells` 解 row-头(col=0) 表头、col-头(row=0) 表头是否复现金标的
    `row:`/`col:` 标签」；逐条判定结构映射是否可靠。
  - 对 14 条：结合 `candidate_question_lexemes_or-trace.json` 判定是「块排名第 9+」还是
    「OR 词未命中」。
- 产物：`i33-rootcause.json`（含 54 条逐条 cause、证据）＋ `i33-rootcause.md`。
- 门：三类计数与根因假设吻合；6 条结构映射可复现 0 冲突才进入 Step 3。

### Step 2 — 评分器/诊断匹配口径：空白归一化包含
- 改动 `EvidenceTarget.matches()`（[scoring.py](file:///home/administrator/FrontierAgent/plugins/corpus/scoring.py#L140-L145)）：
  将 `self.quote in evidence.text` 改为**全空白剥离后** `norm(self.quote) in norm(evidence.text)`，
  与金标 `exact()` 语义对齐。保持 code point 精确（仅剥离空白，不区分大小写/全半角）。
- 同步改 `diagnose_evidence.py` 的字节包含为同一归一化，使诊断与评分口径一致。
- 补/改 scorer 单测（`matching` 空白归一化用例，保 ⱡ 原严格用例的语义变更标注）。
- 门：离线只读重算 34 条在该口径下的命中数；判定其贡献。`uv run pytest plugins/corpus -q`。
- **明确：此步不改金标、不改正文。**

### Step 3 — 证据坐标映射：真实结构解析 row:/col:
- 依据 Step 1 对 6 条的判定，新增一个**结构映射函数**：给定 fetched unit 的
  `(page, element, cells((row,col)))`，经 `fetch_cell(dsn, doc_id, row, col0)` / `(row0, col)`
  解析该行的列头文本与列的表头文本，产出 `row:<表头>`/`col:<表头>` token。
- 接线 `observations_for` 的发证：仅当**该份返回文本的所有单元共享同一 `(row,col)` 头**时
  附加 `row:`/`col:`；否则退回 `page:`（多 cell 文本不妄标，宁可缺坐标不贴错）。
- 复核：映射结果必须与金标该条标签一致；不一致即判定该条需如实 absent，不伪造。
- 门：6 条在正确口径下能复现金标标签且不越权；`fetch_cell` 路径仅隔离库可用。

### Step 4 — 块选择覆盖（14 条）
- 依 Step 1 判定，选取**有界**策略：如「每文档块预算 8→上限提高」「context_refs/标题文本纳入
  可取证证据」或「对已命中文档按块补取」，在限定候选预算（chunk 候选上限）内验证。
- 门：14 条中被该策略覆盖的条数 ≥ 依证据判定可达的上限；候选不饱和即通过。

### Step 5 — 只读重验 + 台账收口
- 对冻结 30 题跑只读重验（复用 `verify_calibration.py` 风格离线重建，不补证据、不看 gold 定位）。
- 更新 `corpus-ingestion-rebuild-tasks.md` §0 与新 audit 目录：记录本轮修复、重验口径、
  各类达成情况；**明确 I3-3 仍按最终冻结由 M6 放行**，本计划不宣告 I3-3“在限定轮内通过”。

## 需改动的关键文件

- [scoring.py](file:///home/administrator/FrontierAgent/plugins/corpus/scoring.py)（Step2 匹配口径）
- [diagnose_evidence.py](file:///home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/diagnose_evidence.py)（Step2 诊断口径）
- [calibrate.py](file:///home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/calibrate.py)（Step3 发证/坐标；Step4 块策略，仅 audit 侧验证）
- [read_pg.py](file:///home/administrator/FrontierAgent/plugins/corpus/preparation/read_pg.py)（Step3 复用 `fetch_cell`/`cells`，如需）
- 新增 `i33-rootcause.json`/`.md`（取证产物）

## 验证

- Step1 产物与门逐一核对。
- `uv run pytest plugins/corpus -q`（scorer 匹配口径）。
- 只读重验 30 题 EvidencePass/误报口径，输出变更前后对照。
- 预检：ruff/pyright/符号闭合；import_smoke 两阶段按既有规则（LLM 零模型模块守卫）。

## 不做

- 不改金标、不『只为通过』重写打分；不改生产检索索引；不宣称 I3-3 在限定轮内通过。