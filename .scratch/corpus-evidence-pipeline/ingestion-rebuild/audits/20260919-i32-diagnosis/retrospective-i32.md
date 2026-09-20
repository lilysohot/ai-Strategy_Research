# I3-2 回溯：遗漏与待提高（2026-09-19，r27 之后）

> 判据（可复现，红/绿）：
> ```bash
> env -u PYTHONPATH uv run python \
>   .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i3_2_completion.py
> ```
> 本次 **exit 1**（`i3_2_complete=false`，3 项 fail）。该门按诊断稿卡点 4 新建，逐项输出
> pass/fail/not_run/not_applicable，复用既有审批/评分/冻结校验，不新增评分算法。

## 0. 结论

**I3-2 尚未达到 `tasks:321` 的完成定义。** r27 自身也写着"仍在未宣告 I3-2 完成"
（`i0c-r27.notes`：正式评分派生件接线、阶段完成门、初始 manifest 未做）。

已完成的部分（本门实测 pass）：

| 判据 | 结果 |
|---|---|
| 上游审批链（建议件→批准投影→完整性门） | **pass**：`ready=true`、0 blocker、20 warning（人工同义映射待审计） |
| 正式评分输入派生件一致 | **pass**：`query-gold-scoring-v1.jsonl` `1b018ceb…`、79 必需 + 20 补充、原字段零改动 |
| P2 阈值/关键题/负例与冻结物一致 | **pass**：policy 5 项与代码现值逐项相同；关键题 28、负例 6 与金标一致 |
| 旧基线身份/范围（7 类适用范围） | **pass（仅身份层）**：r27 冻结、8 项 blocked 清零 |

## 1. 遗漏（fail 项，附证据与动作）

### F1 必要资产未入链（8 项中 7 项）

`i0c-current` 合并绑定实测：**入链 1/8**

| 资产 | 状态 |
|---|---|
| `i3-2/query-gold-scoring-v1.jsonl`（正式评分输入） | **未入链** |
| `i3-2/scoring-input-manifest.json`（派生 lineage） | **未入链** |
| `i3s2_scoring_input.py`（派生器 + 唯一读入口） | **未入链** |
| `p2/policy-and-lists-confirmation.json`（阈值/关键题/负例确认） | **未入链** |
| `p3/baseline-mapping-reconciliation.json`（旧基线对账） | **未入链** |
| `p4/experiment-initial-version.json`（初始版本清单） | **未入链** |
| `freezes/validate_i3_2_completion.py`（本完成门） | **未入链** |
| `baseline-case-manifest.json`（旧基线用例清单） | 入链（r27） |

影响：I3-2 的"确认阈值/关键题/负例""正式评分输入""初始版本"在链上**无凭据**——文件可被静默改动而
`validate_i0c_freeze.py` 仍绿。另：`scoring-input-manifest.status` 仍写 `pending_freeze_r27`（已过期）。
动作：r28 绑定上述文件并把 status 更新为 `frozen`（Agent，零资料）。

### F2 P4 不是"唯一初始实验 manifest"

实测：`status='draft_pending_signoff'`；`query_gold.materialized_draft` 仍指向
**审计目录里的 P1 草稿**，且 `query_gold.formal_path` 同时列正式 gold → **执行器无法唯一选取评分输入**；
`execution`（命令/环境/初始参数）**缺失**。
动作：改为只认 `i3-2/query-gold-scoring-v1.jsonl`（含哈希），把正式 gold 降为 lineage 引用；
补执行段（未实现的入口显式登记为 I3-1 前置，不得写成已可执行）（Agent，零资料）。

### F3 旧基线"映射"层未完成

1. `legacy_retrieval_golden`：19 题的**旧锚点 `(title_contains, doc_prefix)` → 新 `source_id`/locator 映射**
   仍是 `to_be_resolved`（任务要求的是"确认**映射**"，冻结的只是范围与预期）；
2. `formula_7`：每公式的**输入字段** `needs_definition`（只有 formula 名 + 预期 + 容差，无输入字段清单）；
3. **清单引用的资产 13/14 未入链**（`plugins/corpus/golden.py`、`pilot_manifest.json`、机器记录、
   报告与 doc_kind CSV 等）→ 直接违反 I3-2 验收条目"**无未冻结的必要外部指针**"。
   注：`baseline-bindings.json` 只在 r1 绑过；r27 绑的是"**清单本身**"，不是清单指向的资产。
动作：先做 19 题映射（自动首轮 + 人工确认位）、补公式输入字段声明；把引用资产纳入绑定，
或把清单指针改指向已绑定物（Agent，零资料；若某资产无权威版本才需 U）。

## 2. 待提高（不影响"完成"判定，但应处理）

| # | 事项 | 说明 |
|---|---|---|
| P1 | 20 条人工同义映射 warning + `macro-004` 机器 `blocked` 覆盖 | 已由正式审批承载，但属**语义审计风险**；建议定抽样审计计划（谁能审、抽几条、判据） |
| P2 | 完成门未接进流程 | 新门未入链、未写进台账验收命令；建议 r28 绑定 + 在 `tasks` 侧把"三门（i0c 链/完成门/回归）"列为 I3-2 验收命令 |
| P3 | 验证器文案漂移 | `validate_i0c_freeze.py` 已加 r27 规则（第 850 行起），但**成功消息仍只到 r26** |
| P4 | 留出隔离一致性 | 新出现的 `prose_holdout_manifest.json`（天风 prose 留出）**未入链**，且其留出来源不在 `guards/i3.json` 的 4 个 `forbidden_roots` 内 → 隔离是否可强制待核 |
| P5 | M5 F3 | `validate_i1_freeze.py` 对工作区 13 项失配仍单列未修（与本轮 I0-C 链无关，但持续被跳过） |
| P6 | 完成判定此前依赖人读 | 本次之前无机器判据；建议把本门作为 I3-2 收口唯一入口，避免"局部绿灯=完成" |
| P7 | 清单可读性 | `customer_table_12` 的 `expected_asset` 全空（因"以报告为准"），建议显式加 `authority=report` 字段 |

## 3. 明确 not_run（**不算遗漏**，不得用完成门代替）

- I3-5 旧基线真实非回归重验（入口写原库 5432 / 需预算授权）；
- I3-1 三类开发 E2E（需 `i3-e2e` 阶段守卫 + 隔离 PG + 来源读取）；
- I3-5/I3-7 真实生成答案语义验收（须另定输入/判据/预算）。

## 4. 最小修复顺序（Step A→C 全部零资料，Agent 可独立完成）

- **Step A**：P4 唯一化 + 执行段；`scoring-input-manifest.status → frozen`；补 `formula_7` 输入字段声明；
- **Step B**：19 题旧锚点→新 locator 映射表（自动首轮 + 人工确认位）；引用资产入链或改指向；
- **Step C**：r28 冻结（绑定 F1 列表 + 映射表 + 台账回填 + 完成门入链）→ 复跑三门：
  `validate_i0c_freeze.py`、`validate_i3_2_completion.py`、回归 88 passed → 再由复核者/用户签认。

**只有 Step A/B 中出现"某资产无权威版本"时，才需要 U 决策**；其余均为工程动作。
