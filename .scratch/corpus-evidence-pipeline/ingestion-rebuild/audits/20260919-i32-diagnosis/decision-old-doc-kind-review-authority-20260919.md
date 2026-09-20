# 决定：old_doc_kind_review_export 权威版本（U 已确认）

- 裁决：**确认以 `data/corpus/.audit/c1_full84_doc_kind_review_20260912.csv`（sha256 `d69bbb1d49081ab8c27f10ad3dda141f099411b39598f27fa95be56c2d2ac396`）为旧人工审核导出的权威版本**（U，2026-09-19）
- 即：冻结该文件身份与哈希，**不再**扩到 `.audit` 88 个工件
- 记录：`decision-old-doc-kind-review-authority-20260919.json`
- 去向：随 I3-2 冻结 r27 一并绑定

## 绑定

| 字段 | 值 |
|---|---|
| category | `old_doc_kind_review_export` |
| asset | `data/corpus/.audit/c1_full84_doc_kind_review_20260912.csv` |
| sha256 | `d69bbb1d49081ab8c27f10ad3dda141f099411b39598f27fa95be56c2d2ac396` |
| 现况一致 | `sha256_matches_current=True` |
| selector | CSV 行（文档级 doc_kind 覆写候选） |
| 验证阶段 | I3-2 冻结身份；无需重跑 |
| 重跑契约 | 不适用（人工审核导出，非可跑基线） |

## 语义备注

- 该 CSV 是旧人工审核 doc_kind 校正**建议**导出（40 行，industry→company 14、→macro 3），`review_decision` 全部为空——属建议继承，**不是**人工终态裁决。
- 本次确认冻结的是**该导出的权威版本**（文件身份 + 哈希），不改变其内容"建议而非裁决"的语义。
- 该决定解除 `baseline-case-manifest` 中 `old_doc_kind_review_export` 的 `blocked_needs_user` 阻塞项。