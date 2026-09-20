# P4 试验初始版本清单（草稿，未落正式）

- 生成：2026-09-19T18:08:50+08:00；状态：**frozen_r28**
- 用途：冻结『试验初始版本』：I3-1（E2E）与后续对照都以本清单为准，不得凭记忆或事后补录

## 组成（每项带哈希）

| 组成 | 路径 | sha256 |
|---|---|---|
| 评分器 | `plugins/corpus/scoring.py` | `bf9c8b80d7a9…` |
| **评分输入（唯一）** | `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl` | `1b018ceb081f…` |
| 评分输入清单 | `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/scoring-input-manifest.json` | `d0d76862eff7…` |
| query-gold-frozen（仅 lineage） | `.scratch/corpus-evidence-pipeline/ingestion-rebuild/query-gold-frozen.jsonl` | `6f6c5a25d55b…` |
| 批准投影 | `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-approved.json` | `5b89d981e871…` |
| 裁决件 | `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-decisions.json` | `09ed8429e01e…` |
| source-gold | `.scratch/corpus-evidence-pipeline/ingestion-rebuild/source-gold-frozen.jsonl` | `37662c77a76c…` |
| 阈值确认单 | `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remaining-inventory/p2/policy-and-lists-confirmation.json` | `46ef2261cd5b…` |
| 旧基线索引/用例级 | `.scratch/corpus-evidence-pipeline/ingestion-rebuild/baseline-bindings.json` ／ `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i0a4-candidates-v3-20260915.json` | `a397aea92e77…` ／ `016c87e506aa…` |

## 冻结口径（取自 P2）

- `top_k` = `5`
- `min_rate` = `19/20`
- `require_critical_all_pass` = `True`
- `max_false_positives` = `0`
- `max_fabricated_citations` = `0`
- 关键题 28 题（非关键：industry-006、macro-004）
- 负例 6 题（全 critical）

## 声明

- 零模型：不调用任何模型客户端（i3 守卫 blocked_modules + poisoned_env）
- 零数据库写入：I3 阶段守卫 read_roots 为空、无网络；旧基线**不重跑**（其入口非零写 + 原库 5432，需 I3-5 单独授权）
- 未读候选业务结果：本清单只绑定预期/金标/配置字节，不含任何检索或答案输出
- 留出隔离：3 份留出件仍在守卫 forbidden_roots 内（i3.json）

## 生效前必须完成

- P1 材料化落正式（新 query-gold 版本）+ U 签认
- P3 建议的旧基线重绑方式（内联或双哈希强引用）确认
- r27 冻结：绑定上述全部 + P2/P3/P4 产物 + 台账回填
- I3-1（E2E）另需 PG/模型与预算授权，且需 `i3-e2e.json` 阶段守卫（i3.json 注记）
