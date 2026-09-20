# I3-2 Step A—C 执行记录（2026-09-19，r28）

> 本文件是**执行记录**（未入 r28 绑定，避免改动已冻结字节）。判据与残留项以本文件 + `i0c-r28.json` 为准。

## 1. 三门结果（本次实测）

| 门 | 命令 | 结果 |
|---|---|---|
| 冻结链 | `freezes/validate_i0c_freeze.py` | **exit 0**（消息含 `r28 I3-2 derived scoring input + baseline asset binding + legacy anchor mapping verified`） |
| 阶段完成门 | `freezes/validate_i3_2_completion.py` | **exit 0**，`i3_2_complete=true`（6/6 pass） |
| 回归 | 审批契约 + 评分器 + I3-0 复核探针 | **88 passed** |

完成门 6 项判据：上游审批有效／正式评分输入派生件一致／P2 与冻结物一致／旧基线身份·范围闭环（含"无未冻结指针"）／唯一初始实验 manifest／全部必要资产哈希入链——**全部 pass**。

## 2. Step A（派生接线与唯一化）

- `i3-2/query-gold-scoring-v1.jsonl`（`1b018ceb…`）+ `i3-2/scoring-input-manifest.json`（status `frozen_r28`）+
  `i3s2_scoring_input.py`（唯一读入口 `load_scoring_input`，6 条变异反例各自失败）；**审批原件未改**（门仍 ready=true，20 warning 保留）。
- P4 唯一化：`components.query_gold.scoring_input_path`（唯一评分输入）+ `unique=true`，正式 gold 降为 lineage；
  新增 `components.execution`（命令／运行时显式 policy／环境／初始参数／未实现入口登记 2 项）。
- `formula_7` 输入指标按 `plugins/corpus/derivation.py` 逐条登记（7/7），gap 由 `needs_definition` → `confirmed`。

## 3. Step B（旧基线资产入链与映射）

- **引用资产入链 14 项**：`golden.py`、`derivation.py`、`pilot_manifest.json`、机器记录、三份报告、`spec.md`、
  `prose_holdout_manifest.json`、doc_kind CSV、`verify_claims_entry.py`、`i0a5-doclist`、`i0a4-candidates-v3`、
  `baseline-bindings.json`（原来 13/14 未入链 → 现 0 未入链）。plugins 仅作**引用资产**（`golden.py`、`derivation.py`），不改实现。
- **19 题旧锚点映射**（`legacy-anchor-mapping.json`）：`(title_contains, doc_prefix)` → `i0a5-doclist` 的 `doc_id`
  = 新 source 身份；**19/19 唯一命中**、22/22 `source_path` 在磁盘、其中 **5 个 doc_id 与已标注 source-gold 同源**
  （`174b6462`／`6f14cc14`／`793b3967`／`dddc7cd0`／`f8e31696`）；O6 因来源留出排除。
- 澄清：`doc_id` 后缀是**内容哈希**，与 `data/corpus` 文件名后缀不同源；校验用 `source_path` + title。

## 4. 归档（r27 被覆盖字节）

`before-r28/` 保存 5 份：`baseline-case-manifest.json/.md`、`freezes/validate_i0c_freeze.py`、
`docs/plan` 两份台账；归档哈希**与 r27 绑定值逐一相符**（脚本内 `matches_r27_binding=true`），
现随 r28 的 `i3_2_archive` 入链。

## 5. 残留人工复核项（**完成门绿灯不等于业务/语义通过**）

1. **19 题映射 `confirmed=false`**：首轮确定性结果需人工复核（属 Step 5 签认范围）；
2. **20 条人工同义映射 warning** + **`macro-004` 机器 `blocked` 覆盖**：语义审计风险，建议抽样审计计划；
3. **`prose_holdout_manifest.json`（天风 `5520fab6`）不在 `guards/i3.json` 的 `forbidden_roots`** →
   隔离能否强制待核（本轮**未擅自改守卫**；如需纳入应作为独立守卫变更）；
4. **I3-5 真实非回归 / I3-1 三类 E2E / I3-5·I3-7 真实答案语义**：`not_run`，需 PG/模型与预算授权；
5. **M5 F3**（`validate_i1_freeze.py` 对工作区 13 项失配）仍单列未修。
