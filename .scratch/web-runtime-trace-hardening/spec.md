# Web 运行存储与轨迹追溯修复

Status: needs-triage
Type: repair-spec
Date: 2026-09-29

用户要求将本次发现整理为后续修复报告，未要求本轮实施修复或迁移数据。
后续用户明确要求存储位置不合理时在此次修复一并改正：F01 已升级为必交付范围，
具体新路径、历史迁移和回退验收见报告 v1.4；当前仍处于计划整理阶段。

详细证据、影响、修复建议和验收唯一正文见
[修复报告](../../docs/plan/web-runtime-trace-repair-report.md)。产品范围与完成定义依从
[产品需求](../../docs/product-requirements.md)；本目录仅维护任务状态，不另建需求真源。

执行准备统一见[环境准备与执行边界](../../docs/plan/web-storage-validation-environment.md)。
现有环境先只读核实，再用专用测试账号验证正常链路；第二 API 使用同 PG 实例的独立测试库，
实例故障才另建实例/卷。第二 API 不得连接原业务库，以免启动恢复误标原进程活跃 Run。
迁移前置仅包含与本次切换相关的路径、恢复、索引及备份要求，不要求所有 21 项先修完。

## 任务索引

| 任务 | 报告发现 | 依赖 |
|---|---|---|
| [01 持久根目录与历史迁移](issues/01-storage-roots.md) | F01 | 07 的迁移前备份能力；02 防止再次污染构建 |
| [02 构建上下文隔离](issues/02-build-context.md) | F02 | 无 |
| [03 轨迹安全输出](issues/03-trace-redaction.md) | F03 | 无 |
| [04 工具调用身份](issues/04-tool-call-identity.md) | F04 | 无 |
| [05 历史轨迹展示](issues/05-history-trace-ui.md) | F05 | 03、04 |
| [06 轨迹完整性](issues/06-trace-completeness.md) | F06 | 与 04 协调格式契约 |
| [07 保留与恢复](issues/07-retention-recovery.md) | F07 | 盘点先行；联合验收在 01/03/06 后 |

Status 行遵循仓库 triage labels；本轮均待分诊，不代表可无人值守迁移生产数据。
补充复核新增 08—14，其中 08 为多用户上线阻断项，优先处理。

| 补充任务 | 报告发现 | 依赖 |
|---|---|---|
| [08 提交 Run 缺少会话归属校验](issues/08-session-ownership.md) | F08 | 详见报告 v1.1 修复顺序 |
| [09 SSE 游标与终态恢复协议存在缺口](issues/09-stream-replay-contract.md) | F09 | 详见报告 v1.1 修复顺序 |
| [10 流式去重导致文字缺失与用量漏计或重复](issues/10-replay-text-usage.md) | F10 | 详见报告 v1.1 修复顺序 |
| [11 切换 Run 后旧异步响应可能覆盖新视图](issues/11-watch-generation.md) | F11 | 详见报告 v1.1 修复顺序 |
| [12 上传校验与运行创建缺少失败清理](issues/12-upload-atomicity.md) | F12 | 详见报告 v1.1 修复顺序 |
| [13 轨迹读取与事件缓冲缺少容量边界](issues/13-capacity-bounds.md) | F13 | 详见报告 v1.1 修复顺序 |
| [14 排队 Run 的历史上下文没有明确截止点](issues/14-history-boundary.md) | F14 | 详见报告 v1.1 修复顺序 |
推进时只更新单项 issue 的状态和证据，本索引不重复复制进度。

## 全面存储复核补充任务

2026-09-29 全面复核后合计 21 项；动态结果与覆盖边界见
[存储链路复核](../../docs/plan/web-storage-chain-audit.md)，完整修复要求见报告 v1.4。

| 任务 | 报告发现 | 依赖 |
|---|---|---|
| [15 运行落账与崩溃恢复缺少一致性及幂等](issues/15-finalization-recovery.md) | F15 | 详见全面复核迁移顺序 |
| [16 消息序号与关系约束不足](issues/16-database-invariants.md) | F16 | 详见全面复核迁移顺序 |
| [17 产物根目录与回滚基线可经符号链接越界](issues/17-storage-trust-boundary.md) | F17 | 详见全面复核迁移顺序 |
| [18 产物索引与回滚后的文件不一致](issues/18-artifact-index-consistency.md) | F18 | 详见全面复核迁移顺序 |
| [19 存储与迁移故障缺少就绪门禁](issues/19-storage-readiness.md) | F19 | 详见全面复核迁移顺序 |
| [20 Run 模型快照与启动状态未接入持久化](issues/20-run-metadata-snapshot.md) | F20 | 详见全面复核迁移顺序 |
| [21 用户纠正与审批决定缺少持久追溯契约](issues/21-control-history.md) | F21 | 详见全面复核迁移顺序 |

## Comments

- 2026-09-29：基于源码/配置检查建档，未执行动态复现和应用修复。
- 2026-09-29：遗漏复核补充 7 项，合计 14 项；F01 追加 UUID 规范化问题，仍未修改运行代码。
- 2026-09-29：全面复核新增 15—21，合计 21 项；29 个新增契约检查为 26 失败/3 通过，已有相关回归 57 通过。失败为待修复证据。
- 2026-09-29：回查纠正环境准备与证据措辞；失败断言包含目标契约，不等于生产事故。更新报告 v1.4 及环境方案，未新增实例、重启服务、迁移数据或修改运行代码。
- 2026-09-30：执行前准备（E0）只读核验完成，环境台账刷新见[环境方案 §2.1](../../docs/plan/web-storage-validation-environment.md)。确认 API 为 Windows 原生 uvicorn 单 worker、业务库为 PG 18.6 容器 `pg` 的 `apodex` 库（1263 条真实 Run，当前无 queued/running）、运行根与上传根仍在源码树内（F01 未修复）、5173 前端未运行、`SERVER_DEBUG=true`；关键代码与审计基线提交内容一致（22 文件 LF 规范化后 SHA-256 全部匹配）；`.venv` 缺 `pytest` 使隔离审计入口暂不可直接复现。未重启服务、未连接业务库写入、未修改运行代码。
- 2026-09-30：**开始执行修复**。按报告 §5 顺序实现 F01/F03/F04/F08/F09(后端)/F12/F14/F15/F16/F17/F18/F19(就绪门禁)/F20；隔离契约检查由 **4 通过/20 失败** 变为 **24 通过/0 失败**（未放宽断言）。实现要点、framework 最小范围例外（F04）、随修复调整的既有测试、非 F 清单的可移植性修复与部署注意（`alembic upgrade head` 下发 `0003_turn_seq_unique`）见[报告 §8](../../docs/plan/web-runtime-trace-repair-report.md)。未完成项（F02/F05/F06/F07/F09 前端/F10/F11/F13/F21、F19 schema 门禁、E1 结转）在同一节列明，不得视为已验收。
- 2026-09-30：修复期间同批调整 `audit/run_audit.py` 的 Windows 可移植性（先导入 asyncio，放行事件循环自管道的 socketpair，并显式阻断 asyncio 子进程接口），隔离与断网保证不变，见 `audit/README.md`。
- 2026-09-30：**回溯核查与纠正**。① 契约文件 `audit/test_storage_chain.py` 相对 HEAD 零改动，24/24 的对比口径成立；② 发现并修复一处我引入的回归：`_signal_worker` 的 `terminate()` 回退在 `tests/test_stop_t28.py` 造成 3 次中 2 次无限挂起（修复前 3/3 正常），已改为无进程组 API 时不发信号；③ 发现我未收口的后台 pytest 进程（运行约 40 分钟）曾与后续测量共用 `server/dev.db`，已清理并重测；④ 修正此前"受影响文件逐一回到基线"的过度表述——实际只覆盖 9 个逐文件对比的用例集，全量套件因既有 Windows 挂起未完成。详见报告 §8。
- 2026-09-30：E1 执行完成（部分），结果与证据见[环境方案 §2.2](../../docs/plan/web-storage-validation-environment.md)与[批次登记](../../.scratch/web-runtime-trace-hardening/audit/e1-batch-registry.json)。新建 2 个专用测试账号并指向本地 mock（出口仅 loopback）；通过项：提交/worker 启动/轨迹/`/trace`/会话消息回填/上传落盘/协作式停止/前端与 `/api` 代理。新复现：纯文本正常结束被记为 `stopped(no_tool)` 且会话内容被标 `_[partial: no_tool]_`、`usage_json` 与 `started_at` 不落账、`llm_snapshot_json` 全库为空 JSON、运行结束后 SSE 无终态事件。**环境级阻断**：本机解释器缺 `os.getpgid/os.killpg`，`_kill_handle` 抛 `AttributeError` 使产物索引/用量入账/槽位释放被跳过且会话 drain 任务终止 —— 每两次运行后 worker 池耗尽、任何新 Run 只能 `queued`；同类回收路径使 shell 工具全部不可用，故产物索引/下载/回滚类用例在本机不可验收，须在 POSIX 环境复验。本批经批准重启过一次 API 收口 2 条 queued 残留（reconcile 置 `failed/server_restart`）。未复用真实业务会话，未修改运行代码。
- 2026-09-30：**F09 回溯核查完成，状态收口**。后端盲区（结束于其它进程的运行，`run_events` 仍订阅死队列）已按权威状态修复：`Orchestrator.has_worker` + `server/routes/runs.py::_live_queue_for`，本进程无 handle 且行状态非 queued/running → `sse_for_run` replay-only；本进程结束的流仍由 `_closed_stream_ids` 兜底。当日重跑三项证据：隔离审计契约 **24/24 通过**（独立报告 `audit/f09-recheck-results.json`，不覆盖 `post-fix-results.json`）、盲区回归 `tests/test_web_f09_stream_termination.py` **4/4 通过**、前端审计 `F09_steer_sequence_is_not_trajectory_cursor` **仍失败**（10 !== 0，`frontend-results.json` 已刷新）。结论：F09 后端=已修复并有动态证据，前端游标语义=未动，工单 [09](issues/09-stream-replay-contract.md) 维持 `ready-for-human`。本轮回溯未修改运行代码。
