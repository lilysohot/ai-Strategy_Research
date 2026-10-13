# R2 链回溯审计（首轮 → 复查）

- 2026-10-13　零模型调用、只读工作树；审计链：**71 FN 归因 → 72 终态记录 → 74 草案包 → 75 落地脚本**
- 机器产物：`audit-initial.json` / `audit-initial.md`（首轮 23 项检查，7 项未过）、
  `audit-recheck.json` / `audit-recheck.md`（复查 26 项检查，**0 项未过**）
- 谓词（先声明）：`blocking_target` 目标达不成 ｜ `blocking_signoff` 签认会落地不可消费记录或代签
  ｜ `registration` 须登记 ｜ `cosmetic` 措辞

## 一、首轮 7 项未过与处置

| # | 检查 | 级别 | 首轮实然 | 处置 | 复查 |
|---|---|---|---|---|---|
| 1 | `flip_count` | blocking_target | 8 ≠ 7 | **检查器自身公式错**（把"二选一取一"写成了 2 条），草案无此缺陷；修检查器 | PASS |
| 2 | `gate_rebinds_contract_hash` | blocking_signoff | 门仍钉 v4.1 | **首轮谓词本身有问题**：门若同时钉 v4.3 会与其反向钉门形成哈希环。改为先例做法——门只推进到**已签** v4.2，并新增 `contract_version_chase` 登记（含不变量与校验器要求） | PASS |
| 3 | `readjudication_carries_contract_fields` | blocking_signoff | 缺 9 个契约字段 | 改为 **11 条契约形态裁定桩**：候选人裁定的 11 字段逐字保留，新增字段一律 `proposed_*`/`keep_if` 前缀 | PASS |
| 4 | `readjudication_has_verbatim_evidence` | blocking_signoff | 无 `evidence` | 桩内带候选原文 `evidence` 与金标 `gold_locator` | PASS |
| 5 | `no_prefilled_pair_decision` | blocking_signoff | **落地脚本硬编码 `pairs_resolved=NT-I23`** | 属**代签 U 未做的选择**。签认件增设「二选一（I23/I24）」与「三选一（I45/I46/I47）」勾选栏；脚本改为三项全部读件、各自要求恰好一项（选甲时三选一必须留空） | PASS |
| 6 | `frozen_gold_side_binding_registered` | registration | 未登记 | 契约新增 `registrations.frozen_gold_side_contract_binding`（金标字节不可改 ⇒ 登记为例外） | PASS |
| 7 | `quality_gate_wording_current` | cosmetic | 仍写「本契约 v3」 | 改为版本链描述（v2→…→v4.3） | PASS |

## 二、复查新增检查（首轮没有的）

- `stub_pool_shape`：裁定桩 = 5（必需）+ 2（二选一池）+ 4（第 7 条池）= 11
- `all_stubs_contract_form`：全部 11 条桩齐备契约 11 字段
- `decisions_have_boxes_and_are_read`：三项人裁均有勾选位且脚本逐字读取、且脚本列出全部候选选项
- `gate_pins_a_signed_contract_version`：门只允许钉**已签**契约版本
- `contract_version_chase_registered`：版本追逐登记（不变量 + 校验器）
- `terminal_record_is_the_fail_state_being_superseded`：确认被取代对象确为 FAIL 终态

## 三、反向确认（不是遗漏，机器验算）

- **改判只在 `matched` 与 `correct_extra` 之间搬标签** ⇒ 精确率分子/分母不变（240/248）、
  接受数不变（240）⇒ 判据 3/5/6 不受影响。
- 六项阈值与门 v2 **逐字相同**；`threshold_relaxation_after_execution_allowed` 仍为 `false`。
- 已签 v4.2 对门 v2 的绑定与现盘一致（扩链前提成立）。
- 改判目标均不在现有 matched 集合内；必需 5 条的候选此前均未被占用（全部 `correct_extra`）。
- 二选一两条共享**同一候选**（`itm_703720fdd5630e8b`），故只能取一；落地后候选互不重复（已空跑验证：
  甲分支金标集 = I23/I26/I34/I36/I38/I39/I48；乙分支 = I24/I26/I34/I38/I39/I46/I48）。

## 四、已登记但不阻塞的开放项

| 项 | 状态 |
|---|---|
| 门与契约的版本追逐（门钉 v4.2 / 契约 v4.3） | 已登记，不变量＝阈值逐字恒等 + 哨兵与契约 NT-I\* 子集恒等；待校验器落地 |
| 冻结金标侧契约绑定落后（仍是 v2 `2eb24be7…`） | 已登记为例外（金标字节不可改） |
| evidence/72「不可达」终态的取代关系 | 已登记 `registrations.supersedes_terminal_record`；**待 R2 三项签认 + 重新出分后才生效** |
| `tools/evidence_guard.artifact_state` 把未签门草案读成 `signed` | 已单独上报，**未修**（共享护栏，需另行裁定） |

## 五、签认与落地（本次审计之后发生，另存 post-signoff 相位）

| 事项 | 结果 |
|---|---|
| 签认 | `xyl` 2026-10-13，签认件 sha256 `b02dadc2…`（含件内三份草案哈希核对） |
| 三项人裁 | 二选一 = **NT-I23**；第 7 条 = **选项乙**；三选一 = **NT-I45** |
| 落地 | `75-r2-signed-20261013/r0-zero-call/`：`gate-v3.json`（`frozen_before_execution`，countersignature signed）、`scoring-contract-v4.3.json`（`frozen_signed`，已回填门 v3 哈希、`provisional` 标记移除）、`re-adjudication.json`（`named_signed`，7 条，候选互不重复） |
| 签认只动了签认栏 | **可逆还原证明**：把已签件按可逆规则还原，逐字节等于原空白件（`blank-sheet-template.md` 哈希 = 原空白哈希） |
| 新增相位 | `audit-post-signoff.json/.md`：**27 项检查，0 项未过**（新增「签认件三项人裁各恰好一项」独立复核） |
| 重算出分 | `evidence/77-…/r1-score/`：**PASS**（41/48 = 0.854、源1 0.909、源2 0.808、哨兵 11/11、精确率 30/31 不变） |

### 一处我方缺陷（首跑拒了有效签认）

首跑 `apply_r2_signoff.py` 被**拒绝**：我的解析器只认 `☑`／`[x]`／`✓`，而 U 用的是仓库既有约定
（`- 结论： x `，`tools/evidence_guard._TEXT_SIGNATURE_PATTERNS` 认这种）。**属我方解析器缺陷**，
处置：扩到接受 `☑/☒/[x]/✓/x/X`（裸 x/X 需前置非字母数字）、补 7 个自检用例（含 x 约定）、
并给自检加「可逆还原 == 原空白哈希」的基线断言。**未改动签认件任何字节。**

### 落地后的未审计范围

- 发布路线 O1（「显式缺口」）的代码面 —— 见 `evidence/73`，不在本次链内
- 评分器改为读契约（OPEN-1=A 的兑现）—— 代码改动**仍未实施**（本轮的 77 是独立脚本重算，不等于评分器已改造）
- 77 的重算结果由落地脚本的护栏 + 上述还原证明间接支撑；**未**再走一遍 76 的 26 项谓词

## 六、口径说明

**「0 项未过」只说明本脚本声明的 26 条谓词在当前字节上成立**，不构成对 R2 方案的正确性、
可签性或出分结果的背书；签认与否仍由 U 具名决定。
