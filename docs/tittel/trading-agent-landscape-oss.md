# 开源 LLM 交易 / 量化 Agent 框架调研

> 目的：为 FrontierAgent（通用 ReAct + Agent Team harness）上构建「只做机会挖掘与策略生成、明确不做交易执行」的投研平台提供架构参照。
> 调研时间：2026-09。Star / 提交数 / 版本号均为抓取时刻快照。
> 标注约定：`[官方]` = 项目自己的 README / 源码 / 官方文章；`[论文]` = arXiv 原文；`[第三方]` = 独立复现、审计或批评；`[转述]` = 经论文的自动概览层转述，未逐字核对原文。

## 0. 来源可达性说明（先看这一节）

本次调研中 `arxiv.org` 的 abs/html/pdf 路径、`huggingface.co/papers`、`ar5iv` 镜像全部不可达（fetch failed），`nof1.ai` 全站返回 429。因此：

- 论文摘要以 `arxiv.gg` 的 abs 页为准（该镜像直接服务 arXiv 源文件，可视为一手摘要）。
- 论文正文细节（实验设置、指标、消融）无法直取原文处，改由 alphaXiv 论文页的自动概览获取，在文中标为 `[转述]`，**投产前需回到 PDF 复核**。
- Nof1 Alpha Arena 的官方页面未取得，赛季数据来自第三方报道，且第三方之间数字不一致，文中已并列标注。
- GitHub README 与 `raw.githubusercontent.com` 源码文件可正常抓取，这部分是一手。

---

## 1. 总览

| 项目 | 定位 | 仓库 / 论文 | Star | 最后活跃 | 输出形态 | 执行层 |
|---|---|---|---|---|---|---|
| TradingAgents | 多角色股票决策框架 | [GitHub](https://github.com/TauricResearch/TradingAgents) / [arXiv:2412.20138](https://arxiv.org/abs/2412.20138) | 103k | v0.4.0，2026-08-31 | 结构化 Pydantic + 自然语言叙述 | 代码中无券商接口 |
| Nof1 Alpha Arena | 真金白银实盘竞赛 | [nof1.ai](https://nof1.ai/) | 非开源项目 | Season 1.5 于 2025-12-03 结束 | 交易所订单 | 有（Hyperliquid） |
| AI-Trader (HKUDS) | Agent 原生交易平台 + 社区 | [GitHub](https://github.com/HKUDS/AI-Trader) | 22.2k | 2026-06-11 | 信号 / 策略 / 讨论三类 | 有（券商同步、跟单） |
| RD-Agent(Q) | 量化研发全栈自动化 | [GitHub](https://github.com/microsoft/RD-Agent) / [arXiv:2505.15155](https://arxiv.org/abs/2505.15155) | 14.5k | 1018 commits，活跃 | **代码**（因子 + 模型），Qlib 回测 | 无 |
| FinGPT | 金融 LLM 与微调生态 | [GitHub](https://github.com/AI4Finance-Foundation/FinGPT) / arXiv:2306.06031 | 21.2k | 713 commits | 情感 / 预测文本 | 无 |
| FinRobot | 股权研究 Agent 平台 | [GitHub](https://github.com/AI4Finance-Foundation/FinRobot) / [arXiv:2405.14767](https://arxiv.org/abs/2405.14767) | 7.9k | 326 commits，活跃 | 13 章可溯研究报告 | 无 |
| FinMem | 单 Agent 分层记忆交易体 | [arXiv:2311.13743](https://arxiv.org/abs/2311.13743) | 无官方仓库 | 论文 2023-12 | Buy / Sell / Hold | 无 |
| TradingGPT | 分层记忆 + 人格多 Agent | [arXiv:2309.03736](https://arxiv.org/abs/2309.03736) | 无官方仓库 | 论文 2023-09 | Buy / Sell / Hold | 无 |
| QuantAgent | 双层自改进因子挖掘 | [arXiv:2402.03755](https://arxiv.org/abs/2402.03755) | 无官方仓库 | 论文 2024-02 | **代码**（alpha 类） | 无 |
| StockAgent | 市场行为仿真器 | [GitHub](https://github.com/MingyuJ666/Stockagent) / [arXiv:2407.18957](https://arxiv.org/abs/2407.18957) | 698 | 53 commits，已停滞 | 仿真交易记录 | 仿真 |
| Trading-R1 | 金融推理模型（SFT+RL） | [arXiv:2509.11420](https://arxiv.org/abs/2509.11420) | 待发布 | 论文 2025-09 | 结构化投资论证 | 无 |
| FinCon | 概念性语言强化多 Agent | [arXiv:2407.06567](https://arxiv.org/abs/2407.06567) | 无官方仓库 | 论文 2024-11 | 投资决策 | 无 |

---

## 2. TradingAgents（UCLA / MIT / Tauric Research）

### 2.1 架构

`[官方]` 七类角色分五组：Analyst Team（Fundamentals / Sentiment / News / Technical）、Researcher Team（Bull / Bear）、Trader、Risk Management（Aggressive / Conservative / Neutral 三个 debator）、Portfolio Manager。注意代码里的 `selected_analysts` 默认元组是 `("market", "social", "news", "fundamentals")`（[`trading_graph.py`](https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/graph/trading_graph.py)），即 `market` = 技术分析师、`social` = 情绪分析师，与 README 的命名不一致但职责对应。

`[官方]` 编排用 LangGraph（`README` "We built TradingAgents with LangGraph"）。通信是**混合协议**：分析师产出结构化报告写入全局 state，自然语言对话只保留给 Researcher 与 Risk 两组的有界辩论。默认 `max_debate_rounds = 1`、`max_risk_discuss_rounds = 1`、`max_recur_limit = 100`（[`default_config.py`](https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/default_config.py)）。即：**默认配置下每场辩论只打一个回合**。

`[官方]` 风控目录下只有三个文件 `aggressive_debator.py` / `conservative_debator.py` / `neutral_debator.py`（[risk_mgmt 目录](https://github.com/TauricResearch/TradingAgents/tree/main/tradingagents/agents/risk_mgmt)）——风险偏好是靠三个不同人格的 LLM 辩论表达出来的，**没有任何数值化的仓位或亏损约束代码**。

### 2.2 输出形态

`[官方]` v0.2.4 起，Research Manager、Trader、Portfolio Manager 三个决策 Agent 走 `llm.with_structured_output(Schema)`，schema 定义在 [`tradingagents/agents/schemas.py`](https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/agents/schemas.py)：

- `ResearchPlan`：`recommendation`（Buy/Overweight/Hold/Underweight/Sell 五档枚举）+ `rationale` + `strategic_actions`
- `TraderProposal`：`action`（Buy/Hold/Sell）+ `reasoning` + `entry_price` + `stop_loss` + `position_sizing`
  - `position_sizing` 的类型是 **`str | None`**，取值示例如 `"5% of portfolio"`——**仓位是自由文本，不是被校验的数值**。
- `PortfolioDecision`：`rating` + `executive_summary` + `investment_thesis` + `price_target` + `time_horizon`
- `SentimentReport`：`overall_band`（六档枚举）+ `overall_score`（`ge=0.0, le=10.0`，这是全框架唯一被代码强制的数值区间）+ `confidence`（low/medium/high）+ `narrative`

`[官方]` 防错设计的两处细节值得抄：

1. 可选数值字段对 `"None" / "N/A" / "-" / "unknown"` 等占位字符串做前置清洗转 `None`，避免结构化调用直接报错（schemas.py 的 `_NULLISH_FLOAT`）。
2. 解析不出评级时返回 `REVIEW` 哨兵而**不是**静默降级为 `Hold`——`signal_processing.py` 注释写明 "so a parsing failure is visible instead of masquerading as a tradeable neutral signal (#1170)"。

### 2.3 执行层：README 与代码不一致

`[官方]` README 写 "If approved, the order will be sent to the simulated exchange and executed." 但公开仓库里 `TradingAgentsGraph.propagate()` 的返回值是 `(final_state, signal)`，其中 `signal` 只是一个评级字符串；仓库根目录文件清单（`main.py`、`cli/`、`tradingagents/`、`scripts/`）中不存在券商或交易所下单适配器，`scripts/` 下只有一个 `smoke_structured_output.py`。**结论：开源版是决策/研究框架，"simulated exchange" 在代码里没有对应实现。**

### 2.4 回测与评估

`[官方]` 仓库内**没有回测脚本**。内置的绩效闭环只有"决策日志"：`_fetch_returns()` 在下次同 ticker 运行时取持有期（默认 5 个交易日）的实际收益与相对基准的超额收益，基准按交易所后缀映射（`.T`→^N225、`.HK`→^HSI、`.SS`→000001.SS 等，默认 SPY），再让 `Reflector` 生成一段反思注入 Portfolio Manager 的 prompt（[`trading_graph.py`](https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/graph/trading_graph.py)）。

`[论文]` 论文声称的回测设置（**`[转述]`**）：2024-01-01 至 2024-03-29，AAPL / NVDA / MSFT / META / GOOGL，基线为 Buy&Hold、MACD、KDJ+RSI、ZMR、SMA，指标为 CR / AR / Sharpe / MDD；报告 AAPL 累计收益 26.62%、Sharpe 8.21、MDD 0.91%。

`[官方]` README 自己否认可复现性："Backtest results are not guaranteed to match any published figure... Treat the framework as a research scaffold for studying multi-agent analysis, not as a strategy with a fixed, replicable return."

### 2.5 已知缺陷（项目自己在 CHANGELOG 里承认的）

这份清单是整个调研里信息密度最高的部分，来自 [`CHANGELOG.md`](https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/CHANGELOG.md)：

| 版本 | 缺陷 | 编号 |
|---|---|---|
| 0.4.0 | FRED 宏观数据取的是"今天的 vintage"，把后来的修订值泄进历史回测 | #1275 |
| 0.4.0 | StockTwits / Reddit 抓取不带日期，历史回测看到的是当下的舆情 | #1220 |
| 0.4.0 | `get_past_context` 返回全部已结算经验，历史回测能看到未来才知道的教训 | #1251 |
| 0.4.0 | 持有窗口还没走完就结算收益，得到的是残缺收益 | #1169 |
| 0.4.0 | 最新一根 OHLCV bar（close 为 NaN）被静默丢弃，把前一交易日当成最新 | #1201 |
| 0.4.0 | 辩论首轮在没有对手发言的情况下"反驳空回复"，等于编造对方立场 | #1176 |
| 0.4.0 | 不可解析的评级被静默降级成可交易的 Hold | #1170 |
| 0.3.1 | Alpha Vantage 基本面是 JSON 字符串，dict-only 的前视过滤被跳过 | #1115 |
| 0.3.0 | ticker → 公司身份靠模型猜，会张冠李戴；价格与指标会幻觉 | #814, #830 |
| 0.2.5 | 情绪分析师在 prompt 压力下**编造社媒帖子** | #557, #607 |
| 0.2.3 | 回测抓取器在 `curr_date` 落在窗口中间时泄漏未来数据 | #475 |

**前四类（#1275 / #1220 / #1251 / #1169）本质是同一件事：点对时（point-in-time）数据契约缺失。** 一个 103k star、迭代到 v0.4.0 的项目，到 2026-08 才把前视偏差系统性地补上——这条时间线本身就是最重要的教训。

---

## 3. Nof1 Alpha Arena 与 AI-Trader

这两者经常被混为一谈，实际是完全不同的东西。

### 3.1 Nof1 Alpha Arena：真金白银的实盘竞赛

`[第三方]` Season 1（2025-10-18 起，约 17 天）：六个前沿模型各 $10,000 起始资金，在 Hyperliquid 上交易加密货币永续合约（BTC / ETH / SOL / BNB / DOGE / XRP）；**只允许使用数值市场数据（价格、成交量、技术指标），禁止查阅新闻与时事**；目标为最大化 PnL，同时给出夏普比率；动作被简化为做多 / 做空 / 持有 / 平仓；所有模型共用同一 prompt、同一数据接口、无微调。结果：Qwen3-Max 以 +22.32% 夺冠，DeepSeek v3.1 紧随其后，其余四个模型全部亏损，GPT-5 亏损超 62%（[IT之家](https://www.ithome.com/0/894/718.htm)）。另一家第三方口径略有出入：Qwen 3 Max +22.31%，DeepSeek V3.1 是唯一另一个盈利的，其余四个账户亏损均超 40%（[TradeRank](https://www.traderank.ai/traderank-vs-alpha-arena)）。

`[第三方]` Nof1 自己承认的局限（经 IT之家转述其报告）：样本有限、运行时间短、模型无往绩历史、**无累积学习能力**。另外两个观察很关键：

- **提示格式敏感性**：把数据的"新→旧"顺序改成"旧→新"，就能修复部分模型因误读数据产生的错误。模型对输入排列的鲁棒性极差。
- 各模型在风险管理、交易行为、持仓时长、方向偏好上差异显著：某些模型做空次数多，某些几乎不做空；某些持仓时间长、交易频率低，某些频繁交易。

`[第三方]` Season 1.5（2025-11-19 至 2025-12-03）：转向美股，扩到 8 个模型、四个并行主题（每个模型要在"新基线 / 稳健 / 敏感 / 高杠杆"四种交易人格间切换），每个主题 $10,000（共 $32 万），标的为 TSLA / NDX / NVDA / MSFT / AMZN / GOOGL / PLTR，NDX 可用到 20 倍杠杆（[腾讯网](https://new.qq.com/rain/a/20260117A01AEM00)）。结果：8 个模型里只有 Grok 4.20（赛前匿名"Mystery Model"）盈利，撰写时 +22.38%（[WEEX/BlockBeats](https://www.weex.com/fr/news/detail/alpha-arena-15-season-update-grok-420-dominates-the-competition-and-musk-praises-his-trading-skills-682085)），另一来源记为综合 +12.11%（[TradeRank](https://www.traderank.ai/traderank-vs-alpha-arena)）。**两个第三方数字差了约 10 个百分点，说明连"收益率怎么算"都没有统一口径。**

`[第三方]` 值得注意的批评：香港科技大学（广州）金融科技学域助理教授张超对"两周测试能否展现 AI 真实能力"表示怀疑，指出衡量一个金融策略好坏需要跨越一个经济周期、经过回测才能判断（[百家号](https://baijiahao.baidu.com/s?id=1848018327828341473)）。

### 3.2 AI-Trader（HKUDS）：Agent 原生交易平台

`[官方]` [HKUDS/AI-Trader](https://github.com/HKUDS/AI-Trader)，22.2k star、3.4k fork、388 commits，最近更新 2026-06-11。这是一个**带社交层的 Agent 交易平台**（线上服务 ai4trade.ai），不是研究框架：Agent 通过读一个 SKILL.md 自助注册，然后发布信号（Strategies / Operations / Discussions 三类）、参与讨论、被别人一键复制跟单、把自己在 Binance / Coinbase / IB 的持仓同步回来；人类侧提供 $100K 模拟盘。技术栈是 `skills/` + `service/server`（FastAPI）+ `service/frontend`（React），2026-03 上线 Polymarket 模拟交易。

**它与 Nof1 无关，也不是投研框架；对我们的价值主要在于"Agent 通过一份机器可读的技能说明书自助接入"这个接入范式，以及明确不应照搬的跟单 / 积分 / 复制交易形态。**

---

## 4. RD-Agent(Q)（微软亚洲研究院）

### 4.1 架构：两个阶段、五个单元

`[官方]` [论文 arXiv:2505.15155](https://arxiv.org/abs/2505.15155)（NeurIPS 2025 接收），代码在 [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent)（14.5k star、1018 commits）。量化流程拆成 Research 与 Development 两个阶段，细化为五个单元（[微软研究院官方文章](https://www.microsoft.com/en-us/research/articles/rd-agent-quant/)）：

| 单元 | 职责 |
|---|---|
| Specification | 在理论与工程两个维度统一上下文与约束，标准化数据接口、输出格式与回测环境（基于 Qlib） |
| Synthesis | 基于历史实验与领域知识生成假设并映射为可执行任务，用"想法森林"在探索与开发间自适应平衡 |
| Implementation | 代码智能体 **Co-STEER**：任务依赖 DAG + 引导式推理 + 可迁移知识库 |
| Validation | 新因子先与现有最优因子库算相似度去重，只保留不相似的强因子，再与当前最优模型组合回测；新模型对称地与当前最优因子库组合评测 |
| Analysis | 多维诊断 + 更新最优集合 + 生成优化建议；内置**线性 Thompson 采样的上下文多臂老虎机调度器**，决定下一轮优先优化"因子"还是"模型" |

### 4.2 输出形态：代码，不是自然语言信号

`[官方]` 微软的文章里点名批评了另一条路线："不少方法直接以自然语言生成交易信号，这不仅额外引入了由大语言模型带来的决策随机性，还缺乏可验证的因子构建与模型逻辑，难以满足实盘应用中的确定性、可解释性与风控要求。" RD-Agent(Q) 的产出是**可执行的因子与模型代码**，在 Qlib 里跑真实回测。

这一点对我们是决定性的：如果目标是"策略生成"，产出物必须是可回测、可版本化、可 diff 的东西（代码或结构化策略描述），而不是一篇看涨报告。

### 4.3 评估与防护

`[官方]` 数据集为 A 股沪深300；统一因子预测指标（IC、ICIR、Rank IC）与策略指标（ARR、IR、MDD、Calmar）；声称在不同市场和样本外时间上均展现鲁棒性（论文表 2）。

`[官方]` 结果（论文设定下）：只优化因子时，因子数量减少 70% 以上同时 IC 与 ARR 提升；只优化模型时 Rank IC 更优、MDD 更低；因子—模型联合优化时 IC ≈ 0.0532、ARR ≈ 14.21%、IR ≈ 1.74；端到端实验成本低于 10 美元。

`[官方]` 过拟合防护有三道：因子相似度去重、对称评估（新因子配当前最优模型、新模型配当前最优因子库）、多臂老虎机在有限算力下控制探索方向。**注意：这里没有显式的样本外/前视偏差防护语句被官方文章强调，"样本外"是论文表 2 的结果而非机制。**

`[官方]` 法律免责："The RD-agent is aimed to facilitate research and development process in the financial industry and **not ready-to-use for any financial investment or advice**." README 中亦明确不含执行层。

---

## 5. FinMem / FinGPT / FinRobot / StockAgent / TradingGPT / QuantAgent

### 5.1 FinMem：分层记忆 + 人格

`[论文]` [arXiv:2311.13743](https://arxiv.org/abs/2311.13743)，Stevens Institute of Technology，2023-11，被引 21。单 Agent，三模块：Profiling / Memory / Decision-making。

`[转述]` Profiling 含两部分：专业知识库（行业信息 + 公司历史表现）+ **三种风险倾向**（risk-seeking / risk-averse / **self-adaptive**，后者按近期盈亏在两者间动态切换）。Memory 分工作记忆（Summarization / Observation / Reflection）与分层长期记忆：

- Shallow 层：每日新闻，高衰减，稳定期 14 天
- Intermediate 层：季报，中衰减，90 天
- Deep 层：年报与扩展反思，低衰减，365 天

检索打分 `γ = w1·Recency + w2·Relevancy + w3·Importance`，Relevancy 用 embedding 相似度，并配访问计数器把"促成了成功决策"的记忆提升到更深层。决策模块输出 Buy / Sell / Hold。实验（`[转述]`）：TSLA / NFLX / AMZN / MSFT / COIN，训练 2021-08→2022-10、测试 2022-10→2023-04；基线 B&H、PPO/DQN/A2C、Generative Agents、FinGPT；TSLA 与 NFLX 的 Sharpe > 2.0、累计收益 > 35%；消融显示 self-adaptive 人格最优、记忆容量 K=5 最优、davinci-003 与 Llama2-70b 常常退化成一直 Hold。

**风控位置：在人格（prompt）里，不在代码里。** 没有硬性仓位或止损约束。

`[第三方]` 作者未发布官方仓库；社区复现见 [pipiku915/FinMem-LLM-StockTrading](https://github.com/pipiku915/FinMem-LLM-StockTrading)（未经作者确认）。

### 5.2 FinGPT：模型层，不是 Agent 架构

`[官方]` [AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT)，21.2k star、3k fork、MIT。五层栈：数据源层 → 数据工程层 → LLMs 层（LoRA 轻量化微调）→ 任务层 → 应用层。核心卖点是成本：BloombergGPT 训练约 53 天 / 267 万美元，FinGPT 单次微调低于 300 美元；情感分析基准上 FinGPT v3.3 加权 F1 0.882（FPB）/ 0.874（FiQA-SA）/ 0.903（TFNS），优于 GPT-4（0.833 / 0.630 / 0.808）与 FinBERT。里程碑产品是 FinGPT-Forecaster：输入 ticker + 日期 + 回溯周数 + 是否附带基础财务，输出一段分析与"下周股价方向"的自然语言预测。

**没有多 Agent 协作，没有风控模块，没有执行层。** 对我们的价值是组件（情绪打分、财报摘要），不是架构。

### 5.3 FinRobot：确定性计算与 LLM 叙述分离

`[官方]` [AI4Finance-Foundation/FinRobot](https://github.com/AI4Finance-Foundation/FinRobot)，7.9k star、1.3k fork、326 commits、Apache-2.0；[论文 arXiv:2405.14767](https://arxiv.org/abs/2405.14767)。

`[官方]` 经典论文版是四层：Financial AI Agents 层（Financial CoT）→ Financial LLMs Algorithms 层 → LLMOps & DataOps 层 → Multi-source LLM Foundation Models 层；调度由 Smart Scheduler 负责（Director Agent 分配任务、Agent Registration、Agent Adaptor、Task Manager）。

`[官方]` 当前主线（FinRobot Desktop v0.1.0，PydanticAI + FastAPI + React/Tauri）已经重构成一条流水线：

```
User Research Request → Lead Agent / Orchestrator
  → Data Agent → Analysis Agent → Modeling Agent → Synthesis Agent → Report Agent
  → Bull Agent ↔ Bear Agent → Judge Agent
  → Traceable Investment Research Output
```

1 个 Lead Agent + 5 个流水线角色 Agent + 3 个辩论 Agent（Bull / Bear / Judge）；7 条 pipeline（公司研究、DCF、可比公司、LBO、DDM、盈利、IC memo）；**30 个纯 Python 计算算子 + 7 个协调器**负责 DCF / DDM / LBO / WACC / 可比 / 蒙特卡洛；7 个数据供应商带 failover（FMP、Finnhub、yfinance、SEC EDGAR、Adanos、NewsAggregator、FX）。

`[官方]` 最关键的一条设计原则，README 里原文：

> **Numbers are code-calculated. Narratives are LLM-assisted. Every output is provenance-tracked.**

所有估值数字由纯 Python 算子算出，LLM 只负责推理、综合、解释与写作；输出是带证据链接与数值出处的 13 章可溯研究报告与 IC memo。**这一条与我们的"取证永远回到原文/源头，任何 LLM 摘要不得进入证据链"是同一条红线的不同表述，而且它已经在一个 7.9k star 的产品里跑通了。**

风控：无硬性仓位约束；它是研究侧工具，不生成订单。

### 5.4 StockAgent：仿真器，不是策略生成器

`[论文]` [arXiv:2407.18957](https://arxiv.org/abs/2407.18957)，ACM TIST 接收；[代码](https://github.com/MingyuJ666/Stockagent) 698 star、166 fork、53 commits（已基本停滞）。

`[官方]` 目标不是赚钱，而是"用 LLM Agent 仿真真实交易环境下的投资者行为，从而评估宏观、政策、基本面、全球事件等外部因素对交易行为的影响"。工作流分四阶段：Initial / Trading / Post-Trading（日频事件 + 季频事件）/ Special Events（随机日触发）。

`[论文]` 它明确处理了一个别人没处理的问题：**避免测试集泄漏**——阻止模型利用其可能已习得的、与测试数据相关的先验知识。

Robinhood 式的"买卖决策"只是仿真副产物。不适用我们的场景。

### 5.5 TradingGPT：分层记忆 + 人格 + 辩论的先行者

`[论文]` [arXiv:2309.03736](https://arxiv.org/abs/2309.03736)，2023-09，被引 45。多 Agent，每个 Agent 把记忆组织成**三层、各自带自定义衰减机制**以模拟人类记忆的层级性；Agent 之间存在 inter-agent debate；另外给每个 Agent 赋予**不同的交易性格（trading traits）**以增加记忆多样性与决策鲁棒性。

它是 FinMem（分层记忆 + 人格）与 TradingAgents（多空辩论）两条线的共同前身（TradingAgents 论文多次引用它作为要超越的对象）。**未找到作者发布的官方代码仓库。**

### 5.6 QuantAgent：双层自改进循环，输出是代码

`[论文]` [arXiv:2402.03755](https://arxiv.org/abs/2402.03755)，HKUST(GZ) / 倪明选 / 郭健，2024-02，被引 14。

`[论文]` 框架是双层循环：**内循环**在模拟环境里快速迭代（知识库 KB + 上下文缓冲 + Writer LLM + Judge 评估打分与反馈）；**外循环**把产出放到真实环境里检验，用表现反馈回灌 KB（带质量检查与多样性维护）。理论部分把学习过程形式化为 MDP：内循环在"Writer 做隐式贝叶斯推断"的假设下贝叶斯遗憾对迭代次数 T 次线性；外循环用离线 RL 的 pessimism 原理证明性能差距收敛；合起来总迭代 KT 下仍是次线性遗憾。

`[转述]` 落地形态是**挖掘交易信号**：Agent 产出 Python 实现的 alpha 类（用历史价量数据预测市场走势）。实验用 2023 年 500 只中国 A 股，backbone 为 GPT-4。指标三层：预测性能（IC、Sharpe、XGBoost MSE）、信号质量（有效且唯一的实体数量）、交易想法对齐度（LLM 两两比较）。结果显示随 KB 增长，XGBoost 的 MSE 持续下降，胜率矩阵持续改善；消融显示内外循环缺一不可。

**输出是代码、评估是程序化、知识库是结构化积累**——这三个特征与 RD-Agent(Q) 一致，是"策略生成"路线的正确形态。

`[第三方]` 未找到作者官方仓库；检索到的 [pillar/quantagent](https://github.com/pillar/quantagent) 自我描述为 "Official Repository" 但内容是技术指标 + 形态识别 + 趋势分析的多 Agent 分析系统，与论文的双层循环不符，**官方性未能确认**。

---

## 6. 其他 2025–2026 有代表性的工作

- **Trading-R1**（[arXiv:2509.11420](https://arxiv.org/abs/2509.11420)，Tauric 团队）：不走多 Agent 而走模型路线——用 SFT + RL 的三阶段 easy-to-hard 课程训练金融推理模型；训练语料 Tauric-TR1-DB 为 10 万样本，覆盖 18 个月、14 只股票、5 类异构金融数据源；在 6 只主要股票与 ETF 上评估，声称风险调整收益更高、最大回撤更低；产出结构化的、有证据支撑的投资论证。代码将发布在 `github.com/TauricResearch/Trading-R1`。
- **FinCon**（[arXiv:2407.06567](https://arxiv.org/abs/2407.06567)）：manager-analyst 层级通信，配**概念性语言强化**——一个风控组件周期性地启动自我批评，把更新后的"系统性投资信念"作为语言强化**有选择地传播到需要更新的那个节点**，从而降低点对点通信成本。支持单股交易与组合管理。
- **InvestorBench**（[arXiv:2412.18174](https://arxiv.org/abs/2412.18174)，ACL 2025）：首个面向 LLM Agent 金融决策任务的基准，试图解决"缺乏标准化基准与一致数据集"的问题。
- **QuantBench**（arXiv:2504.18600）、**FinTSB**（arXiv:2502.18834）：量化投资方法基准与金融时序预测基准，FINSABER 引用它们作为前序工作。
- 同期多 Agent 方向还有 MarketSenseAI 2.0（2502.00415）、HedgeAgents（2502.13165）、TwinMarket（2502.01506，用 LLM Agent 做可扩展的金融市场行为与社会仿真）、Fin-R1（2503.16252）。

---

## 7. 第三方批评（横切，比任何单个项目的自述都重要）

### 7.1 FINSABER：长期、宽横截面下 LLM 优势崩塌 `[第三方]`

[arXiv:2505.07078](https://arxiv.org/abs/2505.07078)"Can LLM-based Financial Investing Strategies Outperform the Market in Long Run?"（Weixian Waylon Li, Hyeonjun Kim, Mihai Cucuringu, Tiejun Ma）提出 FINSABER 回测框架，批评既有评估"在窄时间窗与有限股票池上进行，因幸存者偏差与数据窥探偏差而高估有效性"。结论：

- 在**二十年、100+ 标的**上的系统回测显示，此前报告的 LLM 优势在更宽横截面与更长周期上**显著恶化**。
- 市场状态分析显示 LLM 策略**在牛市过于保守**（跑输被动基准），**在熊市过于激进**（承受重大损失）。
- 建议：优先发展趋势识别与**状态感知的风控**，而不是继续堆叠框架复杂度。

它点名评估的对象包含 TradingAgents、FinMem、TradingGPT、QuantAgent、FinRobot、FinCon 等——**上面第 2–5 节里几乎所有"论文自称超越基线"的结果，都在它的射程内。**

### 7.2 标准基准失效：应优先审计风险 `[第三方]`

[arXiv:2502.15865](https://arxiv.org/abs/2502.15865)"Standard Benchmarks Fail -- Auditing LLM Agents in Finance Must Prioritize Risk"的核心立场：

- 准确率指标与收益类分数"提供了一种可靠性的幻觉"，忽略了**幻觉事实、过期数据、对抗性 prompt 操纵**等脆弱性。
- 主张金融 LLM Agent 应**首先按风险画像评估，其次才看点估计性能**；提出 model / workflow / system 三层压力测试议程。
- 审计了 6 个 API 型与开放权重 LLM Agent，在三个高风险任务上发现了常规基准看不到的隐藏弱点。
- 建议：发表研究时同时公开压力场景、把"安全预算（safety budget）"作为主要成功判据。

---

## 8. 对我们的可借鉴点

前提：FrontierAgent 是通用 ReAct + Agent Team harness；我们要做的是**机会挖掘 + 策略生成**，明确不做交易执行；已有 [`docs/tittel/fin-research-three-layer-architecture.md`](./fin-research-three-layer-architecture.md) 定义 L1 原文层 / L2 检索层 / L3 数值层，红线是"检索只负责定位，取证永远回到原文/源头；任何 LLM 摘要不得进入证据链"。

### 8.1 直接可用

| # | 借鉴点 | 来源 | 为什么可直接用 |
|---|---|---|---|
| 1 | **确定性计算与 LLM 叙述分离**：数字由代码算子算，LLM 只做推理与写作，每个输出带出处 | FinRobot README 原文 "Numbers are code-calculated. Narratives are LLM-assisted. Every output is provenance-tracked."（[链接](https://github.com/AI4Finance-Foundation/FinRobot)） | 与我们 L3 数值层红线同构。落地口径：任何进入结论的数值必须来自工具返回值或数据库直查，LLM 复述的数值需与工具值逐字比对，不一致即判失败 |
| 2 | **决策节点结构化输出 + 解析失败显式哨兵** | TradingAgents `schemas.py` 的 Pydantic 枚举与 `REVIEW` 哨兵（[链接](https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/agents/schemas.py)、[signal_processing.py](https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/graph/signal_processing.py)） | 我们 Agent 节点已有 `output_fields` 机制；照抄两点即可：(a) 方向与置信度用枚举而非自由文本；(b) 解析不出结论时返回可识别的哨兵值，**绝不能静默降级为"中性/持有"** |
| 3 | **可选数值字段的空值清洗** | schemas.py 的 `_NULLISH_FLOAT`，把 `"None"/"N/A"/"-"/"unknown"` 前置转 `None` | 三行代码，能消掉一大类结构化调用崩溃 |
| 4 | **策略产出物是代码/可执行描述，不是自然语言买卖建议** | RD-Agent(Q) 明确批评"直接以自然语言生成交易信号"缺乏可验证性与确定性（[链接](https://www.microsoft.com/en-us/research/articles/rd-agent-quant/)）；QuantAgent 同样输出 Python alpha 类 | 代码可回测、可版本化、可 diff、可复现，天然满足我们的"可证伪"要求；自然语言报告只能作为代码的说明层 |
| 5 | **前视偏差检查清单（点对时数据契约）** | TradingAgents v0.4.0 修的 6 类缺陷 #1275 / #1220 / #1251 / #1169 / #1201 + #475（[CHANGELOG](https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/CHANGELOG.md)） | 这是一份免费的、用 103k star 项目的真实事故换来的清单。直接转成我们的验收项：数据快照必须带 vintage；文本/舆情检索必须带时间窗上界；记忆/经验注入必须带"何时可知日"；结算必须等窗口走完；最新一根 bar 缺失要报错而非回退 |
| 6 | **决策日志 + 延迟反思 + 相对基准的超额** | TradingAgents 的 `TradingMemoryLog` 与 `_fetch_returns()`（5 日持有 + alpha vs 区域基准 + 一段式反思注入下次 prompt） | 低成本、高价值；我们只需把"基准"换成我们自己的对照集，把"5 日"换成与我们策略周期一致的持有窗口 |
| 7 | **身份与价格的确定性锚定** | TradingAgents #814 / #830：ticker→公司身份在任何 Agent 运行前确定性解析；市场分析师的价格与指标主张强制基于已验证快照 | 与我们的"取证回原文"完全同构，可直接作为工具契约：先解析身份，再取数，最后才允许推理 |
| 8 | **多臂老虎机决定下一轮优化方向** | RD-Agent(Q) Analysis 单元的线性 Thompson 采样调度器 | 当我们有多个可优化维度（数据源 / 因子 / 提示 / 检索策略）且算力有限时，这是现成的调度策略 |

### 8.2 需改造

| # | 借鉴点 | 来源 | 需要改什么 |
|---|---|---|---|
| 1 | **多角色辩论**（多空 + 激进/保守/中性风控） | TradingAgents 的 Bull/Bear 与 risk_mgmt 三 debator（[目录](https://github.com/TauricResearch/TradingAgents/tree/main/tradingagents/agents/risk_mgmt)） | 三处必改：(a) 默认只打 1 轮太浅，放到 2–3 轮但同时设 token 与轮次上限；(b) 必须修掉 #1176——首轮无对手发言时**先自陈观点，不得"反驳空回复"**，否则等于让模型编造对方立场；(c) 辩论产物必须是带证据引用的论点，不是立场陈述，否则辩论只会放大修辞而非信息 |
| 2 | **分层记忆与衰减** | FinMem 的 Shallow(14d) / Intermediate(90d) / Deep(365d) + `γ = w1·Recency + w2·Relevancy + w3·Importance` + 访问计数提层 | 研报库是静态入库的，**写入时间 ≠ 信息时效**。把"Recency"换成"事实有效期/失效事件"（财报被新版覆盖、预测被实际值证伪、评级被下调），把"访问计数"换成"被引用且被验证通过"的次数 |
| 3 | **风险人格** | FinMem 的 risk-seeking / risk-averse / self-adaptive | 我们不做执行，不让 Agent 自己切换风险档。改造为：对同一机会**并行生成多个风险画像的候选策略**，把选择权交给人；self-adaptive 那种"亏了就变保守"的自动切换，在没有回测验证前不应启用 |
| 4 | **因子/策略去重 + 对称验证** | RD-Agent(Q) Validation 单元：新因子与现有最优因子库算相似度去重，再与当前最优模型组合回测；新模型对称评测 | 相似度度量要自己定（我们没有 Qlib 级别的因子栈）：建议用"证据集合重合度 + 触发条件重合度 + 标的重合度"的复合指标，而不是数值相似度 |
| 5 | **周期性自我批评更新"投资信念"并选择性传播** | FinCon 的风控组件 | "信念"是自然语言，会漂移、会与证据脱节。改造为**版本化的结构化信念条目**（含提出时间、支撑证据 ID、证伪条件、当前状态），更新只在证据变化时触发，且全量可回溯 |
| 6 | **绩效指标（IC / ICIR / Rank IC / ARR / IR / MDD / Calmar）** | RD-Agent(Q) 集成 Qlib 的那套 | 在有回测引擎之前这些指标无意义。过渡期改用过程指标：可证伪主张的覆盖率、证据引用命中率、点对时违规次数、结论被后续数据证伪的比例 |

### 8.3 不适用

| # | 项目 / 机制 | 为什么不适用 |
|---|---|---|
| 1 | **一切执行层**：TradingAgents README 里的 "simulated exchange"、AI-Trader 的券商同步 / 一键跟单 / 复制交易、Nof1 的 Hyperliquid 实盘下单 | 我们明确不做交易执行。附带结论：开源 TradingAgents 里其实**没有**真正的下单实现，`propagate()` 只返回评级字符串——连"研究一下它的执行层"这个选项都不存在 |
| 2 | **实盘竞赛式评估**（Nof1 Alpha Arena） | 它自己承认样本有限、周期短、模型无往绩历史、无累积学习；第三方（张超）指出衡量策略需跨越一个经济周期。样本量不足 + 成本极高 + 结论不可复现，无法作为我们的评估手段 |
| 3 | **端到端模型训练**：Trading-R1 的 SFT+RL 三阶段课程（需 10 万样本 / 18 个月 / 14 只股票 / 5 类数据源）、FinGPT 的 LoRA 微调、Fin-R1 | 我们定位在 harness / 平台层，不是做模型；且依赖我们不具备的金融数据授权与训练预算 |
| 4 | **AI-Trader 的社交与商业化层**：信号订阅、积分激励、复制交易、跨券商同步 | 产品形态与合规边界都不属于投研平台 |
| 5 | **StockAgent 的市场行为仿真** | 研究目标是"外部因素如何影响交易行为"，产出是仿真记录而非策略 |
| 6 | **FinGPT 的模型层与 FinRobot 的估值算子作为整体架构** | FinGPT 是模型生态不是 Agent 架构；FinRobot 的 30 个估值算子面向美股个股估值（DCF/DDM/LBO/WACC），与我们的"研报 + 宏观策略"口径不同。两者都应作为**组件**引用，而不是照搬架构 |
| 7 | **论文里报告的收益数字**（TradingAgents 的 AAPL 26.62% / Sharpe 8.21 / MDD 0.91%，FinMem 的 TSLA Sharpe > 2.0 等） | 全部落在 FINSABER 的批评射程内（窄时间窗 + 窄股票池 + 幸存者/数据窥探偏差）；且 TradingAgents README 自己声明"回测结果不保证与任何已发表数字一致"。**这些数字只能用来理解论文主张，不能作为我们系统的目标值** |

---

## 9. 三条硬约束建议（从以上调研反推）

1. **点对时（point-in-time）是一等公民，不是补丁。** TradingAgents 到 v0.4.0（发布后 14 个月）才系统性修完 6 类前视偏差。我们的数据接入层从第一天起就要把"as-of 日期"作为所有取数接口的强制参数，并把"记忆/经验注入"也纳入 as-of 约束。
2. **数值只有一个来源。** FinRobot 的 "Numbers are code-calculated" 与我们 L3 红线一致：LLM 生成的数字必须与工具返回值逐字比对，不一致即失败；不允许"模型算的"和"工具查的"两个数值并存。
3. **不做执行，就不要有"交易信号"这个输出类型。** 输出应为：机会（标的 + 驱动因素 + 证据链 + 失效条件）+ 策略（可执行/可回测的代码或结构化描述 + 适用状态 + 已知风险）。这既是我们与所有上述项目的分界线，也是 FINSABER 与 Standard Benchmarks Fail 两篇批评共同指向的方向——把评估重心从"收益数字"移到"风险画像与可证伪性"。
