# I2-5 独立审核（2026-09-18）

## 结论

任务方向正确：真实 PG 独立连接、双 worker、有限租约、attempt 历史、fencing、发布互斥、重试预算，均与原项目方向一致。J1/J2 的逻辑键锁及 publication 首次插入串行化是有价值的改进。

但“全部强制场景过门、I2-5 完成”的结论仍偏强。当前证据证明若干 Store 级路径，而不是正式引擎的完整恢复与撤销协议。新增探针复现 3 类功能缺口（4 条失败），冻结验证另失败 1 项。建议状态为“实现与首轮真库测试已交付，独立复核待整改”。不推翻历史实测，也不宣告 M5 通过。

## 实际审核范围

- 核对 tasks.md I2-5、design-review C7 的七项 acceptance_cases_i2_5，以及发布幂等协议。
- 阅读 publication_pg 全部 13 项用例、PgStore/MemoryStore 的相关实现与实际 publish_build。
- 当前工作区为 i0c-r7（含 I2-3/I2-7 后续修订），不是仅 r6。历史 31 passed 为 r6 时点声明，本轮没有复跑或冒称复验通过。
- 本轮无 PG 连接、DDL/DML/TRUNCATE，无来源/留出正文读取，无模型调用。仅新增本报告与同目录合成反例，未修改实现、正式测试、台账或冻结文件。
- 使用 diagnosing-bugs 的最小失败信号方法；这是审核，不实施修复。

## 本轮执行结果

1. `validate_i0c_freeze.py`：**exit 1**。

   ```text
   I0C FREEZE CHECK FAILED: i0c-current.binding[docs]: docs/plan/claims-market-closed-loop-plan.md 哈希失配或缺失
   i0c freeze verification FAILED: 1 error(s)
   ```

   文件实际存在，是当前有效绑定与文件字节不一致；不能据此推断数据库或业务实现被破坏。应以新修订绑定当前经过核定的文档，不覆盖历史快照。

2. 同目录 `test_review_probes.py`：**4 failed、1 passed，0.44s**。i1 守卫、env -i，无网络；PG 分支使用假游标终态行，其他反例运行真实 MemoryStore 与合成解析/构建/发布引擎。不是 PG 并发实测替代品。
3. 原有 13+18 真 PG 套件：**本轮未运行**。冻结前置门未过，且套件 autouse 会清空九表；不为只读审核直接运行破坏性清理。后续验收须在修正冻结并明确隔离测试范围后重跑，不允许把 skip 记通过。

## F1 · P1：接管者完成后，旧 attempt 的 finish 被误认成幂等成功

位置：`plugins/corpus/preparation/repository_pg.py:1078-1085`；`repository.py:523-528`。

实现先判断“当前行是否为相同终态”，相同即返回；这一步发生在 owner/fence_token 校验之前。worker 1 的 attempt 1 已失效、worker 2 的 attempt 2 已 succeeded 后，worker 1 携带旧 token 请求 succeeded，得到的却是 worker 2 的成功结果，不报 lease_lost。

证据：`test_pg_stale_finish_after_takeover_terminal_is_rejected` 和 `test_memory_stale_finish_after_takeover_terminal_is_rejected` 均失败。PG 探针直接运行真实 finish_job，仅替换连接/当前行；Memory 探针实际 acquire→过期接管→新持有者完成→旧 token 迟到 finish。

影响边界：本反例未覆盖或改写新结果，但调用方被错误告知旧 attempt 提交成功。违反 C7“同 (build,stage,attempt) 重复 finish 幂等”和“旧 token 迟到 finish 拒绝”，不能把不同 attempt 的相同终态视为同一次提交。

现有测试为何漏掉：真实过期接管用例检查旧 finish 时，新 attempt 仍 running；接管者已完成的用例只检查 put_units/put_chunks/publish，没有再检查 finish。

整改：终态重试先核对同一 attempt/owner/token，再按合法重放返回原检查点；不能机械要求终态必须仍 running 或租约未过期，否则会破坏正常响应丢失重试。补 succeeded/failed/cancelled 终态后的旧 token 拒绝和同 attempt 合法重放对照。

## F2 · P1：发布成功、job 完成前断线，重试不修复执行状态

位置：`plugins/corpus/preparation/engine.py:1147-1153,1165-1184`。

活动指针切换和 finish_job 是两次 Store 调用。若前者成功，后者尚未完成就断线，重试看到相同活动状态立即返回，永远不完成仍 RUNNING 的 PUBLISHED job。类似情况下 FAILED 台账也可能与活动指针并存。

证据：`test_publish_retry_reconciles_unfinished_publication_job` 使用实际合成 build 与 MemoryStore，只在第一次 PUBLISHED finish 前注入 ConnectionError；重试返回 generation=1，但 job 仍 RUNNING，预期 succeeded 断言失败。正常 publish/同 attempt 重放对照通过。

影响：表面发布幂等成立，执行台账/恢复却未闭合；后续 status、恢复、attempt 预算可能与已上线事实不一致。不是重复生成 generation 的问题。

现有丢响应测试只直接重复 store.publish/finish，并未在正式引擎两个提交之间注入断线；因此证明的是重放行为，而非声明的完整故障恢复。

整改：明确活动指针提交与 PUBLISHED 终态的一致性协议，可选择合并原子事务或受 fencing 保护的幂等恢复流程。补提交前失败、发布提交后响应丢失、finish 提交前失败、finish 提交后丢响应、租约到期后新 worker 恢复；应同时核对活动指针、generation、attempt 和 job 终态。

## F3 · P1：正式引擎的成功短路绕过当前准入检查

位置：`engine.py:1147-1155`。

同一 build 曾发布后，当前准入已变为新的排除决定、撤销动作尚未完成时，publish_build 仅核对旧 publication 的 decision/build 就返回成功；不再进入 Store.publish 的当前准入校验。

证据：`test_engine_retry_must_not_accept_superseded_admission` 先实际发布，再追加排除 admission，随后调用正式 publish_build，未拒绝旧决定。该反例测试的是准入改变与显式 retire 之间的窗口，并未声称旧数据被重新写入或已经 retire 后又被复活。

现有撤销测试调用的是 store.publish，再手工 store.retire，没有覆盖引擎短路。这是 Store 级门与实际入口行为不一致。

整改：区分“查询历史发布结果”与“请求当前有效发布”。后者的幂等短路必须服从最新准入/撤销状态，并与发布事务内检查形成一致协议；补引擎及服务入口的排除/缩范围/重发布测试。

## F4 · P2 / 放行前置门：现行冻结文件与当前总计划不一致

本轮验证器仅报告总计划绑定失配，未报告代码绑定失配。历史证据不应改写，但当前放行必须关联当前版本，不能继续照搬 r6 的“31 passed”。

建议先核定文档改动所属阶段与签认状态，再新建冻结修订，保存当前重跑的命令、输出、结果 XML 和版本。不以直接改旧 manifest 哈希解决问题。

## 仍需补充的真 PG 验收（静态风险，不冒称已实测）

1. **准入更新与发布交错**：publish/retire 使用 source advisory 锁，但 put_admission 更新 current_decision_id 未参与该锁。应在 publish 读到旧指针后暂停，让另一连接更新准入，再继续提交，验证最终指针一致性；现有并发用例使用同一 decision 的两个 build，未覆盖此交错。
2. **持锁等待跨 TTL 与续租**：已有真实 sleep 越过 TTL 是进步，但不等于锁等待跨过过期点、heartbeat 与 takeover 同时竞争已验证；应使用明确的测试屏障控制关键 SQL 前后位置，而不是只在线程开始时 barrier 后依赖调度。
3. **真实引擎恢复**：现有 `_publish_chain` 直接操作 Store，手工准备 chunk；没有通过 engine 的 VERIFIED 质量/引用完整性门。底层并发测试可以这样隔离职责，但不能称作引擎全链恢复验收。需保留底层测试并增加真实引擎+PG 的故障注入。
4. **超时与线程收尾**：当前 worker 为 daemon，join 超时后仅 assert；建议加数据库 statement_timeout/lock_timeout 和取消、关闭连接机制，避免失败测试遗留线程与下一用例清理互相阻塞。

## 后续建议

先修当前冻结一致性和 F1—F3，再对当前版本补真实 PG 故障/交错测试、保存新证据，最后更新 I2-5 放行状态。已有 J1/J2 等实现无需推翻，不需要换模型、新增研报或修改金标。I2-5 即使通过也不能替代 I2-7/8 的真实消费者接线与 I2-6 authority 门。

## 反例复现命令

在仓库根执行，当前预期 4 failed / 1 passed；只读现有代码及合成夹具，测试暂存由 pytest 管理。

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
