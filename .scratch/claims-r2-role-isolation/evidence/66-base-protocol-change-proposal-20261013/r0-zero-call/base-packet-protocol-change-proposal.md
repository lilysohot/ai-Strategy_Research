# base 包协议变更提案（7 条 critical 解锁）— 2026-10-13

**状态：proposal_pending_signoff（待 U 具名签认，未签不执行）**
**作者：本会话（零模型调用起草）　预算影响：签认后 ≤2 次调用**

## 一、问题

base 包（`industrial-fulian-md` char:5246-5537，291 字，7 槽，7 条 critical 金标）四次独立配置全部失败：

| 运行 | 模型/参数 | 记账结果 |
|---|---|---|
| r1 | doubao（8192，思考开） | 2 extracted / 5 partial |
| r2 | doubao（262144，思考关） | 2 extracted / 5 partial |
| r3 | deepseek-v4-flash（Ark） | 4 extracted / 3 partial |
| r4 | deepseek-flash（官方） | **6 extracted / 1 partial** |

质量门规则（`material_semantics.py:3438-3476`）：单元内**每个槽位必须显式记账**为
`extracted / no_supported_item / not_candidate` 之一；任一槽 `partial` ⇒ 该单元被
omitted（`roles.py:470-495`）⇒ `role_scope_not_fully_covered` ⇒ 整包 invalid，
**已成功抽取的 6 条也全部不发布**（全有全无）。

## 二、卡点定位（r4 最好成绩，仅剩 1 槽）

3 号槽 `slot_83bd83014d07f67e`（16 字证据碎片「且无新的大额负面管制公告）；」，
嵌在句中、以「且」开头以「）；」结尾）：

- 模型（官方 deepseek）实际产出了字段完整的 item 记录（semantic_type=forecast,
  statement_role=condition, evidence_quote 逐字可达）；
- 本地复现：该字段组合**单独构造 MaterialItem 成功** ⇒ 构造器/枚举不是直接原因；
- 但管线的记账结果为 partial，且 **reasons 未持久化**（store 中 `reasons: None`），
  精确失败分支（item_failed_validation / duplicate_terminal_records / terminal_status_invalid）
  无法从盘上产物直接判定——这是**观测性缺口**（见 P-E）。

## 三、候选方案

### P-A 修复式重试（推荐 ★）

**做法**：base 包的第二次尝试（`attempts_max=2` 早已授权、但现有重试只对传输类失败
触发、从未被使用）改为**携带记账反馈**：prompt 注入第一次尝试的 slot_ledger 摘要
（6 槽已提取、1 槽未决），模型对未决槽补 `no_supported_item`/`not_candidate` 终端
记录或修正重抽。

- 语义不变：每槽仍须显式记账，fail-closed 不放松；
- 成本：+1 次调用（在已签预算内）；
- 代码改动：执行器在 attempt2 前注入 ledger 摘要（小）；prompt 变化须在运行记录中声明；
- 依据：模型并非抽不出，而是对「证据碎片槽」倾向产出 item 而非终端记录——反馈后
  它拥有自我修正所需的一切信息。

### P-B 累积记账

多次尝试的 ledger 取**并集**：任一尝试中 extracted 的槽计入，并集覆盖全部槽 ⇒ 包完成。
语义不变；实现为 coverage 合并层改动（中等）；成本与 P-A 相同但每次尝试独立。

### P-C 单纯拆包（**无效，除非与 P-A/P-B 组合**）

`roles.py` 的 omitted 判定按 **unit** 名下任一 packet 是否 incomplete 连坐——拆成
7 个单槽包后，一个包失败仍使整单元 omitted。此为本次代码核查的重要反直觉发现，
单做等于白做。若与 P-B 组合（每小包独立累积），可把失败面切小，但改动面最大。

### P-D 放宽记账要求

允许未决槽静默通过。**不推荐**：直接弱化 fail-closed，与 §8 冲突。

### P-E 观测性修复（无论选哪个都应一并做）

把 slot_ledger 的 `reasons`/`missing_signals` 持久化（当前构建后被丢弃），
否则每次失败都要靠推断，违反「失败可归因」的退出判据 5。

## 四、推荐与请求裁定

**推荐 P-A + P-E**。签认后执行序：P-E 代码修改 → base 重跑（doubao，1+1 修复式
尝试，≤2 次调用）→ 若 7 槽全部记账成功，7 条 critical 候选发布 → 与原 222 合并
（base 候选为新增，不存在跨模型可比性问题）。

## 五、签认栏

- 选项：☐ P-A+P-E（推荐）　☐ P-B+P-E　☐ P-C 组合　☐ P-D　☐ 退回修改
- 授权预算：☐ ≤2 次调用　☐ 其他：______
- 授权人：______　日期：______
