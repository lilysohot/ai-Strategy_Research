# 04 · Claims、R2 items 与 relations 的独立角色入口

Status: ready-for-human
Execution: 已验收
Type: task
Plan: W2；R2-S2
Blocked by: 无本地任务依赖（02、03 已验收）
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

用小 Interface 组合既有抽取能力，隔离三类角色和调用，使 Claims/items 可独立执行、relations 可消费固定 items 运行版本。

## 前置与外部门

02/03 已验收；01 的协议支持矩阵已冻结。测试只用 fake/replay；不以现有 extract_relations=False 在单分支生效来冒充所有协议已支持拆分。

## 范围与预期文件

- plugins/corpus/evidence_pipeline.py、material_semantics.py、service.py 及
  `plugins/corpus/structured/roles.py` facade；输出用 `corpus-role-artifact-v1` 包裹既有业务 Schema。
- tests/test_corpus_structured_roles.py；保留旧 MaterialRun/EvidenceRun 兼容所需回归。
- 确定性路由与角色范围、表格规则分支、独立 items/relations 入口和角色输出的覆盖封装。
- 关系候选生成规则为确定性、可版本化，不先新增一个通用抽取/分类 LLM；首轮协议精确限定为
  `claims-deterministic-v1`、`claims-json-v2`、`material-atomic-jsonl-v4`、
  `material-relations-jsonl-v1`，其他模式调用前拒绝。

## 验收条件

- [x] 纯定性、指标数值、混合条件及类型不明均有明确路由理由；漏路由可在评分中计 FN。
- [x] Claims table 不产生模型请求，正文只调用 Claims；items-only 在所有支持模式下零 relations 请求。
- [x] 不支持的模式在调用前拒绝，不静默联合抽取；未知/延期不被标成无内容。
- [x] relations 只接收固定且合格的 R2 item IDs 与同源证据，不读“最新 items”，不重抽 items/Claims。
- [x] 任一条目角色失败不阻断另一角色独立合格结果；关系失败保留合格 items 并显式未覆盖。
- [x] 角色都保留影响自身含义的条件/否定/归属；R2 value 不直接转换为获准 calculate 的 Claim。
- [x] 本票提供调用意图/结果接缝；所有实际执行统一交 05 预留和计账，角色内部不能绕过预算重试。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_roles.py tests/test_corpus_structured_relation_guards.py tests/test_corpus_evidence_pipeline.py tests/test_corpus_material_semantics.py tests/test_corpus_structured_snapshot.py tests/test_corpus_structured_config.py tests/test_corpus_structured_contracts.py tests/test_corpus_semantic_gates.py tests/test_corpus_context_integrity.py tests/test_corpus_llm_diagnostics.py -q --tb=short
uv run ruff check plugins/corpus tests/test_corpus_structured_roles.py tests/test_corpus_structured_relation_guards.py
```

按每个受支持协议断言请求角色、次数、输入版本和依赖，不只检查最终条目数。

## 非目标

不新增第三套业务断言 Schema，不做联合单次输出替代双角色，不用 Claims fact_id 当 R2 关系端点。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
- 2026-10-02：用户授权核查达标后闭环 02/03；两票本地验收通过，依赖解除。本票转为
  ready-for-agent，Execution 仍为未开始；下一步按既定范围实现独立角色入口和 fake/replay 测试。
- 2026-10-02：已按用户指令开始执行；任务认领，进入实现与本地 fake/replay 验收阶段。
- 2026-10-03：实现完成并转 `ready-for-human` / 待验收。新增
  `plugins/corpus/structured/roles.py` facade（SHA-256
  `2bb9a07e9261dd8f9aa4565e8c44a2f482d1293077a81e89069c99e41bf04cab`）及
  `tests/test_corpus_structured_roles.py`（SHA-256
  `bb5c6d1806694d51fdd32f1281ac7ba0b0e453d19b496029a3e40dd302af92eb`）；复用
  EvidenceRun/EvidenceFact 与 MaterialRun/MaterialUnderstanding，以
  `corpus-role-artifact-v1` 封装。Claims table/prose、R2 items、R2 relations 四协议均在入口
  allowlist；关系候选 `material-relation-candidates-v1` 只接收显式 items run、
  `material-items-validation-v1`、固定合格端点和同源快照。items-only 不再因未请求 relations
  被误标不完整，旧入口默认语义保持兼容；无内部重试，真实 attempt 授权/预留继续交 05。
- 2026-10-03：验收命令（均从仓库根目录、零真实模型/零生产库）：任务卡 pytest 命令退出 0，
  **67 passed**；任务卡 Ruff 命令退出 0，`All checks passed!`；structured contracts/config/
  snapshot/roles 扩展回归退出 0，**124 passed**；目标 Pyright（四个改动模块）退出 0，
  **0 errors**；`tools/check_symbols.py` 退出 0，**0 missing across 475 files**；
  `tools/import_smoke.py --stage 1` 退出 0，**376/376 modules imported**；`git diff --check`
  退出 0。全仓 `uv run pyright` 另有 5 个既有/范围外错误（`deploy/huggingface/app.py` 1、
  `scripts/run_retention.py` 3、`server/orchestrator.py` 1），本票改动模块无错误。未运行真实模型
  preflight；真实模型调用与生产数据库访问均为 0。
- 2026-10-03：用户要求重新核查、补遗漏并在达标后闭环。按规范与规格两个轴复核发现前次
  勾选不足以证明验收：空 Claims 范围会扩大、部分 slots 输出可能被误接受、关系端点和
  依赖证据资格检查不足、请求接缝缺少完整回执，以及条件上下文与严格协议边界覆盖不足。
  以上均已修复；新增对抗测试与旧入口回归，不以原有通过数替代本次复核。
- 2026-10-03：最终修复包括：空/子集范围精确绑定及显式遗漏；严格 JSON/JSONL、截断与
  joint-output 拒绝、item/coverage 必填槽位 ID；同源原文区间、槽位唯一资格、不可变上游
  工件/版本和依赖上下文校验；按原文顺序生成稳定候选，禁止共现链式推导；完整条件、否定、
  归属进入请求/证据，Claims 缺失限定信息时禁止 calculate/compare；空候选关系结果绑定
  candidate set；新增 `RoleRequest`/`RoleCallResult`/dispatcher 接缝并保留未知、预算拒绝、
  取消和延期回执，缺省 error_type 不再丢失结果，无内部重试。Material extractor 升为 v14，
  历史 v13 run 的读取和哈希校验有明确回归。
- 2026-10-03：最终验收命令从仓库根目录运行（WSL 使用
  `/home/administrator/miniconda3/bin/uv`），均退出 0：
  - 本票上列 pytest：**269 passed**（含 33 项角色测试、30 项关系护栏测试）。
  - 本票上列 Ruff：`All checks passed!`。
  - `uv run ruff format --check plugins/corpus/evidence_pipeline.py plugins/corpus/material_semantics.py plugins/corpus/service.py plugins/corpus/structured/roles.py tests/test_corpus_structured_roles.py tests/test_corpus_structured_relation_guards.py`：6 files already formatted。
  - `uv run pyright plugins/corpus/evidence_pipeline.py plugins/corpus/material_semantics.py plugins/corpus/service.py plugins/corpus/structured/roles.py`：0 errors。
  - `uv run python tools/import_smoke.py --stage 1`：376/376；`--stage 2`：425/425。
  - `uv run python tools/check_symbols.py`：475 files、0 missing；`git diff --check`：通过。
  - 规范复核重放预算拒绝原始反例，确认阻断解除；规格复核确认资格、上下文和严格协议
    补漏完成。真实模型调用、生产库访问均为 0；未读取真实 .env，未运行付费 preflight。
- 2026-10-03：最终交付 SHA-256（替代上方首次交付指纹）：
  - `plugins/corpus/structured/roles.py`：`4d89a83f73cf499f2815d4aea9260884af1deceec400546b9a6be9e6b96e0437`
  - `plugins/corpus/evidence_pipeline.py`：`6a37b8d8f8dd836e1c1c56300f5d4bc5c53bc5a0a190bf9b2f48ec90dd49410c`
  - `plugins/corpus/material_semantics.py`：`96e92e9164a8d1b4103e40b6c2c55539afa5f6ef8f39ce6bc469fb7c1a34b391`
  - `plugins/corpus/service.py`：`2e7d87b78d0e08413f7b83b89d57b47b6255727dc4bf6fe426cbfbb28e864f2a`
  - `tests/test_corpus_structured_roles.py`：`48cbd16e129d413afde9f7c737e61efbd105961d2b323e7b7dfcf273eb3f1ad4`
  - `tests/test_corpus_structured_relation_guards.py`：`0fd925b3d395cd656854a81cf5282aa7cff075f693b12919e34d07bd705d0d27`
- 2026-10-03：按用户授权，本票本地验收闭环，Execution 改为已验收，沿用 02/03 的
  `ready-for-human` 归档惯例（不新增 triage 标签）。本票验收条件无未通过项；解除 05 的
  本地前置依赖，但不执行 05，不将角色入口视为持久预算账已实现，不推进主计划外部门。
  全仓 Pyright 上次发现的 5 项范围外错误仍单列保留，本次仅声称改动模块检查通过。
- 2026-10-08：角色入口沿用 02 的共享 fail-closed 表格门：未经显式完整性核验的 PDF reader
  表格仍可在角色工件中审计，但以 `partial / table_untrusted_or_incomplete` 进入，Claims table
  确定性分支和 R2 items 均为零记录、零模型调用；依赖表格的 prose 也不得通过 context 绕过该门。
  共享角色验收命令重跑 **279 passed**；扩展套件的唯一 publication condition 映射失败与本门无关，
  详情记于 02，不将范围外失败伪装成全绿。
- 2026-10-08：该范围外红项已继续诊断并闭合：无条件词来源上的伪 `condition` 会在角色校验阶段
  规范化为 `claim`，不是合法的跨角色 condition 冲突；publication 应比较规范化后的最终记录。
  未放宽显式条件识别，也未修改冲突比较实现。修复后全部 structured 回归 **352 passed**。
