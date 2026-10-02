# 04 · Claims、R2 items 与 relations 的独立角色入口

Status: ready-for-agent
Execution: 未开始
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

- [ ] 纯定性、指标数值、混合条件及类型不明均有明确路由理由；漏路由可在评分中计 FN。
- [ ] Claims table 不产生模型请求，正文只调用 Claims；items-only 在所有支持模式下零 relations 请求。
- [ ] 不支持的模式在调用前拒绝，不静默联合抽取；未知/延期不被标成无内容。
- [ ] relations 只接收固定且合格的 R2 item IDs 与同源证据，不读“最新 items”，不重抽 items/Claims。
- [ ] 任一条目角色失败不阻断另一角色独立合格结果；关系失败保留合格 items 并显式未覆盖。
- [ ] 角色都保留影响自身含义的条件/否定/归属；R2 value 不直接转换为获准 calculate 的 Claim。
- [ ] 本票提供调用意图/结果接缝；所有实际执行统一交 05 预留和计账，角色内部不能绕过预算重试。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_roles.py tests/test_corpus_evidence_pipeline.py tests/test_corpus_material_semantics.py -q
uv run ruff check plugins/corpus tests/test_corpus_structured_roles.py
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
