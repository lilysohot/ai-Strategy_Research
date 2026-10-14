# Claims 角色参数化落地记录（机器生成）

日期 2026-10-14；零模型调用；改动文件 4 个，冻结件全部未变：True。

## 一、验证命令

| 命令 | 退出码 | 判定 |
|---|---|---|
| `ruff_check_changed`: uv run ruff check plugins/corpus/structured_scoring.py tools/check_claims_gate.py tests/test_claims_gate_invariants.py tests/test_claims_contract_role.py | 0 | ok |
| `focused_tests`: uv run pytest tests/test_claims_gate_invariants.py tests/test_claims_contract_role.py tests/test_corpus_contract_gate.py tests/test_corpus_structured_scoring.py tests/test_corpus_structured_scoring_adjudicated.py tests/test_corpus_adjudication_assembly.py -q | 0 | ok |
| `import_smoke_stage1`: uv run python tools/import_smoke.py --stage 1 | 0 | ok |
| `check_symbols`: uv run python tools/check_symbols.py | 0 | ok |
| `p03_binding_verifier`: uv run python .scratch/claims-r2-role-isolation/evidence/78-p03-binding-catchup-20261013/r0-zero-call/verify_p03_binding.py --no-write | 0 | ok |
| `claims_gate_checker`: uv run python tools/check_claims_gate.py | 0 | ok |

## 二、改动文件哈希

| 文件 | sha256 |
|---|---|
| `plugins/corpus/structured_scoring.py` | `571bad6fcd61a4ddc36fefd0dc380564441702d20dbac1b7eda16a0873695f86` |
| `tools/check_claims_gate.py` | `770bc51de0010e1a2003c0111533d6d307421c70ee4d7b24ad631a733a075875` |
| `tests/test_claims_gate_invariants.py` | `1e44799ba7710611f6340cab68290486f70acdbecf0340a691af3143ca6299cb` |
| `tests/test_claims_contract_role.py` | `8a760338e51fc805c28b5a73bfacc8e814fc96e1368f947053e2ca68185c80b0` |

## 三、冻结件未变（逐条哈希）

| 文件 | 期望 == 实测 |
|---|---|
| `evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json` | True |
| `evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json` | True |
| `evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json` | True |
| `evidence/17-structured-extraction-convergence-closure-20261009/p1r5-claims-adjudication-v2/candidate-adjudications.signed.json` | True |
| `evidence/83-claims-scope-gate-draft-20261014/r0-zero-call/claims-gate-v1.proposed.json` | True |
| `evidence/84-claims-gate-v2-draft-20261014/r0-zero-call/claims-gate-v2.proposed.json` | True |

## 四、契约 v4.4 草案

- 路径：`evidence/86-claims-contract-v44-draft-20261014/r0-zero-call/scoring-contract-v4.4.proposed.json`（`79e8651d12d9…`，status=`draft_pending_human_signature`）
- 删除叶子：无；计划外改动：无；六项阈值逐字不变：True

## 五、85 号审核后的状态变化（回扫）

| 组件 | 审核时 | 现在 | 说明 |
|---|---|---|---|
| F7-一致性校验器 + 复算回归 | landed_now | **landed_now** | 无变化（85 号已落地） |
| F8-契约读取器按角色参数化 | needs_human_decision | **landed_now** | 本轮落地：loader 支持 role 参数、role_sections 分支与 schema v4.4 白名单；items 行为逐字不变（P03 绑定校验 8/0、既有测试全过）；claims 分支在 v4.3 上 fail-closed |
| C3-claims 读路径取值 | needs_human_decision | **needs_human_decision** | 仍未实施：86 号只给 carrier 提案（四字段 0 载体），生效须签认 |
| C1/C2/C4/C5/C6 | needs_human_decision | **needs_human_decision** | 86 号写为 agent 提案并附实测值；未签认前不改任何默认行为 |
| 门侧（claims gate） | 84 号草案（D4 行不完整） | **84 号字节未动；D4 行补全并入『契约签认后生成 claims 门 v3』这一步** | 门必须与已签契约互钉，故门版本在契约签认后再出，避免草案互钉成环 |
| F9-生产侧接缝 | not_executable_this_round | **not_executable_this_round** | 候选池仍冻结；要体现效果须 F6 重跑授权 |

## 六、仍未完成

- C1/C2/C3/C4/C5/C6 六格签认（86 号 claims-contract-v4.4-signoff.md）
- 契约签认后：生成 claims 门 v3（含 84 号 D4 行补全）+ 与契约互钉
- C2 落地：RoleMetrics.precision 计入 duplicate_fp（改默认行为，须具名）
- C3 落地：claims 读路径 + 装配器 ROLE_CARRIERS[claims]
- C4 落地：用途分级（拆 reason 轴）
- F6：是否授权重跑产出新池（唯一能让目标线可达）

## 七、未覆盖范围

- 未复核 .scratch/evidence/01–82 的全部内容
- 未归因 full_suite 中 13 项既有失败的根因（只声明非本次引入）
- 未执行任何模型调用、发布、query/delivery/context_use、M_main 消费

## 八、全量测试（本次手动执行，非本脚本）

- 命令：`uv run pytest tests -q`；结果：13 failed, 3194 passed, 238 skipped；归因：environment/pre-existing
- 依据：失败文件均不导入被改模块（structured_scoring / adjudication_assembly / ContractGateRequirements）；失败形态为 TimeoutError、wall_deadline、reader-pdf 环境断言
- 未归因声明：上述断言失败未逐条归因到既有缺陷；本记录只声明它们不由本次改动引入

