# t6 权威版本裁定（2026-09-21，U 确认）

决定：**整体采纳工作树当前字节为权威版本**，新建 `i0c-r42` 完成 t6 重绑，并另起新冻结修订重建
`scoring-input-manifest.json` 血缘（`lineage.scorer.sha256`=空白规约 `f61573d7`、`status`=`frozen`）。
机读记录：`decision-t6-authority-20260921.json`。

## 裁定清单

| 类别 | 资产 | sha256（当前权威） | 采纳于 |
|---|---|---|---|
| scorer（已冻结，沿用） | `plugins/corpus/scoring.py` | `f61573d7…` | r41 |
| reader-pdf-5 | `readers/base.py` | `338c9f08…` | r42 |
| reader-pdf-5 | `readers/pdf_reader.py` | `bc8d0691…` | r42 |
| I3-3 重塑 | `search_pg.py` | `04bc7d61…` | r42 |
| I3-3 重塑 | `chunk.py` | `b0c034ea…` | r42 |
| I3-3 重塑 | `clean.py`（含 S5） | `e169bb6e…` | r42 |
| I3-3 重塑 | `engine.py` | `3d7ec3f8…` | r42 |
| I3-3 重塑 | `repository_pg.py` | `3ae3d0f5…` | r42 |
| I3-3 重塑 | `contract.py` | `8c439630…` | r42 |
| 测试 | `test_corpus_preparation_chunk.py` | `50e8ea6c…` | r42 |
| 测试 | `test_corpus_preparation_clean.py`（含 S5） | `480094d4…` | r42 |
| 测试 | `test_corpus_preparation_readers.py` | `3c072e40…` | r42 |
| 回归脚本 | `rerun_or.py` | `a8215e4c…` | r42 |
| 文档 | `corpus-ingestion-rebuild-tasks.md` | `14006ef8…` | r42 |
| 血缘重建 | `scoring-input-manifest.json` | 重建后（r42 内钉） | r42 |
| 计划绑定 | `calibration-plan-v2.json` | 更新后（r42 内钉） | r42 |

## 依据

- **whitespace-norm scorer**：r41 已冻结 `f61573d7`，band 产品（spec §10.5 option A）建立其上。
- **reader-pdf-5**：i35–i41 全链已在其上运行（i35 8/8 built、i36 54→43、i37/i40/i41 全链证据）。
- **I3-3 重塑**：议题 A/B、band 产品、票 05 全部建立在当前工作树。

## 不做

- 不修改任何被绑字节的语义。
- 不采纳「还原旧字节」路径（会破坏全部下游成果）。

## 交付

- `i0c-r42` 绑定 15 条漂移（含重建后的 manifest/计划/验证器）
- 两个门全绿：`validate_i0c_freeze.py` exit=0、`validate_i3_2_completion.py` `i3_2_complete=true`
