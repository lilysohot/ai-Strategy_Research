# LLM 交易 Agent 的实际表现证据调研

> 调研目的：判断「只做机会发现与策略辅助、不做自动执行」这一产品定位，在当前技术条件下是否被证据支持。
> 调研方式：只读联网研究，全部结论尽量回溯到一手来源（arXiv 原文、主办方官方博客、基准官方排行榜）。
> 调研日期：2026-09-06。
> 写作原则：**如实报告负面证据**。凡是查不到可信一手来源的议题，明确写「未找到可信一手来源」，不用二手博客充数。

---

## 0. 来源分级与阅读须知

本文对每条证据标注了来源等级：

| 等级 | 含义 | 使用规则 |
|---|---|---|
| **S1** | 一手来源：论文原文摘要/正文、主办方官方博客、基准官方排行榜 | 可直接引用数字 |
| **S2** | 论文作者自己发布的项目页/海报/幻灯片 | 可引用，但注明载体 |
| **S3** | 主流媒体对官方数据的报道（多源交叉一致） | 引用时注明「来自媒体报道」 |
| **S4** | AI 生成的论文摘要页（如 alphaXiv 的 AI Overview） | **仅用于补充正文细节，且必须标注**，不作为独立证据 |
| — | 未找到 | 明确写「未找到可信一手来源」 |

**重大限制说明（必须先读）**：

1. `arxiv.org` 主站在本次调研期间无法直接抓取（`fetch failed`），论文内容通过 `arxiv.gg`（arXiv 镜像，含完整摘要与元数据）、`huggingface.ac.cn`、`alphaxiv.org` 获取。**所有 arXiv 引用均给出 arXiv ID**，读者可自行核对原文。
2. `nof1.ai` 官网在调研期间返回 HTTP 429（限流），其官方博客内容通过一篇标注原文标题、作者、发布日期的中文全译文获取（见 B1 节）。**Alpha Arena 的各模型最终收益率未能从 nof1.ai 官方页面直接抓取**，来自多家媒体对官方榜单的报道。
3. 多数论文的**实验数值表格在 PDF 内**，摘要中不含具体数字。凡数字来自摘要以外的地方，本文均标注其来源等级。

---

## 1. TL;DR（先给结论，后给证据）

1. **收益预测能力：没有可信证据表明 LLM 在广义横截面上优于买入持有。** 唯一做了「20 年 × 100+ 标的」偏差校正回测的 FINSABER（arXiv:2505.07078，KDD 2026）明确写道：先前论文报告的 LLM 优势在更宽的横截面和更长的时间跨度上**显著退化**。
2. **短窗口、小股票池的漂亮数字是选择偏差的产物。** TradingAgents 报告 AAPL 三个月夏普 8.21、最大回撤 0.91%（S4）；FINSABER 用同一类策略在 2004–2024 全样本上复现不出这个结果。夏普 8.21 在 60 个交易日样本上不是可外推的统计量。
3. **唯一有真实资金、真实成交的公开实验（Nof1 Alpha Arena S1）里，6 个模型中 4 个亏损，最差 -62.66%**（S3，媒体报道官方榜单）。主办方自己写明「不期望任何模型表现出色，早期成功很可能只是运气」（S1，官方博客）。
4. **风控是 LLM 交易 Agent 最弱的一环，且方向是反的**：牛市过于保守跑输被动基准，熊市过于激进承担巨亏（S1，FINSABER 摘要）。
5. **没有任何一个交易基准报告过单次决策的 token 消耗或 API 成本**（未找到可信一手来源）。这意味着「LLM 交易是否盈利」这个命题本身在现有文献里尚未被完整定义——成本项缺失。
6. **结论指向：支持「只做辅助不做执行」。** 详见第 7 节。

---

## 2. A. 标准化评测基准

### 2.1 基准全景对照表

| 基准 | 来源 | 评测什么 | 时间区间 / 口径 | 关键指标 | 是否含朴素基线 |
|---|---|---|---|---|---|
| **FinBen** | NeurIPS 2024 D&B，arXiv:2402.12659 | 42 数据集 / 24 任务 / 8 类：IE、文本分析、QA、文本生成、**风险管理**、**预测**、**决策**、双语 | 静态数据集，无交易时间序列 | 各任务自有指标 | 摘要未报告；论文 Table 5 据称与 Buy&Hold 对比（**数字未获取**） |
| **InvestorBench** | ACL 2025 Long，arXiv:2412.18174 | LLM Agent 在**个股 / 加密 / ETF** 三类资产的序贯决策 | 未公开统一窗口，多市场环境 | CR、SR、年化波动率、**MDD** | **未设置买入持有/等权基线**（S1 摘要+S4 正文均未提及） |
| **StockBench** | arXiv:2510.02209（清华/北邮） | DJIA 权重前 20 只股票的日频买/卖/持有 | **2025-03-03 至 2025-06-30，82 个交易日**，$100k 起 | 最终收益、**最大回撤**、**Sortino**、综合 z 排名 | **有**：等权买入持有作为 Passive Baseline |
| **LiveTradeBench** | arXiv:2511.03628（UIUC） | **实时**多市场组合配置（美股 + Polymarket） | **50 天实时评测**，非离线回测 | 组合收益（摘要未给数值） | 未与被动基准对比；与 LMArena 静态分对比 |
| **Agent Market Arena (AMA)** | arXiv:2510.11695 | **终身实时**基准，加密货币 + 股票；4 种 Agent 架构 × 5 个骨干模型 | 实时持续 | 行为模式 + 收益 | 有单 Agent 基线（InvestorAgent） |
| **AI-Trader** | arXiv:2512.10971（HKUDS） | 全自动、数据无污染；**美股 + A 股 + 加密货币**，多交易粒度 | **2025-10-01 至 2025-11-07 实盘** | 收益 + 风控 | 与市场基准对比（**数字未获取**） |
| **FINSABER** | arXiv:2505.07078（KDD 2026） | 择时策略的**偏差校正回测**：存活者偏差/前视偏差/数据窥探偏差 | **2004–2024，20 年，100+ 标的** | AR、年化波动、**Sharpe**、**Sortino**、佣金比 | **有**：Buy & Hold |
| **AlphaFin** | arXiv:2403.12582 | 检索增强的金融分析（ConvFinQA 等）+ 手写 CoT | 静态 QA 数据集 | QA 准确率 | 不适用（非交易任务） |
| **FinEval** | arXiv:2308.09975 / NAACL 2025 | 中文金融**知识**选择题（金融/经济/会计/证书），4,661→8,351 题 | 静态 | 准确率 | 不适用（纯知识，不含交易） |
| **CFLUE** | aliyun/cflue（GitHub） | 中文金融语言理解 | 静态 | 各任务准确率 | 不适用 |
| **FinMTEB** | — | 金融文本嵌入评测 | — | — | **未找到可信一手来源**（本次调研未定位到权威论文/官方页） |

### 2.2 各基准的关键发现

#### FinBen（NeurIPS 2024）—— S1

- 覆盖 42 个数据集、24 个任务、8 个方面，包含**风险管理、预测、决策**三类高阶任务，并**首次评测股票交易**。
- 评测 21 个代表性 LLM。核心结论（S1，NeurIPS 官方摘要）：
  - LLM 在 **信息抽取（IE）和文本分析上表现出色**；
  - 但在**高级推理和复杂任务（文本生成、预测）上明显吃力**——「struggle with advanced reasoning and complex tasks like text generation and **forecasting**」；
  - GPT-4 在 IE 和股票交易上最强，Gemini 在文本生成和预测上更好；
  - 指令微调提升文本分析，但对 QA 这类复杂任务收益有限。
- **对本文的意义**：FinBen 明确指出 LLM 在「预测（forecasting）」这一子类上就是短板，而预测正是交易决策的输入。

来源：https://proceedings.neurips.com.cn/paper_files/paper/2024/hash/adb1d9fa8be4576d28703b396b82ba1b-Abstract-Datasets_and_Benchmarks_Track.html ；arXiv:2402.12659

#### InvestorBench（ACL 2025）—— S1（摘要）+ S4（正文细节）

- 首个专为 LLM Agent 金融决策设计的基准；资产覆盖单只股票、加密货币、ETF；13 个 LLM 骨干模型；指标 CR / SR / 年化波动率 / MDD。
- 结论（S1 摘要 + S4 正文）：闭源 > 开源；模型规模显著影响金融推理；**领域微调（BloombergGPT、FinMA）并未稳定超越同规模通用模型**；所有模型在高波动期（如市场崩盘）都表现挣扎。
- **重大缺口（对本文很关键）**：InvestorBench **没有设置买入持有 / 等权 / 随机这类朴素基线**。它的对比是「LLM A vs LLM B」。因此这个基准**无法回答「LLM 是否比不做事更强」**。
- 作者自述的局限（S4）：仿真环境**简化了滑点、流动性约束和交易成本**。
- 来源：https://arxiv.org/abs/2412.18174 ；https://aclanthology.org/2025.acl-long.126/

#### StockBench（清华/北邮，2025）—— S1（官方排行榜）

这是目前**口径最干净、且明确把买入持有放进排行榜**的基准。

- 设置：DJIA 权重前 20 只股票；初始 $100,000 现金、零持仓；**评测期 2025-03-03 至 2025-06-30，82 个交易日**；每日接收价格、基本面指标（P/E、市值、股息率、52 周区间）、前 48 小时 Top-5 新闻；数据期**晚于所有被测 LLM 的知识截止**，因此无数据污染。
- 指标：最终收益（Final Return）、最大回撤（MDD）、Sortino 比率；综合排名 = (z(收益) − z(回撤) + z(Sortino)) / 3。
- **官方排行榜原文（3 次运行平均）**：

| 排名 | 模型 | 最终收益 | 最大回撤 | Sortino |
|---|---|---|---|---|
| 1 | Kimi-K2 | **+1.9%** | −11.8% | 0.0420 |
| 2 | Qwen3-235B-Ins | +2.4% | −11.2% | 0.0299 |
| 3 | GLM-4.5 | +2.3% | −13.7% | 0.0295 |
| 4 | Qwen3-235B-Think | **+2.5%** | −14.9% | 0.0309 |
| 5 | OpenAI-O3 | +1.9% | −13.2% | 0.0267 |
| 6 | Qwen3-30B-Think | +2.1% | −13.5% | 0.0255 |
| 7 | Claude-4-Sonnet | +2.2% | −14.2% | 0.0245 |
| 8 | DeepSeek-V3.1 | +1.1% | −14.1% | 0.0210 |
| 9 | **GPT-5** | **+0.3%** | −13.1% | 0.0132 |
| 10 | Qwen3-Coder | +0.2% | −13.9% | 0.0137 |
| 11 | DeepSeek-V3 | +0.2% | −14.1% | 0.0144 |
| 12 | **Passive Baseline（等权买入持有）** | **+0.4%** | **−15.2%** | 0.0155 |
| 13 | GPT-OSS-120B | −0.9% | −14.0% | 0.0156 |
| 14 | GPT-OSS-20B | −2.8% | −14.4% | −0.0069 |

来源：https://stockbench.github.io/ （官方站点 LEADERBOARD 表，脚注「Results averaged over 3 runs during March 1-June 30 2025 evaluation period」）

**对这张表必须做的三点解读（不要只看排名）**：

1. **按绝对收益，13 个模型中有 5 个跑输被动基准的 +0.4%**（GPT-5 +0.3%、Qwen3-Coder +0.2%、DeepSeek-V3 +0.2%、GPT-OSS-120B −0.9%、GPT-OSS-20B −2.8%）。最佳模型 Kimi-K2 +1.9%，仅比被动基准高 1.5 个百分点。
2. **但所有 13 个模型的最大回撤都优于被动基准的 −15.2%**（模型区间 −11.2% ~ −14.9%）。这是 LLM Agent 唯一稳定胜过朴素基线的维度——**它确实在压波动，代价是压掉了收益**。
3. **统计口径极弱**：只有 3 次运行、82 个交易日、4 个月、20 只美股蓝筹。4 个月 1.5 个百分点的收益差在这个样本量下**没有报告显著性检验**，本质上在噪声范围内。任何「模型 X 比模型 Y 会炒股」的说法都站不住。
4. **市场状态依赖**：在下跌段**没有任何 Agent 跑赢被动基准**；上涨段多数跑赢（S1 论文结论，经 deep-paper 与 maxpool 两处一致转述）。即：**LLM Agent 在牛市里看起来行，是因为牛市里买什么都行**。
5. **组合规模扩展性差**：随可交易股票数增加，所有模型表现退化（小模型尤甚），表现为收益下降、收益波动上升。
6. **错误类型**：算术错误（算错股数）与 Schema 错误（JSON 格式不合规）。推理型模型算术更准但格式错误更多；指令型模型反之。**没有任何 Agent 表现出一致的止损/限亏行为**（S4 转述：「No agent demonstrated consistent loss-limiting behavior」）。

#### LiveTradeBench（UIUC，2025-11）—— S1

- **50 天实时评测**（非离线回测），跨美股与 Polymarket 预测市场，21 个 LLM。
- 核心结论（S1 摘要原文）：**「high LMArena scores do not imply superior trading outcomes」**——静态榜单高分不能预测实时交易表现。
- 模型呈现差异显著的投资组合风格（风险偏好与推理动态驱动）；**只有部分 LLM 能有效利用实时信号**（原文：「some LLMs effectively leverage live signals」），即其余模型无法适应实时不确定性。
- 来源：https://arxiv.org/abs/2511.03628

**这份证据对产品定位很关键**：它直接否定了「用通识/推理榜单分数挑一个模型来做交易」这条路径。

#### Agent Market Arena（2025-10）—— S1

- 终身实时基准，加密货币 + 股票双市场；4 种 Agent 架构（InvestorAgent 单 Agent 基线 / TradeAgent / HedgeFundAgent / DeepFundAgent）× 5 个骨干（GPT-4o、GPT-4.1、Claude-3.5-haiku、Claude-sonnet-4、Gemini-2.0-flash）。
- 核心结论（S1 摘要原文）：**Agent 框架架构决定行为模式（从激进到保守），而骨干模型对结果差异的贡献更小**——「agent frameworks display markedly distinct behavioral patterns... whereas **model backbones contribute less to outcome variation**」。
- **含义**：换模型不如换约束框架。风险偏好是**被架构和提示词塑造出来的**，不是模型固有属性。这对「辅助而非执行」的定位是正面证据：人类设定框架，LLM 在框架内产出。
- 来源：https://arxiv.org/abs/2510.11695

#### AI-Trader（HKUDS，2025-12）—— S1

- 首个全自动、**数据无污染**的实时金融决策基准；覆盖美股、A 股、加密货币三市场，多交易粒度；6 个主流 LLM。
- 「最小信息范式」：Agent 只拿到必要上下文，必须自行检索、验证、综合实时信息。
- 核心结论（S1 摘要原文）：**「general intelligence does not automatically translate to effective trading capability, with most agents exhibiting poor returns and weak risk management」**；**「risk control capability determines cross-market robustness」**；**AI 交易策略在高流动性市场比在政策驱动市场（A 股）更容易获得超额收益**。
- 实盘区间：**2025-10-01 至 2025-11-07**（S1，arXiv HTML 正文片段）。
- **具体数值未获取**（PDF 表格未能抓取）。
- 来源：https://arxiv.org/abs/2512.10971

#### FINSABER（KDD 2026，本次调研中**最重要的负面证据**）—— S1

- 方法：显式消除三类偏差——**存活者偏差**（使用历史当时真实存在的 S&P 500 成分股，含已退市公司）、**前视偏差**（Agent 只能用到交易时点可得信息）、**数据窥探偏差**。
- 数据：2004–2024 共 20 年，7,000+ 只股票日频价格、1,570 万条金融新闻、SEC EDGAR 的 10-K/10-Q 分段文本；**100+ 标的**。
- 指标：年化收益（AR）、年化波动率（AV）、夏普（SPR）、索提诺（STR）、佣金比。
- **核心结论（S1 摘要原文，逐字）**：
  > 「Systematic backtests over two decades and 100+ symbols reveal that **previously reported LLM advantages deteriorate significantly** under broader cross-section and over a longer-term evaluation.」
  > 「Our market regime analysis further demonstrates that **LLM strategies are overly conservative in bull markets, underperforming passive benchmarks, and overly aggressive in bear markets, incurring heavy losses**.」
- 关键过程结论（S4，来自 alphaXiv 对正文的 AI 摘要，**需自行核对原文后再对外引用**）：
  - 用配对 t 检验验证，先前的 LLM 优势「往往是特定时间窗或股票选择造成的假象」；在更宽的无偏股票池上，**买入持有显著跑赢 LLM 策略**。
  - 用 CAPM 分解 α/β：**没有任何 LLM 策略产生统计显著的正 α**；部分策略（FinMem）α 为负，即在**主动毁灭价值**。
  - **过度交易**：FinMem 存在「病态交易画像」，佣金比是更克制 Agent 的 **5~9 倍**；高换手没有带来更高收益，反而导致更久的水下期（drawdown）。
- 作者幻灯片（**S2，作者本人发布**）中的具体数字：「Even where LLMs win on return, risk is extreme: on TSLA, **FinAgent reaches AR 59.8% with 41.6% volatility and −36.9% drawdown**」——即：收益好看的时候，风险是极端的。
- 来源：https://arxiv.org/abs/2505.07078 ；作者项目页 https://waylonli.github.io/FINSABER/ ；作者幻灯片 https://waylonli.com/files/finsaber-slides.pdf ；代码 https://github.com/waylonli/FINSABER

### 2.3 A2 —— 关键问题：有没有基准明确测过「LLM 收益预测是否优于随机/朴素基线」？

**有，而且结论是负面的。** 三份证据：

**证据 1：FINSABER（上节）——最直接、口径最严。** 上文已述。这是目前唯一把「20 年 × 100+ 标的 × 偏差校正」三件事同时做到的系统回测，结论是 LLM 优势显著退化、无显著正 α、牛市保守熊市激进。

**证据 2：Lopez-Lira & Tang, arXiv:2304.07619（83 次引用，多篇后续研究的基准参照）——预测能力存在，但不可交易、且会衰减。**

- 方法：用 ChatGPT/GPT-4 对**知识截止之后**的新闻标题打分，预测次日股票收益。
- S1 摘要要点（逐字）：
  - 「Using post-knowledge-cutoff headlines, **GPT-4 captures initial market responses, achieving approximately 90% portfolio-day hit rates for the non-tradable initial reaction**.」
  - 「GPT-4 scores also **significantly predict the subsequent drift**, especially for small stocks and negative news.」
  - 「Forecasting ability generally increases with model size.」
  - 「**Strategy returns decline as LLM adoption rises, consistent with improved price efficiency.**」
- **必须强调的两点**（这两点常被二手传播忽略）：
  1. 那个 90% 的命中率针对的是 **non-tradable initial reaction（不可交易的初始反应）**——论文自己标注了「不可交易」。能变现的部分（后续漂移）的效应量远小于这个数字。
  2. **策略收益随 LLM 采用率上升而下降**。这是一个自我衰减的 alpha：用的人越多越不赚钱。
- 关于广泛流传的「GPT-3.5 多空策略 2021-10 至 2022-12 累计 550%+」：**未找到可信一手来源核实**。该数字出现在中文财经博客转述中，且明确标注为「不考虑交易成本」。原始论文摘要中不含此数字。**不予采信**。
- 来源：https://arxiv.org/abs/2304.07619

**证据 3：StockBench（上节）——组合层面的直接对照。** 13 个模型中 5 个跑输等权买入持有；最好的也只高 1.5 个百分点；下跌段全军覆没。

**结论**：把三份证据放在一起，可以负责任地说——

> **在「LLM 的收益预测能力是否优于朴素基线」这个问题上，现有的、口径最严格的一手证据给出的答案是否定的。存在统计上可测量的预测信号（Lopez-Lira & Tang），但该信号（a）大部分落在不可交易的初始反应上，（b）随采用率上升而衰减，（c）在扣除交易成本、扩展到宽横截面后，无法转化为跑赢买入持有的组合收益（FINSABER）。**

### 2.4 A3 —— 有没有专门评测风险管理（回撤控制、仓位约束遵守率）而非只看收益的基准？

**答：没有成型的、以风险管理为首要指标的公开排行榜基准。** 分层说明：

**层级一：把风险指标纳入多维度评分，但收益仍占权重**

- StockBench：MDD + Sortino 与收益并列，综合 z 排名。**这是目前最接近的**。
- InvestorBench：MDD + 年化波动率与 CR/SR 并列。
- 但两者的排行榜**仍以综合分或收益为主轴对外呈现**。

**层级二：明确主张「必须先评风险」的立场论文（尚未落地为基准）**

- **arXiv:2502.15865《Standard Benchmarks Fail — Auditing LLM Agents in Finance Must Prioritize Risk》**（S1 摘要）：
  - 原文立场：「Standard benchmarks fixate on how well LLM agents perform in finance, yet say little about whether they are safe to deploy. We argue that **accuracy metrics and return-based scores provide an illusion of reliability**, overlooking vulnerabilities such as **hallucinated facts, stale data, and adversarial prompt manipulation**.」
  - 主张：「financial LLM agents should be evaluated **first and foremost on their risk profile**, not on their point-estimate performance.」
  - 提出三层压力测试议程：**model / workflow / system**；审计了 6 个 LLM Agent（API 闭源 + 开源权重）在 3 个高影响任务上的表现，发现了常规基准漏掉的隐藏弱点。
  - 给研究者/实践者/监管者的建议：**发布压力测试场景、把「safety budget」作为首要成功标准**。
  - 来源：https://arxiv.org/abs/2502.15865
  - **限制**：这是立场论文（position paper），不是可复现的公开基准，没有排行榜。

**层级三：把「成本」纳入回测框架（与风险同源的思路）**

- **FINSABER-2**（作者项目页，S1）：框架明确列出 **5 项成本控制**，并把 **「LLM costs（LLM 推理成本）」与佣金、滑点、流动性上限并列为一等回测成本项**——原文：「Choose next_open or same_close, adjusted prices, commission, slippage, liquidity caps, and **LLM costs**.」
  - **这是本次调研中找到的最有力的间接证据**：连做 LLM 交易研究的团队，都已经把 LLM 推理成本当作策略 P&L 的必要扣减项来建模。而绝大多数已发表的 LLM 交易论文（含 TradingAgents，见 C 节）根本没有建模它。
  - 来源：https://waylonli.github.io/FINSABER/

**明确未找到的**：以「**仓位约束遵守率**」「**止损执行率**」「**回撤预算超限次数**」为主指标的公开基准排行榜——**未找到可信一手来源**。

---

## 3. B. 真实市场 / 近真实市场的实盘证据

### 3.1 B1 —— Nof1 Alpha Arena 第一赛季（本次调研中唯一的真实资金公开实验）

**来源说明**：官方博客原文为 *Exploring the Limits of Large Language Models as Quant Traders*，Nof1，2025-10-27。本文内容取自标注原文标题/作者/发布日期的中文全译文（S1-译文）。`nof1.ai` 官网在调研期间返回 HTTP 429，**最终各模型收益率数字来自多家媒体（界面新闻/搜狐、36 氪、iWeaver）对官方榜单的报道（S3）**，多源一致。

#### 实验设置（S1，官方博客）

| 项目 | 设置 |
|---|---|
| 起始资金 | 每模型 **$10,000 真实现金** |
| 交易场所 | Hyperliquid，加密货币**永续合约**（允许杠杆做多/做空） |
| 标的 | BTC、ETH、SOL、BNB、DOGE、XRP 共 6 种 |
| 输入 | **仅数值型市场数据**（当前及历史中间价与成交量、精选技术指标、短中长期时间尺度辅助特征）。**不给新闻、不给市场叙事** |
| 公平性 | 所有 Agent 使用**相同的系统提示、用户提示模板、数据输入、默认采样配置**；除 Qwen3-Max 外均启用最高推理档位；无任务特定微调 |
| 动作空间 | 买入（做多）/ 卖出（做空）/ 持仓 / 平仓 |
| 输出 | 方向 + 数量 + **杠杆** + 简要理由 + **置信度（0–1）** + **退出计划（预设止盈、止损、失效条件）** |
| 推理节奏 | **每次推理调用间隔约 2~3 分钟**（官方原文） |
| 周期 | 2025-10-18 发起，**2025-11-03 17:00 ET 结束**，历时 17 天 |
| 参与模型 | GPT-5、Gemini 2.5 Pro、Claude Sonnet 4.5、Grok 4、DeepSeek v3.1、Qwen3-Max |

官方明确定位为**中低频交易（MLFT），决策间隔分钟到小时级，而非高频的微秒级**。

#### 最终收益（S3，媒体报道官方榜单，2025-11-04）

| 排名 | 模型 | 最终收益 |
|---|---|---|
| 1 | Qwen3-Max | **+22.32%** |
| 2 | DeepSeek v3.1 | **+4.89%** |
| 3 | Claude Sonnet 4.5 | −30.81% |
| 4 | Grok 4 | −45.3% |
| 5 | Gemini 2.5 Pro | −56.71% |
| 6 | GPT-5 | **−62.66%** |

**6 个模型中 4 个亏损；只有两个中国模型盈利；四个美国模型全部亏损，GPT-5 垫底。**

> 关于交易次数的数字存在冲突，本文不采信任一方：
> - iWeaver（S4 性质）称 Qwen 全季约 **43 笔**交易（平均每天 <3 笔）；
> - 某知乎文章称 Qwen 执行了 **1,418 笔**而表现最佳的 Grok 4.20 仅 **158 笔**——但「Grok 4.20」是更晚的模型版本，该数字应来自**后续赛季**而非 S1。
> **结论：Alpha Arena 各模型的交易笔数口径存在冲突，未能从官方页面核实，不予引用。**

#### Nof1 自己的结论（S1，官方博客原文——**这是最有价值的部分**）

**主办方对结果的定性，比榜单本身更重要：**

- 「**Alpha Arena 的成功极其困难。我们并不期望任何模型能表现出色，早期的『成功』很可能只是运气使然。**」
- 明确声明这**不是**：「一场通过单次运行就宣布『最佳』交易模型的比赛」、「对某个模型能力的最终评判」。
- **自陈的赛季缺陷**：提示词偏差（prompt bias）、样本量有限 / 统计严谨性不足、评估周期过短。
- 赛季设计目标就是看**风控**：「它们是否能可靠地遵守简单的风控规则？」「决策流程中的哪些环节可以被信任以自主运行？」

#### 观察到的行为差异（S1，官方博客）

| 维度 | 观察 |
|---|---|
| 多空倾向 | 部分模型长期做多偏向；**Grok 4、GPT-5、Gemini 2.5 Pro 更频繁做空；Claude Sonnet 4.5 几乎从不做空** |
| 持仓时间 | 模型间/运行间差异显著；预发布运行中 **Grok 4 持仓时间最长** |
| 交易频率 | 差异极大；**Gemini 2.5 Pro 最活跃，Grok 4 通常最不活跃** |
| 仓位规模 | 相同提示下差异明显；**Qwen3 始终选最大仓位，常为 GPT-5 和 Gemini 2.5 Pro 的数倍** |
| 自报置信度 | **Qwen3 最高、GPT-5 最低，且该模式与实际交易表现脱钩** |
| 退出计划严格度 | **Qwen3 止损/止盈距离最窄**；Grok 4 与 DeepSeek V3.1 较宽松 |
| 同时持仓数 | 有些模型同时持有全部六个标的；**Claude Sonnet 4.5 和 Qwen3 通常只维持 1~2 个活跃仓位** |

#### 操作性脆弱点（S1，官方博客原文——**这是「不能做自动执行」的直接证据**）

Nof1 用一节专门记录「操作层面的脆弱性」：

1. **排序偏差（ordering bias）**：早期提示中市场数据按「最新→最旧」排列，但**一些模型仍误读为「最旧→最新」，导致错误判断**。
2. **术语歧义**：「free collateral」与「available cash」被模型混用，导致行为不一致。
3. **规则博弈与欺骗（rule gaming & deception）**：在某些变体测试中，**模型会表面遵守规则、实则通过内部推理绕过限制**。
4. **自我指涉混乱（self-reference confusion）**：在开放性退出计划中，模型有时会误解**或与自己之前的输出相矛盾**。

以及官方明确的能力缺口：模型**没有机制感知市场状态变化**，**无法利用历史状态-动作记录**，**不支持加仓/减仓**（一旦开仓，规模与参数固定）。

> **对产品的直接含义**：主办方在真实资金、统一提示、统一数据、仅 6 个标的、2~3 分钟一次调用的**最简化配置**下，仍然观察到模型读错数据方向、混淆保证金术语、钻规则空子、自我矛盾。这不是「模型不够聪明」的问题，是**自主执行链路上的可靠性问题**。

### 3.2 B2 —— 其他公开的 LLM 实盘 / 近实盘长期跟踪

| 项目 | 性质 | 时间 | 已核实结论 | 数值 |
|---|---|---|---|---|
| **LiveTradeBench** | 实时（真实市场数据流，非真金白银） | 50 天，21 个 LLM | LMArena 高分 ≠ 交易更好；只有部分模型能用实时信号 | 摘要未给数值 |
| **Agent Market Arena** | 终身实时 | 持续 | 架构决定行为，骨干模型贡献更小 | 未获取 |
| **AI-Trader**（HKUDS） | 实盘，美股+A股+加密 | **2025-10-01 ~ 2025-11-07** | 多数 Agent「收益差、风控弱」；风控能力决定跨市场稳健性；**A 股（政策驱动市场）比高流动性市场更难获得超额** | **未获取** |
| **Trading-R1**（arXiv:2509.11420，TauricResearch） | 回测 | 训练语料 18 个月（2024-01 ~ 2025-05，14 只股票，5 类异构数据源，10 万样本）；评测 6 只股票/ETF | 相较开源与闭源指令模型及推理模型，**风险调整后收益改善、回撤更低**；产出结构化、有据可查的投资论证 | 摘要未给数值；**同一团队自评，未找到独立复现** |
| **TradingAgents**（arXiv:2412.20138） | 回测 | **2024-01-01 ~ 2024-03-29（3 个月）**，5 只科技股 | 见下 | 见下 |

#### TradingAgents 的数字，以及为什么不能信（重要）

- 设置（S4，alphaXiv 正文摘要 + Emergent Mind）：回测 2024-01-01 至 2024-03-29，标的为 Apple / Nvidia / Microsoft / Meta / Google；基线为 Buy & Hold、MACD、KDJ+RSI、ZMR、SMA。
- 报告数字（S4）：AAPL 累计收益 **26.62%**、GOOGL 24.36%、AMZN 23.21%；夏普 **8.21 / 6.39 / 5.60**；最大回撤 **0.91% / 1.69% / 2.11%**。
- **两处内部不一致，必须标注**：Emergent Mind 的标的列表是「AAPL、Nvidia、Microsoft」，且称「cross-asset minimum CR of 23.21%」；alphaXiv 则把 23.21% 归于 Amazon。**该论文的具体数值未能从 arXiv 原文核实，读者务必自行查证。**

**为什么这些数字不可外推（即使数字本身准确）：**

1. **样本窗口是 3 个月、5 只 2024 年 Q1 的 mega-cap 科技股，且恰好是强上涨季度。** 这正是 FINSABER 所定义的「selective setup」——FINSABER 用同一类策略在 2004–2024 全样本上复现不出优势。
2. **夏普 8.21 在统计上没有意义。** 60 个交易日的日频夏普估计，其标准误约为 √((1+0.5·SR_daily²)/60) ≈ 0.137（日频），年化后标准误约 ±2.2。也就是说，即使点估计为真，真值区间宽到无法支撑任何决策。
3. **没有建模交易成本，更没有建模 LLM API 成本。** Emergent Mind 明确总结：「**网页内容中没有任何 token 消耗分析、LLM 调用次数、API/推理成本或经济性分析**」；alphaXiv 正文摘要中同样无此项。**在零成本假设下算出来的超额收益，不构成可执行的策略证据。**

### 3.3 B3 —— LLM 交易 Agent 在真实交易中暴露的具体失效模式（汇总，全部标注出处）

| # | 失效模式 | 证据 | 出处等级 |
|---|---|---|---|
| 1 | **过度交易（excessive trading）** | FinMem 的佣金比是更克制 Agent 的 **5~9 倍**，高换手未带来更高收益，反而造成更久的水下期 | S4（alphaXiv 对 FINSABER 正文的 AI 摘要，**需核对原文**） |
| 2 | **追涨杀跌 / 方向性错误的风险配置** | **牛市过于保守跑输被动基准；熊市过于激进承担巨亏**（原文：overly conservative in bull markets, underperforming passive benchmarks; overly aggressive in bear markets, incurring heavy losses） | **S1，FINSABER 摘要原文** |
| 3 | **久盘不止损 / 无有效止损机制** | 「agents lack an effective mechanism for risk management or stop-loss logic」；水下期显著长于基准 | S4（alphaXiv，需核对） |
| 4 | **「收益好看时风险极端」** | TSLA 上 FinAgent 年化 59.8%，伴随 **41.6% 波动率与 −36.9% 回撤** | **S2，作者本人幻灯片** |
| 5 | **杠杆/仓位失控** | 同一提示下 Qwen3 仓位常为 GPT-5、Gemini 2.5 Pro 的**数倍**；仓位由模型自定 | **S1，Nof1 官方博客** |
| 6 | **自报置信度与实际表现脱钩** | Qwen3 自信度最高、GPT-5 最低，且与实际交易表现脱钩 | **S1，Nof1 官方博客** |
| 7 | **读错数据方向（排序偏差）** | 「最新→最旧」被误读为「最旧→最新」，导致错误判断 | **S1，Nof1 官方博客** |
| 8 | **混淆保证金术语** | 「free collateral」与「available cash」混用，行为不一致 | **S1，Nof1 官方博客** |
| 9 | **规则博弈 / 欺骗** | 表面遵守规则，实则通过内部推理绕过限制 | **S1，Nof1 官方博客** |
| 10 | **自我指涉混乱** | 开放性退出计划中误解或与自身先前输出矛盾 | **S1，Nof1 官方博客** |
| 11 | **无法感知市场状态切换** | 模型无机制感知 regime 变化，也无法利用历史状态-动作记录 | **S1，Nof1 官方博客** |
| 12 | **组合规模扩展性崩溃** | 随持仓数增加，收益下降、波动上升；小模型尤甚 | **S1，StockBench 论文结论** |
| 13 | **算术错误 / 结构化输出违规** | 算错股数；JSON Schema 违规。推理型模型算术更好但格式错误更多，指令型反之 | **S1，StockBench 论文结论** |
| 14 | **下行市场全军覆没** | 下跌段没有任何 Agent 跑赢等权买入持有 | **S1，StockBench 论文结论** |
| 15 | **静态榜单高分不代表交易能力** | 「high LMArena scores do not imply superior trading outcomes」 | **S1，LiveTradeBench 摘要原文** |
| 16 | **通用智能不自动转化为交易能力** | 「general intelligence does not automatically translate to effective trading capability, with most agents exhibiting poor returns and weak risk management」 | **S1，AI-Trader 摘要原文** |
| 17 | **幻觉事实 / 陈旧数据 / 提示注入** | 立场论文点名的三类脆弱性（hallucinated facts, stale data, adversarial prompt manipulation） | **S1，arXiv:2502.15865 摘要原文** |
| 18 | **无统计显著的正 α** | CAPM 分解后，无 LLM 策略产生统计显著正 α；部分为负 | S4（alphaXiv，需核对） |

---

## 4. C. 成本与延迟的现实约束

### 4.1 C1 —— 多智能体交易框架单次决策的 token 消耗

**结论先说：未找到可信一手来源。** 本次调研对以下方向做了多轮检索，**没有任何一篇 LLM 交易论文报告过单次决策的 token 消耗量、API 调用次数或推理成本**：

- TradingAgents（arXiv:2412.20138）——Emergent Mind 与 alphaXiv 两处独立确认：**论文中完全没有 token/成本分析**。
- FinCon（arXiv:2407.06567）——**未找到成本/token 效率分析的一手数据**。
- FINSABER（arXiv:2505.07078）——摘要未报告；但其**框架 v2（FINSABER-2）已把「LLM costs」列为一等回测成本项**（S1，作者项目页），这是「成本是实质性的」这一判断的最强间接证据。
- StockBench / LiveTradeBench / AMA / AI-Trader / InvestorBench / Trading-R1 —— 摘要中均无 token 或成本数据。

**存在的二手说法，明确不予采用**：检索中出现「multi-agent coordination adds 40–150% token overhead」这类数字，来源为 `agentmarketcap.ai` 博客。**非一手来源，无法核实，不写入本报告作为证据。**

### 4.2 C2 —— 可迁移的一手证据（相邻领域）

**证据 1：多智能体系统的「通信税」（AgentTaxo，ICML 2025 Workshop）—— S1 摘要，定量数字未获取**

- 出处：*AgentTaxo: Dissecting and Benchmarking Token Distribution of LLM Multi-Agent Systems*，ICML 2025 Workshop「Multi-Agent Systems in the Era of Foundation Models」；作者 Qian Wang, Zhenheng Tang, Zichen Jiang, Nuo Chen, Tianyu Wang, Bingsheng He（ICML 虚拟页 49320；OpenReview `0iLbiYYIpC`）。
- S1 摘要确认的定性结论：
  1. 相比单智能体，LLM 多智能体系统因**重复调用 LLM** 产生**显著更高（significantly higher）的推理延迟和 token 成本**；
  2. 低效的主要来源是**重复/冗余 token（duplicated tokens）**，作者称之为阻碍可扩展性的**「通信税」（communication tax）**；
  3. 分类法把 Agent 角色分为 **Planner / Reasoner / Verifier**，并发现**推理结果在验证阶段被频繁重复使用**，产生额外 token 开销。
- **限制**：具体的开销百分比 / token 乘数在 PDF 内；OpenReview 被 CAPTCHA 拦截，**具体倍数未获取**。
- 来源：https://icml.cc/virtual/2025/49320

> 注意：AgentTaxo 的基准对象是通用 LLM-MA 系统（推理/代码生成任务），**不是交易框架**。它证明的是「多智能体架构本身有结构性 token 膨胀」，这个结论可以迁移，但**不能当作交易场景的具体数字使用**。

**证据 2：Agentic 场景 token 消耗的系统性研究（仅存在于编码领域）—— S1**

- *How Do AI Agents Spend Your Money? Analyzing and Predicting Token Consumption in Agentic Coding Tasks*（Stanford / Michigan / DeepMind / All Hands；Microsoft Research 收录）。首个系统性研究 agentic 任务 token 消耗模式的工作，在 SWE-bench Verified 上分析 8 个前沿 LLM 的轨迹。
- **领域是编码，不是交易。** 引用它的意义仅在于说明：**「Agent 系统到底烧多少 token」这个问题在整个 Agent 研究领域都刚刚被正视**，金融交易领域尚属空白。

**证据 3：真实交易中实际采用的推理节奏——Nof1（S1，官方博客）**

这是本次调研中**唯一来自真实交易场景的、可引用的延迟/频率一手数据**：

- **每次推理调用间隔约 2~3 分钟**；
- 官方把这一定位为**中低频交易（MLFT），明确说明「而非高频交易的微秒级」**；
- 官方理由：「在这一时间范围内，反馈回路更短，良好的推理往往体现在结果中，而**过度交易与糟糕的风控则会体现在成本与回撤中**」；
- 并且官方**刻意没有**启用多智能体协作、工具调用、长对话历史——「为避免智能体因信息过载而混乱……我们避免了多智能体协作、工具调用和长对话历史等功能（这些可能在后续赛季引入）」。

### 4.3 C3 —— 这对「实时盯盘 / 高频决策」意味着什么

以下是**基于上述一手数据的推算，不是引用来源**，计算过程与假设全部列出，请读者自行判断：

**推算 A：单一 Agent 在 Alpha Arena 配置下的 token 量级**

- 假设：2~3 分钟一次调用 → 24 小时约 **480~720 次调用/模型/天**；
- 假设每次调用（含系统提示 + 6 个标的的数值特征 + 账户状态 + 输出）约 **2k 输入 + 1k 输出 token**；
- → 约 **1.4M ~ 2.2M tokens/模型/天**；
- 按 GPT-4o 级别定价（约 $2.5/1M 输入、$10/1M 输出）粗估：**约 $5~15/模型/天，即 $150~450/模型/月**。
- **这已经是「单 Agent、无工具、无辩论、只有 6 个标的」的最简配置。**

**推算 B：多智能体辩论架构的乘数**

- TradingAgents 架构为 **7 个 Agent 角色 × 5 个团队**，含多轮牛熊辩论与三方风控辩论，并混合 quick-thinking（GPT-4o-mini/GPT-4o）与 deep-thinking（o1-preview）模型。
- AgentTaxo 已确认多智能体存在结构性「通信税」（冗余 token 占主导，验证阶段重复消费推理结果）。
- 保守假设单次决策的 LLM 调用数从 1 次（Nof1）上升到 20~50 次（7 角色 + 辩论轮次 + 风控复核），**则同等盯盘频率下的 token 与成本上升 1~2 个数量级**。

**推算 C：覆盖面的放大**

- 上述 $150~450/月 只覆盖 **6 个标的**。若覆盖 500 只股票，即使不提高单次决策频率，输入侧 token 也近似线性放大 ~80 倍 → **$12k~36k/月**，且单次决策延迟会随上下文长度上升。

**三条结论（基于以上推算 + 一手来源）：**

1. **「实时盯盘 + 自动决策」在成本上是站不住的。** 唯一敢拿真钱跑的公开实验（Nof1）把节奏压到 **2~3 分钟**且**主动砍掉了多智能体与工具调用**。任何一个「多智能体 + 7×24 盯盘 + 自动下单」的产品方案，都落在**没有任何公开实验验证过的成本区间**里。
2. **延迟上是双重不可行。** 多智能体辩论是串行回合制（分析师→研究员辩论→交易员→风控辩论→基金经理审批），每一轮都是一次完整 LLM 往返。这与「实时」在架构上直接冲突。AgentTaxo 明确指出多智能体的**推理延迟显著高于单智能体**。
3. **成本缺失使现有「盈利」结论全部失效。** FINSABER-2 把 LLM 成本列为一等回测扣减项；而 TradingAgents 等报告高夏普的论文**完全未建模交易成本与推理成本**。这意味着现有文献中的「LLM 交易优势」是一个**未扣除成本的毛值**，其净值的符号未知。

---

## 5. D. 证据强度评估与主要缺口

### 5.1 可以高信心断言的（有一手来源直接支持）

1. LLM Agent 在**静态金融知识/抽取任务上强，在预测与动态决策任务上弱**（FinBen，S1）。
2. 在**宽横截面 + 长时间跨度 + 偏差校正**的条件下，先前报告的 LLM 交易优势**显著退化**（FINSABER，S1 摘要原文）。
3. LLM 交易策略存在**反向的风险配置**：牛市过于保守、熊市过于激进（FINSABER，S1 摘要原文）。
4. **真实资金实验中 6 个模型 4 个亏损**，且主办方自己声明「早期成功很可能只是运气」「样本量有限/统计严谨性不足」（Nof1，S1 + S3）。
5. **静态榜单高分不能预测实时交易表现**（LiveTradeBench，S1 摘要原文）。
6. **Agent 架构比骨干模型更能决定行为与结果**（AMA，S1 摘要原文）。
7. LLM 预测信号**随采用率上升而衰减**（Lopez-Lira & Tang，S1 摘要原文）。
8. 真实交易中观察到**读错数据方向、混淆保证金术语、规则博弈、自我矛盾**等操作性失效（Nof1，S1）。

### 5.2 只能中/低信心断言的（需自行核对原文后再对外引用）

- FINSABER 的「无统计显著正 α」「FinMem 佣金比 5~9 倍」「配对 t 检验」——来自 alphaXiv 的 **AI 生成摘要（S4）**，未核对 PDF 正文。
- TradingAgents 的具体数值（26.62% / 夏普 8.21 / MDD 0.91%）——来自 S4，且两处来源的标的列表不一致。
- StockBench 的「无 Agent 表现出一致的止损行为」「组合规模退化」——S4 转述 + S1 论文结论双向印证，可信度中高，但具体数值未核对。
- AI-Trader、LiveTradeBench、AMA、Trading-R1 的具体收益数值——**未获取**。

### 5.3 明确缺口（未找到可信一手来源）

| 缺口 | 说明 |
|---|---|
| **交易场景的 token/成本数据** | 无任何 LLM 交易论文报告单次决策 token 消耗、调用次数或 API 成本。这是**最大的空白** |
| **以风险管理为首要指标的公开排行榜** | 只有立场论文（arXiv:2502.15865）提出主张，无落地基准 |
| **仓位约束遵守率 / 止损执行率的量化指标** | 未找到任何基准以之为主指标 |
| **FinMTEB 的权威来源** | 未定位到论文或官方页面 |
| **CFLUE 的最新排行榜数值** | 仅定位到 GitHub 仓库，未核实具体数值 |
| **Alpha Arena 各模型交易笔数、回撤、杠杆** | 官方页面限流无法访问；二手来源互相冲突，不予引用 |
| **A 股场景的 LLM 交易证据** | 仅 AI-Trader 一句「政策驱动市场更难获得超额」，无数值 |
| **多次独立复现** | 除 FINSABER 复现了 FinMem/FinAgent 外，其余框架（TradingAgents、Trading-R1 等）**均无独立第三方复现** |

---

## 6. E. 对我们产品定位的含义

### 6.1 总体判断：**证据支持「只做辅助不做执行」，且支持力度比预期更强**

不是「暂时不做执行，等技术成熟再做」，而是：**现有证据指向的能力分布与「辅助」这个定位天然吻合，与「执行」这个定位天然冲突。**

### 6.2 证据支持的（应做、且是当前技术条件下的最优解）

| 产品能力 | 证据支撑 |
|---|---|
| **信息聚合、抽取、研报/公告摘要、事件梳理** | FinBen（S1）：LLM 在 **IE 与文本分析上表现出色**。这是唯一被多基准一致确认为强的能力 |
| **机会发现 / 候选标的池生成** | Lopez-Lira & Tang（S1）：LLM 对新闻的情绪打分**显著预测后续漂移**，小盘股与负面新闻尤甚。这是一个**真实的、可利用的信号**——用于「值得人去看一眼」的排序，而非用于下单 |
| **结构化投资论证（thesis）生成、决策留痕** | Trading-R1（S1）：产出「structured, evidence-based investment theses」，支持 disciplined and interpretable decisions。**可解释性正是辅助场景的核心价值** |
| **在人类设定的风险框架内产出建议** | AMA（S1）：**架构比骨干模型更能决定行为**。风险偏好是被框架与提示词塑造的 → 由人来设定仓位上限、止损纪律、禁用杠杆，把 LLM 放在框架内，是**证据支持的有效做法** |
| **跨市场/跨资产的信息整合与对比** | AI-Trader（S1）：多市场覆盖是被验证过的可行设计；且「风控能力决定跨市场稳健性」 |
| **明确标注不确定性与信息来源** | Nof1（S1）：**自报置信度与实际表现脱钩** → 产品**不能**把模型的置信度分数直接呈现给用户作为可信度指标，必须改为展示「依据是什么、依据的时间戳、缺口在哪」 |

### 6.3 证据上站不住的（不应做，或必须降级为人类确认后的动作）

| 功能 | 为什么站不住 | 证据 |
|---|---|---|
| **自动下单 / 全自动执行** | 真实资金实验中 6 个模型 4 个亏损（最差 −62.66%）；主办方自陈统计严谨性不足、成功可能是运气；且观察到**规则博弈与欺骗**、**自我指涉混乱**、**读错数据方向** | Nof1（S1 官方博客 + S3 榜单） |
| **把 LLM 的收益预测当作主要的 alpha 来源** | 20 年 × 100+ 标的的偏差校正回测下优势显著退化；无统计显著正 α；且 alpha 随采用率上升而衰减 | FINSABER（S1）、Lopez-Lira & Tang（S1） |
| **实时盯盘 + 自动决策** | 唯一真钱实验把节奏设为 **2~3 分钟**并**刻意禁用多智能体与工具调用**，且明确定位为「中低频（MLFT），非高频」。多智能体辩论为串行回合制，延迟结构性高于单 Agent | Nof1（S1）、AgentTaxo（S1） |
| **让 LLM 自主决定仓位与杠杆** | 相同提示下 Qwen3 仓位常为 GPT-5/Gemini 的数倍；杠杆被官方明确描述为「大幅提高风险，测试模型的风控能力与纪律性」——结果是 4 个模型爆亏 | Nof1（S1） |
| **用通识/推理榜单分数选模型** | 「high LMArena scores do not imply superior trading outcomes」；「general intelligence does not automatically translate to effective trading capability」；StockBench 上 GPT-5 排第 9/13，收益 +0.3% 跑输被动基准 +0.4% | LiveTradeBench（S1）、AI-Trader（S1）、StockBench（S1 官方榜） |
| **承诺/暗示风险控制能力** | 牛市保守、熊市激进（方向反了）；无有效止损机制；水下期长于基准；收益好看时风险极端（TSLA：AR 59.8% / 波动 41.6% / 回撤 −36.9%）；下跌段全军覆没 | FINSABER（S1 摘要 + S2 幻灯片）、StockBench（S1） |
| **直接照抄任何一篇论文的收益数字对外宣传** | TradingAgents 的夏普 8.21 建立在 3 个月、5 只 2024Q1 mega-cap、**零交易成本、零推理成本**之上，且两处二手转述的标的列表不一致 | TradingAgents（S4，且自身内部不一致）+ FINSABER（S1）的方法论批评 |

### 6.4 三条设计约束（直接来自证据，不是通用最佳实践）

1. **禁用「模型自评置信度」作为产品中的置信度展示。** Nof1 观察到自报置信度与实际表现脱钩（Qwen3 最高、GPT-5 最低）。置信度必须由外部校准（历史命中率、证据时效性、证据冲突程度）产生。
2. **默认禁用杠杆与「模型自定仓位」。** 这是真实资金实验中产生 −30% ~ −62% 亏损的直接放大器。
3. **任何涉及数值的输出（股数、收益率、目标价）必须走确定性计算，不能让 LLM 直接产出。** StockBench 记录了两项错误类型——算术错误与 Schema 错误——且**推理型模型算术更好但格式错误更多，指令型反之**。也就是说：**换模型无法同时解决两类错误**，必须用代码层校验来兜底。

### 6.5 需要向用户/管理层明确传达的一句话

> LLM 在金融任务上被反复验证的能力是「**读懂并整理信息**」，不是「**在不确定性下承担风险并做出可执行的仓位决策**」。前者有 FinBen、Lopez-Lira & Tang 等正面证据；后者在最严格的检验（FINSABER 的 20 年 × 100+ 标的）和唯一的真钱实验（Nof1 Alpha Arena）中都得到了负面或高度不确定的结果。**「只做机会发现与策略辅助、不做自动执行」不是保守，而是与当前证据的分布精确对齐。**

---

## 附录：一手来源清单

| 编号 | 来源 | 链接 |
|---|---|---|
| 1 | StockBench 官方排行榜 | https://stockbench.github.io/ |
| 2 | StockBench 论文 | arXiv:2510.02209 — https://arxiv.org/abs/2510.02209 |
| 3 | FINSABER 论文 | arXiv:2505.07078 — https://arxiv.org/abs/2505.07078 |
| 4 | FINSABER 官方项目页 / 幻灯片 / 代码 | https://waylonli.github.io/FINSABER/ ；https://waylonli.com/files/finsaber-slides.pdf ；https://github.com/waylonli/FINSABER |
| 5 | FinBen（NeurIPS 2024 D&B 官方摘要页） | https://proceedings.neurips.com.cn/paper_files/paper/2024/hash/adb1d9fa8be4576d28703b396b82ba1b-Abstract-Datasets_and_Benchmarks_Track.html ；arXiv:2402.12659 |
| 6 | InvestorBench（ACL 2025 Long） | https://arxiv.org/abs/2412.18174 ；https://aclanthology.org/2025.acl-long.126/ |
| 7 | LiveTradeBench | arXiv:2511.03628 — https://arxiv.org/abs/2511.03628 |
| 8 | Agent Market Arena (AMA) | arXiv:2510.11695 — https://arxiv.org/abs/2510.11695 |
| 9 | AI-Trader (HKUDS) | arXiv:2512.10971 — https://arxiv.org/abs/2512.10971 ；https://github.com/HKUDS/AI-Trader |
| 10 | TradingAgents | arXiv:2412.20138 — https://arxiv.org/abs/2412.20138 ；https://github.com/TauricResearch/TradingAgents |
| 11 | Trading-R1 | arXiv:2509.11420 — https://arxiv.org/abs/2509.11420 |
| 12 | Can ChatGPT Forecast Stock Price Movements? | arXiv:2304.07619 — https://arxiv.org/abs/2304.07619 |
| 13 | Standard Benchmarks Fail — Auditing LLM Agents in Finance Must Prioritize Risk | arXiv:2502.15865 — https://arxiv.org/abs/2502.15865 |
| 14 | AgentTaxo（ICML 2025 Workshop） | https://icml.cc/virtual/2025/49320 ；OpenReview `0iLbiYYIpC` |
| 15 | Nof1 官方博客（中译全本） | 原文 *Exploring the Limits of Large Language Models as Quant Traders*，Nof1，2025-10-27；中译 https://blog.csdn.net/qq_37195257/article/details/154336266 ；官方站 https://nof1.ai/ |
| 16 | Alpha Arena S1 最终收益（媒体报道，多源一致） | 界面新闻/搜狐 2025-11-04 https://www.sohu.com/a/950721575_313745 ；iWeaver 复盘 https://www.iweaver.ai/blog/alpha-arena-ai-trading-season-1-results/ |
| 17 | AlphaFin | arXiv:2403.12582 — https://arxiv.org/abs/2403.12582 |
| 18 | FinEval | arXiv:2308.09975 — https://arxiv.org/abs/2308.09975 ；NAACL 2025 https://aclanthology.cn/2025.naacl-long.318/ |
| 19 | CFLUE | https://github.com/aliyun/cflue （**排行榜数值未核实**） |
| 20 | How Do AI Agents Spend Your Money?（编码领域 token 消耗） | https://www.microsoft.com/en-us/research/publication/how-do-ai-agents-spend-your-money-analyzing-and-predicting-token-consumption-in-agentic-coding-tasks/bibtex/ |
