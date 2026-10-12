# 路线 a/b 同量纲成本-收益表

- 预注册：`preregistered-ab-inputs.json` `sha256:97979128647373bfe5225fbb794f6728e5430ef0f23e0482425053439b6271b8`
- 单位：成本 = 模型调用 / 人工裁定条数 / 冻结修订 / 门次 / 零调用代码改动；收益 = 可匹配金标条数

## 实测输入（全部取自既有产物）

| 量 | 值 |
|---|---|
| 金标分母 | 48 |
| 归一化后字段逐字对齐 | 7 |
| 逐字证据可达（evidence/35） | 39 |
| 人工裁定区间（上−下） | **32** |
| 覆盖槽位内无候选 | 9（其中丢包 7） |
| items 零载体必需字段 | ['source_stance'] |
| relations 结构性不可评分字段 | ['from_gold_record_id', 'to_gold_record_id'] |
| gate-32 expected_attempts | {'industrial-fulian-md': 10, 'optical-module-docx': 14} |
| gate-32 automatic_retries | 0 |
| 门 28 unresolved_candidates_max | 0 |
| 契约 matching.mode | `human_adjudicated_semantic_equivalence_then_one_to_one_mapping` |

## 工作项 × 成本（归属：共同 / route a 边际 / route b 边际 / 独立）

| ID | 事 | 归属 | 模型调用 | 人工裁定 | 冻结修订 | 门次 | 代码改动 | 依据 |
|---|---|---|---|---|---|---|---|---|
| C1 | 口径归一化条款（契约 v4 修订） | 共同 | 0 | 0 | 1 | 0 | 0 | issue-34 §5.9 口径差实测（perspective 0→32 等）；§7-11 |
| C2 | Stage 2 阻塞条款：候选→契约字段由谁负责、凭据是什么 | 共同 | 0 | 0 | 0 | 0 | 0 | 并入 C1 同一份 v4（issue-34 §7 注：1 与 3 应合并为一轮） |
| C3 | 评分器读契约 + 阈值单源（对齐门 28） | 共同 | 0 | 0 | 1 | 0 | 1 | 全仓零代码读 scoring-contract.json；阈值硬编码 structured_scoring.py:332 |
| C4 | 重建门 33 工作台（补 speaker_ref 与 layer B 字段） | 共同 | 0 | 0 | 0 | 0 | 1 | evidence/38 已完成（§5.10），成本已付 |
| C5 | 人工裁定全部候选（unresolved_candidates_max = 0 的硬要求） | 共同 | 0 | 222 | 0 | 0 | 0 | 门 33 草案：accepted 19 + pending 203 = 222；契约 matching.mode 要求人 |
| C6 | 门 33 Stage 3 严格评分 | 共同 | 0 | 0 | 0 | 1 | 0 | issue-33 §3 三步流程 |
| A1 | 实现正式读路径（layer A + layer B + text → 契约字段） | a 边际 | 0 | 0 | 1 | 0 | 1 | 工作台 v2 已给出 contract_view 雏形（evidence/38）；条款并入 v4 |
| A2 | 口径映射的回归测试（防映射随数据/模型漂移） | a 边际 | 0 | 0 | 0 | 0 | 1 | 映射是事后口径，非源头口径（issue-34 §5.7 读路径须与记录 ID 无关） |
| B1 | 把口径写进协议文本（material_semantics.py 提示词） | b 边际 | 0 | 0 | 0 | 0 | 1 | gate-32 freeze-manifest 绑定 material_semantics_module = 1305d |
| B2 | 重抽：单臂 24 包（md 10 + docx 14）；含对照臂则 48 | b 边际 | 24 | 0 | 0 | 0 | 0 | gate-32 expected_attempts = {md:10, docx:14}（实测字段）；若需 contro |
| B3 | 推进 extractor_version 并登记 _HISTORICAL_RUN_PAYLOAD_SHAPES | b 边际 | 0 | 0 | 0 | 0 | 1 | 环境硬约定：推进 version 不登记旧 current 会导致旧产物读不回（现 current 产物为 materi |
| B4 | 新冻结 + 新门（gate-32 冻结作废） | b 边际 | 0 | 0 | 1 | 1 | 0 | 见 freeze-impact.json |
| I1 | 补跑被传输事件丢掉的 1 个包（md 第 8 包，7 条 critical） | 独立 | 1 | 0 | 0 | 1 | 0 | issue-34 §5.1/§6；gate-32 automatic_retries = 0（损失根因）⇒ 须先定重试/ |
| I2 | 裁定 B-1 两条（NT-I06 / NT-I41）的性质 | 独立 | 0 | 1 | 0 | 0 | 0 | issue-34 §5.8 backlog B-1 |

## 分维度合计与共同项占比

| 维度 | 共同项 | a 边际 | b 边际 | 独立 | 共同项 ≥ 两边际之和 |
|---|---|---|---|---|---|
| `model_calls` | 0 | 0 | 24 | 1 | False |
| `human_adjudication_records` | 222 | 0 | 0 | 1 | True |
| `freeze_revisions` | 2 | 1 | 1 | 0 | True |
| `gate_runs` | 1 | 0 | 1 | 1 | True |
| `zero_call_code_changes` | 2 | 2 | 2 | 0 | False |

## route a vs route b（仅边际项）

| 维度 | route a | route b |
|---|---|---|
| `model_calls` | 0 | 24 |
| `freeze_revisions` | 1 | 1 |
| `gate_runs` | 0 | 1 |
| `human_adjudication_records` | 222（在现候选集上） | 222（在**新**候选集上，不可复用现裁定） |

> route b 的收益（是否能减少 32 条人工裁定区间）未证；route a 的收益下界/上界见 benefit S1。

## 收益情形（三态：measured / bounded / unverified）

| 情形 | 内容 | 可匹配金标 | 状态 |
|---|---|---|---|
| S0 | 现状（不修任何项） | 0（实测） | measured |
| S1 | 共同项完成后（口径条款 + 评分器读契约 + 工作台 v2 + 人工裁定） | [7, 39] | bounded_by_measurement |
| S2 | S1 + 补跑丢失包（7 条 critical） | [7, 48] | unverified |
| S3 | S2 + route b 重抽 | [7, 48] | unverified |

## 伪二分假设（EC-AB3）

- 假设：共同项成本占主导 ⇒ 先做共同项优于先分叉（可能为伪二分）
- 成立的维度：['human_adjudication_records', 'freeze_revisions', 'gate_runs']
- 不成立的维度：['model_calls', 'zero_call_code_changes']
- 判定：在 ['human_adjudication_records', 'freeze_revisions', 'gate_runs'] 上成立：共同项 ≥ 两边际项之和。其中人工裁定维度由契约 matching.mode 决定——route a 与 route b 都必须付这一项，且 route b 在新的候选集上无法复用 route a 的裁定结果，故该维度上『先分叉』不省成本。在 ['model_calls', 'zero_call_code_changes'] 上不成立（边际项更大）：这两项正是路线分叉真正的差异所在，须由缺口 1（人工可裁定比例）与缺口 2（route b 收益）补齐后才能定。
- 状态：authored_from_measured

## 剩余缺口

- gap_1：32 条区间的人工可裁定比例 —— 需 xyl 分层抽样裁定（本批不代替）
- gap_2：route b 的抽取差可修复性 —— 需执行 route-b-experiment-protocol（需授权）
- gap_3：本批已关闭（同量纲表已产出）
- gap_4：本批已关闭（freeze-impact.json）
