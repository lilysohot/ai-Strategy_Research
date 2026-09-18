# I2-5 整改清单（2026-09-18）

| 项 | 内容 |
| -- | -- |
| 状态 | **draft · 待 U/执行者核定**。本清单不是执行授权，不新增/降低阶段门，不改任务编号 |
| 日期 | 2026-09-18 |
| 上游依据 | 同目录 [review.md](review.md)（独立复核，F1—F4）；[tasks.md I2-5](../../../../../docs/plan/corpus-ingestion-rebuild-tasks.md)（8 关键步骤）；[架构 §8.1](../../../../../docs/plan/corpus-ingestion-rebuild-architecture.md)（I2 必验七项） |
| 进度真源 | [总计划 · 台账](../../../../../docs/plan/claims-market-closed-loop-plan.md)；本清单只列整改动作与关闭判据，完成/放行裁决回填总台账 |
| 纪律 | 遵守 tasks.md §5：不虚构耗时；改动影响运行即建新冻结修订，不覆盖历史；生产库 I4 前零写入 |

## 0. 放行口径与本次判定

- I2-5 现状：**实现 + 首轮真库测试已交付；整项验收未达标**。`Store` 层真库并发门有效
  （2026-09-18 复跑：`publication_pg.py` 13 passed；加 `repository_pg.py` 31 passed，无 skip），
  但「全部强制场景 + 不以 Store 级测试代替引擎恢复」未满足。
- 阻断关系：**RM-1～RM-3 未闭环前，I2-5 不得记 `complete`**；**M5 维持 `not_declared`**
  （另有 I2-8/I2-4/I2-6 未完成）。
- 环境纪律：RM-5～RM-8 的 PG 场景须在 `i2-sandbox` 守卫 env、目标 `i2_sandbox_corpus` 下执行，
  **PG 门不得 skip**，不得以内存锁代替；运行统一 `env -u PYTHONPATH`（去宿主注入，非放宽守卫）。
- 反例基线：`review.md` 的探针命令当前预期 **4 failed / 1 passed**（2026-09-18 复现一致）。

## 1. 整改项总表

| ID | 严重度 | 摘要 | 阻断 I2-5 | 状态 |
| -- | ---- | ---- | ------- | ---- |
| RM-1 | P1 | `finish_job` 终态幂等短路先于 owner/token 校验，陈旧 token 迟到 finish 被误判成功 | 是 | open |
| RM-2 | P1 | 发布指针已切换、PUBLISHED 未完成前断线，重试短路返回，job 永远 RUNNING | 是 | open |
| RM-3 | P1 | 引擎发布幂等短路绕过 `_verify_publication_ready` 与当前准入校验 | 是 | open |
| RM-4 | P2 | PG/Memory 双 Adapter fencing 判据次序相反，台账「同步收敛」表述失实 | 否 | open |
| RM-5 | P2 | `heartbeat_job` 正向续租零覆盖；「续租/过期恰好临界」未测 | 否（进入 §8.1 验收口径） | open |
| RM-6 | P2 | 架构 §8.1「连接断开」无任何用例 | 否（同上级别不足，但列为 I2 必验缺口） | open |
| RM-7 | P2 | `put_admission` 未参与 source 级互斥，准入更新可与 publish 交错 | 否 | open |
| RM-8 | P2 | 13 用例用 `_publish_chain` 直操作 Store，未覆盖引擎全链恢复（含 VERIFIED 质量/引用门） | 否 | open |
| RM-9 | P3 | 测试卫生：daemon 线程 + join 超时仅 assert；无 `statement_timeout`/`lock_timeout` | 否 | open |
| RM-10 | P3 | `chunk_rev` 未随 search_text 规则（全角 ％ 归一化）联动 | 否 | open |
| RM-11 | — | 重冻当前配置/实现/测试/结果（新修订），不覆盖历史快照 | 是（收口动作） | open |
| RM-12 | — | 总台账与任务清单回填 0918 复核结论，修正 I2-5 状态 | 是（收口动作） | open |
| RM-13 | P3 | F4「冻结与工作区不一致」经核验**已自愈**，登记关闭 | — | closed |

## 2. 整改项明细

### RM-1（P1）finish 终态短路先于所有权校验

- 位置：[repository_pg.py:1078-1085](../../../../../plugins/corpus/preparation/repository_pg.py#L1078-L1085)；
  [repository.py:523-527](../../../../../plugins/corpus/preparation/repository.py#L523-L527)。
- 现状（已复现）：接管者完成 attempt 2 后，旧 worker 携 attempt 1 的旧 token 请求 succeeded，
  命中「当前行已是相同终态 → 直接返回」分支，**不报 lease_lost**，调用方被错误告知旧提交成功。
- 根因：把「不同 attempt 的相同终态」当作同一次提交重放；幂等判定未先锚定 `(attempt, owner, token)`。
- 整改要求：
  1. 终态重试先核对 `<当前行.attempt, owner_id, fence_token>` 与请求一致，再按合法重放返回原检查点；
  2. 不一致时返回 `lease_lost` 语义错误（不得退化为「状态提示」）；
  3. 保持「同 attempt 提交成功但响应丢失 → 恒幂等」不被破坏；不得机械要求「终态仍须 running」。
- 必须新增/转正的回归用例（双 Adapter 对称）：
  - 接管者已完成（succeeded/failed/cancelled）后，旧 token finish → 拒绝且语义为 lease_lost；
  - 同 attempt/同 owner/同 token 重复 finish（三种终态）→ 返回原行、不增行、不刷时间；
  - 接管进行中（新 attempt 仍 running）旧 token finish → 拒绝（既有行为不得回归）。
- 不动项：不改 `_TERMINAL_STATES` 集合、不改 finish 只能终态的入参校验、不改 finished 行 `lease_until=NULL` 语义。

### RM-2（P1）发布成功、job 未完成前断线不恢复

- 位置：[engine.py:1147-1153](../../../../../plugins/corpus/preparation/engine.py#L1147-L1153)（短路）
  与 [engine.py:1184](../../../../../plugins/corpus/preparation/engine.py#L1184)（finish）。
- 现状（已复现）：活动指针切换与 PUBLISHED 终态是两次 Store 调用；前者成功、后者前断线后，
  重试被幂等短路直接返回，**PUBLISHED job 永久停在 RUNNING**；同类情况下 FAILED 台账可与已上线指针并存。
- 整改要求：为「指针切换 ↔ PUBLISHED 终态」定义一致性协议，二选一并写明理由：
  - 方案 A：Store 层合并为单事务提交（指针 + job 终态同事务），引擎只调一次；
  - 方案 B：保留两次调用，但幂等短路前先做**受 fencing 保护的终态补齐**（持当前租约 finish，再返回）。
- 必须新增的回归用例（真 PG，引擎入口）：
  - 发布提交后、finish 前断线 → 重试后 `job.state == succeeded` 且 `generation` 不重复递增；
  - finish 提交前失败 → 重试补齐；finish 提交后丢响应 → 恒幂等；
  - 租约到期后新 worker 恢复 → 核 `active_build_id`、`generation`、`attempt`、job 终态四者一致。
- 不动项：不改 `publish_idempotency_v2` 的「不以时间为键」原则（同目标状态仍恒幂等）。

### RM-3（P1）引擎成功短路绕过当前准入检查

- 位置：[engine.py:1145-1155](../../../../../plugins/corpus/preparation/engine.py#L1145-L1155)。
- 现状（已复现）：同一 build 曾发布后，准入已追加排除决定、撤销动作尚未完成时，`publish_build`
  仅比对旧 publication 的 `(decision_id, active_build_id)` 即返回成功，**不再进入** `store.publish`
  的当前准入校验；`_verify_publication_ready` 同样被跳过。这是 Store 门与真实入口行为不一致。
- 整改要求：区分两种语义并分别实现——
  - **查询历史发布结果**（只读）：可短路；
  - **请求当前有效发布**（默认入口）：幂等短路必须服从最新准入（含排除/缩范围）与撤销状态，
    与发布事务内检查形成同一协议。
- 必须新增的回归用例（引擎 + 服务入口）：
  - 发布后追加排除决定、未 retire → 引擎重试拒绝；
  - 缩范围/新决定版本 → 引擎重试走重评而非旧短路；
  - 显式 retire 后重发布 → 按新决定正常发布。
- 关联：RM-7 的交错窗口修好后，本项需在同一批次重跑。

### RM-4（P2）双 Adapter fencing 判据次序统一

- 位置：PG [repository_pg.py:312-320](../../../../../plugins/corpus/preparation/repository_pg.py#L312-L320)
  （凭据优先）；Memory [repository.py:559-566](../../../../../plugins/corpus/preparation/repository.py#L559-L566)、
  [589-596](../../../../../plugins/corpus/preparation/repository.py#L589-L596)、
  [602-608](../../../../../plugins/corpus/preparation/repository.py#L602-L608)（状态优先）。
- 现状：同一输入两边错误语义不同（PG `lease_lost` vs Memory「处于 succeeded 态，无当前所有权」）。
  台账 I2-5 修复③称「双 Adapter 同步收敛」，与代码不符。
- 整改要求：以 PG 语义为准统一 Memory；三处判定次序改为 `owner/token → 非 running → 过期`。
- 必须新增的回归用例：同一反例在两 Adapter 上**断言同一错误语义**（参数化跑双 Store）。
- 不动项：不改 PG 侧已达成的次序。

### RM-5（P2）续租正向路径与恰好临界

- 现状：全仓 `heartbeat_job` 测试仅 2 处且均为失败路径
  （[contract.py:408-417](../../../../../tests/test_corpus_preparation_contract.py#L408-L417) token 不匹配；
  [publication_pg.py:385-392](../../../../../tests/test_corpus_preparation_publication_pg.py#L385-L392) 已过期）。
  §8.1「续租」正向行为（`lease_until` 前移）从未验证；UPDATE 写错现有测试全不红。
- 整改要求（真 PG）：`heartbeat` 成功后 `lease_until ≈ db_now + ttl`、`heartbeat_at` 前移；
  过期点两侧（`lease_until - ε` / `+ ε`）与 takeover 竞争的行为分别验证；纯 DB 时间、调用方时钟被忽略。
- 验收：`heartbeat_interval ≤ TTL/3` 的 I0C-2 冻结参数在用例中可见引用，不新造参数。

### RM-6（P2）连接断开场景（§8.1 明列，当前零用例）

- 现状：「提交响应丢失」（RM-2 之前的 `test_lost_commit_response_replay_is_idempotent`）是**重放**，
  不等价于连接断开；`_backdate_leases` 是记账式改写，不是断连。
- 整改要求：新增真实连接中断场景（在关键 SQL 前后切断连接，或注入 `OperationalError`），
  验证：不产生半提交、不误判 lease、重连后按 §8.1.6 读取已提交检查点。
- 建议同时加 `statement_timeout`/`lock_timeout`（吸收 RM-9）。

### RM-7（P2）准入更新纳入发布互斥

- 位置：[repository_pg.py:454-497](../../../../../plugins/corpus/preparation/repository_pg.py#L454-L497)
  `put_admission` 未取 `_ADVISORY_PUB_NS` 锁；publish 在 [787](../../../../../plugins/corpus/preparation/repository_pg.py#L787)、
  retire 在 [842](../../../../../plugins/corpus/preparation/repository_pg.py#L842) 取该锁。
- 风险窗口：publish 读到旧指针后，另一连接更新准入 → 最终指针与最新准入不一致。
- 整改要求：明确互斥范围（准入指针更新是否须与 publish 同临界区），选定后加锁或改用条件写；
  需要写清「谁赢、如何收敛」，不做无边界的隐式串行化。
- 必须新增的用例（真 PG 双连接 + 测试屏障）：在 publish 关键 SQL 前/后暂停，另一连接更新准入，
  验证最终 `active_build_id`/`current_decision_id` 组合始终合法（指针指向与当前决定一致或为空）。

### RM-8（P2）引擎级全链恢复验收

- 现状：13 用例经 [`_publish_chain`](../../../../../tests/test_corpus_preparation_publication_pg.py#L224-L253)
  直操作 Store、手工构造 chunk，**绕过 VERIFIED 质量门与引用完整性门**。Store 级并发隔离职责合理，
  但不能作为引擎全链恢复验收。
- 整改要求：保留现有底层用例，另增「真实引擎 + PG」的故障注入族（与 RM-2/RM-3 用例合并，不重复造轮子）；
  覆盖 plan→execute→publish 各阶段失败后的恢复跳算与检查点复用。
- 验收：断言实际读取的 `build_id`/活动指针，而不仅断言调用成功。

### RM-9（P3）测试卫生

- 现状：worker 为 daemon 线程，`join(timeout=60)` 超时仅 assert；无 PG 语句/锁超时。
- 整改要求：非 daemon 或显式收尾；连接注册 `statement_timeout`/`lock_timeout`；失败用例不遗留线程阻塞后续 TRUNCATE。

### RM-10（P3）chunk_rev 与索引文本规则联动

- 现状：`normalize_search_text` 已改变 search_text 生成规则（新增全角 ％ 归一化），但 `chunk_rev` 仍 `chunk-2`；
  [engine.py](../../../../../plugins/corpus/preparation/engine.py) 注释称「索引文本规则随 chunk_rev 绑定」，
  只看 `chunk_rev` 无法察觉规则已变（正确性无碍，属版本可追溯性问题）。
- 整改要求：确定 search_text 规则变更是否应升 `chunk_rev`（或明确改由 `index_rev` 单独表达），
  二选一并同步注释与冻结说明；若升版则按 §5 建新 build 全量重建。

### RM-11（收口）重冻当前版本

- 现状：`i0c-r6` 绑定 `test_corpus_preparation_publication_pg.py = 09e9d8c4…`、`repository_pg.py = d894ce58…`；
  当前工作区已是 `3978ccc6…` / 新一轮字节（r7 时点），I2-5 的「冻结当前配置/实现/结果」须重做。
- 整改要求：整改批次完成后新建冻结修订（`i0c-r8` 或后续修订），绑定当前实现/测试/守卫/文档与**本轮重跑命令 + 输出**；
  `validate_i0c_freeze.py` 须 exit 0；不得改写历史快照哈希。
- 备注：2026-09-18 已核验 `validate_i0c_freeze.py` **exit 0**（r7 血缘完整）；本项是「整改后」的重冻，不是修 F4。

### RM-12（收口）台账与清单回填

- 现状：`docs/plan/claims-market-closed-loop-plan.md` 与 `corpus-ingestion-rebuild-tasks.md` **各 0 处**提及本复核；
  I2-5 仍记 `complete`。
- 整改要求：按 tasks.md §0「每轮必须回填」纪律，回填：复核链接、F1—F3 现状、
  I2-5 状态改 `partial · 独立复核待整改`、M5 维持 `not_declared`、本清单链接与批次计划。

### RM-13（已关闭）F4 冻结与工作区不一致

- 复核时（09-18 00:14，有效绑定 `i0c-r6`）报 `docs/plan/claims-market-closed-loop-plan.md` 哈希失配。
- 核验结论：10 分钟后创建的 `i0c-r7`（00:24）绑定当前文档字节 `4d89c869…`，与工作区一致；
  2026-09-18 实跑 `validate_i0c_freeze.py` **exit 0**。**当前不复现，登记关闭**，不改历史快照。

## 3. 建议执行顺序与依赖

```text
批次 A（代码缺陷，先做）
  RM-1 ─┐
  RM-2 ─┼─→ 双 Adapter 对称回归 + 引擎入口回归
  RM-3 ─┤
  RM-4 ─┘
批次 B（真 PG 场景补测，须 i2-sandbox 守卫 env）
  RM-7 → RM-5 → RM-6 → RM-8   （RM-9 随 RM-6/RM-8 一并吸收）
批次 C（收口）
  RM-10 → RM-11（重冻）→ RM-12（回填台账）
```

- 批次 A 与批次 B 可部分重叠，但 **RM-3 必须在 RM-7 之后重跑**（同一交错窗口）。
- RM-11 依赖批次 A/B 全部改动冻结；RM-12 依赖 RM-11 的修订 ID。
- 任一环节环境缺失/必需用例 skip → 该环节未通过，**不得以「新 CLI 通过」或「Store 级通过」代替**。

## 4. 明确不做（防范围膨胀）

- 不推翻 I2-5 已完成的 J1/J2 advisory 锁修复与既有 31 passed 记录（历史证据追加不覆盖）。
- 不换模型、不新增研报、不改金标/冻结参数（TTL/heartbeat/max_attempts 保持 I0C-2 冻结值）。
- 不改 tasks.md 的门定义与任务编号；不提前放行 M5；不执行 I2-8/I2-4/I2-6 的范围。
- 不动生产库（`127.0.0.1:5432`）与 `apodex`/`i0b2_verify_*`；写入仅限 `i2_sandbox_corpus` 的 `corpus` schema。
- 性能类改造（连接池、分区、GIN 批量维护、LIMIT 下推）**不列入本轮**，另立需求与实测标定。

## 5. 关闭判据（Definition of Done）

1. `review.md` 探针命令在当前工作区从 **4 failed / 1 passed** 转为**全 passed**（或等价的正式回归替代），
   且 F1—F3 对应的正式测试在双 Adapter 与引擎入口均转正；
2. 真库门复跑：`publication_pg + repository_pg` **全 passed、零 skip**，新增用例含 RM-2/RM-5/RM-6/RM-7/RM-8 场景；
3. i1 守卫 env 与普通 env 定向回归无新增失败；`ruff` / `pyright` / `import_smoke --stage 1` 全绿；
4. 新建冻结修订绑定当前字节 + 本轮命令与输出，`validate_i0c_freeze.py` exit 0；
5. 总台账与任务清单已回填，I2-5 状态与 M5 声明按 §0 口径更新。

不在上述 1—5 全部满足前，**不得**将 I2-5 记 `complete`、不得宣告 M5。

## 6. 反例复现（当前基线）

在仓库根执行，当前预期 **4 failed / 1 passed**（只读现有代码与合成夹具，测试暂存由 pytest 管理）：

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  PYTHONPATH=/home/administrator/FrontierAgent \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  CORPUS_GUARD_PHASE=i1 \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json \
  .venv/bin/python -B -m pytest --noconftest -c /dev/null \
  -p no:cacheprovider -p plugins.corpus.preparation.guard_pytest \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i25-review/test_review_probes.py \
  -q --tb=short
```

真库门复跑（2026-09-18 实测 13 passed / 合并 31 passed，无 skip）：

```bash
env -u PYTHONPATH \
  CORPUS_GUARD_PHASE=i2-sandbox \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-sandbox.json \
  CORPUS_I2_DSN="postgresql://postgres:***@127.0.0.1:543/i2_sandbox_corpus" \
  uv run pytest tests/test_corpus_preparation_publication_pg.py \
    tests/test_corpus_preparation_repository_pg.py -q \
  -p plugins.corpus.preparation.guard_pytest --noconftest -c /dev/null
```
