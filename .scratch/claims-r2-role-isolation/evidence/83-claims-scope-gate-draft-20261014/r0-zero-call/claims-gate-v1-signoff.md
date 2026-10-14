# Claims 门 v1 草案 · 签认件

状态：草稿，**未签认**。`status = draft_pending_human_signature`，`reviewer/signed_on` 留空。

本草案只建立 claims 角色的度量基准，不改变任何冻结金标、签认裁定、items 门 v3 与契约 v4.3 的字节。

## 结论（请签认人勾选）

- [ ] 认可 claims 门 v1，并按下表阈值作为 claims 唯一度量基准（若改动请在右侧改写）：

| 判据 | 当前提案值 | 改写 |
|---|---|---|
| target_recall_overall_min | 0.85 | |
| target_recall_per_source_min | 0.80 | |
| candidate_precision_min | 0.80 | |
| unresolved_candidates_max | 0 | |
| accepted_records_total_min | 见 OPEN-A | |
| accepted_records_per_source_min | 见 OPEN-A | |
| 哨兵清单 | 见 claims-gate-v1.proposed.json `sentinels.proposed_ids` | |

### 待裁项

- OPEN-A accepted 总数/分源下限：a 平移 items 的 40/20 ｜ b 按 20 条目标缩放 17/8 ｜ c 不 gating 只诊断
- OPEN-B 与 items/relations 金标更接近的候选是否计入 claims 分母（out_of_scope 是否合法）
- OPEN-C 契约 11 个 claims 必需字段中 4 个无载体：补载体 ｜ 修订契约
- OPEN-D compare/calculate 是否仍受 `evidence_pipeline.py:404` 的「零 reason」全或无规则约束

## 签名

 reviewer:     adjudicator:     signed_on: 