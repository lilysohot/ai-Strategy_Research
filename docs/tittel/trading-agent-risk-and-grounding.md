# 交易 Agent 的三个工程细节：外部实证与可照搬做法

> 只读调研，无代码改动。证据分三级：
> **A 级 = 我实际读取的一手源码/官方页面**；**B 级 = 论文/数据集官方页面（摘要或 README 原文）**；**C 级 = 衍生文档/二手解读（明确标注）**。
> 相关文档：`trading-strategy-platform-feasibility.md`（平台可行性）、`fin-research-three-layer-architecture.md`（研报三层库）。

---

## 议题一：如何阻止 LLM 编造/算错金融数字

### 1.1 有没有"LLM 定性 + 确定性代码算数值"的分工

**有，而且这是主流开源交易 Agent 里唯一跑通的模式。**

#### 证据 A：ai-hedge-fund（63.3k stars）——代码算 allowed_actions，LLM 只做选择

系统架构页（**C 级，Devin/DeepWiki 衍生文档，索引于 commit `ce9715`，2026-07-03**）给出的决策管线，四步里前三步全是代码：

```
1. Analyst Signals        → 多智能体填充 state["data"]["analyst_signals"]
2. Risk Limits            → risk_management_agent 按当前组合权益与波动率计算
                            remaining_position_limit   (src/agents/risk_management.py:46-47)
3. Allowed Actions        → portfolio_management_agent **确定性**计算 allowed_actions
                            (buy/sell/short/cover/hold) 与最大数量
                            (src/agents/portfolio_manager.py:96-157)
4. Final Decision         → LLM 只从 allowed_actions 集合里选一个
                            (src/agents/portfolio_manager.py:177-185)
```

该页的总结句直接点明定位：**"Safety: Risk and Portfolio management agents act as deterministic filters on LLM-generated signals."**
来源：https://deepwiki.com/virattt/ai-hedge-fund/2-system-architecture

同构 fork 的**实际源码**（A 级，我逐行读取）——`51bitquant/ai-hedge-fund-crypto/src/graph/risk_management_node.py`：

```python
# 基础限额：组合总值的 20%
position_limit = total_portfolio_value * 0.20
# 已有持仓要扣减
remaining_position_limit = position_limit - current_position_value
# 再与可用现金取小，保证不会超出现金
max_position_size = min(remaining_position_limit, portfolio.get("cash", 0.0))

risk_analysis[ticker] = {
    "remaining_position_limit": float(max_position_size),
    "current_price": float(current_price),
    "reasoning": {
        "portfolio_value": float(total_portfolio_value),
        "current_position": float(current_position_value),
        "position_limit": float(position_limit),
        "remaining_limit": float(remaining_position_limit),
        "available_cash": float(portfolio.get("cash", 0.0)),
    },
}
```

要点：
- **三个数（limit / remaining / max_position_size）全是 Python 算术**，LLM 一个数字都不碰。
- 结果既作为 `HumanMessage(content=json.dumps(risk_analysis))` 进上下文，也写入 `data["analyst_signals"]["risk_management_agent"]` 供审计——**同一份数据既喂模型又留痕**。
- `reasoning` 字段把中间量全部摊开，模型能"看懂"限额是怎么来的，而不是拿到一个黑箱数字。
来源：https://github.com/51bitquant/ai-hedge-fund-crypto/blob/main/src/graph/risk_management_node.py

#### 证据 B：TradingAgents（103k stars）——指标计算完全外包给确定性库

`tradingagents/dataflows/stockstats_utils.py`（A 级，全文读取）：

```python
class StockstatsUtils:
    @staticmethod
    def get_stock_stats(symbol, indicator, curr_date):
        data = load_ohlcv(symbol, curr_date)
        df = wrap(data)                      # stockstats 确定性计算
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        df[indicator]                        # 触发指标计算
        matching_rows = df[df["Date"].str.startswith(curr_date_str)]
        ...
```

**LLM 只提供一个指标名字符串**，数值由 `stockstats` 库算。同一文件里还有三条"拒绝而非降级"的防线，非常值得抄：

| 防线 | 代码 | 语义 |
|---|---|---|
| 防前视 | `data = data[data["Date"] <= curr_date_dt]` | 回测永不见未来价格 |
| 陈旧拒绝 | `_assert_ohlcv_not_stale(...)`，超过 `MAX_OHLCV_STALE_DAYS = 10` 天直接 `raise NoMarketDataError(... "refusing to use it")` | **不把旧价当现价用** |
| 未收盘不静默丢弃 | `if not data.empty and pd.isna(data["Close"].iloc[-1]): raise NoMarketDataError(...)` | 最新 bar 无收盘价 → 报错，不让"前一交易日"伪装成"最新" |
| 只重试限流 | `yf_retry` 仅捕获 `YFRateLimitError` 做指数退避，其他异常立即抛 | 不掩盖真错误 |

来源：https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/dataflows/stockstats_utils.py

#### 证据 C：NautilusTrader——所有金额/保证金算术在引擎里，不在策略里（详见议题二）

**结论**：1.1 的答案是明确的"有"，且**业内共识是"闸门输出端给离散集合，LLM 在集合里选"**，而不是"LLM 给出数值后代码去校验"。后者做不到——因为自然语言里混着对的和错的算术，代码无从分辨哪个数是"仓位"。

---

### 1.2 结构化输出的实践：Pydantic / JSON Schema 约束 + 不合规时怎么办

#### 做得最好的样例：TradingAgents 的 `tradingagents/agents/schemas.py`（A 级，全文读取）

文件顶部自述了设计意图（原文摘录）：

> The framework's primary artifact is still prose... Structured output is layered onto the three decision-making agents (Research Manager, Trader, Portfolio Manager) so that:
> - Their outputs follow consistent section headers across runs and providers
> - Each provider's native structured-output mode is used (json_schema for OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic)
> - **Schema field descriptions become the model's output instructions**, freeing the prompt body to focus on context

具体机制：

**（1）枚举收紧评分档位**

```python
class PortfolioRating(str, Enum):   # 5 档
    BUY = "Buy"; OVERWEIGHT = "Overweight"; HOLD = "Hold"
    UNDERWEIGHT = "Underweight"; SELL = "Sell"

class TraderAction(str, Enum):      # 3 档
    BUY = "Buy"; HOLD = "Hold"; SELL = "Sell"

class SentimentBand(str, Enum):     # 6 档
    BULLISH / MILDLY_BULLISH / NEUTRAL / MIXED / MILDLY_BEARISH / BEARISH
```

**（2）Field description 直接当输出指令**（省掉 prompt 正文重复约束）

```python
recommendation: PortfolioRating = Field(description=(
    "Exactly one of Buy / Overweight / Hold / Underweight / Sell. "
    "Choose Hold when the evidence is balanced, materially conflicting, "
    "ambiguous, or insufficient to justify changing exposure; otherwise commit "
    "to the side with the clearly stronger arguments. "
    "Do not pick a direction merely to be decisive."))
```

**（3）唯一的数值范围约束**

```python
overall_score: float = Field(ge=0.0, le=10.0, description=(
    "Numeric sentiment intensity on a 0–10 scale... "
    "Only the 0–10 bounds are enforced."))
```

**（4）不合规时的处理：是"修复"，不是"拒绝"**（issue #1058）

```python
_NULLISH_FLOAT = {"", "none", "n/a", "na", "null", "nil", "-", "tbd", "unknown"}

def _coerce_optional_float(value):
    if isinstance(value, str) and value.strip().lower() in _NULLISH_FLOAT:
        return None
    return value

class TraderProposal(BaseModel):
    entry_price: float | None = Field(default=None, ...)
    stop_loss:   float | None = Field(default=None, ...)
    position_sizing: str | None = Field(default=None, ...)

    @field_validator("entry_price", "stop_loss", mode="before")
    @classmethod
    def _nullish_float_to_none(cls, v):
        return _coerce_optional_float(v)
```

代码注释原文：*"LLMs sometimes write a placeholder string ("None", "N/A", ...) into an optional numeric field instead of omitting it. Coerce those to None so the structured call validates instead of erroring."*

来源：https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/schemas.py

#### **关键负面发现（对我们最重要）**

TradingAgents 有结构化输出，但**没有数值正确性闸门**：

1. `TraderProposal.entry_price` / `stop_loss` / `position_sizing` 和 `PortfolioDecision.price_target` 都是 **LLM 直接生成的 `float | None`，代码层零校验**——不校验 `stop < entry`、不校验仓位上限、不校验是否来自工具。
2. `tradingagents/agents/managers/portfolio_manager.py` 的 docstring 自陈降级路径（A 级）：
   > *"Uses LangChain's `with_structured_output` so the LLM produces a typed `PortfolioDecision` directly, in a single call... **When a provider does not expose structured output, the agent falls back gracefully to free-text generation.**"*
   → **没有重试，没有拒答，只有降级为自由文本**。降级发生时，schema 这道闸门整个消失。
3. CHANGELOG v0.4.0 的 **"Trader price grounding" (#1167)**（A 级），看 `trader.py` 实现，是**纯提示词层约束**：

```python
market_report = (state["market_report"] or "").strip()
if market_report:
    grounding = (
        "Ground concrete price levels (entry, stop-loss, position sizing) in the technical "
        "market report's price structure -- current price, support/resistance, ATR, and "
        "volatility -- and use the research plan for direction and strategy. "
    )
    report_section = f"Technical Market Report:\n{market_report}\n\n"
```

→ "grounding" 在这里的意思是**把原始价格结构喂给模型**，不是"输出后校验数字是否真的来自该报告"。

来源：
- https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/trader/trader.py
- https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/managers/portfolio_manager.py
- https://github.com/TauricResearch/TradingAgents/blob/main/CHANGELOG.md

**结论**：可抄的是它们的**枚举 + Field-as-instruction + nullish 强制转换**三件套；必须补上它们缺的**数值关系校验**、**工具来源校验**，以及把"降级为自由文本"改成"重试一次，仍失败则拒答"。

---

### 1.3 数字溯源（citation grounding）：喂数据侧有，输出校验侧没有

#### 喂数据侧（A 级，TradingAgents CHANGELOG）

| 版本 | 条目 | 性质 |
|---|---|---|
| v0.3.0 (2026-06-22) | **Verified data-access contract**：`Symbol normalization on every vendor path`; `a typed VendorError taxonomy`; `look-ahead-safe news windows`; `stale-OHLCV rejection` | 数据接入契约 |
| v0.3.0 Fixed | **Instrument identity**：`Deterministic ticker-to-company resolution prevents wrong-company hallucination, and **a verified market-data snapshot grounds price and indicator claims** (#814, #830) | 快照锚定 |
| v0.4.0 (2026-08-31) | **Trader price grounding**：`The Trader saw only the digested plan; it now also receives the technical market report so entry/stop levels anchor to real price structure` (#1167) | 提示词层 |

**但没有任何一条是"输出侧自动校验"**。翻遍 schemas.py / portfolio_manager.py / trader.py，没有比对"终稿数字 vs 本 run 工具返回值"的代码。

#### 可直接抄的数据模型：FinanceBench 的 EvidenceDict（B 级，官方 README 字段定义）

FinanceBench（Patronus AI）把每条证据结构化到**页级**：

```
Each EvidenceDict contains four fields:
    "evidence_text"          (str): Extracted evidence text from annotators (sentence, paragraph or page)
    "evidence_doc_name"      (str): Unique Document Identifier of the relevant document containing the evidence
    "evidence_page_num"      (int): Page number of the evidence text (ZERO-indexed)
    "evidence_text_full_page"(str): Full page extract containing the evidence text
```

`evidence_text_full_page` 是关键——它让自动化校验可以做**逐字子串匹配**（断言 `evidence_text ⊂ evidence_text_full_page`），而不必再回源文档。我们三层库方案的 `report_id + page + quote` 与此同构，缺的就是把整页文本也存下来。
来源：https://github.com/patronus-ai/financebench

#### 自动校验的方法论：OmniEval（B 级，EMNLP 2025 官方摘要）

> *"...we utilize a **multi-stage evaluation pipeline to assess both retrieval and generation performance**... Finally, **rule-based and LLM-based metrics are combined** to build a multi-dimensional evaluation system, enhancing the reliability of assessments through **fine-tuned LLM-based evaluators**."*

即"规则指标（逐字/数值精确匹配）+ 模型指标（语义一致性）双层"，并**微调一个专用 evaluator** 而不是直接用通用大模型打分。数据生成侧人工接受率 87.47%。
- 论文：https://aclanthology.org/2025.emnlp-main.292/ | https://aclanthology.cn/2025.emnlp-main.292/
- 代码：https://github.com/RUC-NLPIR/OmniEval

#### 未找到可信来源

**没有任何一个主流开源交易 Agent 在输出侧实现了自动 attribution 校验**（"终稿里的每个数字是否都能在本 run 的工具返回里找到"）。
检索到的 FinVet（"A Collaborative Framework of RAG and External Fact-Checking Agents for Financial Misinformation Detection", 2025）查的是**外部金融谣言**，不是系统自查自身输出，不适用。
→ **这块业界是空白，得我们自己造**（见 §4 第 9 条）。

---

### 1.4 "LLM 在金融计算上错误率"的量化研究

#### （1）FinanceBench —— 最硬的一组数（B 级，官方 README 原文）

> *"We test 16 state of the art model configurations (including GPT-4-Turbo, Llama2 and Claude2, with vector stores and long context prompts) on a sample of 150 cases from FinanceBench, and **manually review their answers (n=2,400)**... Notably, **GPT-4-Turbo used with a retrieval system incorrectly answered or refused to answer 81% of questions**... We find that all models examined exhibit weaknesses, such as **hallucinations**, that limit their suitability for use by enterprises."*

- 论文：arXiv 2311.11944（https://arxiv.org/abs/2311.11944）；配套数据集 10,231 题，开源样本 150 题
- 关键补充：长上下文喂证据能提升但"**unrealistic for enterprise settings due to increased latency**"——即"把全文塞进去"不是工程解法
- 引申：**这 81% 包含"答错 + 拒答"**，所以不能简单读成"错误率 81%"，但"答对率不到 19%"这个上界是成立的

来源：https://github.com/patronus-ai/financebench

#### （2）FinanceReasoning（ACL 2025）—— 数值精度的量化（B 级，ACL Anthology 摘要原文）

> *"(3) **Challenge**: Models are required to apply multiple financial formulas for precise numerical reasoning on **238 Hard problems**. The best-performing model (i.e., **OpenAI o1 with PoT**) achieves **89.1% accuracy**, yet **LRMs still face challenges in numerical precision**. We demonstrate that **combining Reasoner and Programmer models** can effectively enhance LRMs' performance (e.g., 83.2% → 87.8% for DeepSeek-R1)... we construct **3,133 Python-formatted functions**, which enhances LRMs' financial reasoning capabilities through refined knowledge (e.g., **83.2% → 91.6% for GPT-4o**)."*

读法：
- 需要多公式串联的 Hard 题，最强模型仍有 **~11% 错误率**
- **PoT（Program-of-Thought，即"让模型写程序而不是自己算"）本身就是最强干预**：给 GPT-4o 注入 3,133 个 Python 金融函数，83.2% → 91.6%
- → 这直接为我们的红线提供了量化背书：**把算术从"模型内算"换成"调确定性函数"，是论文里验证过的最高收益单点干预**

来源：https://aclanthology.org/2025.acl-long.766/（Tang et al., ACL 2025, pp. 15721–15749, DOI 10.18653/v1/2025.acl-long.766）

#### （3）ConvFinQA（EMNLP 2022）—— 多轮场景更糟（C 级，二手研究笔记 + arXiv 原文片段）

- 众包非专家标注者的**执行准确率 46.90% / 程序准确率 45.52%**（arXiv 2210.03849 原文片段）
- 标题即结论："**the 21-Point Gap Between Models and Human Experts**"
- 关键失败模式：单轮能算对的模型，一旦问题引用两轮之前的数字就崩
- 来源（C 级，需以原文核对）：https://beancount.io/bean-labs/research-logs/2026/05/15/convfinqa-chain-numerical-reasoning-conversational-finance-qa ；原文 https://arxiv.org/abs/2210.03849

---

## 议题二：风险约束的落地层次

### 2.1 写在 system prompt 里、代码硬校验里、还是两层都有

三个可对照的真实样本：

| 项目 | 约束落点 | 证据 |
|---|---|---|
| **TradingAgents** | **只有提示词层**（反例） | 见下 |
| **NautilusTrader** | **只有代码层**（且配置层就校验） | 见 2.2 |
| **ai-hedge-fund** | **两层都有**（正确做法） | 代码算 allowed_actions（硬）+ LLM 在集合内选（软） |

#### TradingAgents：约束全在 prompt 文本里（A 级）

`portfolio_manager.py` 里的"风险约束"长这样——就是一段拼进 user message 的 markdown：

```python
prompt = f"""As the Portfolio Manager, synthesize the risk analysts' debate and deliver the final trading decision.
{instrument_context}
---
**Rating Scale** (use exactly one):
- **Buy**: Strong conviction to enter or add to position
- **Overweight**: Favorable outlook, gradually increase exposure
- **Hold**: Maintain current position, no action needed
- **Underweight**: Reduce exposure, take partial profits
- **Sell**: Exit position or avoid entry
...
Ground every conclusion in specific evidence from the analysts. Commit to a directional call
only when the evidence clearly supports one; choose Hold when the case is balanced...
"""
```

**这就是它全部的风险约束。** 同步核对：
- `schemas.py` 里唯一的数值约束是 `overall_score` 的 `ge=0, le=10`——**没有仓位上限、没有止损必填、没有集中度**
- `tradingagents/agents/managers/` 目录下只有 `portfolio_manager.py` 和 `research_manager.py` 两个文件（A 级，目录列表核实），**没有任何 `risk_manager.py`**（v0.2.2 的 CHANGELOG 记录 `risk_manager` 已重命名为 `portfolio_manager`）
- 三个 `risk_mgmt/` 下的 debator（aggressive/conservative/neutral）是**辩论角色**，产出的是自然语言论点，不是可执行的约束

→ TradingAgents 的"风险管理"是**让三个 LLM 互相吵架**，吵完由第四个 LLM 拍板。没有一行代码会拒绝一个违反任何约束的决策。

#### 结论

**必须两层都有，且分工明确**：
- 提示词层负责"模型往正确方向想"（降低成本、提高一次通过率）
- 代码层负责"错的出不去"（这才是约束）
- 只做提示词层 = 没有约束（TradingAgents 即是证明）

---

### 2.2 硬性闸门（hard gate）在哪一层

**最完整的参考答案：NautilusTrader 的 `RiskEngine`——一个独立于策略、坐在策略与执行引擎之间的组件。**

#### 闸门位置（A 级，`crates/risk/src/engine/mod.rs` 全文读取）

文档注释原文：

```rust
/// Central risk management engine that validates and controls trading operations.
///
/// The `RiskEngine` provides pre-trade risk checks including order validation,
/// balance verification, position sizing limits, and trading state management. It acts as
/// a gateway between strategy orders and execution, ensuring all trades comply with
/// defined risk parameters and regulatory constraints.
```

消息总线接线：所有交易指令先到 `MessagingSwitchboard::risk_engine_execute()`，通过后由 `execution_gateway()` 转发到 `MessagingSwitchboard::exec_engine_*`。**策略无法绕过这一跳。**

```
Strategy ──TradingCommand──▶ RiskEngine.execute()
                                  │
                                  ├─ bypass? ──yes──▶ 直送执行（默认 false）
                                  │
                                  ├─ handle_submit_order()
                                  │    ├─ reduce-only 校验
                                  │    ├─ instrument 存在性
                                  │    ├─ check_order()          → 价格精度/数量精度/GTD 过期
                                  │    └─ check_orders_risk()    → 名义值/保证金/余额
                                  │
                                  └─ execution_gateway()  ← 按 TradingState 分流
                                       ├─ Halted   → 全部 deny
                                       ├─ Reducing → 只有 is_reducing_submission() 放行
                                       └─ Active   → throttled_submit.send()
```

#### 具体拒绝点（全部 A 级，函数名可定位）

`check_orders_risk_for_account()` 内的检查序列：

| 检查 | 拒绝原因枚举 |
|---|---|
| 单笔名义 > `max_notional_per_order` | `NotionalExceedsMaxPerOrder` |
| 名义 < 品种 `min_notional` | `NotionalBelowMinimum` |
| 名义 > 品种 `max_notional` | `NotionalExceedsMaximum` |
| 数量 > `max_quantity` / < `min_quantity` | `QuantityExceedsMaximum` / `QuantityBelowMinimum` |
| 保证金账户：初始保证金 > 可用 | `InitialMarginExceedsFreeBalance` |
| 保证金账户：**累计**保证金 > 可用 | `CumulativeInitialMarginExceedsFreeBalance` |
| 现金账户：名义 > 可用余额 | `NotionalExceedsFreeBalance` |
| 现金账户：**累计**买入名义 > 可用余额 | `CumulativeNotionalExceedsFreeBalance` |
| 市价单无可用价格 | `MarketPriceUnavailable` |
| 名义值计算失败 | `NotionalCalculationFailed` |

`deny_order()` 的实现形态：

```rust
fn deny_order(&self, order: &OrderAny, reason: &str) {
    log::warn!("SubmitOrder for {} DENIED: {}", order.client_order_id(), reason);
    if order.status() != OrderStatus::Initialized { return; }
    ...
    let denied = OrderEventAny::Denied(OrderDenied::new(
        order.trader_id(), order.strategy_id(), order.instrument_id(),
        order.client_order_id(), reason.into(), UUID4::new(),
        self.clock.borrow().timestamp_ns(), self.clock.borrow().timestamp_ns(),
    ));
    msgbus::send_order_event(MessagingSwitchboard::exec_engine_process(), denied);
}
```

**三个设计要点（照抄价值极高）**：
1. **拒绝是"发事件"，不是抛异常、不是静默 clamp**——下游（审计、UI、告警）都能订阅到 `OrderDenied`
2. **原因是枚举 `OrderDeniedReason`，不是自然语言**——可聚合、可路由、可翻译；`log::warn!` 里保留人类可读字符串
3. **有累计检查**——`cum_notional_buy` / `cum_margin_required` 累加器，把"多笔合起来超限"这个最常见的绕过方式堵死

#### 其他值得抄的细节

- **已提交未成交的量计入敞口**（`orders_open` 的 `leaves_qty` 求和），防止重复挂单超额
- **减仓单豁免余额检查，但仍受名义上限约束**：`is_position_reducing` 的判定同时考虑 `order.is_reduce_only()`、`full_position_exit`、`cum_sell_qty_raw <= available_long_qty_raw`
- **限流也是闸门**：`create_submit_throttler` 的 failure_handler 直接用 `OrderDeniedReason::RateLimitExceeded` 拒单
- **全局开关三态**：`TradingState::{Active, Reducing, Halted}`，`set_trading_state()` 会广播 `TradingStateChanged` 事件

#### 配置层就拦截非法配置（A 级，`crates/risk/src/engine/config.rs` 全文读取）

```rust
pub struct RiskEngineConfig {
    pub bypass: bool,                                        // 默认 false
    pub max_order_submit: RateLimit,                         // 默认 100 / 秒
    pub max_order_modify: RateLimit,                         // 默认 100 / 秒
    pub max_notional_per_order: AHashMap<InstrumentId, Decimal>,
    pub full_position_exit_venues: AHashSet<Venue>,
    pub debug: bool,
}

impl RiskEngineConfig {
    pub fn validate(&self) -> ConfigResult<()> {
        let mut errors = ConfigErrorCollector::new();
        for (instrument_id, notional) in &self.max_notional_per_order {
            errors.check(
                *notional > Decimal::ZERO,
                ConfigError::range("max_notional_per_order",
                    format!("notional for {instrument_id} must be positive, was {notional}")),
            );
        }
        errors.into_result()
    }
}
```

两个可抄点：
- **配置非法在构建期就拒收**，不是运行期才发现
- **收集全部违规一次性报出**（`ConfigErrorCollector` + `ConfigError::Multiple`），测试 `test_multiple_violations_collected` 断言 `errors.len() == 2`——用户体验上是"一次改完所有参数"，不是挤牙膏

来源：
- https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/risk/src/engine/mod.rs
- https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/risk/src/engine/config.rs

---

### 2.3 人类确认（HITL）环节：有没有现成的交互协议

#### 通用框架层：LangGraph 的 `interrupt()`（A 级，官方文档全文读取）

机制：
1. 在节点**或工具函数内部**调用 `interrupt(payload)`（payload 必须 JSON-serializable）
2. 抛特殊异常 → 运行时**保存 checkpoint** → 挂起，无限期等待
3. 恢复：`graph.stream_events(Command(resume=<value>), config, version="v3")`
4. `resume` 的值**成为 `interrupt()` 调用的返回值**
5. 前端通过 `stream.interrupted` / `stream.interrupts` 拿到挂起项

四种既有模式：

| 模式 | 实现 |
|---|---|
| **Approve or reject** | `decision = interrupt({"question": ..., "details": state["action_details"]})` → `Command(goto="proceed" if decision else "cancel")` |
| **Review and edit** | `updated = interrupt({"instruction": ..., "content": state["generated_text"]})` → 直接把 resume 值写回状态 |
| **Interrupts in tools** | 在 `@tool` 函数里 `interrupt(...)`，审批逻辑跟着工具走，跨图复用；resume 值**可以覆盖工具入参**（`final_to = response.get("to", to)`） |
| **Validating human input** | 每个 node 调用只 interrupt 一次 + 条件边回环（避免指数重放） |

**三条硬约束**（违反了会出真 bug）：
- ❌ 不要用 try/except 包住 `interrupt()`（会吞掉中断异常）
- ⚠️ 恢复时**节点从开头重跑**，`interrupt()` 之前的副作用必须幂等
- ❌ 单节点内不要 `while True` + `interrupt()`（第 n 次恢复会重放 n 次 → 指数爆炸）

来源：https://docs.langchain.com/oss/python/langgraph/human-in-the-loop

#### 我们自己其实已经有 HITL，而且比 LangGraph 更严（A 级，本仓库 `server/approval.py` 全文读取）

文件头注释已经写清了契约：

> *"The observer half (`ApprovalObserver`) classifies each tool call with apodex's own `assess_with_rules` (the single source of approval semantics — no new parsing points) and, for `confirm`-level calls, parks an asyncio Future here and emits `approval_requested`. The agent loop **suspends on that future (the LLM cannot advance)** until the user's decision arrives over the stdin JSONL channel."*
>
> *"Safety contract (§6.1): a pending approval **times out fail-closed** — the waiter receives `reject` and any late resolve for the same id is refused — and a **hard deny never reaches this gate at all** (the observer blocks it before any event is emitted), so no decision can bypass it."*

协议：

```
POST /api/runs/{id}/approve
  → orchestrator → stdin JSONL
  → {"action":"approve","approval_id":...,"decision":...,"replacement_command"?}
  → worker._stdin_watch → gate.resolve
```

已有能力：
- `DEFAULT_TIMEOUT_S = 300.0`，**超时 fail-closed 变 reject**
- `ApprovalDecision.decision ∈ {once, reject, session_bash, session_all, persist}`
- `replacement_command`：**拒绝并改道**——被拒调用的返回值变成重定向指令，模型下一轮自行适配，而不是盲目重试（对齐 CLI `[e] redirect` 语义）
- `RISK_DENY` 级别在观察者层直接拦掉，**根本不进闸门**
- session 记忆按精确命令字符串做 key（`session_bash` 用完整命令，不做前缀匹配——注释明写"prefix matching would let a remembered `pytest -q` silently allow `pytest -q -x`"）

#### 未找到可信来源

**没有任何主流开源交易 Agent 内置"大额/高风险决策人工确认"的完整交互协议。** LangGraph 提供的是通用原语；券商侧的做法是产品级（App 二次确认），无开源实现可抄。
→ 我们要做的是**在自己已有的 `ApprovalGate` 上叠一层"金额维度"的分级**，而不是新造机制。

---

## 议题三：非执行型（advisory-only）金融 Agent 的合规设计

### 3.1 明确不做交易执行的开源项目，及其"结构性排除"的做法

#### 样本 A：TradingAgents —— **最好的例子：不是"不下单"，是"系统里只有模拟撮合器"**

README 原文（A 级）：

> *"The Portfolio Manager approves/rejects the transaction proposal. **If approved, the order will be sent to the simulated exchange and executed.**"*
>
> *"**TradingAgents framework is designed for research purposes.** Trading performance may vary based on many factors, including the chosen backbone language models, model temperature, trading periods, the quality of data, and other non-deterministic factors. **It is not intended as financial, investment, or trading advice.**"*

这个设计的价值在于：系统的执行路径**唯一地**指向一个 simulated exchange。想改成真金白银下单，得先造一个真实交易所客户端——**这是个需要主动施工的动作，不会意外发生**。
对比我们：`_BUILTIN_TOOLS` 白名单是"不注册即不存在"，属于同一类"结构性排除"，但更强（连模拟执行都没有）。

#### 样本 B：virattt/ai-hedge-fund —— 反面警示

README 原文（A 级）：

> *"This project is for educational purposes only and is not intended for real trading or investment."*
>
> *"**Note: the system does not actually make any trades.**"*
>
> *"**DISCLAIMER** — This project is for educational and research purposes only.*
> *- Not intended for real trading or investment*
> *- No investment advice or guarantees provided*
> *- Creator assumes no liability for financial losses*
> *- Consult a financial advisor for investment decisions*
> *- Past performance does not indicate future results"*

**但是**（A 级，README 的 VISION 段落 + 目录列表）：

> *"🚧 The project is evolving. We're rebuilding it into a persistent, always-on AI hedge fund — a fund as a first-class entity you can **backtest, paper-trade, and (opt-in) run live**..."*

且当前 `main` 分支的 `hedge_fund/` 下**已经出现 `brokers/` 目录**（与 `backtesting/`、`portfolio/`、`risk/`、`signals/`、`strategies/`、`validation/` 并列）。

**这正是我们要避开的坑**：免责声明是"承诺"，会随项目演进而漂移；白名单/协议只读是"结构"，不会漂移。一个 63k stars 的项目，从"does not actually make any trades"到规划 opt-in live，中间只隔着一次版本迭代。

#### 样本 C：OpenBB —— **未核实**

定位是"Investment Research for Everyone"的开源金融数据/研究平台（https://github.com/OpenBB-finance/OpenBB）。
**三次抓取 GitHub 页面均超时，未能核实其是否完全没有经纪执行能力，不作断言。**

---

### 3.2 免责声明与输出定性的措辞、落位

三个项目的共同做法（A 级，均为 README 原文）：

| 落位规则 | 实证 |
|---|---|
| **放在最顶部，紧跟一句话简介之后** | ai-hedge-fund：标题 → 一句话介绍 → *"This project is for educational purposes only and is not intended for real trading or investment."* → *"Note: the system does not actually make any trades."*。**不在页脚。** |
| **用独立分节，条目化** | ai-hedge-fund 有独立的 `## DISCLAIMER` 标题 + 5 条短句列表，每句一个独立断言，不写成长段落 |
| **输出定性为"研究/推演"，不是"建议"** | TradingAgents：*"designed for research purposes"* + *"not intended as financial, investment, or trading advice"*；ai-hedge-fund：*"proof of concept"* + *"educational and research purposes only"* |
| **必写的四条** | ① 非真实交易/非投资建议 ② 不承担损失责任 ③ 请咨询持牌顾问 ④ 历史业绩不代表未来 |
| **不写"仅供参考"这类模糊措辞** | 三个项目全部用 "only" / "not intended" / "not...advice" 这类**排他性**表述 |

可提炼的措辞模板（直接对应我们平台）：

```
本项目为研究性推演工具，仅供学习研究使用，不构成投资建议。
- 不提供、不描述、不暗示任何交易执行通道
- 输出不含任何收益承诺或保证
- 使用者应自行咨询持牌投资顾问
- 历史回测结果不代表未来收益
```

落位要求：**README 顶部 + 产品每屏 UI + 每份产物文件内的 `disclaimer` 字段**（产物离屏后仍须自带免责）。

---

### 3.3 可参考的监管框架与指引

#### （1）FINRA Regulatory Notice 24-09（**A 级，官方页面全文读取**）

- 标题：*FINRA Reminds Members of Regulatory Obligations When Using Generative Artificial Intelligence and Large Language Models*
- 发布日期：**2024-06-27**；类型：Guidance
- 官方页面：https://www.finra.org/rules-guidance/notices/24-09

要点摘录：

> *"This Notice does not create new legal or regulatory requirements or new interpretations of existing requirements, nor does it relieve member firms of any existing obligations..."*
>
> *"FINRA's rules—which are intended to be **technology neutral**—and the securities laws more generally, continue to apply when member firms use Gen AI or similar technologies..."*
>
> *"...pursuant to **Rule 3110 (Supervision)**, a member firm must have a reasonably designed supervisory system tailored to its business. If a firm is using Gen AI tools as part of its supervisory system—for the review of electronic correspondence, for instance—its policies and procedures should address **technology governance, including model risk management, data privacy and integrity, reliability and accuracy of the AI model**."*
>
> *"...FINRA has provided guidance that the content standards of **Rule 2210 (Communications with the Public)** apply **whether member firms' communications are generated by a human or technology tool**..."*

明确引用的规则：**FINRA Rule 2210**（对外沟通内容标准）、**FINRA Rule 3110**（监督）；脚注 5 指向 FAQ 的 **B.4 "Supervising Chatbot Communications"** 与 **D.8 "AI Created Communications"**。

**翻译成工程要求**：
- 输出准确性必须可复核（对应我们的 attribution 校验与 `as_of` 契约）
- 对外文案（含免责、评级、策略卡）须过统一的内容标准检查，且**不因"是 AI 生成的"而豁免**
- 需要技术治理文档：模型风险管理、数据完整性、模型可靠性

#### （2）SEC：Predictive Data Analytics 提案 —— ⚠️ **已被撤销，不能当合规依据**

- 提案：*Conflicts of Interest Associated With the Use of Predictive Data Analytics by Broker-Dealers and Investment Advisers*，Release No. **34-97990**，2023-07-26
  - 官方 PDF：https://www.sec.gov/files/rules/proposed/2023/34-97990.pdf
  - Fact Sheet：https://www.sec.gov/files/34-97990-fact-sheet.pdf
  - 联邦公报：88 FR 53960，2023-08-09，https://www.federalregister.gov/documents/2023/08/09/2023-16377/
  - 核心机制：要求券商/投顾**识别并消除**使用 covered technology 时"把公司利益置于客户利益之上"的利益冲突，需书面政策、程序与记录
- **现状（重要更正）**：该提案已于 **2025-06-12** 被 SEC 以 Release Nos. **33-11377 / 34-103247 / IA-6885 / IC-35635** 正式撤销（"Notice of Withdrawal of Proposed Regulatory Actions"，联邦公报 2025-06-17）
  - 官方 PDF：https://www.sec.gov/files/rules/final/2025/33-11377.pdf
  - SEC 项目页：https://www.sec.gov/rules-regulations/2025/06/s7-12-23

→ **只能作为"监管意图的风向标"引用，不能作为合规依据。** 但"利益冲突必须识别并消除"这个思路对产品设计仍有参考价值（我们不接券商返佣、不做自营撮合，本身就是最强的冲突消除）。

#### （3）中国

**① 《生成式人工智能服务管理暂行办法》（国家网信办等七部门令第 15 号）**
- 2023-05-23 审议通过，2023-07-10 发布，**2023-08-15 施行**
- 官方全文：https://www.gov.cn/zhengce/zhengceku/202307/content_6891752.htm ｜ https://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm
- （B 级：链接为搜索命中的官方域名，未逐条读取正文）
- 相关要点：提供者对生成内容承担主体责任；训练数据处理须合法、保证质量；要求**采取措施提高生成内容的准确性与可靠性**；标识义务；投诉举报与处置机制
- → **这是"输出必须可溯源、必须准确"的国内法源**，直接支持我们的红线 2（数字可逐字溯源）

**② 《关于规范金融机构资产管理业务的指导意见》（银发〔2018〕106 号，即"资管新规"）**
- 2018-04-27，中国人民银行、银保监会、证监会、外汇局联合发布
- 官方全文：https://www.gov.cn/zhengce/zhengceku/2018-12/31/content_5433072.htm ｜ https://www.gov.cn/gongbao/content/2018/content_5323101.htm
- 其中关于"**金融机构运用人工智能技术开展投资顾问、资产配置等资产管理业务**"的条款（**C 级：条号未逐字核对，请以 gov.cn 原文为准**）要求大致包括：**非现场开展需经许可**、**报备模型主要参数与资产配置主要逻辑**、**充分提示风险**、**不得夸大或误导宣传**、**算法同质化引发市场波动时须人工介入**，以及投资者适当性要求
- → 对我们最有约束力的是"**不得借助人工智能夸大宣传或误导投资者**"和"**须人工介入**"两条，前者落到产品文案，后者落到 HITL

**③ 参考性材料（非规范性文件）**
- 中国证券投资基金业协会《人工智能在资本市场中的应用、风险与应对》（2025-05）：https://www.amac.org.cn/hyyj/sy/202505/P020250530388154144589.pdf
- 中国证券投资基金业协会《基金行业生成式人工智能可解释性治理探讨》（2026-04）：https://www.amac.org.cn/hyyj/sy/202604/P020260408624258724685.pdf
- 证监会科技监管司 2025-12 关于"构建促进人工智能健康发展的行业生态"的表态（媒体报道，非规范）：https://www.cs.com.cn/tj/02/02/202512/t20251229_6530664.html

**④ 未核实，不写入结论**
坊间常引用的《人工智能算法金融应用评价规范》（JR/T 0221-2021）、《人工智能算法金融应用信息披露指南》（JR/T 0287-2023）等金融行业标准，本次未能核实原文，**不作断言**。

---

## 4. 可直接照搬的做法（每条注明在 FrontierAgent 的哪个位置改什么）

> 前置事实（本仓库已核实，A 级）：
> - 工具注册：`plugins/tools/__init__.py` 的 `_BUILTIN_TOOLS`（24 个）；同步改 `tests/test_tool_registry.py::EXPECTED_TOOLS`
> - 工具可见性：`workflows/stateful_react_agent/nodes/main_agent.py:543` `_tools_for_stateful_react()` 读 `agent_cfg.get("agent_tools")`，**必须已注册否则 skip**
> - 注入通道：`server/profile.py:33 MARKET_TOOL_NAMES`（空列表，T4.2 填充）；`server/worker.py:334` `profile_overrides`；`server/worker.py:351` `_sys_prompt_addendum`（消费方 `main_agent.py:817`）；`server/worker.py:345` `sdk_extra_observers`（消费方 `main_agent.py:1028-1030`）

---

**1. 配置对象构建期全量校验（抄 Nautilus `RiskEngineConfig::validate`）**
- 照搬：`max_notional_per_order` 逐个校验 `> 0`，用 `ConfigErrorCollector` **收集全部违规后一次性报出**，而不是遇到第一个就返回
- 改在哪：`plugins/tools/_trade_risk.py`（新增，P0 计算内核）。在 `position_sizing` / `strategy_lint` 入口对 `capital_total > 0`、`0 < risk_budget_pct <= 100`、`0 < max_single_weight_pct <= 100` 做同样形态的校验，返回结构化 violations 数组
- 对应 Nautilus 测试：`test_multiple_violations_collected`（断言 len == 2）——我们照抄这个测试用例到 `tests/test_trade_risk.py`

**2. 拒绝是"发事件 + 原因枚举"，不是异常、不是静默 clamp（抄 `deny_order()`）**
- 照搬：`log::warn!("SubmitOrder for {} DENIED: {reason}")` + `OrderDenied{reason: OrderDeniedReason}` 事件
- 改在哪：`plugins/tools/_trade_risk.py` 的 `strategy_lint` 返回值。形状固定为：
  ```python
  {"passed": False, "violations": [
      {"code": "WEIGHT_EXCEEDS_MAX",       # 固定枚举，非自然语言
       "symbol": "600519.SH", "limit": 0.20, "actual": 0.435},
      {"code": "STOP_LOSS_MISSING", "symbol": "600519.SH"}]}
  ```
- 关键：`code` 必须是枚举（前端渲染、审计聚合、多语言都靠它），人类可读描述另开 `message` 字段。**这个返回值直接进工具结果、不经 LLM 改写**

**3. 必须有累计（组合级）检查，不能只查单笔（抄 `check_orders_risk_for_account`）**
- 照搬：`cum_notional_buy` / `cum_margin_required` 累加器；以及把 `orders_open` 的 `leaves_qty` 计入已占用敞口
- 改在哪：`strategy_lint` **必须接收整个 positions 数组**（不是单个 position）。除单票 `max_single_weight_pct` 外，还要算 `gross_exposure_pct`、行业集中度，并且**已挂未成交的委托量要计入**（对应我们的"用户回填成交价"场景：回填前视为 pending）

**4. 显式区分"开仓 / 减仓 / 平仓"（抄 `is_reducing_submission` + `TradingState::Reducing`）**
- 照搬：减仓单豁免余额/最小名义类检查，但仍受集中度上限约束；`TradingState::Reducing` 状态下**只允许减仓方向**
- 改在哪：策略卡 schema 加 `intent: Literal["open","reduce","close"]`（`trading-strategy-platform-feasibility.md` §4.2 的 JSON 尚无此字段，需补）；`strategy_lint` 按 intent 分流规则集。同时给平台加一个全局 `Reducing` 模式开关，命中的表现是"只产出减仓方案"

**5. LLM 只在代码算出的离散集合里选（抄 ai-hedge-fund 的 `allowed_actions`）**
- 照搬：代码算 `allowed_actions` + `max_quantity`，LLM 只从集合里挑
- 改在哪：`position_sizing` 工具的返回值**不要是"建议仓位"**，而是给模型的可选集合：
  ```python
  {"allowed_actions": [
      {"action": "buy",  "max_shares": 300, "max_amount": 435000, "weight_pct": 0.0435},
      {"action": "hold"}]}
  ```
  配套提示词经 `metadata["profile_inline"]`（`main_agent.py:346/632`，天然 bypass 缓存）或 `_sys_prompt_addendum`（`main_agent.py:817`）注入：**"只能从 allowed_actions 中选择，且不得超过 max_* 字段"**

**6. 结构化 schema：抄三件套，但补上他们缺的三道校验**
- 抄（TradingAgents `schemas.py`）：① 评档用 `str, Enum` 收紧；② `Field(description=...)` 当输出指令，省掉 prompt 重复；③ `_NULLISH_FLOAT` + `@field_validator(..., mode="before")` 把 `"N/A"`/`"none"`/`"tbd"` 强制转 `None`
- 补（他们没做，我们必须做）：
  - 关系校验：`@model_validator(mode="after")` 强制 `stop_loss < entry_low < entry_high < target`
  - 来源校验：`position_sizing` 返回时附带一次性 `computed_by` 与 `quote_id`；落卡时校验 `quote_id` 存在于本 run 的工具调用记录里，否则拒收
  - **降级策略反过来**：TradingAgents 是"provider 不支持结构化输出 → 降级自由文本"（`portfolio_manager.py` docstring），这等于闸门消失。我们改成：**重试一次固定 prompt，仍失败则本次不落卡并明确告知用户**

**7. 行情的三条"拒绝而非降级"防线（抄 `stockstats_utils.py`）**
- 照搬：`MAX_OHLCV_STALE_DAYS = 10` 超期 `raise`；`data[data["Date"] <= curr_date]` 防前视；最新 bar 无收盘价 `raise` 而非静默 drop；`yf_retry` 只对 429 退避
- 改在哪：`plugins/market/` 的 `MarketDataSource` 协议中，把 `as_of` 与 `stale` 从"约定"升级为**返回值必填字段 + 契约测试**；新增 `MAX_STALE_DAYS` 常量与 raise 语义（可行性文档 §3.2 已把 `as_of`/`stale` 列为红线，本条把它从文档要求变成代码强制）

**8. 证据字段结构照抄 FinanceBench 的 EvidenceDict**
- 照搬：`evidence_text` / `evidence_doc_name` / `evidence_page_num` / **`evidence_text_full_page`**
- 改在哪：三层库的 L2 索引与策略卡 `evidence` 字段。关键增量是**存整页文本**——这样 `EvidenceAuditObserver` 可以做纯字符串子串断言（`quote in evidence_text_full_page`），无需回源文档，O(1) 可完成
- 策略卡 shape：`evidence: [{doc_name, page_num, quote, kind: Literal["fact","forecast"]}]`

**9. 自动 attribution 校验（业界空白，我们自己造；方法论抄 OmniEval）**
- 照搬 OmniEval 的"**rule-based + LLM-based 双层指标 + 微调专用 evaluator**"
- 改在哪：`EvidenceAuditObserver`，经 `metadata["sdk_extra_observers"]` 注入（注入点 `server/worker.py:345`，消费点 `main_agent.py:1028-1030`），**零上游改动**
- 机制：
  - `on_tool_result`：收集本 run 所有工具返回的数值字面量，规范化（去千分位、统一小数位、百分比→小数、全角→半角）后入集合
  - `on_loop_end`：扫描 `final_answer` 与 `/outputs/strategy.json` 中的数字，未命中者在产物中标记 `unattested: true`，**不静默放行**
  - 语义层（可选，默认关）：一次 LLM 调用判定"引用的数字与证据句是否支持该论断"

**10. HITL 复用现成的 `ApprovalGate`，只补"金额维度"分级**
- 现状（已核实）：`server/approval.py` 的 `ApprovalGate` + `ApprovalObserver` 已 fail-closed（超时 300s → reject；`RISK_DENY` 在观察者层直接拦掉、不进闸门；决策枚举 `once/reject/session_bash/session_all/persist` + `replacement_command` 拒绝改道）。协议：`POST /api/runs/{id}/approve` → orchestrator → stdin JSONL → `worker._stdin_watch` → `gate.resolve`
- 缺什么：现在按**工具名 + 命令前缀**分级（`apodex.agent_tools.assess_with_rules`），交易场景要加**金额维度**
- 改在哪：经 `sdk_extra_observers` 加一个 `TradeApprovalObserver`（不动 `apodex/`）——在 `on_tool_call` 里读 `args["amount"]`，超过阈值则要求 confirm。**不要新造闸门**
- 抄 LangGraph 的三条硬约束进我们的实现备注：审批前的副作用必须幂等；不要把审批包在 try/except 里；单个 turn 内不要循环审批

**11. 结构性排除执行能力——三层，且学 TradingAgents 的"只有模拟器"**
- 三层（本仓库既有，务必全部落实）：
  1. `plugins/tools/__init__.py` 的 `_BUILTIN_TOOLS` **不注册**任何下单/账户/券商类工具（fail-closed；同步改 `tests/test_tool_registry.py::EXPECTED_TOOLS`）
  2. `MarketDataSource` 协议只声明读方法，无写语义
  3. `server/profile.py:33` 的 `MARKET_TOOL_NAMES` 显式列出可读工具；`main_agent.py:543` 只从注册表取，不在名单即不可见
- 额外建议（学 TradingAgents）：**如果将来非要加执行环节，只在内部提供 simulated exchange**，让"执行"在系统内永远指向模拟器，而不是靠 README 承诺
- 反面警示（ai-hedge-fund）：README 写着 "does not actually make any trades"，VISION 已在规划 "opt-in run live"，且 `hedge_fund/brokers/` 目录已出现——**README 会漂移，白名单不会**

**12. 免责落位三处，措辞排他**
- 抄：三个项目全部把免责放在**最顶部 + 独立分节 + 短句列表**，不在页脚
- 改在哪：
  - 产品每屏：复用 T3.7 的 `DisclaimerBar.vue`（已是每屏必带、文案单点定义）
  - 产物内：策略卡 JSON 的 `disclaimer` 字段（**产物离屏后仍自带免责**，可行性文档 §4.2 已设计）
  - 输出定性：经 `profile_inline` / `_sys_prompt_addendum` 注入，强制"研究性推演"而非"投资建议"
- 措辞模板（四个"only/not"式排他短句，逐条独立成行）：
  ```
  本研究性推演不构成投资建议，不涉及任何交易执行。
  - 不提供、不描述、不暗示任何交易执行通道
  - 输出不含任何收益承诺或保证
  - 使用者应自行咨询持牌投资顾问
  - 历史回测结果不代表未来收益
  ```

---

## 5. 本报告的"未找到可信来源"清单

1. **输出侧自动 attribution 校验**：没有任何主流开源交易 Agent 实现"终稿数字 vs 本 run 工具返回值"的自动比对。FinanceBench 只提供数据模型，OmniEval 只提供评测方法论，FinVet 查的是外部谣言而非自查。
2. **交易场景的 HITL 交互协议**：LangGraph 只有通用原语，券商侧做法无开源实现。
3. **OpenBB 是否完全无经纪执行能力**：三次抓取 GitHub 页面超时，未核实。
4. **中国金融行业 AI 标准（JR/T 系列）**：未核实原文，不作断言。
5. **资管新规智能投顾条款的具体条号**：未逐字核对 gov.cn 原文，正文中以描述性方式引用，条号需自行核对。
6. **"LLM 金融计算错误率"的单一权威数字**：不存在。可用的三个锚点是 FinanceBench 81%（答错+拒答合计，n=150/人工复核 2400 条）、FinanceReasoning 89.1%（o1+PoT，238 道 Hard 题）、ConvFinQA 非专家 46.9% 执行准确率。**三者口径不同，不可直接比较。**
