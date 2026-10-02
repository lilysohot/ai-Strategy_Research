# 01 · 冻结范围、公共契约与开工资产

Status: ready-for-human
Execution: 已验收
Type: task
Plan: W0；R2-S0（接口决议供 S2 使用）
Blocked by: 无本地任务依赖；仅可开始规格与合成资产准备
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；本票所列契约/合成测试资产现已交付，生产实现仍不存在。

## 目标

把 report 的设计语义变为后续任务共同遵循的可机读契约与合成验收资产，不在本票实现抽取业务或调用模型。

## 前置与外部门

核对主计划 I0 范围、I1 实现及 I3 质量门的证据引用。只核对公开计划/批准清单，不读取受保护材料。资料不全时记录具体缺口；合成规格工作可以继续，但不得宣告真实开发范围或 S0 整体已过门。

## 范围与预期文件

- 更新 spec.md 第 4 节的全部决议：模块落点、命令/工具名、配置键、首轮支持协议、状态/错误码、存储事务方式。
- 新增专项 contracts/ 下的版本化 Schema/示例和 contract-manifest.json（名称在本票固定），复用现有业务 Schema，只定义必要封装。
- 新增 tests/fixtures/corpus_structured_synthetic/ 合成材料与资产清单，以及 tests/test_corpus_structured_contracts.py。
- 更新各下游票据中尚待本票决定的精确落点/命令。修改已有冻结文件之前先按主计划另立修订，不覆盖历史。
- 真实样本清单只记录已明确获准的来源/build/范围；未获准部分交 10，不以“已在仓库内”推定可读。

## 验收条件

- [x] 快照、task/attempt、角色产物、语义发布、查询/分页和报告语义引用封装都有字段类型、必需性、schema_version、错误码与合法/非法样例。
- [x] 执行、协议、发布、语境、跨角色映射及质量状态分开；所有状态及转换有唯一解释，未关联不算一致。
- [x] hash 包含必要版本、坐标、类型和元数据；明确原文 code point 区间，避免跨文本坐标混用。
- [x] env 缺失行为、文件根目录配置、持久预算事务、发布指针更新及故障恢复策略已落定，不能继续写“实现时再定”。
- [x] 合成夹具覆盖普通数字、纯观点、混合条件、否定、预测/实际、表头/脚注、跨包限定、重复引文、解析缺口；不含真实业务原文。
- [x] 给出哪些主计划前置已核验、哪些仍未核验；下游任务可以据此判断是否可开始，不自行替用户签认。
- [x] 无模型、网络业务调用、生产库访问；所有新文件是规格、Schema 或合成测试资产。

## 验收命令

交付下列新增测试后，从仓库根目录执行：

```bash
uv run pytest tests/test_corpus_structured_contracts.py -q
git diff --check -- .scratch/claims-r2-role-isolation tests/test_corpus_structured_contracts.py tests/fixtures/corpus_structured_synthetic
```

同时逐项检查 spec 第 4 节已从“待冻结”变为明确决议，附 Schema/夹具指纹。命令通过不能替代外部门核验。

## 非目标

不实现模型抽取、生产数据库对象、完整调度器、研究工具或自动任务执行；不扩大首轮入口与材料范围。

## 验收记录与后续

2026-10-02 本轮交付：

- `contracts/contract-manifest.json` 及 v1 README、状态/错误码目录、六类 JSON Schema、每类合法/
  非法样例；manifest SHA-256：
  `8cbe94827de6764feda994da4c33c9fcaf57e3ee77d3beec32da177c0cbce154`。
- `tests/fixtures/corpus_structured_synthetic/asset-manifest.json` 与 `cases.json`；清单 SHA-256：
  `6f9cc51597601b05e220ce3b74696269311ff50d246cf8272aced833a491d073`，cases SHA-256：
  `df2f1c9e4005a13702df798df0141b397c99a90e68ff9a8f1b4179692a23b179`。
- `tests/test_corpus_structured_contracts.py`；覆盖 Schema 正反例、snapshot 身份/文本/元数据 hash、
  Unicode code-point 区间、六状态域/转换、错误码、manifest 字节绑定、合成场景和公共协议矩阵。
- spec 第 4 节已冻结模块/Interface/CLI、配置、SQLite 事务、发布恢复、协议、坐标、状态、查询/分页、
  报告引用和外部门；02—10 已回填精确落点/协议/工具名。

实际验收命令及结果：

```text
uv run pytest tests/test_corpus_structured_contracts.py -q
11 passed in 0.32s                                      exit 0

uv run ruff check tests/test_corpus_structured_contracts.py
All checks passed!                                      exit 0

git diff --check -- .scratch/claims-r2-role-isolation \
  tests/test_corpus_structured_contracts.py tests/fixtures/corpus_structured_synthetic
(no output)                                             exit 0
```

外部门核对：主计划公开台账中的 I0 已完成、I1/M4 已独立复核并由 U 签认；I3 整体仍未过门，
I3-1 的 company 0/2、`per_class_min_2=false` 与阻断缺口处置仍未关闭。主计划既有 I3 批准来源不
自动转授给本专项；当前没有本专项获准的真实 source/build/scope 清单，未读取真实/受保护材料。
该边界不阻碍 01 自身验收。用户已于 2026-10-02 明确批准，因此本票已收口并解除 01 的本地依赖；
但不宣告 R2-S0 整体放行，不解除各下游票据自身的外部门，也不启动真实模型或生产库工作。

本轮真实模型调用 0，生产数据库访问 0，业务网络调用 0；未运行真实 preflight。未修改主计划、
report 或任何历史 freeze/guard/gold 文件。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
- 2026-10-02：用户要求开始执行；进入契约冻结与合成资产准备阶段，继续保持真实模型调用与生产库访问为 0。
- 2026-10-02：契约、正反例、合成夹具和专项测试已交付并自验全绿；转 `ready-for-human / 待验收`。
  I3 与真实 source/build/scope 外部门保持未通过，未解除下游依赖。
- 2026-10-02：用户明确批准；01 人工验收完成，本票本地依赖解除。该批准不扩展为 I3/R2-S0
  阶段签认、真实样本准入、真实模型预算或生产数据库授权。
