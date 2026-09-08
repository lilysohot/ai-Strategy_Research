# P0 投研内核与最小资料库 · 主题计划

| 项 | 内容 |
|---|---|
| 版本 / 状态 | v1.0 · P0a 未开始（11 项全部 ⬜） |
| 上游文档 | [plan.md](./plan.md) · [trading-strategy-platform-feasibility.md](../tittel/trading-strategy-platform-feasibility.md) · [tech-stack.md](../tech-stack.md) |
| 施工规格 | [p0-implementation-spec.md](../p0-implementation-spec.md)（算法、schema、改动点详见此文） |
| 远期架构 | [corpus-ingestion-architecture.md](../corpus-ingestion-architecture.md)（Discord / IMA / 向量 / 信号层均推后） |
| 任务清单 | [.scratch/p0a-research-kernel/issues/](../../.scratch/p0a-research-kernel/issues/)（一票一文件） |
| 状态图例 | ✅ 已完成 · 🔄 进行中 · ⬜ 未开始 · 🅿️ 暂缓 · ⛔ 阻塞 |

> **本文是 P0 的排期与验收入口**；实现细节（算法、schema、注册改动点）见施工规格，
> 单票实施细节见 `.scratch/`。

---

## 1. 目标与范围

把「**算术不出 LLM**」这条核心设计先跑通：Agent 只做定性判断（选什么、为什么），
所有数字由确定性工具产出，经 `strategy_lint` 硬校验后落 `strategy.json`。

**为什么要先做它**（`trading-strategy-platform-feasibility.md:271` 原文）：
> 「P0 不依赖任何外部数据源，却已经能验证整个交互闭环与『算术不出 LLM』这条核心设计。
> 若 P0 跑不通，后面投再多数据也救不回可信度。」

### 不在本次范围

| 项 | 推到 | 理由 |
|---|---|---|
| `backtest_strategy` | P1 | 依赖历史行情源；用假行情回测得出的数字全是假的 |
| 向量检索 / BGE-M3 / sqlite-vec | P1（按判据决定） | 先用 FTS5 跑黄金集，看 Recall 缺口再决定 |
| 论证单元 LLM 抽取（claim/entities） | P1 | 全量 8000 份约 24 万次调用，须分级后再做 |
| `screen_tickers` 挖掘能力 | P1 | 20 份样本算出的「新标的」是统计噪声 |
| Discord / IMA 接入 | P1 | 已确认推后 |
| 前端表单（CapitalForm / FillPriceForm） | Web 阶段 | TUI 无前端；接 web 时用 server 现成通道 |
| `EvidenceAuditObserver` 在线审计 | P2 | P0 先用离线脚本，逻辑跑对后再搬进 observer |
| 表格抽取（pdfplumber） | P1 | P0 只做正文 |
| 全量 8000 份 ingest | P0b 之后 | 独立批处理任务（2–7 小时），不阻塞 P0 |

---

## 2. 三条硬闸（验收底线，机械可验证）

1. **数字可溯源**：产出物里每个数字都能在被引用原文的 `source_ref + 页码` 处逐字找到
2. **算术不出 LLM**：`strategy.json` 的 `sizing` 必须带 `computed_by: "position_sizing@v1"`
3. **schema 完备**：止损 / 失效条件 / 时间窗必填，`strategy_lint` 硬校验

> 这三条**不保证「指导有投资价值」**（做不到），但保证「**不产出骗人的策略**」。
> 前者是能力问题，后者是诚信问题——本项目的分界线在这里。

---

## 3. 架构总览（P0 范围）

```
┌─ P0b 数据面（确定性，零 LLM）────────────────────────────┐
│  20 份 PDF/DOCX → PyMuPDF / python-docx 解析              │
│      → normalize（去重 · boilerplate 剥离 · 数字单位绑定）  │
│      → L1 原文存档 + L2 FTS5 索引（jieba 预分词）          │
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

TUI 走 `apodex.local_tools`（宿主 cwd），资料库工具读本地库文件是天然的，不经沙箱网络限制。

---

## 4. 已定前置结论（评审已定，无需再查）

| # | 问题 | 结论 | 影响 |
|---|---|---|---|
| 1 | TUI 侧有结构化输入通道吗？ | **没有** — `apodex/` 下搜 `addendum\|extra_prompt\|user_context` 零命中；`_sys_prompt_addendum` 仅 server 侧有 | 参数走首轮 task 文本 + Agent 追问，不建通道 |
| 2 | CLI 能切 profile 吗？ | **不能** — `apodex/cli.py:130-163` 无 `--profile`；mode 即 profile（`apodex/session.py:126`） | 改 **apodex 的** profile YAML，不是 `workflows/.../tui.yaml` |
| 3 | TUI 新增工具要改几处？ | **4 处**（+2 处配套）— `apodex/agent_tools.py:80` registry 明示 *"unknown name is a hard error at load time"* | 漏一处则 TUI 起不来或每次调用都要人工确认 |
| 4 | 用什么解析 PDF？ | PyMuPDF（**未安装**；现有 `document-readers` 是 pypdf，**无版面坐标**） | P0b 前需加 `pymupdf` + `jieba` |
| 5 | 数据落地在哪？ | `data/corpus/`（仓库根 + `.gitignore`） | 不用 `plugins/fin_data/`：会拖慢 import_smoke / ruff |

---

## 5. P0a 任务清单（stub 研报，不碰真实数据）

> 单票细节见 [.scratch/p0a-research-kernel/issues/](../../.scratch/p0a-research-kernel/issues/)。
> 状态以 issue 文件的 `Status:` 行为准，下表为索引。

| # | 任务 | 依赖 | 状态 | 要点 / 验收 |
|---|---|---|---|---|
| 01 | 数据落地骨架 + `.gitignore` | — | ✅ | `data/corpus/`；`git check-ignore` 命中（`.gitignore` 的 `data/` + 新增显式 `data/corpus/`） |
| 02 | 手写 stub 研报 5 份 | 01 | ✅ | `tests/fixtures/stub_reports/`；看多 / 看空 / 重复段 / 失效条件 / **无数字**各一 |
| 03 | `position_sizing` 工具 | — | ✅ | 风险与资金上限取小，取整到 `lot_size`；返回恒带 `computed_by` |
| 04 | `position_sizing` 单测 | 03 | ✅ | 15 例；含 `shares<一手`、`stop>=entry`、`computed_by` 契约 |
| 05 | `strategy_lint` 工具 | — | ✅ | 10 ERROR + 2 WARN；纯函数无副作用 |
| 06 | `strategy_lint` 单测 | 05 | ✅ | 23 例；**删掉 `computed_by` 必须 ERROR**（硬闸②回归，最关键） |
| 07 | `strategy.json` schema + 落盘 | 03, 05 | ✅ | `plugins/corpus/strategy_schema.py`；`evidence[].quote` 逐字；`kind` 分 fact / forecast / opinion |
| 08 | 工具注册（TUI 需改 6 处） | 03, 05, 07 | ✅ | 6 处全改；**另需** workflow `tui.yaml` 的 `agent_tools`（详见 Answer） |
| 09 | `TOOL_META` 条目 | 08 | ✅ | `category="finance"`，`timeout=5` |
| 10 | 提示词：引用纪律 + 缺失参数追问 | 07, 08 | ✅ | 未建 TUI 通道，复用 workflow 既有的 `_sys_prompt_addendum` |
| 11 | TUI 端到端 + P0a 验收 | 全部 | ⏸ | **代码侧已就绪，待真模型跑一次 TUI**（需配 `OPENAI_*`）。§7.1 的第 1/2/5 条只能由实跑判定；第 3/4/6 条已由 `tests/test_p0a_chain.py` 确定性覆盖 |

**可并行**：01 / 03 / 05 三条线无依赖，可同时推进。

> **⚠️ 对 08 的实测修正（施工时发现）**
> 「改 apodex 的 profile 而不是 `workflows/stateful_react_agent/profiles/tui.yaml`」
> 这条结论与代码不符。`--mode react` 走的是 **native workflow**
> （`apodex/task_runner.py::_run_native_workflow` → `BenchmarkSession`），
> apodex 的 `react.yaml` 只提供 `workflow` + `workflow_profile` 两个名字，
> **工具可见性实际由 workflow profile 的 `agent.agent_tools` 决定**
> （`workflows/stateful_react_agent/nodes/main_agent.py::_tools_for_stateful_react`，
> 亦见 `docs/tech-stack.md`：「可见性另由 `agent.agent_tools` 控制」）。
> 因此 08 实际改了 **7 处**，多出的是 `tui.yaml` 的 `agent_tools`——
> 不改这一处，两个工具在 TUI 下根本不会出现在模型可见的工具表里。
> `benchmark.yaml` / `simple.yaml` 未动，评测路径不受影响。

---

## 6. P0b 任务清单（20 份真实研报，P0a 通过后启动）

> B 系列 issue 文件待 P0a 验收后在 `.scratch/p0b-minimal-corpus/` 建立。

| # | 任务 | 依赖 | 状态 | 要点 / 验收 |
|---|---|---|---|---|
| B1 | 挑选 20 份样本 | — | ⬜ | **刻意挑选**：跨机构 / 同系列连续 4 期 / docx / 含表格 / 含扫描页 / 故意重复各一 |
| B2 | `ingest` 管道 | B1 | ⬜ | PyMuPDF + python-docx；去重 + boilerplate 剥离 + 数字单位绑定；`first_observed_at` |
| B3 | FTS5 索引 | B2 | ⬜ | jieba 预分词；`30%` / `47.3亿` 绑成整体 token |
| B4 | `corpus_search` / `corpus_fetch` | B3 | ⬜ | snippet 只定位，取证必须走 `corpus_fetch` |
| B5 | 接入 P0a 对话 | B4 | ⬜ | — |
| B6 | 20 道黄金题 | B1 | ⬜ | 数字型 8 / 观点型 6 / 对比型 3 / 时效型 3；同时是向量判据输入 |
| B7 | 离线校验脚本 | B4, B6 | ⬜ | 三条硬闸；数字溯源命中率 100% |

**20 份样本配额**（刻意设计，非随机——覆盖同行业跨机构、同系列多期、双格式、故意重复）：

| 配额 | 份数 | 验证点 |
|---|---|---|
| A 行业 × 4 家不同机构 | 5 | 近重复（同行业雷同论点） |
| B 行业 × 3 家不同机构 | 4 | 跨机构分歧呈现 |
| C 行业 × 同一机构连续 4 期 | 4 | `superseded_by` + 「数字变了文本没变」翻车场景 |
| D 行业 × 2 家机构 | 3 | 对照组 |
| docx（非 PDF） | 1 | 双格式解析 |
| 含大量表格 | 1 | 数字规范化（只验证不崩） |
| 含扫描页 | 1 | `needs_ocr` 降级路径不崩 |
| 与已有某份完全相同 | 1 | 精确去重（content_hash） |

---

## 7. 验收标准

### 7.1 P0a 验收

```
uv run frontier-agent --mode react --cwd <工作目录>
> 我有100万，空仓，风险偏好中等，想做3-6个月，帮我分析 X
```

| # | 标准 | 验证方式 |
|---|---|---|
| 1 | Agent **调用** `position_sizing`（而非自己算） | trajectory / TUI 工具卡片 |
| 2 | Agent **调用** `strategy_lint` 且返回 `passed=true` | 同上 |
| 3 | `/outputs/strategy.json` 产出，`sizing.computed_by == "position_sizing@v1"` | 读文件 |
| 4 | `/outputs/report.md` 产出，关键数字带 `source_ref` | 读文件 |
| 5 | 故意漏给风险预算 → Agent **追问**而非假设 | 重跑，只说「我有100万，帮我分析 X」 |
| 6 | 手工核对 `sizing` 数字与 `position_sizing` 返回一致 | 手算或脚本比对 |

**反例验收（必须也能过）**：构造 `stop_loss >= entry_low` 的策略 → `strategy_lint`
返回 `passed=false`，Agent **修正后重跑或直接报告不可行**，**不得绕过校验落卡**。
只测正向路径的话，「校验是否真有约束力」这件事没被验证。

### 7.2 P0b 验收

| # | 标准 |
|---|---|
| 1 | 20 份全部 ingest 成功（或明确标记 `needs_ocr` / 解析失败并有降级） |
| 2 | 20 道黄金题 Agent 全部答对 |
| 3 | 离线校验脚本：数字溯源命中率 100%（未溯源数字数 = 0） |
| 4 | 故意重复的那份只入库一次 |
| 5 | 同系列 4 期中，检索返回的是最新一期（`superseded_by` 生效） |

---

## 8. 实施排期与停点

| 阶段 | 内容 | 预估 |
|---|---|---|
| **P0a** | 01–11 | **约 1.5 天** |
| — | **停点：P0a 验收** | — |
| **P0b** | B1–B7 | **约 4–5 天** |

**停点规则**：**P0a 未通过则不启动 P0b。**
若 P0a 跑不通，回到 03 / 05 / 07 / 08 定位，而不是继续投数据——
数据不会让一个算术错误的系统变可信。

---

## 9. 已知不覆盖的风险（记账，避免将来误判已验证）

| 风险 | 说明 | 何时暴露 |
|---|---|---|
| **未验证「挖掘」** | 标的由用户指定，P0 **没验证**「从库里发现标的」这条路径 | P1 |
| **20 份的统计噪声** | 无法验证 novelty / 共识度等聚合指标 | P1 |
| **表格数字未入 L3** | P0 只做正文，表格里的数字检索不到 | P1 |
| **LLM 抽取未做** | 无 claim 字段，检索质量是 BM25 基线 | P1（先测 Recall 再决定） |
| **溯源校验是宽松的** | 只要数字出现在任一被引用原文中即算溯源；抓不出「张冠李戴」，但能 100% 抓出「完全编造」 | P2 |
| **合规** | 已确认自有合法订阅、仅内部使用；但 P0 演示与文档不引用真实研报内容 | 持续 |

---

## 10. 进度规则

1. 状态以 `.scratch/p0a-research-kernel/issues/NN-*.md` 的 `Status:` 行为准；
   完成后在 issue 底部 `## Answer` 记录实际结果（含发现的 bug），本表同步改 ✅
2. 出现阻塞时标记 ⛔ 并在 issue 内注明阻塞原因与解除条件
3. P0a 全部 11 项 ✅ 后，方可建立 `.scratch/p0b-minimal-corpus/` 并启动 B 系列
4. 范围变更需先回写 [p0-implementation-spec.md](../p0-implementation-spec.md) 再改本清单
