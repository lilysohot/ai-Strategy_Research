# R2 边界词表清退 · 冻结预算草案 v8

| 项 | 内容 |
|---|---|
| 状态 | **草案 / 未签认 / 未执行**（无模型调用，无入库） |
| 日期 | 2026-10-09 |
| 预算文件 | `.scratch/corpus-evidence-pipeline/r2-lexicon-retirement-development-budget-v8.json` |
| 零调用探针 | `.scratch/corpus-evidence-pipeline/probe_lexicon_retirement.py` |
| 上游契约 | `docs/corpus-material-understanding-contract.md` §5–§6 |
| 非退化政策 | `.scratch/corpus-evidence-pipeline/r2-non-regression-policy-v1.json` |

## 1. 要回答的唯一问题

> 在冻结的 4 个 development 材料上，把 `material_semantics._ATOMIC_BOUNDARY_RE` 里的
> **过拟合边界词表**清退后，item / 关系门是否相对 `r2-non-regression-policy-v1` 的
> **逐类下限**发生退化？

**不是**要回答"换个材料还灵不灵"——那需要非 dev 材料，而 `holdout_calls_allowed = 0`，
且 dev 正是词表的拟合目标，本预算在原理上无法证伪泛化。这一点写进 §6 不做清单。

## 2. 零调用探针已经给出的证据（尚未花任何模型调用）

命令（幂等、`--no-write`、无墙钟）：

```bash
uv run python .scratch/corpus-evidence-pipeline/probe_lexicon_retirement.py --no-write
```

### 2.1 清退不损失任何金标证据的义务覆盖

口径：金标 item 的 evidence quote 去空白/小写后**完整落在某一个**候选槽位文本内（严格包含，
属**阻断性诊断**，不是评分器——评分器用 `SequenceMatcher` 模糊比）。

| 样本 | 金标 item / critical | 槽位 current → all | 覆盖 current → all | 覆盖丢失 |
|---|---|---|---:|---|
| dev-company-report | 5 / 4 | 76 → 69 | 1 → 4 | 0 |
| dev-industry-qa-report | 4 / 4 | 56 → 55 | 3 → 3 | 0 |
| dev-personal-trade-review | 4 / 4 | 15 → 11 | 2 → 4 | 0 |
| dev-expert-call-copper-foil | 11 / 11 | 496 → 493 | 4 → 5 | 0 |

`coverage_lost_total = 0`（两种范围都是 0）。critical 未被覆盖项只减不增
（公司 3→1，复盘 2→0，铜箔 7→6，行业 1→1）。

**顺带发现的既有事实**（与清退无关，先记；按纪律不回流本次）：当前词表切分过碎，
公司研报 5 条金标引文里有 4 条**跨了槽位边界**、落在不到任何一个槽里。这是既有问题。

### 2.2 词表命中率：谁是真正的过拟合

每千字符边界命中数（`_DOMAIN_BOUNDARY_CUES` / `_SAMPLE_SPECIFIC_BOUNDARY_PATTERNS`）：

| 材料 | split | chars | 域词/千字 | 样本专有/千字 |
|---|---|---:|---:|---:|
| dev-company-report | dev | 3054 | 2.292 | 0.327 |
| dev-expert-call-copper-foil | dev | 11818 | 0.338 | 0.000 |
| dev-industry-qa-report | dev | 1508 | 0.000 | 0.663 |
| dev-personal-trade-review | dev | 674 | 0.000 | 5.935 |
| **stress:optical-unlabelled（非 dev、非金标）** | — | 7039 | **0.994** | **0.000** |

结论（与我上一轮的判断**部分相反**，以数据为准）：

- `_SAMPLE_SPECIFIC_BOUNDARY_PATTERNS`（英文交易行、`和“强推”`/价差扩张）**确认是样本级过拟合**：
  只在交易复盘样本命中，在包括非 dev 材料在内的**其它全部材料为 0**。
- `_DOMAIN_BOUNDARY_CUES`（`营收/毛利率/存货/应收/云计算/GPU/ASIC/CPO…`）**不能确认为过拟合**：
  在非 dev 的光模块材料上仍有 0.994/千字命中——它们是**该行业材料的通用词**，不是 dev 答案。
  之前"照样本抠出来"的说法对这部分下得太重，此处更正。

因此 `retirement_scope.variant` 有两个可辩护取值，由 U 选：
`retire_sample_specific_only`（保守，只清确认过拟合的 4 条）或 `retire_all_overfit`（草案默认）。

### 2.3 调用计划（确定性）

容量 `max_slots_per_batch=16 / max_items_per_packet=64`（= 每批 16 槽）下，全量义务集的 item 批数：

| 样本 | current | 清退后 |
|---|---:|---:|
| dev-company-report | 5 | 5 |
| dev-industry-qa-report | 4 | 4 |
| dev-personal-trade-review | 1 | 1 |
| dev-expert-call-copper-foil | 33 | 33 |
| **合计** | **43** | **43** |

清退**不改变**调用计划；铜箔一份占 33 次。故 `planned_calls_upper_bound = 43`。
该值在补丁落盘后**必须**由 `--plan-only` 复算核对，不一致即中止（见 §4）。

## 3. 预注册退出判据

> **口径规则（v9 修订，2026-10-09）**：**只有被实际执行的阶段所产生的指标类才进判据**。
> 某阶段按预算 `deferred`，该类指标必须记为 `not_measured` 并从通过/失败中排除，
> **不得**记为"违反"。同理，"有意不请求的阶段"不得计入 `failed_or_partial` / `omitted_areas`。
> v8 违反了这条，导致关系类被判"违反"、每个包被判 `partial`（见 §8.6）。

**Stage 0（0 次模型调用，先跑）**

- 通过条件：冻结金标 item 的严格义务覆盖丢失数 `== 0`。
- 失败动作：停止，**不发起任何模型调用**，只报失败与遗漏。

**Stage 1（模型，仅当 Stage 0 通过）**

- 唯一轮次 `lexicon-retirement-baseline`，计划上限 43 次、单文档 ≤33 次、单次 60 秒、`holdout = 0`。
- 通过条件（全部满足）：
  1. `r2-non-regression-policy-v1` 的**每个** `protected_samples` 类目的**每个** `metric_floors`
     不下降；
  2. 6 个 `protected_micro_scopes` 各自 `metric_floors` 不下降，且 `max_negative_relation_hits` /
     `max_false_positive_relations` 不上升；
  3. 每样本 `failed_or_partial` 包数不上升（不得超过 policy 的 `max_failed_or_partial_packets`）。
- 任一不满足 ⇒ 停止；**不追加轮次、不重试模型、不访问 holdout、不入库**。

**工程门（与模型调用无关，须全绿）**

全量 corpus pytest、R1 金标校验器、微金标校验器、目标 pyright、Ruff、import smoke stage 1+2、
symbol closure。另加：本次的两个差分（边界正则等价探针自检、`MaterialRun.verify_identity`
版本表差分）。

## 4. 绑定与冻结动作（签认后执行）

1. 补丁落盘（把 `retirement_scope.constants` 所指常量按选定 variant 置空，由既有拼接式重建正则；
   **不改**通用词表、不改顶层分支顺序）。
2. `uv run python .scratch/corpus-evidence-pipeline/run_material_development.py --budget <v8> --plan-only`
   → 核对 `planned_calls_upper_bound == 43` 且新槽位 ID 不触发 scope drift。
3. 回填并冻结 `non_regression_policy.sha256`、`probe.sha256`。
4. 三处哈希（gold / micro gold / 政策 / 探针）与 `--plan-only` 输出一起进签认栏。

## 5. 归属规则（按根因层）

- 金标引文跨槽 ⇒ **我方契约缺陷**（切分口径），进 backlog，不算模型行为。
- 槽位已给出、模型不填 ⇒ **模型行为**，只作我方结论的前置条件，不改 prompt 迁就。
- 判定所需接口不存在 ⇒ 我方缺陷；本轮不新增接口。

## 6. 范围外 / 不做清单

1. 不验证泛化 / 不证伪过拟合（holdout 禁用；dev 是拟合目标）。
2. 不清退通用边界词表与否定词表。
3. 不改槽位协议、关系协议、契约版本、`MATERIAL_EXTRACTOR_VERSION`。
4. 不改金标 / 微金标 / 阈值 / 评分器。
5. 不入库、不写 corpus schema、不动生产库。
6. 不开第三轮。
7. 任何结果**不得**表述为 R2 验收通过。
8. 判据外的新发现一律进 backlog，**不回流本次**。

## 7. 待 U 裁决

| # | 事项 | 选项 |
|---|---|---|
| D1 | 清退范围 | `retire_sample_specific_only`（保守，推荐）/ `retire_all_overfit`（草案默认） |
| D2 | 是否接受 43 次上限（铜箔独占 33） | 接受 / 改为更小容量+更少样本（会违反 policy 的 `sample_ids_must_equal_protected_samples`） |
| D3 | `model` 取值 | 由 `configured_model()` 在 plan 时确认，草案暂填 `glm-5.3-flash` |
| D4 | `response_format` | 草案填当前 `material-atomic-jsonl-v5`（v7 为 v4，存在漂移，需确认） |

## 8. 执行记录（2026-10-09）

授权：U 于 2026-10-09 指示"执行吧"（授权执行，实施方不得自宣通过）。

执行前实跑（命令与结果）：

| 步骤 | 命令 | 结果 |
|---|---|---|
| Stage 0（0 调用） | `uv run python .scratch/corpus-evidence-pipeline/probe_lexicon_retirement.py --out .scratch/corpus-evidence-pipeline/r2-lexicon-retirement-stage0-v8.json` | 三个清退范围 `coverage_lost = []`；产物 sha256 `19391298acb34c1e9ec96a64e1259c939eaa741003969498451e0078082bcd09` |
| 组合式安全前置修复 | `plugins/corpus/material_semantics.py::_ATOMIC_BOUNDARY_PATTERN` | 原实现在清空样本 pattern 后会残留尾部 `\|`（实证：4 字符文本产生 5 个零宽匹配）；改为 `"\|".join(...)`，冻结回归 86 passed、探针自检通过 |
| 计划核对 | `run_material_development.py --budget <v8> --round lexicon-retirement-baseline --plan-only` | `planned_calls_upper_bound = 43`，与冻结值一致 |
| 连通性预检 | 1 次非抽取调用（`build_default_llm` 最小请求） | OK，返回 `{"ok": true}`；**不计入 43**，如实记录 |

执行期发现并处理：

1. **D1 取 `retire_sample_specific_only`**（实施方建议值）。若要 `retire_all_overfit` 需另行裁决并重跑。
2. **D3/D4 由实测确认**：`configured_model() = glm-5.3-flash`、`MATERIAL_SLOT_JSONL_VERSION = material-atomic-jsonl-v5`，均与预算一致。
3. **归档运行器脱节已修**：`run_material_development.py:17` 的 `plugins.corpus.claims_v2` → `plugins.corpus.claims_detail`（模块已并入）。属运行器修复，非生产语义变更。
4. **`--plan-only` 需带 `--round`**：运行器先做 round 校验再看 plan_only。
5. **补丁**：`_SAMPLE_SPECIFIC_BOUNDARY_PATTERNS` 置空（原值见本预算文件与 git 历史）；`_DOMAIN_BOUNDARY_CUES` **未**清退，`_GENERAL_BOUNDARY_CUES` / 否定词表**未**动。

Stage 1：`--round lexicon-retirement-baseline`，唯一轮次，上限 43 次，`holdout = 0`。

### 8.1 Stage 1 结果（已执行）

- 报告：`material-semantics-runs/report-e54423a80d6df2eeefe40b34ddabd2040e3f298e48aeaa368c2393274dd46ac7.json`
  - `report` sha256 `d3651f339a84cfced6c134033ade36229ce67bd51a782e3cc994d53ea332a433`
  - `budget_sha256` `57b3883e252af9452cb0d19dd92b19263b825cc266d4d2a22d040178ba25de73`
- 实际 `model_calls = 43`（用满，无追加）；usage prompt 120825 / completion 102935 tokens。
- runner 自评 `business_acceptance = false`。

逐类对 `r2-non-regression-policy-v1.json` 的 floor 比较：

| 样本 | item 类 7 项 floor | 违反项 |
|---|---|---|
| dev-company-report | 全部 OK | `partial` 1（限 0）、`complete=false`（要求 true） |
| dev-industry-qa-report | 全部 OK | `partial` 1（限 0）、`complete=false`（要求 true） |
| dev-personal-trade-review | 全部 OK | `partial` 1（限 0）、`complete=false`（要求 true） |
| dev-expert-call-copper-foil | item 4 项 OK | `source_relation_recall 0.0 < 0.25`、`source_relation_precision 0.0 < 1.0`、`partial` 4（限 1） |

**判定：按预注册判据 Stage 1 未通过（`business_acceptance = false`）。**

### 8.2 归因：违反项不可归于词表清退

1. **关系类 floor 结构性不可达**：本预算 `relation_mode = "deferred"` ⇒ 预测关系恒为 0；而关系 floor 是按**抽取了关系**的基线标定的（旧基线铜箔 `source_relation_recall = 0.25`）。属**预算缺陷**，非清退证据。
2. **`partial` 出现在全部四个样本**，含**清退零影响**的行业问答样本（其槽位仅 56→55，一处变化）⇒ `partial` 非清退所致，而与本预算的**批次容量**（16 槽/次）有关；旧基线为 1 槽/次、包状态全为 `completed`。
3. **item 类指标相对旧冻结基线是上升的**（aggregate `item_recall` 0.833 → 0.958、`attribution` 0.333 → 0.917），无下降项。
4. **缺同代码对照组**：本轮只有"清退后"单臂，对照的是旧 extractor 的冻结报告 ⇒ 混入代码漂移，**既不能证明也不能证伪清退导致退化**。

### 8.3 本预算的两处预注册缺陷（实施方自查）

- **D-a 判据内部矛盾**：退出判据含关系类 floor，却把关系阶段 `deferred`，该 floor 必然不可达。
- **D-b 无法归因**：缺同代码基线（control arm），对照物是旧基线 ⇒ 归因不可能。

### 8.4 处置

- 按 §3/§4 的停止与回滚条款：**回滚清退补丁**——`_SAMPLE_SPECIFIC_BOUNDARY_PATTERNS` 已恢复为 4 条原值（回滚后 `current` 槽位回到 76/56/15/496，146 项回归通过）。
- **保留**组合式安全修复（`"|".join(...)`）：该修复独立于清退，已验证为行为等价（探针自检 + 冻结回归）。
- **不追加轮次、不重试、不访问 holdout、不入库**。
- 预注册的 v8 预算文件**不得事后修改**；本执行记录只写在方案中。
- 后续若要重做，必须是**重新冻结**的新预算：修掉 D-a（关系阶段要么同轮跑、要么判据明确排除关系类）、补 D-b（同代码 control + treatment 两臂）。

### 8.5 待办（backlog，不回流本次）

1. 既有事实：当前词表切分过碎，公司研报 5 条金标引文有 4 条跨槽（严格包含口径）。
2. 批次容量与 `partial` 的关系需要单独立项量化（1/4/8/16 槽每批的终态完整率）。
3. `_SEMANTIC_SIGNAL_PATTERNS["qualitative"]` 的通用/领域两分（选项 B）。

### 8.6 v8 判定更正（按 §3 口径规则）

v8 的 `business_acceptance = false` 依然成立（在 v8 自己的判据下确实未通过），但两项"违反"必须更正归类：

| v8 记为 | 实际归类 | 依据 |
|---|---|---|
| 铜箔 `source_relation_recall 0.0 < 0.25`、`source_relation_precision 0.0 < 1.0` | **`not_measured`，不计入判据** | `relation_mode=deferred` 未产生任何关系预测；floor 是按"抽了关系"的基线标的 |
| 四样本 `partial` / `complete=false`（含 `relations_not_processed`） | **运行器缺陷**，非实验结论 | 运行器只设 `extract_relations=False` 而未设 `relations_required=False`；管线本就有 `not_requested_for_items_role` 路径 |

更正后 v8 唯一可用结论：**item 类指标上四个样本均不低于冻结 floor**（aggregate `item_recall` 0.958、
`attribution` 0.917，相对旧基线 0.833/0.333 上升）。对清退本身：**既未证明有害、也未证明无害**
（单臂无对照，不可归因）。

## 9. 后续（v9，2026-10-09）

本次修复的两处确定性改动：

1. **判据一致性**：§3 新增口径规则；`r2-lexicon-retirement-development-budget-v9.json` 的
   `stage1_gate` 明确 `in_scope = item`、`excluded = relation: not_measured`，
   并声明 `relations_not_processed_counts_as_incomplete = false`。
2. **"有意 defer 不算失败"**：运行器补 `relations_required = (relation_mode != "deferred")`；
   常驻回归 `tests/test_corpus_material_semantics.py::test_deferred_relation_stage_is_not_recorded_as_an_omission`。
3. **`claim`/`summary` 软信号化**（根因修复）：完成判定只用 `_HARD_SIGNAL_TYPES`；`claim`
   （`_slot_signals` 的兜底标签）与 `summary` 缺失只记录 `missing_signal:*`，不再把槽位打成 `partial`，
   从而不再惩罚模型对署名/邮箱/清单等非命题内容给出的合法 `other`。
   `MATERIAL_EXTRACTOR_VERSION` 推进为 `material-semantics-23`，并把 `-22` 登记进兼容表
   （`drops_absent_relation_identity=False`），保证既有产物仍可读回。
   常驻回归 `...::test_soft_signal_labels_do_not_fail_a_slot_the_model_declines`。

v9 计划核对：`--plan-only` → `planned_calls_upper_bound = 43`（与冻结值一致）。

**v9 仍未纳入同代码 control 臂**（`known_gap` 已写进预算）：在 v9 上仍只能判"是否低于 floor"，
不能把结果归因于清退。

## 10. 签认栏

| 角色 | 姓名 | 结论（同意/驳回/附条件） | 日期 | 备注 |
|---|---|---|---|---|
| 实施方 | | | | 只能提交，不得自宣 |
| 独立复核 | | | | |
| U（具名） | | | | 放行的唯一权威 |

> 未具名签认前，本文件与 v8 预算**不得**被当作已冻结或已授权执行。
