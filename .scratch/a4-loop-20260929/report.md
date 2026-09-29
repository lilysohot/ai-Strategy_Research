# A4 环内修正闭环的真实模型验证（补取 → 改表述 → 重新提交）

- 方案：[`docs/data_clean_dos/01-table-recovery.md` §A4.5](../../docs/data_clean_dos/01-table-recovery.md#a45-评审修订契约c1c7s1s2本轮)「已知未实现」第 1 条
- 探针：[`a4_loop_probe.py`](./a4_loop_probe.py)（真实模型、逐题可续跑、解析清单提交与问题码）
- 结果：[`a4_loop_probe.json`](./a4_loop_probe.json)、[`a4_loop_probe.guided.json`](./a4_loop_probe.guided.json)、[`a4_loop_probe.early.json`](./a4_loop_probe.early.json)
- 日期：2026-09-29 · 模型：`glm-5.3-flash`（react/tui profile）· 语料库：只读

## 1. 目的与背景

方案 §A4.5 明确记录：清单生产者 `corpus_submit_manifest` 的即时回验与**环内修正闭环从未在真实模型运行中验证**——既有 3 题冒烟早于该工具存在，验证状态恒为 `draft`。本报告在真实工作流上回答该问题：

> 真实模型能否按 `corpus_submit_manifest` 的**逐条反馈**完成「补取原文 / 修改表述 / 移除结论 → 重新提交完整清单 → 收敛」？

## 2. 方法

命令（与既有 A4 冒烟同口径，仅问题文本不同）：

```bash
uv run frontier-agent --mode react --no-tui --yes -p "<question>"
```

- profile：`tui`（含 `corpus_search`/`corpus_fetch`/`corpus_inventory`；`corpus_submit_manifest` 由**伴随绑定**自动注入，`publisher_boundary` 接 stateful_react 最终答案出口）。
- 只读：子进程 `PGOPTIONS=-c default_transaction_read_only=on`；run 工件走文件系统。
- 三档，同一冻结题 `company-003`（国信证券财务预测表，光力科技 EPS／经营活动现金流）：
  - **自然档**：原始问题，不加引导；
  - **引导档**（`--guided`）：追加「先提交一次清单，按逐条问题修正后重新提交」的显式要求；
  - **早提交档**（`--early`）：要求**取证完成前先提交一次**，以逼出 `not_delivered`/`pending` → 补取分支。
- 判定：解析 `trace.jsonl` 的 `corpus_submit_manifest` 调用序列（参数/返回值/逐条 status 与 problems 码）＋ `corpus/manifests/*.json`（每次提交独立落盘）＋ `corpus/manifest_verification.json`（发布边界重算）。

## 3. 结果

| 档 | 墙钟 | 提交次数 | 环内轨迹 | 环内闭环 | 发布边界（重算） | 金标取回/答案 |
|---|---|---|---|---|---|---|
| 自然 | 344.6s | **1** | 提交即 `verified`（无需修正） | 未触发（无反馈） | `partial`（4×`not_in_report`） | 6/6 · 6/6 |
| 引导 | 618.1s | **2** | t13 `partial`(4×`missing_dependencies`) → t14 `verified` | **成立**（改表述/补依赖） | `partial`（`supported 6/partial 4`） | 6/6 · 6/6 |
| 早提交 | 534.4s | **2** | t4 `partial`(2×`not_delivered`+`missing_dependencies`) → 补取 13 次 → t13 `verified` | **成立**（补取→改表述→重提） | `partial`（`supported 2/partial 2`） | 6/6 · 6/6 |

token：自然 494,987 in／15,410 out；引导 777,980／23,378；早提交 552,032／20,204（合计约 1.82M input）。

### 3.1 早提交档逐帧（闭环的直接证据）

```text
turn 3  corpus_search
turn 4  SUBMIT  → partial   {supported 0, partial 2}   c1/c2 = not_delivered + missing_dependencies
turn 5  corpus_inventory
turn 6  fetch 1 locator        ← 反馈驱动的补取从这里开始
turn 7  fetch 8 locators
turn 8  fetch 2+2+4 locators
turn 9  fetch 3+2+2 locators
turn 10 fetch 3+2 locators
turn 11 fetch 3+2 locators
turn 12 fetch 2+2 locators
turn 13 SUBMIT  → verified  {supported 2, partial 0}   c1/c2 全部 supported
```

即：**模型读到 `not_delivered` 后对该 locator 补取（13 次 fetch），修正引用后重新提交，环内状态由 `partial` 收敛为 `verified`**。引导档另证「改表述/补依赖」分支（`missing_dependencies` → 调整 `purpose`/`required_dependencies` → `verified`）。

## 4. 关键发现

### F1（正面）环内闭环在真实模型中成立
三档中两档出现「反馈 → 修正 → 重新提交 → 环内 `verified`」，且每次都生成独立候选文件（`manifest-000/001`）。**模型确实能按逐条问题码行动**：`not_delivered` 触发 `corpus_fetch` 补取，`missing_dependencies` 触发证据 purpose／依赖修正。这一条回答并关闭了 §A4.5「已知未实现」第 1 条的主要疑问。

### F2（缺陷）发布边界把**被取代的旧候选**并入，修正成功后边界仍判 `partial`
`ledger._merge_manifests` 以 `payload.get("owner_role") or path.stem` 作 owner；`write_manifest_file` 不写 `owner_role`，故同一代理的**同一轮多次提交**被当成不同 owner（`manifest-000` 与 `manifest-001`）**求并集**而非「后者覆盖前者」：

```text
早提交档边界结论:
  manifest-000/c1 partial ['not_in_report','missing_dependencies']   ← 已被取代的旧版本
  manifest-000/c2 partial ['not_in_report','missing_dependencies']
  manifest-001/c1 supported []                                       ← 修正后的版本
  manifest-001/c2 supported []
→ 汇总 status = partial（supported 2 / partial 2）
```

后果：**环内已 `verified` 的修正，在发布边界被旧候选拖回 `partial`**；引导档同样如此（`missing_dependencies` 4 条全部来自 `manifest-000/*`）。这与审计留存（历史候选全保留）无关——问题在**判定**取了并集。多代理各自的候选应聚合，但**同一 owner 的重复提交应按最新候选取代**。

### F3（语义边界）`report_quote` 的问题只在边界暴露，环内无法修正
自然档模型把 `report_quote` 写成了**描述性长句**而非最终回答中的逐字锚点，环内工具（按设计不做报告绑定）返回 `verified`，边界才判 4×`not_in_report` → `partial`。模型**无从在环内看到并修正**该类问题。若要让该问题可环内修正，需让工具端能拿到（或近似）最终文本锚点，或把锚点检查前移。

## 5. 结论与限制

- **结论**：A4 的「补取 → 改表述 → 重新提交」闭环**在真实运行中成立**（两档独立复现，含补取分支）。但**发布边界的汇总语义存在缺陷（F2）**，使闭环成果无法反映到最终判定；连同 F3，**A4 仍不能作为可信的默认发布门**——与既有评审结论（`A4_ENFORCE` 默认关闭）一致，且给出了新的具体原因。
- **限制**：单题（company-003）、n=3 档，非独立盲测（题目选自冻结集）；`--guided`/`--early` 为**机制验证档**（显式要求迭代提交），非自然效果度量；自然档未触发反馈，故「自然使用下闭环是否被需要」未直接观测。

## 6. 修复（2026-09-29）：F2 发布边界聚合语义

**改动**（校验语义变更 + 回归测试）：

| 落点 | 改动 |
|---|---|
| [`plugins/corpus/ledger.py`](../../plugins/corpus/ledger.py) | `write_manifest_file(..., owner=)` 写入 `owner_role`（显式值不覆盖）；`_merge_manifests` 改为**跨拥有者并集、同拥有者取最新**；`load_manifest_files` 按提交序号**数值**排序（>999 也保持「后者取代前者」） |
| [`plugins/tools/corpus_manifest.py`](../../plugins/tools/corpus_manifest.py) | `_current_owner()` 取当前 `ExecutionScope.task_id`（每个代理实例一个、跨该代理多次提交不变）→ 落盘 `owner_role`，并在响应回显 `owner` |

拥有者身份用 `ExecutionScope.task_id` 而非代理角色：角色（`stateful_react`/`sub_agent`）会把
同一任务的多**个子代理**混成一个拥有者、互相取代；`task_id` 才是 per-agent 实例。

**确定性前后对照**（[`replay_f2_fix.py`](./replay_f2_fix.py)，零模型，直接重放早提交档的真实 run 产物，不传 `final_text` 以隔离聚合语义本身）：

| 口径 | status | counts | 结论 ids |
|---|---|---|---|
| 修复前（全量并集） | `partial` | supported 2／partial 2 | `manifest-000/c1`、`manifest-000/c2`、`manifest-001/c1`、`manifest-001/c2` |
| 修复后（同拥有者取最新） | **`verified`** | supported 2 | `c1`、`c2` |

**回归测试**：`tests/test_corpus_ledger.py`（`owner` 注入、同拥有者取代、跨拥有者并集）、
`tests/test_corpus_manifest_tool.py`（作用域 owner + 同代理重提取代、无作用域降级）。
修复前这两条新用例必失败（并集/无 `owner` 字段），修复后通过。

**修复后真实运行复核**（`--early --tag early-fixed`，2026-09-29，run
`20260929-141806+0800-react-7406`）：turn 3 提交 → `unsupported`（`quote_not_found`）→
补取 → turn 8 重新提交 → `verified`（7 条 supported），两次提交 `owner` 均为
`stateful_react:3173adfdc7d6`；**发布边界重算 `status=verified`（supported 7／partial 0／
unsupported 0），结论 id 无前缀**——同一路径修复前为 `partial`。墙钟 676.9s，
input 382,186／output 26,881。

## 7. 复现

```bash
# 自然档
uv run python .scratch/a4-loop-20260929/a4_loop_probe.py --query-ids company-003
# 引导档
uv run python .scratch/a4-loop-20260929/a4_loop_probe.py --query-ids company-003 --guided --tag guided
# 早提交档（逼出补取分支）
uv run python .scratch/a4-loop-20260929/a4_loop_probe.py --query-ids company-003 --early --tag early
```

逐题产物在 `model_runs/<tag>/<query_id>/result.json`（存在即跳过，可续跑）；run 工件在 `.apodex/runs/<session-id>/corpus/`。

## 8. 修复后复核（Round 2，2026-09-29）

用与 Round 1 完全相同的方式重跑 `company-003` 三档（详见
[`round2_review.md`](./round2_review.md)）：

| 档 | 提交次数 | 候选清单 owner | 环内闭环 | 发布边界 | 边界 counts |
|---|---|---|---|---|---|
| 自然 | **8** | 8/8 同一 owner | 否（同一 `missing_dependencies` 8 次未修） | `partial` | supported 4／partial 1 |
| 引导 | **0** | 无 | 未触发 | `draft` | — |
| 早提交 | 2 | 2/2 同一 owner | **是** | **`verified`** | supported 2／partial 0 |

- **F2 修复确认**：每份候选都带同一 `owner_role`；自然档 8 份候选共 40 条结论，边界 counts
  恰为**最新一份**的 5 条（不再并集）；早提交档边界 `verified`（修复前同路径 `partial`）。
- **边界是「最新提交」的忠实反映**：自然档 `partial` 是模型确实未满足自报 `value` 依赖，
  属诚实信号而非污染。
- **新发现 F4（模型行为方差）**：引导档本轮**零提交**（合规不保证）→ 边界 `draft`；
  自然档 **8 次重提无进展**（1240.7s、1.45M input token）＝ thrashing。二者都是
  「是否默认启用阻断」的直接输入：本轮三档会有 **2/3 被降级**，且原因在模型行为层，
  不是校验机制缺陷。
