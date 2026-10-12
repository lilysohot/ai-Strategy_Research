# 契约 v4.1 审阅件（合并草案）

> **草案，未签认**；签认前不生效。已签 v4 与 donor 草案字节均未改动。

- 基：已签 v4 `sha256:6806f1399e3bbf5ace41264598f6228998f706dd082f20d580d5303a48ab712d`
- 供方：并行草案 `sha256:b3f88649e9eca70cf21b95c466ea4a4950ef6a316aa521e2b42822c4eae7818f`（`proposed_pending_signoff`，**从未签认**）
- 结果：`status = draft_pending_human_signature`；只增不删（删项 0）

## 一、并入了什么

共新增 **22** 条叶子；其中 3 条是核心读路径条款：

| 核心条款 | 作用 |
|---|---|
| `read_path.carrier_mapping.rule` | 只允许确定性载体映射（候选 `text`→契约 `proposition`），**只改字段名**，不生成/改写/摘要语义文本 |
| `read_path.absent_required_fields.rule` | 缺字段记 `absent`，**不得因缺字段直接判不匹配**，也不得补造 |
| `read_path.equivalence_judgement.scorer_contract` | **评分器不得以身份相等为匹配前提**，只消费裁定完成的映射 |

完整清单见 `merge-reconciliation.json` 的 `added_leaf_paths`。

## 二、按已签结论落地的条目

| 路径 | 处置 | 理由 |
|---|---|---|
| `threshold_source.required_alignment` | resolve_by_signed_decision | donor 记为 PENDING_SIGNOFF，但该分叉已由 U 于 2026-10-12 签认（OPEN-1=A）；保留 pending 会与已签状态矛盾。 |
| `threshold_source.pending_signoff_detail` | rename_subtree | 该叶子描述分叉本身，仍有追溯价值；但名称含 pending，故改名为 decision_history 并更新说明，避免与已签状态冲突。 |

## 三、需要你确认的两处（可质疑项）

- threshold_source.decision_history：由 donor 的 pending_signoff_detail 改名而来，其 why_not_chosen 描述的是决策前的状态，已签 OPEN-1=A；请确认该历史条目保留与否。
- read_path.absent_required_fields.alignment_with_caliber_rules：由本脚本撰写，用于调和 donor「记 absent」与 base「移出匹配基」两种表述，属可质疑项。

- 冲突（基值保留、未覆盖）：0 条

## 四、签认栏（草案）

- 复核人：　xyl　　　日期：2026-10-12
- 结论：x 认可并签认 v4.1　☐ 退回修改
- 备注：

> 签认 v4.1 后：并行草案标 `superseded_by`；契约绑定再绑定（P12）以 v4.1 哈希为准；门 28 `metric_basis` 随之推进（P13）。
