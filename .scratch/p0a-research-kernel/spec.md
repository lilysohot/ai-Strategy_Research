# Spec: P0a — 投研内核（确定性计算 + 策略卡）

把「算术不出 LLM」这条核心设计先跑通：Agent 只做定性判断（选什么、为什么），
所有数字由确定性工具产出，并经 `strategy_lint` 硬校验后落 `strategy.json`。

- **Design doc**: [docs/p0-implementation-spec.md](../../docs/p0-implementation-spec.md)
- **远期架构**: [docs/corpus-ingestion-architecture.md](../../docs/corpus-ingestion-architecture.md)
- **上游规划**: [docs/tittel/trading-strategy-platform-feasibility.md](../../docs/tittel/trading-strategy-platform-feasibility.md)（P0 阶段来源）
- **Tracker**: `.scratch/p0a-research-kernel/issues/`
- **范围**: **不碰真实研报**（用手写 stub）；`backtest_strategy`、向量检索、Discord/IMA 接入均不在本范围

## 三条硬闸（验收底线，机械可验证）

1. **数字可溯源**：产出物里每个数字都能在被引用原文处逐字找到
2. **算术不出 LLM**：`strategy.json` 的 `sizing` 必须带 `computed_by: "position_sizing@v1"`
3. **schema 完备**：止损 / 失效条件 / 时间窗必填，`strategy_lint` 硬校验

> 不要求「指导有投资价值」（做不到），但要求「不产出骗人的策略」。

## 前置结论（评审已定，无需再查）

| # | 问题 | 结论 | 影响 |
|---|---|---|---|
| 1 | TUI 侧有结构化输入通道吗？ | **没有** — `apodex/` 下搜 `addendum\|extra_prompt\|user_context` 零命中；`_sys_prompt_addendum` 仅 server 侧有 | 参数走首轮 task 文本 + Agent 追问，不建通道 |
| 2 | CLI 能切 profile 吗？ | **不能** — `apodex/cli.py:130-163` 无 `--profile`；mode 即 profile（`apodex/session.py:126`） | 改 apodex 的 profile YAML，不是 `workflows/.../tui.yaml` |
| 3 | TUI 新增工具要改几处？ | **4 处** — `_BUILTIN_TOOLS` / `apodex/agent_tools.py:80` registry（unknown name = **hard error at load time**）/ `:112` `_READ_ONLY` / apodex profile YAML | 漏一处则 TUI 起不来或每次调用都要确认 |
| 4 | 用什么解析 PDF？ | PyMuPDF（**未安装**；现有 `document-readers` 是 pypdf，**无版面坐标**） | P0b 前需加 `pymupdf` + `jieba` 依赖 |
| 5 | 数据落地在哪？ | `data/corpus/`（仓库根 + `.gitignore`） | 不用 `plugins/fin_data/`：会拖慢 import_smoke / ruff |

## 与 P0b 的边界

P0a 只依赖 stub 研报，**不依赖任何 ingest / 检索能力**。P0a 通过后才启动 P0b
（20 份真实研报 + FTS5 + `corpus_search`/`corpus_fetch`）。若 P0a 跑不通，P0b 不做。
