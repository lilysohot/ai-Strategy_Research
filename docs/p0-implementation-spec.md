# P0 实施规格：投研内核 + 最小资料库

> **本文档是 P0 历史施工规格，不是本轮语料重构施工依据**，对应
> `docs/tittel/trading-strategy-platform-feasibility.md` 的 P0 阶段。
> 2026-09-15：语料部分的新目标见[重构草案 v1.1](plan/corpus-ingestion-rebuild-architecture.md)，
> I0 后才冻结实施；数字溯源、受控计算、策略校验和安全要求继续有效，未因语料重构退休。
> 完整远期架构见 [corpus-ingestion-architecture.md](corpus-ingestion-architecture.md)——
> **该文档中 Discord / IMA 接入、向量检索、信号层、跨源共振均不在 P0 范围，已推后**。
> 原则：**P0 验证机制，不验证质量；但绝不产出无法溯源的数字。**

---

## 0. 范围

### 0.1 做什么

| 子阶段 | 内容 | 数据源 |
|---|---|---|
| **P0a — 内核** | `position_sizing` + `strategy_lint` + `strategy.json` schema + 策略对话闭环 | **手写 stub 研报，不碰真实数据** |
| **P0b — 数据** | 20 份真实研报 ingest + FTS5 + `corpus_search`/`corpus_fetch` + 接进 P0a | 20 份自有合法订阅研报 |

### 0.2 明确不做（Deferred）

| 项 | 推到 | 理由 |
|---|---|---|
| `backtest_strategy` | P1 | 依赖历史行情源；用假行情回测得出的数字全是假的，违反精度原则 |
| 向量检索 / BGE-M3 / sqlite-vec | P1（按判据决定） | 先用 FTS5 跑黄金集，看 Recall 缺口再决定 |
| 论证单元 LLM 抽取（claim/entities） | P1 | 依赖重型 LLM 调用；8000 份全量约 24 万次调用，必须分级后再做 |
| `screen_tickers` 挖掘能力 | P1 | 20 份样本算出的「新标的」是统计噪声 |
| Discord / IMA 接入 | P1 | 已确认推后 |
| 前端表单（CapitalForm / FillPriceForm） | Web 阶段 | TUI 无前端；接 web 时用 server 现成通道 |
| `EvidenceAuditObserver` 在线审计 | P1 | P0 先用离线脚本，逻辑跑对后再搬进 observer |
| 表格抽取（pdfplumber） | P1 | P0 只做正文；表格入 L3 是独立工程 |
| 全量 8000 份 ingest | P0b 之后 | 独立批处理任务，不阻塞 P0 |

---

## 1. 验收标准

### 1.1 三条硬闸（全程不可违反，机械可验证）

1. **数字可溯源**：产出物里每个数字都能在被引用原文的 `source_ref + 页码` 位置逐字找到
2. **算术不出 LLM**：`strategy.json` 的 `sizing` 必须带 `computed_by: "position_sizing@v1"`
3. **schema 完备**：止损 / 失效条件 / 时间窗必填，`strategy_lint` 硬校验

> 这三条不保证「指导有投资价值」（做不到），但保证「**不产出骗人的策略**」。

### 1.2 P0a 验收（目标：1 天内判定）

```
输入：frontier-agent --mode react --cwd <dir> "我有100万，空仓，风险偏好中等，
      想做3-6个月，帮我分析 X"
通过标准：
  ✅ Agent 调用 position_sizing（而非自己算）
  ✅ 产出 /outputs/strategy.json，sizing 带 computed_by
  ✅ strategy_lint 返回 passed=true
  ✅ 产出 /outputs/report.md，关键数字带 [source_ref]
  ✅ 缺失参数（如未说风险预算）时 Agent 主动追问而非自行假设
```

### 1.3 P0b 验收

```
输入：20 份真实研报入库 + 20 道「答案只在研报里」的问题
通过标准：
  ✅ 20 份全部 ingest 成功（或明确标记 needs_ocr / 解析失败并有降级）
  ✅ 20 道题 Agent 全部答对
  ✅ 离线校验脚本：数字溯源命中率 100%（未溯源数字数 = 0）
  ✅ 精确去重生效：故意重复的那份只入库一次
  ✅ 同系列 4 期中，检索返回的是最新一期（superseded_by 生效）
```

---

## 2. 架构总览（P0 范围）

```
┌─ P0b 数据面（确定性，零 LLM）────────────────────────────┐
│  20 份 PDF/DOCX → PyMuPDF/python-docx 解析               │
│       → normalize（去重 · boilerplate 剥离 · 数字单位绑定） │
│       → L1 原文存档 + L2 FTS5 索引（jieba 预分词）         │
└──────────────────┬───────────────────────────────────────┘
                   ↓ 两个原生 @tool（宿主进程内，只读）
┌─ 推理面（TUI，ReAct）────────────────────────────────────┐
│  corpus_search（定位）→ corpus_fetch（取证）               │
│  position_sizing（算仓位）→ strategy_lint（校验）          │
│  LLM 只做「选什么、为什么」；所有算术由工具产出             │
└──────────────────┬───────────────────────────────────────┘
                   ↓
┌─ 产出 / 校验 ────────────────────────────────────────────┐
│  /outputs/strategy.json + /outputs/report.md              │
│  → 离线校验脚本跑三条硬闸                                  │
└──────────────────────────────────────────────────────────┘
```

**关键点**：TUI 走 `apodex.local_tools`（宿主 cwd），资料库工具读本地库文件是天然的，
不经沙箱网络限制——与「原生 tool 读本地库」的设计一致。

---

## 3. P0a：确定性内核

### 3.1 `position_sizing` — 仓位计算（纯算术）

```python
@tool
async def position_sizing(
    capital_total: float,        # 总资金
    risk_budget_pct: float,      # 单笔风险预算（占总资金 %），必填，无默认
    entry_low: float,            # 入场区间下沿
    entry_high: float,           # 入场区间上沿
    stop_loss: float,            # 止损价，必填
    lot_size: int = 100,         # A股一手 100 股
    max_weight_pct: float = 40.0 # 单票权重上限
) -> str:
    """计算单笔仓位：风险预算与资金上限取小，向下取整到最小交易单位。

    采用保守口径：风险与资金占用均按入场区间上沿（最差成交价）计算。
    """
```

计算逻辑（确定性，可单测）：

```
risk_per_share   = entry_high - stop_loss          # 最差成交价下的单股风险
risk_amount      = capital_total * risk_budget_pct / 100
shares_by_risk   = floor(risk_amount / risk_per_share)
shares_by_capital= floor(capital_total * max_weight_pct / 100 / entry_high)
shares           = min(shares_by_risk, shares_by_capital)
shares           = floor(shares / lot_size) * lot_size   # 取整到手
amount           = shares * entry_high
weight_pct       = amount / capital_total * 100
```

返回 JSON（含 `computed_by` 供硬闸校验）：

```json
{
  "shares": 300, "amount": 435000, "weight_pct": 43.5,
  "risk_per_share": 140.0, "risk_amount": 42000,
  "constrained_by": "risk",          // risk | capital | lot
  "computed_by": "position_sizing@v1"
}
```

**边界处理**（必须在工具内处理，不让 LLM 猜）：
- `shares < lot_size` → 返回 `shares=0` 并给出原因「风险预算不足以买入一手」
- `stop_loss >= entry_low` → 直接报错，不计算
- `risk_budget_pct` 超出 [0.1, 5.0] → 报错（由 `strategy_lint` 兜底）

### 3.2 `strategy_lint` — 策略校验（纯校验）

```python
@tool
async def strategy_lint(strategy_json: str) -> str:
    """校验策略卡：价格关系、风险上限、必填字段、参数数量。返回 errors/warnings。"""
```

| 校验项 | 级别 | 规则 |
|---|---|---|
| 价格关系 | ERROR | `stop_loss < entry_low < entry_high < target` |
| 风险预算 | ERROR | `0.1 <= risk_budget_pct <= 5.0` |
| 单票权重 | ERROR | `weight_pct <= max_weight_pct` |
| 失效条件 | ERROR | `invalidation` 非空（无失效条件的策略不允许落卡） |
| 时间窗 | ERROR | `horizon` 非空且为预设枚举 |
| 止损存在 | ERROR | `stop_loss` 必填 |
| 最小交易单位 | ERROR | `shares >= lot_size` 且为 `lot_size` 整数倍 |
| `computed_by` | ERROR | `sizing.computed_by` 必须存在（硬闸②） |
| 参数数量 | WARN | 可调参数 ≤ 6（反过拟合） |
| 风险收益比 | WARN | `(target-entry_high) / (entry_high-stop_loss) >= 1.5` |

输出：`{"passed": bool, "errors": [...], "warnings": [...]}`

### 3.3 `strategy.json` schema

在 `docs/tittel/trading-strategy-platform-feasibility.md:185-207` 基础上，按 P0 收窄
（去掉 portfolio 聚合，强化 evidence 溯源）：

```jsonc
{
  "version": 1,
  "capital_total": 1000000,
  "position": {
    "symbol": "600519.SH",
    "thesis": "……",                        // 定性判断，LLM 产出
    "evidence": [                          // 每条必带出处，可逐字溯源
      {"source_ref": "corpus:doc017#p12", "page": 12,
       "quote": "……逐字原文……", "kind": "fact"}   // fact | forecast | opinion
    ],
    "entry": {"low": 1420, "high": 1450},
    "stop_loss": 1310, "target": 1720,
    "invalidation": "季度营收同比转负",      // 可证伪的失效条件，必填
    "horizon": "3-6M",                     // 必填
    "sizing": {
      "risk_budget_pct": 1.0, "shares": 300, "amount": 435000, "weight_pct": 43.5,
      "computed_by": "position_sizing@v1"  // 硬闸②
    }
  },
  "lint": {"passed": true, "errors": [], "warnings": []},
  "disclaimer": "本研究性推演不构成投资建议，不涉及任何交易执行。"
}
```

### 3.4 stub 研报（P0a 专用）

手写 3–5 份**极简假研报**（markdown 即可，不需要 PDF），内容刻意包含：

| 内容 | 用于验证 |
|---|---|
| 明确的数字（「目标价 1720 元」「营收同比 +23.4%」） | 数字溯源校验 |
| 一处 fact 与一处 forecast | fact/forecast 字段级区分 |
| 一段与另一份完全重复的风险提示 | 近重复折叠（P0b 验证，P0a 先埋点） |
| 一个明确的失效条件表述 | `invalidation` 抽取 |

**stub 的目的不是模拟真实研报，而是让 P0a 的链路可以被手工预期**——
你知道正确答案是什么，才能判断 Agent 是否真的读了、真的调了工具。

### 3.5 结构化输入（无新增通道）

已确认：**首轮 task 文本 + Agent 追问**，不建 addendum 通道。

- 事实：`apodex/` 下搜索 `addendum|extra_prompt|user_context` 零命中——TUI 侧**没有**结构化注入通道
- server 侧有 `metadata["_sys_prompt_addendum"]`（`server/worker.py:351` → `main_agent.py:817`），接 web 时零成本复用
- P0 提示词要求：缺失参数必须**追问**而非假设。缺失参数清单：总资金 / 风险预算 / 持仓 / 时间窗

### 3.6 策略对话闭环

```
用户: "我有100万，空仓，帮我分析 X"
  ↓ Agent: corpus_search / corpus_fetch（P0a 阶段读 stub）
  ↓ Agent: 判断缺失参数 → 追问 "单笔风险预算多少？"
用户: "1%"
  ↓ Agent: position_sizing(...) → 得到 shares/amount
  ↓ Agent: 组装 strategy.json → strategy_lint 校验
  ↓ 若 lint 报错 → 修正后重跑（不得绕过）
  ↓ 写 /outputs/strategy.json + /outputs/report.md
```

---

## 4. P0b：最小资料库

### 4.1 20 份样本挑选方案（必须刻意挑选，不可随机）

| 配额 | 份数 | 验证点 |
|---|---|---|
| A 行业 × 4 家不同机构 | 5 | **近重复**（同行业雷同论点） |
| B 行业 × 3 家不同机构 | 4 | 跨机构**分歧**呈现 |
| C 行业 × 同一机构**连续 4 期** | 4 | **`superseded_by`** + 「数字变了文本没变」翻车场景 |
| D 行业 × 2 家机构 | 3 | 对照组 |
| docx 格式（非 PDF） | 1 | 双格式解析 |
| 含大量表格 | 1 | 数字规范化（P0 只验证不崩，不做表格入 L3） |
| 含扫描页 | 1 | `needs_ocr` 降级路径不崩 |
| 与已有某份**完全相同**，重复投放一次 | 1 | **精确去重**（content_hash） |

> 刻意设计的 20 份能覆盖的验证面，比随机 200 份更全。挑选约 1–2 小时。

### 4.2 ingest 管道

```
python -m plugins.corpus.ingest --src ~/reports/sample20 [--rebuild] [--verify]
```

| 步骤 | 实现 | 零 LLM |
|---|---|---|
| ① 扫描去重 | `sha256(文件)` 对比 manifest，跳过已入库 | ✅ |
| ② 解析 | PyMuPDF 逐页（保留页码/坐标）+ python-docx 按样式提章节 | ✅ |
| ③ 章节切分 | 正则匹配 `一、二、三、` / `1. 2.` 标题 | ✅ |
| ④ 清洗 | boilerplate 剥离（DF>30% 段落 + 显式模板清单：风险提示/免责声明/分析师声明/评级说明） | ✅ |
| ⑤ 近重复 | SimHash 汉明距离 ≤3 → 打 `duplicate_of`（**不物理删除**，检索时折叠） | ✅ |
| ⑥ 数字处理 | jieba 预分词时把「数字+单位」绑成整体 token：`30%` / `47.3亿` / `120bp` | ✅ |
| ⑦ 时间抽取 | 「2025Q3」→ `period_start`/`period_end` 结构化字段 | ✅ |
| ⑧ FTS5 入库 | 元数据 + BM25 全文索引 | ✅ |
| ⑨ 登记 | manifest.json（report_id / 哈希 / 页数 / `first_observed_at`） | ✅ |

**`first_observed_at` 必填**：研报署名日期远早于实际可见时间，任何时序分析以它为准
（防前视偏差）。

### 4.3 两个检索工具

```python
@tool
async def corpus_search(
    query: str,
    tickers: list[str] = [],      # 预留：为 P1 的「Agent 从库里选标的」留门
    since: str = "", until: str = "",
    top_k: int = 10,
) -> str:
    """在资料库中检索相关原文片段。只返回定位信息（source_ref + 片段 + 时间戳），
    引用任何观点前必须先用 corpus_fetch 按 source_ref 取回逐字原文。"""

@tool
async def corpus_fetch(source_ref: str, context_chars: int = 2000) -> str:
    """按 source_ref 取回逐字原文。这是唯一可引用的证据来源。"""
```

`Hit` 返回体（稳定契约）：

```python
Hit(source_ref, jump_hint, page, published_at, first_observed_at,
    snippet, score, duplicate_of=None, superseded_by=None, stale=False)
```

- `snippet` 仅定位用，**禁止引用**——这条边界是精度红线在接口层的体现
- `duplicate_of` / `superseded_by` 命中时，返回体显式说明，不静默丢弃

---

## 5. 工具落地改动清单（TUI 下必须改 4 处）

> **关键事实**：`apodex` 有独立于 `plugins/tools/_BUILTIN_TOOLS` 的工具注册表。
> `apodex/agent_tools.py:80-107` 的 `terminal_tool_registry()` 自称
> *"Authoritative name → tool map for what YAML profiles may request"*，且
> **"an unknown name is a hard error at load time"**。

| # | 文件 | 改动 | 不改的后果 |
|---|---|---|---|
| 1 | `plugins/tools/__init__.py:34-58` | `_BUILTIN_TOOLS` 追加 4 个工具 | 沙箱/workflow 侧不存在 |
| 2 | `apodex/agent_tools.py:80` | 加进 `terminal_tool_registry()` | **TUI 加载即 hard error** |
| 3 | `apodex/agent_tools.py:112-120` | 加进 `_READ_ONLY` | 每次调用都要人工确认 |
| 4 | apodex 的 profile YAML | `tools:` 列表追加 | 工具不可见 |
| 5 | `plugins/tools/meta.py:46` | `TOOL_META` 加 4 条 | 无输出限界/超时控制 |
| 6 | `tests/test_tool_registry.py:6` | `EXPECTED_TOOLS` 同步 | **CI 红** |

**注意**：第 4 项是改 **apodex 的 profile**（`--mode react` 对应的那份），
**不是** `workflows/stateful_react_agent/profiles/tui.yaml:75`。CLI 无 `--profile` 参数
（`apodex/cli.py:130-163` 全量参数：`--model --cwd --max-turns -y -p --plan --no-color
--no-tui --docker --no-sandbox --version`），mode 即 profile
（`apodex/session.py:126`）。

新工具 meta 建议：

```python
"corpus_search":   ToolMeta(is_read_only=True, concurrency_safe=True, timeout=30,
                            category="corpus", max_result_chars=8_000, result_is_ranked=True),
"corpus_fetch":    ToolMeta(is_read_only=True, concurrency_safe=True, timeout=30, category="corpus"),
"position_sizing": ToolMeta(is_read_only=True, concurrency_safe=True, timeout=5,  category="finance"),
"strategy_lint":   ToolMeta(is_read_only=True, concurrency_safe=True, timeout=5,  category="finance"),
```

检索类设 `result_is_ranked=True`（`_overflow.py:173` 会据此用 head-only 截断，
而非 head+tail——排序结果的尾部是最差的条目）。

---

## 6. 数据落地与 gitignore

```
data/corpus/                    # 仓库根，加入 .gitignore
├─ originals/                   # 原文不可变存档（PDF/docx，按 report_id 组织）
├─ corpus.db                    # SQLite WAL：records + FTS5 + manifest
└─ manifest.json                # 报告级元数据（含 sha256、first_observed_at）
```

**不放 `plugins/fin_data/`**（原研报方案的位置）：`plugins/` 是代码层，把数据塞进去会让
`import_smoke.py` 分层扫描、`ruff` 遍历、备份全部变慢。`deploy/Dockerfile.web` 已挂载 `../data`。

全量 8000 份时原文按 5–20GB 估，**必须 gitignore**。

---

## 7. 离线校验脚本（硬闸执行者）

```
python -m plugins.corpus.verify --run-dir <run_dir>
```

| 闸 | 校验逻辑 |
|---|---|
| **① 数字可溯源** | 1. 解析 `strategy.json` 的 `evidence[]`，逐条取 `source_ref` 回查原文，确认 `quote` 逐字存在（空白归一化后比对）<br>2. 正则提取 `report.md` 中所有数字（`\d+(\.\d+)?%?`、`\d+亿/万`）<br>3. 每个数字检查是否出现在**任意一条被引用原文**中<br>4. 未命中的输出为「未溯源」清单 |
| **② 算术出工具** | `strategy.json.sizing.computed_by` 存在且等于 `position_sizing@v1`；且 `shares × entry_high == amount`（重算一遍，不信任字段） |
| **③ schema 完备** | `stop_loss` / `invalidation` / `horizon` 非空；`lint.passed == true` |

> 闸①的匹配是**宽松**的：只要数字出现在任一被引用原文中即算溯源。它抓不出「张冠李戴」
> （A 报告的数字安到 B 报告名下），但能 100% 抓出「完全编造」。P0 阶段这个强度是恰当的；
> 精确关联（数字 ↔ 具体 evidence 条目）留到 P1 的 `EvidenceAuditObserver`。

---

## 8. 20 道黄金题（P0b 验收 + P1 向量判据输入）

从 20 份研报人工出题，**答案必须只在研报里**（不能靠常识答对）：

| 类型 | 数量 | 示例 | 验证什么 |
|---|---|---|---|
| 数字型 | 8 | 「XX 公司 2026 年营收预测是多少」 | 数字精确性、溯源 |
| 观点型 | 6 | 「哪家机构对光模块 2026 年需求最谨慎」 | 语义检索 |
| 对比型 | 3 | 「A 机构和 B 机构对同一标的的分歧是什么」 | **跨机构分歧保留** |
| 时效型 | 3 | 「该系列最新一期的目标价是多少」 | **`superseded_by` 生效** |

每题标注：问题 + 预期答案 + 预期 `source_ref`。

**复用价值**：这 20 道题同时是远期架构里「要不要上向量」那个判据的输入
（见 corpus-ingestion-architecture.md 第 6.4 节：Recall@10 ≥ 0.85 则不上向量）。

---

## 9. 依赖变更

新增 `corpus` extra（或独立依赖组）：

```
pymupdf>=1.24      # PDF 解析，保留页码/版面坐标（pypdf 无坐标，无法做结构感知切片）
jieba>=0.42        # 中文预分词（FTS5 unicode61 对中文按字切分，质量差）
```

**不新增**（已确认推后）：`pdfplumber`（表格）、`sqlite-vec` / `torch` / `sentence-transformers`
（向量）、任何调度框架。

> 现状：`document-readers` extra 提供的是 **pypdf**（`pyproject.toml:34`），
> PyMuPDF / pdfplumber / jieba 均未安装。

---

## 10. 实施顺序

| # | 任务 | 子阶段 | 预估 |
|---|---|---|---|
| 1 | `data/corpus/` 落地 + `.gitignore` | 准备 | 0.5h |
| 2 | 手写 3–5 份 stub 研报 | P0a | 1h |
| 3 | `position_sizing` 工具 + 单测 | P0a | 3h |
| 4 | `strategy_lint` 工具 + 单测 | P0a | 3h |
| 5 | `strategy.json` schema + 写文件 | P0a | 2h |
| 6 | 4 处工具注册 + profile 改动 | P0a | 1h |
| 7 | TUI 跑通策略对话，过 P0a 验收 | P0a | 3h |
| — | **P0a 完成（约 1.5 天），独立验收** | | |
| 8 | 挑选 20 份样本 | P0b | 2h |
| 9 | `ingest` 管道（解析/切分/清洗/去重） | P0b | 1d |
| 10 | FTS5 索引（jieba + 数字单位绑定） | P0b | 0.5d |
| 11 | `corpus_search` / `corpus_fetch` | P0b | 0.5d |
| 12 | 接进 P0a 对话 | P0b | 0.5d |
| 13 | 出 20 道黄金题 | P0b | 3h |
| 14 | 离线校验脚本 | P0b | 0.5d |
| 15 | 跑 P0b 验收 | P0b | 0.5d |
| — | **P0b 完成（约 4–5 天）** | | |

**P0a 与 P0b 之间必须停下来验收**。P0a 若跑不通，P0b 全不做——这正是
`trading-strategy-platform-feasibility.md:271` 的论证。

---

## 11. P0 阶段已知不覆盖的风险

| 风险 | 说明 | 何时暴露 |
|---|---|---|
| **未验证「挖掘」** | 标的是用户指定的，P0 没验证「从库里发现标的」这条路径 | P1 |
| **20 份的统计噪声** | 无法验证 novelty / 共识度等聚合指标 | P1 |
| **表格数字未入 L3** | P0 只做正文，表格里的数字现在检索不到 | P1 |
| **LLM 抽取未做** | 无 claim 字段，检索质量是 BM25 基线 | P1（先测 Recall 再决定） |
| **合规边界** | 已确认自有合法订阅、仅内部使用；但 P0 演示与文档不引用真实研报内容 | 持续 |

---

*本规格由架构评审收敛而来。所有代码路径与行号基于当时代码快照，施工前请以最新代码复核。*
