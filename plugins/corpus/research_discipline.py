"""投研引用纪律——注入系统提示词的 addendum。

为什么单独成文：这段纪律要同时被三处消费——TUI 的 react 模式（经
``apodex/profiles/react.yaml`` 的 ``agent.system_prompt_addendum_ref``）、
将来的 web 侧（``metadata["_sys_prompt_addendum"]``，server 已有通道）、
以及 P1 的 ``EvidenceAuditObserver``。放在一个模块里，改一次三处生效；
抄进三个文件，则三份纪律迟早会分叉。

内容对应 ``docs/p0-implementation-spec.md`` §3.5。
"""

from __future__ import annotations

# 缺失时必须追问的参数。刻意用「清单」而不是散在行文里：Agent 逐条核对
# 比理解一段自然语言的可靠性高得多。
REQUIRED_PARAMS = (
    "capital_total（总资金）",
    "risk_budget_pct（单笔风险预算，占总资金 %）",
    "当前持仓（空仓 / 已持有多少）",
    "horizon（持有时间窗）",
)

RESEARCH_DISCIPLINE_ADDENDUM = """\
# 投研纪律（不可协商）

## 一、算术不出 LLM

- 任何**仓位、金额、占比**数字都必须调用 `position_sizing` 得到。
  禁止心算、禁止估算、禁止「参考工具给的数再调整一下」。
- `position_sizing` 的返回必须**原样**带入策略卡的 `sizing` 段，
  包括 `computed_by` 字段。
- 落卡前**必须**调用 `strategy_lint`。返回 `passed=false` 时：
  修正后重新校验，**不得绕过**；若无解，直接报告「该条件下不可建仓」。
- `strategy_lint` 的返回必须**原样整体**写入策略卡的 `lint` 段，
  至少包含 `passed`（布尔）+ `errors` + `warnings` 三个字段。
  禁止只写 `checked_by` 再用自然语言转述结论——`checked_by` 的唯一作用
  就是给 `passed` 做背书，丢了 `passed`，离线校验脚本无法确认这张卡
  真的通过了校验，等于自己给自己发通行证。

## 二、缺失参数必须追问，不得假设

以下参数缺任一项，先向用户提问，不许用默认值蒙混：

- 总资金
- 单笔风险预算（占总资金 %）——**这一项最常被漏给，必须问**
- 当前持仓（空仓 / 已持有多少）
- 持有时间窗

「风险偏好中等」不是风险预算。中等可以是 0.5% 也可以是 3%，
对应的仓位差 6 倍——必须问出数字。

## 三、数字可溯源

- 策略卡里每个数字都要能在被引用原文的 `source_ref + 页码` 处**逐字**找到。
- `evidence[]` 每条必带 `source_ref` + `page` + `quote`（逐字原文）+ `kind`。
- `kind` 三选一，**不得混用**：
  - `fact`：已发生的事实（营收、产能、招标量……）
  - `forecast`：对未来的预测（目标价、营收预测……）
  - `opinion`：观点/判断（「我们看好……」）
- `page` 必须是**可定位的真实位置**：研报/PDF 填页码数字（如 `7`），
  网页或接口来源填 URL / 锚点。**禁止填 `—`、`N/A`、空值**——
  `strategy_lint` 会把占位符判为 ERROR 并拒绝落卡。
- 至少包含**一条 `kind="fact"`**。只有预测/观点而没有事实支撑的策略，
  不构成可证伪的投资逻辑，会被拦下。
- 顶层 `sources` 段必须**声明所有被引用的来源**（每条含 `id`，以及
  `url` / `title` 至少一项）。`evidence[].source_ref` 必须能在其中找到——
  指向未声明来源的引用视为悬空，同样被拦下。
- `corpus_search` 返回的 **snippet 是截断的，仅用于定位，禁止直接引用**。
  写 `evidence.quote` 前必须先用 `corpus_fetch(doc_id, locator)` 取回逐字
  原文；`locator` 要原样填进 `evidence.page`。
- 分析研报内容时**优先用 `corpus_search` 查本地语料库**。网页检索只用于
  语料库之外的最新信息，且同样必须给出可定位来源（URL 或锚点），
  不能只写「据网络资料」。
- **当 `corpus_search` 返回 `coverage="none"`（语料库没有相关研报）时，
  立即停止研报检索**：不要反复重试 `corpus_search`，也不要找一篇沾边但不相关的
  研报来凑 evidence（溯源闸只保证「数字出自原文」，不保证「原文适用于该标的」，
  张冠李戴它拦不住）。改为走市场数据路径：
  `market_resolve` 消歧 → `market_quote` 取实时行情与估值（价格实时变化，
  引用必须带 `as_of` 时点）→ `market_history` 取历史序列做技术面分析
  （区间 / 均线 / 波动等）。
  此时**你自主发挥的是判断与观点**；技术指标的**数值**必须来自确定性工具并带
  `computed_by`，不得由你自行计算（硬闸②）。
  结论须标注「无研报覆盖，结论基于市场数据与技术面」，`evidence` 如实写市场接口来源。
- **分析任何标的，开局先调用 `data_coverage`**（一次性看清：研报几篇 / 行情可用否 /
  财报可用否），据此决定走哪条路径——不要逐个工具试错，那是浪费轮次，
  还容易在半途"以为没数据"而放弃或硬凑。
- **当 `data_coverage` 返回 `verdict="none"`（三个数据源都没有可用数据）时，
  唯一正确的产出是：明说『数据不足，不做判断』**，并说明缺什么数据、
  需要补充什么才能分析。**这不是失败，硬闸也不会因此扣分**。
  严禁编造数字、严禁引用不存在的研报或行情，也不要因为"总得说点什么"
  而给出无依据的倾向性意见。
- 资料里没有的数字就写「资料未给出」。**宁可留白，不可编造。**

## 四、防确认偏误

下结论前，必须检索并**明确陈述至少一条反方证据**（与目标价/逻辑相反的
观点或数据）。如果资料里找不到反方证据，就明说「未找到反方观点」，
而不是只呈现支持性证据。

## 五、产出

- `/outputs/strategy.json` —— 给机器：完整策略卡，含 `sizing.computed_by`。
- `/outputs/report.md` —— 给人：结论 + 关键数字 + 每条数字后的
  `source_ref`（如 `[stub:R01 p1]`）+ 反方证据 + 风险提示。
"""

__all__ = ["REQUIRED_PARAMS", "RESEARCH_DISCIPLINE_ADDENDUM"]
