# P12 / P13 记账提案（均需具名签认；**未就地改任何产物**）

- 本目录只出**提案**：`freeze-manifest.json`／`freeze-state.json`／`preregistered-gate.json` 字节不变。

## P12 金标冻结链契约绑定再绑定

- 记录值：`2eb24be7e74f9e6003ca623487…`（v2）
- 实际值：`sha256:c76ac13ec0a10907477…`（v4.1）
- 链：v2 (recorded) → v3 (signed) → v4 (OPEN-1=A/OPEN-2=C) → v4.1 (signed 2026-10-12)
- 8 条输入中漂移：**1** 条；其余稳定：7 条

| 输入 | 状态 |
|---|---|
| `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/gold-review-candidates.json` | match |
| `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/gold-review.md` | match |
| `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/scoring-contract.json` | drift |
| `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/validation-report.json` | match |
| `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/draft-manifest.json` | match |
| `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r1/source-prose-units.json` | match |
| `data/corpus/工业富联_投委会决策报告_20260829.md` | match |
| `data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx` | match |

- 建议落位：evidence/10-quality-gold-freeze-20261008-r2/rebinding-v4.1-<date>.json（新文件；`freeze-manifest.json` 与 `freeze-state.json` 字节不变）
- 需：具名签认（冻结链修订）
- 并行先行记录（针对 v2→v3，**不能沿用**）：`.scratch/claims-r2-role-isolation/evidence/41-items-chain-accounting-20261012/r3-signoff-apply/freeze-rebinding-record.json`

## P13 门 28 `metric_basis` 推进

- 门 28 现记：`non-table-selected-target-scoring-contract-v3`
- 建议改为：`non-table-selected-target-scoring-contract-v4.1`
- 循环引用：契约 v4.1 的 `threshold_source.effective` 取自门 28 `quality_requirements`；门 28 的 `metric_basis` 指向 `non-table-selected-target-scoring-contract-v3`（v3），不是 v4.1
- 后果：『权威源』的基准版本落后于引用它的契约 ⇒ 单一口径并未真正闭合，须同轮修。
- **第二处漂移**：门 28 `gold.scoring_contract_sha256` = `sha256:d9bc51f286a977ec923…`（v3），须与 `metric_basis` 同轮推进
- 先例：门 28 已有同类先例：`revision_history[1].changes` = 『gold.scoring_contract_sha256 由 v2 哈希 2eb24be7 再绑定至已签认 v3 哈希』+『quality_requirements.metric_basis 由 -v2 改为 -v3』。故本次推进不是新发明，而是沿用同一手续（新版本记录，不就地改）。
- 阈值逐字不变：逐字不变（0.85 / 0.80 / 0.80 / 40 / 20 / 0）
- 评分器仍硬编码 0.95/0.90（P03 未执行）：见 `threshold_single_source_effect`

## 顺序

1. P12 与 P13 可同一轮签认（都是记账，不改语义）。
2. 签认后：**P03 评分器读契约** 才有完整依据（契约 v4.1 + 门 28 推进记录）。
3. **P01/P02（装配器与匹配改造）不依赖本目录**，可并行开工。
