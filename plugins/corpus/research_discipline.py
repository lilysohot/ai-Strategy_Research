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
- 检索返回的 **snippet 仅用于定位，禁止引用**——引用前必须取回逐字原文。
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
