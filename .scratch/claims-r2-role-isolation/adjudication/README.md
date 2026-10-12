# Stage 2 裁定工作台 · 操作说明

- 工作表：`worksheet.json`（**222 条**，每条已是契约 11 字段形态，确定性字段已预填）
- 金标参照：`gold-reference.json`（48 条，匹配时对照用；**裁定人可以看金标**，禁止的是把金标抄进候选）
- 自检：`uv run python .scratch/claims-r2-role-isolation/adjudication/validate.py`
- 依据：已签契约 v4.2 `adjudication_clause`；装配器 `plugins/corpus/adjudication_assembly.py`

## 每一条怎么裁（5 步）

打开 `worksheet.json`，定位 `candidate_id`，看 `original_candidate.text` 与 `evidence.quote/locator`：

1. **判断这条候选说什么**，对照 `gold-reference.json` 的 48 条命题：
   - 能对上某条金标 ⇒ `"judgement": "matched"`，`"matched_gold_id": "NT-Ixx"`
   - 内容正确但不在 48 条目标内 ⇒ `"correct_extra"`
   - 说错了 ⇒ `"incorrect"`
   - 与已 matched 的另一条同义重复 ⇒ `"duplicate"`（只有第一条能 matched）
   - 明显不在裁定范围 ⇒ `"out_of_scope"`
2. **确认/填写 4 个人判字段**（`canonical_observed_fields` 内）：
   - `semantic_type`、`statement_role`：候选自带初值，**你确认或改**（读原文判断，不默认通过）
   - `source_stance`：现为 `"absent"`，**必须读原文**给 `reported`/`challenged` 等；不确定就留 absent 并在 reason 说明
   - `condition`：非条件记录留 `"absent"`；`statement_role == "condition"` 的记录必须判定 text 是否表达了该条件
3. **`reason` 必填**：一句话判据（为什么 matched / 为什么 incorrect）
4. **`evidence`**：已按候选自带引文预填，可改；必须保留逐字引文或定位
5. **`reviewer`** 已预填 `xyl`（契约 responsible_party），如实际裁定人不同请改

**不要碰**：`proposition`、`speech_role`、`perspective`、`polarity`、`speaker_ref`、`attribution`、`original_candidate`——这些是确定性载体/已排除项，装配器会重算并**拒绝任何不一致**。

## 三条硬纪律（契约条款，违反即被装配器拒绝）

1. **不得把金标内容抄进候选**（确定性字段不一致即报错——`carrier_mapping.forbidden`）
2. **每条必须有 evidence**（逐字引文或定位——`evidence_required`）
3. **`judgement` 只能是六值之一**；`unresolved` 会被门拒绝（`unresolved_max = 0`）——**真遇到定不了的，标 unresolved 并停下来找我升级**，不要猜

## 自检与完成

```bash
uv run python .scratch/claims-r2-role-isolation/adjudication/validate.py
```

输出：已填/未填、装配通过/被拒、逐条错误、按源 matched 分布。**`gate_ready: true` 即 222 条全部通过装配器校验**，届时告诉我，我立即装配 → 跑门 33 评分 → 出分。

## 已知边界

- 工作表**不含 Stage-1 建议**（契约 `suggestion_policy`：独立裁定必须隐藏建议，防污染）
- 203 条建议置信度为 low/none 的记录需要读原文；`source_slug` 在 `original_candidate.source_slug`（industrial-fulian-md / optical-module-docx）
- 遇到疑似「这条金标根本不该在这里」「两条金标重复」之类的问题，记在 reason 里标 unresolved 升级，不要自行改金标
