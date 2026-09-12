# D2 Claims v2 · 架构重塑设计（已失效）

> **状态：已失效。** 本文档已与质量加固清单合并，不再作为实施、验收或排期依据。
> 当前唯一有效计划见 [D2 Claims 优化改进执行计划](./d2-claims-optimization-plan.md)。

| 项 | 内容 |
|---|---|
| 状态 | **已失效 · 仅保留历史记录** |
| 日期 | 2026-09-12 |
| 前版 | [d2-claims-design.md](./d2-claims-design.md)（v1.1，P0–P7 已全部落地，作为遗产清单保留） |
| 输入 | [d2-claims-quality-hardening.md](./d2-claims-quality-hardening.md)（缺口清单）· [research-data-closed-loop-optimization-report.md](./research-data-closed-loop-optimization-report.md)（闭环契约）· glm 全量跑批实测（290/628 块在库） |
| 本文档要回答的问题 | v1 的哪些结构问题是修补解决不了的？v2 的表结构、管线、评估、重入语义长什么样？ |

> **一句话**：v1 把「按公司研报设计的抽取器」改造成了三插槽体系，补齐了三态、单位、审计、元数据；
> 但 **`metric` 一个字符串同时承载主体、指标、口径** 这个出生时的决定没动过，坐标系只能事后审计、
> 无法写入时校验，评级观点进不了候选，叙事没有载体，金标评估是缺的，文档重入语义是未定义的。
> v2 一次性重排这五件事，并为「研报预期 vs 市场实际」闭环提供 claims 侧的契约字段。

---

## 1. v1 遗产与 v2 的理由

### 1.1 v1 已交付（不重做，直接继承）

块级台账 + 指纹跳过 + 熔断/死信（P0）· 三态拆分 + `as_of`/`value_num`/`unit` 落列（P1）·
行业/宏观插槽（P2）· 别名归并 + 单位基准 + 跨块去重（P3）· 表格追加段 + 截断抢救（P4）·
三类审计 CLI + JSONL 留痕（P5）· 文档元数据入库（P6）· company 插槽收编（P7）。

### 1.2 v1 靠修补解决不了的结构问题（v2 的立项理由）

| # | 结构性问题 | v1 修补的局限 | v2 方案 |
|---|---|---|---|
| 1 | **`metric` 字符串身兼四职**：`US.NFP.previous`（地域.指标.状态）、`利润表.每股收益`（子表.行名）、`每股收益`（裸名）三种形态混在一列 | 别名表只能归并裸名层；编码层的错误（`FFR.hikeprob` vs `FFR.HIKEPROB`）无法索引、无法 lint、D4 聚合要写三层字符串解析 | **坐标拆列**（§3.1）：scope/subject/metric/basis 四列 + `metric_raw` 溯源 |
| 2 | **评级观点进不了候选**：`has_signal` 以数字为硬前提，「维持买入评级」在 LLM 调用前就被丢弃 | 与 claim 定义（承认评级观点）直接矛盾；修补要动 triage 的返回结构，不如随 v2 信号层重写 | **kind 增设 `opinion`** + 信号原因码（§4.1） |
| 3 | **坐标系只能事后审计**：kind↔period 自洽、ticker 越界、三态混用全靠 P5 审计在落库后扫 | 错误数据已经入库、已经花了钱；审计只能发现不能阻止 | **写入时 lint 门**（§4.3）：非法坐标不落库，标记待复核 |
| 4 | **叙事无处安放**（v1 缺陷 7 悬置）：宏观研报最值钱的主题/逻辑链没有载体 | v1 排期外；架构级重做是补这块的唯一时机 | **`narratives` 新表**（§3.3） |
| 5 | **金标评估缺失**：每轮改进靠个案验收，没有可复现的召回率/准确率基线 | hardening PR-1 的金标集是"最长杆"，v2 直接把它定为基建 | **金标集 + 基线作业**（§5） |
| 6 | **文档重入语义未定义**：数据清洗后重入库，blocks 变了，claims/台账指向什么？ | v1 只有 ON DELETE CASCADE 这个被动行为，没有主动定义 | **重入协议**（§6）：rev 版本化 + 显式级联 |
| 7 | **闭环缺 claims 侧契约字段**：闭环报告的 `ComparableObservation` 需要 `instrument_id + metric_id + period_end + known_at`，v1 只有 `tickers[]` + 编码 metric | 每次比较都要现做映射 | **`subject` 规范化 + 受控 `metric_id` 层**（§3.2） |

## 2. 设计原则（继承 + 新增）

继承 v1 硬纪律：数字幻觉率 0% 的溯源要求（locator + claim_text + `metric_raw`/`period_raw` 原文层）、
宁缺勿错（不确定留空不猜）、逐块原子提交、指纹跳过、fail-closed 审计。

v2 新增四条：

1. **坐标先行**：没有任何 claim 能绕过坐标四列落库；坐标不合法 = 不落库，而不是落库后靠审计捞。
2. **原文不可变**：一切归一（别名、期间等价类、单位换算）只发生在**派生列**，`*_raw` 原文列永不回写。
3. **评估先行**：金标集没建好之前，v2 管线不切换；新旧差异报告是一切切换的门槛。
4. **重入显式**：文档清洗重入是显式动作（rev+1，级联清除该文档的 claims/blocks），不静默 upsert。

## 3. 数据模型 v2

### 3.1 claims v2（核心变化：坐标拆列）

```sql
CREATE TABLE claims_v2 (
    claim_id      BIGSERIAL PRIMARY KEY,
    doc_id        text        NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    seq           integer     NOT NULL,
    locator       text        NOT NULL,          -- 取证句柄（不变）
    claim_text    text        NOT NULL,          -- 原文层（不变）

    -- ── 坐标四列（v2 核心）──────────────────────────
    scope         text        NOT NULL,          -- company | industry | macro（冗余 doc_kind 便于索引）
    subject       text,                          -- 规范主体：company→600519.SH；industry→化学原料；macro→US
    metric_raw    text,                          -- 模型原文（溯源，永不归一）
    metric        text,                          -- 受控归一名：每股收益 / NFP / 营业收入
    basis         text,                          -- 口径状态：actual|consensus|previous（macro）、
                                                 -- YoY|MoM（industry）、子表名（company 表格块）

    -- ── 值与时间（继承 v1，period 拆列）──────────────
    kind          text        NOT NULL,          -- fact | forecast | opinion（v2 新增 opinion）
    value_text    text,
    value_num     numeric,
    unit          text,
    period_raw    text,                          -- 原文期间（溯源）
    period_end    date,                          -- 无歧义等价归一后的期末；有歧义 = NULL + review
    period_grain  text,                          -- annual | half | quarter | month
    as_of         date,                          -- 发布/预测时点（不变）

    -- ── 治理列（v2 新增）────────────────────────────
    lint_status   text        NOT NULL DEFAULT 'ok',   -- ok | review | rejected
    coord_reason  text,                          -- 分类/坐标判定原因码（hardening PR-3）

    confidence    real,
    extracted_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (doc_id, seq, claim_text)
);
```

要点：

- `tickers[]` 退役为 `subject`：闭环报告已把 `instrument_id` 定为比较主键，单标的公司研报占 96%+
  场景，数组列换成规范单值列；「一文档多标的」降级为每标的一条 claim（同文档同指标多 subject 是合法形态）。
- `metric_id`（闭环 §3.2 的 `eps.basic` 等受控名）**不进 claims 表**，作为 `MetricMap` 的映射目标放在
  连接层——claims 保持中文受控名，映射表负责到市场字段的翻译。理由：受控财务字段名是市场侧概念，
  强塞进语料库层会让 claims 依赖 market 模块。
- `basis` 收编三种口径：macro 三态、industry YoY/MoM、company 子表名。跨 scope 取值受 lint 约束（§4.3）。
- 兼容：`claims`（v1）全量保留作对照基线，`claims_v2` 并行建表；切换由差异报告放行（§5.3）。

### 3.2 别名表升级

`METRIC_ALIASES` 从代码常量升级为**带证据的表**：`(canonical, alias, evidence_doc, evidence_locator, 反例)`。
新增条目必须三件套（样本依据 + fixture + 不误合并反例），沿用 P3 纪律但落库可查。

### 3.3 narratives（新表，填 v1 缺陷 7）

```sql
CREATE TABLE narratives (
    narrative_id  BIGSERIAL PRIMARY KEY,
    doc_id        text   NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    seq           integer NOT NULL,
    locator       text   NOT NULL,
    ntype         text   NOT NULL,   -- theme（主题）| logic_chain（逻辑链）| risk（风险）| catalyst（催化）
    summary       text   NOT NULL,   -- 一句话概括
    body          text   NOT NULL,   -- 定位摘录（溯源）
    extracted_at  timestamptz NOT NULL DEFAULT now()
);
```

只在 macro/industry 文档抽取，独立插槽 + 独立 LLM 调用，**不与 claims 混算**（闭环 §7 第一条）。

## 4. 抽取管线 v2

```text
blocks → 信号层（原因码）→ 分类层（kind+reason+confidence）→ 插槽抽取
       → 解析层（坐标模型）→ lint 门 → 落库（claims_v2 / narratives + 台账）
```

### 4.1 信号层重构（收编 hardening PR-2）

- `triage_blocks` 返回 `(is_candidate, reason_code)`，原因码：`numeric | rating | noise | no_signal`。
- `rating` 放行不含数字的评级文本（维持买入/上调至增持/Buy/Overweight）；评级说明页、免责声明、
  联系人页仍按 noise 过滤（反例 fixture 钉死）。
- 成本红线：**rating 候选数 ≤ numeric 候选数的 30%**（金标实测后校准），超线先收紧噪声过滤而不是放任扩量。

### 4.2 分类层（收编 hardening PR-3）

`classify_doc_kind` 保持现有接口，新增 `classify_doc_kind_detail() → (kind, reason, confidence)`。
原因码：`manual_override | title_ticker | single_body_ticker | multiple_tickers | industry_title |
macro_title | fallback`。`fallback` 与低置信度文档进审计的**人工覆写候选清单**；审计只建议不写入。

### 4.3 lint 门（收编 hardening PR-4，从"只报告"升级为"写入时拦截"）

不变量（违规 → `lint_status=rejected`，保留行、不进聚合，审计可见）：

- company claim 的 `basis` 不得取三态值；非 company claim 的 `subject` 不得是个股代码（**双向**，v5 审计缺反向检查）；
- `actual/consensus/previous` 不得混入同一坐标；
- `period_end` 为空且 `period_raw` 有歧义 → `review`，不得猜；
- 同一坐标下 unit/数值冲突 → 冲突行标 `review`（P5 审计的跨块数值冲突检查前移到写入时）；
- `kind=opinion` 不参与任何数值聚合（查询层强制过滤 + 告警）。

### 4.4 表格与期间（收编 hardening PR-5）

- **结构优先压缩**：`is_flat_table` 块保留标题/表头/单位/期间行 + 数值行，正文受控截断——
  glm 实测 16384 上限仍有截断，继续调 token 不是答案。
- **期间锚定**：`2026H1`↔`2026 年上半年` 等价归一只发生在 `period_end` 派生层；`period_raw` 不动；
  表格块期间无法锚定 → `review`，不推断填充（P4 零虚构纪律不变）。
- `is_flat_table` 的 precision/recall 进金标报告，调阈值必须先看基线。

## 5. 评估基建（v2 的一等公民）

### 5.1 金标集

- 分层 ≥180 块（company/industry/macro 各 ≥60），强制覆盖：纯评级、带数字预测、宏观三态、
  普通表格、压平长表、目录、免责声明、联系人页、无信号正文。
- 标注项：是否候选 / 正确 doc_kind / 是否表格 / 应有 subject / period 与 value 可否可靠抽取。
- fixture 只存 `doc_id + locator + 标注结果`（私有原文不入库）；**fixture 稳定性依赖 locator 稳定，
  语料清洗重入前必须先冻结金标 doc 的 locator**（重入协议 §6 的例外条款）。

### 5.2 指标定义

候选召回率、噪声放行率、doc_kind 准确率、表格识别 P/R、坐标合法率、period_end 可锚定率、
字段有效率、空结果率、失败率、平均 token/耗时。报告中区分：候选层漏失 / LLM 输出错误 / 解析落库错误。

### 5.3 新旧对照（放行门槛）

现库 290 块 glm 数据 + 台账**原样保留**作为 v1 对照基线。v2 切换条件（全部满足才切）：

1. 金标指标无回退（或回退已被记录并批准）；
2. 抽样 doc 的新旧差异报告归档（新增/删除/坐标变化/数值变化四类）；
3. lint 拒绝率与 review 率在预期区间（初步 <10%，金标实测后校准）。

## 6. 重入协议（配合用户的数据清洗）

```text
数据清洗（用户）→ 重入（ingest --force，rev+1）→ 级联清除该文档 blocks/claims/台账运行行
→ 元数据重派生 → 金标 doc 跳过强制重入（locator 冻结）→ 增量重抽（指纹跳过其余文档）
```

- `documents` 增 `source_rev integer NOT NULL DEFAULT 1`；重入 = 同 doc_id rev+1，历史台账行保留
  （`rev` 列区分），claims 级联重建。审计报告按 rev 切片。
- 清洗规则由用户执行；**ingest 层不改**（目录结构不变是前提），v2 只接重入动作。

## 7. 分工与排期

| 阶段 | 内容 | 依赖 | 行为变化 |
|---|---|---|---|
| R0 | 金标集标注（用户主导 + agent 预标复核）· 基线指标报告 | 无 | 否 |
| R1 | `claims_v2`/`narratives` 建表 + 坐标模型代码 + 重入协议 | R0 金标冻结 | 否（并行表） |
| R2 | 管线 v2：信号层 rating 召回 + 分类 reason + lint 门 + 表格压缩 | R1 | 是 |
| R3 | 小范围重抽（金标 doc + 抽样 10 份）→ 新旧对照报告 → 放行评审 | R2 | 可控 |
| R4 | 全量重抽 + narratives 抽取 + 审计 v2（reason 码/重入切片） | R3 放行 | 是 |
| R5 | 闭环契约查询（instrument_id+metric+period_end+known_at 投影）· MetricMap 三项接入 | R4 | 否（只读层） |

发布门槛沿用 hardening §10：`pytest tests/test_corpus_claims.py tests/test_corpus_metadata.py -q`、
ruff、pyright，外加金标指标报告。

## 8. 明确不做（继承 v1 §11 + hardening §11）

- 不把叙事塞进 claims（narratives 独立表）；不用 LLM 自由匹配 MetricMap；
- 不在金标集建好前切管线；不做 v1→v2 的字段级自动迁移（并行表 + 重抽，干净切换）；
- 不自动写 `doc_kind_override`；lint 不回改历史行（只拒新行）；
- 不因重塑而中断正在进行的闭环 P0-A（market 侧证据链修复与 v2 无依赖，可并行）。

## 9. 开放问题（评审拍板）

1. **D3/D4 的迁移成本**：`tickers[]` → `subject`、`metric` 编码 → 四列拆分，D3 挖掘 / D4 共识的现有查询
   要跟着改——是否接受「v2 期间双读（v1 表兼容查询保留到 D3/D4 改完）」？
2. **评级 opinion 的归属**：进 `claims_v2`（kind=opinion，提案如此）还是进 narratives？前者可被
   评级漂移分析消费，后者更语义纯净。
3. **金标标注人力**：agent 预标 + 用户复核的流程是否可行？180 块的复核预算多少？
4. **对照判定的容差**：新旧差异报告里，坐标变化（metric 拆列导致的必然变化）和数值变化分开统计，
   坐标类变化默认放行还是逐条看？
