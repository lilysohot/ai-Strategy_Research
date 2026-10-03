# 06 · 工件保存、语义发布与跨运行回读

Status: ready-for-human
Execution: 待验收
Type: task
Plan: W3；R2-S2/S3（文件试点，不代表生产 S5）
Blocked by: 无本地任务依赖（05 已验收）
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

让合格角色结果经受控文件 Adapter 发布，并在另一研究运行中可发现、核验和读取；独立发布与后到冲突不破坏版本一致性。

## 前置与外部门

05 已验收，01 已固定根目录配置键/索引结构/发布写入策略。仅写测试临时目录或明确实验输出；不迁移生产数据库，不修改旧 corpus_evidence_runs。

## 范围与预期文件

- 文件 store/发布固定落在 `plugins/corpus/structured/store.py`；不可变对象在
  `objects/sha256/`，发布 manifest 在 `manifests/`，权威 head/generation 在
  `index/structured.sqlite3`，`cache/heads/` 仅为可重建缓存。角色校验使用 v1 contract。
- tests/test_corpus_structured_store.py、tests/test_corpus_structured_publication.py。
- 不可变 raw/角色工件、校验和、执行账引用、逐角色覆盖和语义发布 manifest；研究消费账/报告清单不存入此目录。
- 跨角色映射区分确定对应、疑似、未关联和字段冲突；规则版本与证据绑定。

## 验收条件

- [x] 同一输入的不同模型运行保留独立身份；文件存在不等于发布，旧加载器不能成为新 JSON 回读路径。
- [x] 精确引用、原文依赖与用途检查通过才进入可用清单；未关联不算一致，同 locator 多命题不误合并。
- [x] Claims 可先发布 P1，R2 后到冲突发布 P2 收紧受影响用途；失效 items 的关系不能继续以有效状态提供。
- [x] 首轮单发布写入者或已冻结的父版本检查生效，双路提交无丢更新；断电/崩溃不暴露半份清单，历史可诊断复现。
- [x] 来源更新、规则升级、撤回与过期分开处理；不以“最新一次失败”覆盖旧合格历史，更不能把旧结果当新 build。
- [x] 关闭写端、切换 cwd 和研究 run 后可按配置根目录和发布索引读取；不依赖内存对象/临时 cwd，不全盘搜索。
- [x] 缺目录、权限不足、损坏哈希、未知 schema、未发布和撤回分别报错；检查零模型、无自动重抽。
- [x] 路径解析限制在配置根目录，工件引用不允许越界；读端不获得后台写权限，不泄露 raw 密钥信息。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_store.py tests/test_corpus_structured_publication.py -q
uv run ruff check plugins/corpus tests/test_corpus_structured_store.py tests/test_corpus_structured_publication.py
```

必须包含两个进程/两个 cwd 的真实文件回读测试、发布竞态和损坏工件反例，不能仅复用进程内字典。

## 非目标

不恢复旧 evidence 表，不将 JSON 试点冒充生产 PG 保存，不修改来源正文或建设全库缓存治理。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
- 2026-10-03：用户明确要求执行 06；本票已认领并进入实现。继续限定为合成夹具与本地
  临时文件 store，真实模型调用和生产数据库访问保持为 0；不顺带执行 07。
- 2026-10-03：用户要求开启执行。前置核查确认 05 仍为 `ready-for-agent` / 未开始，且仓库中
  不存在本票依赖的 `plugins/corpus/structured/ledger.py`、structured CLI、执行账测试或
  `index/structured.sqlite3` Schema。06 的发布事务需与 05 共用该索引并引用稳定的
  batch/task/attempt，无法在不猜测账本接口的情况下满足父 generation、并发写入和执行账引用
  验收。因此本票保持 `needs-triage` / 未开始 / `Blocked by: 05`，未创建 store/发布代码，
  未调用真实模型，未访问生产数据库。需先执行并验收 05，或由用户明确调整任务顺序和接口边界。
- 2026-10-03：05 经回塑、双轴复核和最终门禁后已验收闭环，稳定执行账、复合 batch/task/attempt
  作用域及只读核查入口现已具备；本票解除本地依赖并转 `ready-for-agent`。Execution 仍为未开始，
  本次没有执行 06、没有创建发布/store 实现，真实模型调用和生产数据库访问仍为 0。
- 2026-10-03：实现完成并转 `ready-for-human / 待验收`。新增
  `plugins/corpus/structured/store.py`，在 05 的同一 `index/structured.sqlite3` 中登记不可变
  publication、逐工件 batch/task 引用及 source/build 权威 head/generation；manifest 先原子落盘，
  `BEGIN IMMEDIATE` 内比较冻结父版本并切换 head，`cache/heads` 仅在提交后尽力刷新且读端从不依赖。
  读端以 SQLite `mode=ro` 按配置根目录精确定位，校验 manifest/对象/角色 payload/快照/原文区间、
  必要依赖、用途、关系上游与端点，不调用旧 `load_evidence_run`，不扫描 cwd，也不返回凭据配置。
- 2026-10-03：跨角色规则固定为 `cross-role-map-v1`；confirmed/suspected/unlinked/conflict 分开，
  exact span 参与映射，同 locator 非重叠命题不合并。Claims P1 可先发布；R2 后到的可验证 value/
  factuality 冲突形成 P2，当前视图撤去受影响 compare/calculate 而保留历史 P1；缺失或失效 items
  的 relations 在发布前拒绝。来源更新、规则升级、撤回和过期使用独立 lifecycle，旧 build/head
  与历史 manifest 保留，失败的新发布不切换旧 head。
- 2026-10-03：精确验收命令原样通过：`19 passed`；指定 Ruff 命令 `All checks passed`。
  扩展 `tests/test_corpus_structured_*.py` 回归 `227 passed`；定向 Pyright `0 errors`；import smoke
  为 framework `379/379`、eval `428/428`；symbol closure 为 `0 missing` / 478 文件；
  `git diff --check` 通过。测试覆盖两个独立读进程/两个 cwd、配置根目录、父版本双写竞态、
  提交前/后崩溃窗口、损坏 manifest/角色工件、未知 schema、权限、未发布、撤回/过期、路径
  symlink 越界及只读 DB mtime。所有业务路径显式拒绝网络、真实模型和生产 CorpusService。
- 2026-10-03：全仓 Pyright 另报 5 个既有非 06 路径错误：`deploy/huggingface/app.py` 缺
  gradio、`scripts/run_retention.py` 3 项类型错误、`server/orchestrator.py` 1 项 Queue 类型错误；
  本票定向 Pyright 与全部相关测试均通过，未越界修改这些文件。交付指纹：`store.py`
  `24a060efc68103715f692e752950b0e5c941087fe9dcf32efb6b1752ca49f61d`；`ledger.py`
  `4968f7ef49830759af9576a6c68e08e1ae6352086a8fed0adeab7501d9955a4d`；
  `test_corpus_structured_store.py` `5c19ef1cc179846486ff583ffe0306839039eeae7c7c31f703c1ee12ebd77102`；
  `test_corpus_structured_publication.py`
  `1343e2fb0e707d276f0564c9653a7f122e668a97c78a522e5e9dc4a6e4a881b7`。真实模型调用 0、
  生产数据库访问 0；未执行真实模型 preflight，也未启动 07。
