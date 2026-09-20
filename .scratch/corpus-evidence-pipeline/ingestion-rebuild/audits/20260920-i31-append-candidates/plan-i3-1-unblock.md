# I3-1 解卡方案（缺口阻断 → 收口）

- 生成：2026-09-20
- 状态：**待 U 裁定**（只读分析已完成；本文件不含任何代码/政策变更）
- 关联证据：本目录 `verify_candidates.py`、`i3-1-append-candidates-preflight.json`；
  `../../audits/20260919-i3-1-e2e/i3-1-screening.{json,md}`；`../../audits/20260920-i31-dev-lane/i3-1-dev-lane-e2e.{json,md}`
- 边界声明：**不改任何被冻结字节**；不改 `docs/plan/*`、不改 `plugins/**`、不改 `guards/i3.json`。
  本方案若被批准，落地时按 `archive_first()` 归档 + 新修订（`i0c-r36`，parent=`r35`）重绑。

---

## 0. 摘要（一页看完）

| 问题 | 结论 |
|---|---|
| 当前卡点是什么 | 4 份料共 **13 处阻断缺口**（4 图区 + 9 表线）→ 发布门拒绝 → `per_class_min_2` 不满足（company 1/3、macro 1/2） |
| 为什么卡住 | 缺口坐标是 `page:N`，批准范围坐标是 `char:a-b`；`_outside_scope` 只认 `char` → **PDF 页级缺口不可证「范围外」→ 恒 blocking** |
| 补 OCR 能解吗 | **不能**。OCR 只治 4 处图区，**macro 那份卡在表格上** → 即使 OCR 完美上线，`per_class_min_2` 仍为 false |
| 真正能解的是什么 | **P0（立即）追加 2 份已准入、已筛干净、零阻断的现成研报**：零人工、零代码、零政策变更 |
| 根治是什么 | **P1** 补齐缺口坐标映射（`page` → `char`/元素）+ 给「人工判级」正式入口；**P2** OCR 独立立项（连带「派生证据」契约） |

---

## 1. 问题定义

### 1.1 卡点的完整链路

```
读取器发现读不到 → clean 建合成区域(ordinal=None) → 缺口进台账 quality_report.gap_regions
   → gaps.py 默认分级(6 类 = blocking)
   → 唯一降级出口 evaluate_against_scope（只认 char: 坐标）
   → 发布门 engine._verify_publication_ready（一处 blocking 即整份拒绝）
   → 该料未发布 → per_class_min_2 计数掉一格
```

### 1.2 逐条病灶（13 处，按来源）

| 来源（sha256 前 8） | 域 | 阻断缺口 | 病灶 | OCR 可解 |
|---|---|---|---|---|
| 华创·贵州茅台 `6f14cc14` | company | `image_region_unreadable@page:2` | 看不见 | 是 |
| 国信·光力科技 `dddc7cd0` | company | `image_region_unreadable@page:7`（**金标引用页**） | 看不见 | 是，但需核对金标 |
| 长江·化工十问十答 `174b6462` | industry | `image_region_unreadable@page:1`、`@page:2`；`table_lines_without_extraction@page:3,12,13,17,18,21,22,24` | 混合 | **部分**（8 处表线不能） |
| 华福·新材料周报 `f8e31696` | industry | 无 | — | — |
| 华创·宏观专题 `cc03f55b` | macro | 无 | — | — |
| 光大·美国非农 `793b3967` | macro | `table_lines_without_extraction@page:6` | 拿不出结构 | **否** |

合计：`image_region_unreadable` 4 + `table_lines_without_extraction` 9 = **13**。

### 1.3 为什么不能直接忽略（设计立场，非洁癖）

- 发布 = 对外宣称"我读全了"。`read_pg.py:481-486`：**只要活动 build 的缺口台账非空，`processing` 即降为 `scoped`、`availability` 降为 `unknown`**。
  抹掉缺口 ⇒ 系统会对外报 `full` + `available`，下游把"读到的不全"当成"全读到了"。
- 本链是**逐字证据**链而非搜索链（`evidence.py:342`："No OCR, interpolation, missing-cell filling"）：搜索漏条目无害，证据漏段落会**静默改变结论方向**。
- 9 类码里已有 3 类（`empty_page`／`image_region_small`／`unterminated_code_fence`）是"确知没丢正文 → 放行 + 记账"。所以「忽略」这个动作**已存在**，只是必须**具名**。

### 1.4 为什么 OCR 不是解药（算术证明）

假设 OCR 完美上线、4 处图区全消除：

| 类别 | 现在 | OCR 之后 | 门（≥2） |
|---|---|---|---|
| company | 1/3 | **3/3** | ✓ |
| industry | 2/3 | 2/3 | ✓ |
| macro | 1/2 | **1/2** | ✗ |

macro 的缺额（光大非农）卡在 `table_lines_without_extraction` —— OCR 吐出的是一串文字，不是行列结构，且本链禁止补格/插值。
⇒ **OCR 全做对，门依旧不过。**

---

## 2. 候选方案对照

| # | 方案 | 解缺口 | 能过 I3-1 门 | 人工 | 代码/机制改动 | 是否破门 | 建议 |
|---|---|---|---|---|---|---|---|
| **A** | **追加 2 份已准入干净料** | 不需要解 | **能**（已实测 0 阻断） | **0** | **0** | 否 | **★ P0 立即执行** |
| B | 人工认可入口（具名放行缺口） | 要（逐处判） | 能 | 13 次（或 1 次+不变量） | 有（新机制） | 否 | P1 一并做 |
| C | 补齐缺口坐标映射（`page`→`char`/元素） | 自动降级约 12/13 | 能 | 0 | 有（破冻结件） | 否 | P1 根治 |
| D | 表格抽取改进（受控 Adapter） | 解 9 处表线 | 能 | 0 | 有（改读取器） | 否 | P1 备选 |
| E | OCR | 只解 4 处 | **不能** | — | 大（四道墙） | 否 | P2 独立立项 |
| F | 显式登记"不覆盖"（改 I3-1/M6 判据） | — | 能 | — | 改判据 | **是（降要求）** | **不建议** |

### OCR 接入的四道墙（记录 P2 的前置条件）

1. `readers/__init__.py:4`：链上明文"**不执行 OCR**、零模型调用"
2. `guards/i3.json`：零模型 / 无网络 / `read_roots: []`（OCR 需外网 + 外部服务，与守卫直接冲突）
3. **`raw_text` 逐字原文契约**：每个单元必须是源文件逐字切片（`verify_clean_region` 逐字符校验）。
   OCR 文本回溯不到源字节 ⇒ 必须新增「派生证据」身份 + 引用时标注，否则等于把不确定文本注入权威源
4. 架构明文："首版不允许自动 OCR"

⇒ 结论：**"链路打通后再补 OCR"的排序正确，不需调整**。

---

## 3. 推荐方案（分三阶段）

```
P0（立即，本方案主体）  追加 2 份干净料           → I3-1 收口
P1（紧随，独立修订）    补缺口坐标 + 人工判级入口  → 结构性根治，少卡
P2（I3 之后，独立立项） OCR + 派生证据契约        → 提高读取覆盖率
```

### 3.1 P0：追加 2 份干净料（本方案要 U 裁定的部分）

**候选料（已实测）**

| 域 | 来源 | source_id 前 8 | i0a2 终态 | 本地只读复核（2026-09-20 实跑） |
|---|---|---|---|---|
| company | 国信证券·贵州茅台 2026-08-17（`bbba671e.pdf`） | `c195233b` | `admitted` / `research_report` / company | **439 单元，6 缺口 / 0 阻断**（6 acknowledged） |
| macro | 国盛证券·宏观点评·这次不一样 2026-09-07（`08d04511.pdf`） | `1e021a8c` | `admitted` / `research_report` / macro | **83 单元，5 缺口 / 0 阻断**（5 acknowledged） |

- 两份均为**生产口径 `in_scope`**（`i0a2-adjudicated-20260915.json`），**不需要 dev lane、不需要 supersedes 取代链、不需要改 `admission-policy.json`(v1)**。
- 只读复核命令与结果：
  ```
  uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-append-candidates/verify_candidates.py
  → all_clean = true（两份 source_id 与 i0a2 admitted 记录一致）
  ```
- 若需缓冲，2026-09-19 只读筛料还留有 **5 份 industry 干净料**（华源环保／国金地产／国泰海通机器人／国金电力设备／国泰海通农业）。

**执行步骤（落地时按序做）**

| 步 | 动作 | 产物 |
|---|---|---|
| 1 | 沙箱 PG seed 2 条 `ReviewedDecision(decision=ADMITTED, reviewer=U 批准件, research_domain=…)` | 2 个 `decision_id` |
| 2 | 生成追加后 manifest（原 8 行 + 2 行，含 `domain_hint` / `review_decision_ids`） | `dev-scope-append10.json` |
| 3 | `corpus plan`（只读预检）→ `build` → `publish`（逐份，`--operator` 具名） | E2E 记录 |
| 4 | 重跑计数与格式矩阵 | `i3-1-append10-e2e.{json,md}` |
| 5 | `guards/i3-e2e.json` 允许路径 8 → 10；重跑守卫自检（write-once） | 新自检报告 |
| 6 | 台账回填 `tasks.md` / `plan.md`（`archive_first()` 归档后重绑） | `i0c-r36`（parent=`r35`） |
| 7 | 三门复跑：冻结链 / I3-2 完成门 / 语料族（651 passed / 12 skipped 基线） | 链门日志 |

**验收判据（机读，全部满足才算通过）**

1. 10 份 build 全 `SUCCEEDED`
2. 新增 2 份 `publish` exit **0**
3. 逐类可发布 = company **2**/4、industry **2**/3、macro **2**/3 → **`per_class_min_2 = true`**
4. §12.1 格式门仍 **true**（pdf 4/8、docx 1/1、md 1/1）
5. `audit_corpus_chain` 冲突 0、被拒句柄 0、取证核验全过
6. **缺口台账仍如实登记 13 处**（不得因追加而减少、隐藏或改写）
7. 生产判定逐字不变（v1 政策下 `in_scope` 材料恒 `research_report`、`rule_rev` 稳定；dev lane 载入仍 fail-closed）

**不变量（本方案明确不做的事）**

- 不放宽 §7.3 默认分级表（`blocking` 仍是 `blocking`）
- 不改 `GAP_POLICY_REV`、不改 I3-1 / M6 判据
- **不撤换**任何已进 I3-2 批准投影的料（只追加）
- 不引入自动 OCR
- 不把 dev lane 数字（4/8）当生产覆盖口径引用

**残余未解（诚实登记）**

- 13 处缺口**仍存在**；4 份料（茅台／光力／长江／光大）**仍不可发布**；光力 `page:7` 因是金标引用页，追加**不能替代**它
- 本方案对裁定①是**"绕开"而非"解决"**：机制层问题（缺口坐标不可判定）由 P1 根治，本阶段不处理
- I3-2 不受影响（其输入为冻结文件 `i3-2/query-gold-scoring-v1.jsonl` 等）；追加只会改变语料库内容与 I3-1 计数

**所需 U 裁定（一句话）**

> 批准在 I3-1 开发集**追加**两份已准入研报：company `c195233b`（国信证券·贵州茅台）与 macro `1e021a8c`（国盛证券·宏观点评）；
> 并确认"不发布被阻断来源、以合规干净料补足每类≥2"可作为裁定①（阻断缺口处置）的本阶段口径。

**为什么必须 U 批准**：2026-09-19 曾发生"Agent 自选 + 换料范围"被整批撤回（守卫允许路径 15→6，沙箱 teardown 重建）——
开发范围的权威源只能是 U 批准的件。本方案把待裁定对象从"13 处缺口怎么处置"缩小为"批准追加这两份"。

### 3.2 P1：结构性根治（独立修订，紧随 P0）

| 项 | 内容 | 效果 |
|---|---|---|
| 缺口坐标映射 | 让 `page:N` / `body[i]` 能映射到 `char:a-b`（或建立页↔字符区间的可判定对应） | 13 处里约 **12 处**可自动落 `out_of_scope`；人工只在**真命中金标区域**时介入（只剩光力 p7） |
| 人工判级入口 | 为"确知该区域不影响本任务"提供**具名签署**路径（带机检不变量：认可区域与已批准金标 locator 不相交） | 无需换料也能放行；缺口仍可见、`coverage` 仍降 `scoped` |
| （备选）表格抽取 | 受控表格 Adapter 改进 | 直接消掉 9 处表线，比 OCR 对症 |

前置：会动 `gaps.py` / `engine._parse_scope_ref` / §7.3 表 → 需架构修订 + `GAP_POLICY_REV` 升级 + 新修订重绑。

### 3.3 P2：OCR（独立立项，后置）

前置条件（缺一不可）：

1. 「派生证据」契约（OCR 文本不是源文件切片 → 与 `raw_text` 分开的身份 + 引用标注）
2. 守卫形态变更（网络 / 服务地址放行）与自检重跑
3. 架构 §5.3 修订 + `extractor_rev` 变更
4. OCR 不确定性的判级口径（置信度不足时如何记缺口）

**不得**把 OCR 当作当前卡点的解药——它只提高"读到的比例"，不改变"读不到的部分如何被合法处置"。

---

## 4. 风险与回滚

| 风险 | 影响 | 处置 |
|---|---|---|
| 新追加 2 份 build 出现意外阻断缺口 | 计数不达标 | 已用本地只读探针预验（0 阻断）；若实际仍有阻塞，从 5 份 industry 缓冲料或备用 macro/company 干净料替换（**替换前须重新筛**） |
| 守卫允许路径 8→10 需重跑自检 | 自检报告为 write-once | 新报告另起文件，不覆盖旧报告 |
| 台账回填牵动冻结链 | 链门变红 | 按既定流程：`archive_first()` → 重绑 → 三门复跑；生成器须可重入且产物确定 |
| 被误读为"降门" | 合规风险 | 本方案零门改动；`blocking` 恒 `blocking`；缺口台账不减；E2E 证据逐条登记 |

回滚：沙箱数据层 teardown + 按原 8 份重建（先例：2026-09-19 撤回流程，`residue=0`）；
文档类改动按 `archive_first()` 归档回滚；守卫允许路径改回 8。

---

## 5. 证据索引（本方案引用）

| 证据 | 位置 | 要点 |
|---|---|---|
| 只读候选复核（今日实跑） | 本目录 `verify_candidates.py` + `i3-1-append-candidates-preflight.json` | 两份 0 阻断 |
| 只读筛料（2026-09-19） | `audits/20260919-i3-1-e2e/i3-1-screening.{json,md}` | 41 份研报中干净 9 份 |
| dev lane E2E（当前基线 8 份） | `audits/20260920-i31-dev-lane/i3-1-dev-lane-e2e.{json,md}` | 可发布 4/8、13 处缺口、逐类 1/2/1 |
| 分级与坐标口径 | `plugins/corpus/preparation/gaps.py:74-86`、`:247-262` | `blocking` 表；`_outside_scope` 只认 `char` |
| 覆盖度降级机制 | `plugins/corpus/preparation/read_pg.py:468-486` | 台账非空 ⇒ `scoped` + `gap_regions_present` |
| 逐字证据立场 | `plugins/corpus/evidence.py:342-343` | 禁 OCR/插值/补格/推断 |
| 范围解析 | `plugins/corpus/preparation/engine.py:247-265` | 只支持 `char:<start>-<end>` |
| 发布门 | `plugins/corpus/preparation/engine.py:1173-1181` | 一处 `blocking` 即整份拒绝 |

---

## 6. 待 U 决定的事项清单

1. **是否批准 P0 追加**（`c195233b` company + `1e021a8c` macro）
2. **是否确认口径**：裁定①在本阶段以"不发布被阻断来源 + 追加合规干净料补足每类≥2"落地（而非 OCR／人工逐处判／降判据）
3. **P1 是否立项**（缺口坐标映射 + 人工判级入口），以及排在 I3-1 收口之前还是之后
4. **P2（OCR）是否确认后置**至 I3 之后独立立项
5. 若不采纳 P0，需明确替代口径（例如改 I3-1/M6 判据 = 方案 F，属降要求，本方案不建议）
