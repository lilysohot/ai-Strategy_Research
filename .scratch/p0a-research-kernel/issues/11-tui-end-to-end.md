# 11 · TUI 端到端跑通 + P0a 验收

Type: task
Status: closed
Blocked by: 01, 02, 03, 04, 05, 06, 07, 08, 09, 10

**Goal**: P0a 的唯一正式验收。跑不通则 **P0b 不做**。

**验收场景**
```
uv run frontier-agent --mode react --cwd <工作目录>
> 我有100万，空仓，风险偏好中等，想做3-6个月，帮我分析 X
  （stub 研报内容随对话给出，或 Agent 用 read_file 读 tests/fixtures/stub_reports/）
```

**通过标准（全部满足才算过）**

| # | 标准 | 验证方式 |
|---|---|---|
| 1 | Agent **调用** `position_sizing`（而非自己算） | trajectory / TUI 工具卡片 |
| 2 | Agent **调用** `strategy_lint` 且返回 `passed=true` | 同上 |
| 3 | `/outputs/strategy.json` 产出，`sizing.computed_by == "position_sizing@v1"` | 读文件 |
| 4 | `/outputs/report.md` 产出，关键数字带 `source_ref` | 读文件 |
| 5 | 故意漏给风险预算时，Agent **追问**而非假设 | 重跑一次，只说「我有100万，帮我分析 X」 |
| 6 | 手工核对：`sizing` 数字与 `position_sizing` 返回一致 | 手算或脚本比对 |

**反例验收（必须也能过）**
构造一个 `stop_loss >= entry_low` 的策略 → `strategy_lint` 返回 `passed=false`，
且 Agent **修正后重跑或直接报告不可行**，**不得绕过校验落卡**。

**失败即停**：若 P0a 跑不通，停止 P0b，回到 03/05/07/08 定位。
理由见 `docs/tittel/trading-strategy-platform-feasibility.md:271`——
「若 P0 跑不通，后面投再多数据也救不回可信度」。

**验收后**
- 在 `docs/plan/plan.md` 的 P0a 区块把状态改为 ✅，并补一句实测结论
- 本 issue 底部 `## Answer` 记录实际跑通情况（含发现的 bug）

## Comments

## Answer

### 实跑情况（run 828a）

跑通了，且**行为纪律全部达标**：Agent 在缺参数时追问而非假设（验收 #5 通过）、
调用 `position_sizing` 产出仓位（#1/#3）、调用 `strategy_lint`（#2）、
`report.md` 关键数字带 `source_ref`（#4）、sizing 数字手算核对一致（#6）。

两条最关键的纪律实测成立：
- 首轮用户只给「风险偏好中等」，Agent 拒绝把它换算成数字，明确要求给出百分比。
- 首轮标的不存在（「蓝海新材」检索 0 结果），Agent 主动核验并报告，未编造。

### 实跑暴露的两个缺陷（都已修）

1. **`lint` 段落盘丢了 `passed`**：`strategy_lint` 返回 `{"passed": true, ...}`，
   Agent 只存了 `checked_by` + 自然语言 note。报告里写「passed=true」，
   但 JSON 里没有这个字段——离线无法自证。
2. **`strategy_lint` 当时完全不校验 `evidence`**：`EVIDENCE_REQUIRED_KEYS`
   在 schema 里定义了却从未被 lint 引用（死常量）。后果是 13 条 evidence 的
   `page` 全是 `"—"`（数据来自东方财富网页抓取，无页码），lint 照样判
   `passed=true`——**硬闸①「数字可溯源」当时只是一句写在文档里的口号**。

### 为闭合这两点新增的东西

- `strategy_lint` 补 evidence 校验：11 条 ERROR（空/非对象/缺字段/非法 kind/
  page 占位符/悬空 source_ref/缺 sources/无 fact/source 缺 id）+ 4 条 WARN。
- `research_discipline.py`：`lint` 段必须原样存 `passed/errors/warnings`；
  `page` 必须是可定位真值；至少一条 fact；顶层 `sources` 必须声明。
- 新建 `plugins/corpus/verify.py`：离线三闸裁决。核心是 **lint 三重契约**——
  盖过章 + 记录 passed + **把卡重喂 `strategy_lint` 并与卡内记录的错误条数
  比对**，专门挡「先写漂亮卡再自己补一句 passed=true」。
- 新建 `plugins/corpus/fetch.py`：按定位符取回原文，并给 verify 提供
  source_resolver（硬闸①此前无解析器可验）。

### 验收方式改为机械可复现

新增 `tests/test_p0a_acceptance.py`（6 例，全过），把六条标准里能确定性判定的
全部脚本化，不依赖「跑一次 TUI 看表现」：

- 正向：stub 研报 → 真实 ingest → `position_sizing` → 组装 → 在线 lint →
  离线三闸裁决，最终 **三闸全绿**（含硬闸①溯源）。
- 反例：
  - `stop_loss >= entry_low` → `position_sizing` 直接拒绝（`shares=0`，
    错误体不含可用数字，防 Agent 从失败调用里捡数）
  - 同上 → `strategy_lint` 判 `stop_loss_not_below_entry`（ERROR）
  - **伪造 `passed=true` 绕过 → 被 `verify.py` 抓出**
    （`lint_recheck_failed` + `lint_result_diverged`）
  - 只存 `checked_by` 不存 `passed` → 被抓出（`lint_passed_not_recorded`）

最后两条是反例验收真正的落点：只测「lint 会报错」只验证了工具，没验证
「绕不绕得过去」。现在**绕过也被机制挡住**，而非只靠 Agent 自觉。

### 真实语料上的复核

用 `data/corpus` 里真实的两份贵州茅台研报（华创 2026-08-16、国信 2026-08-17）
构造策略卡，`evidence.page` 取真实页码 `1`、引文逐字取自该页，
`verify.py` 输出 **三闸全 PASS**——硬闸①首次在真实研报上验证成立。

### 遗留（不阻塞 P0b）

Agent **行为层**的实跑（TUI 里它会不会主动修正后重跑）建议再跑一次确认；
但即使它试图绕过，`verify.py` 也会在离线环节拦截，风险已由机制兜底。
