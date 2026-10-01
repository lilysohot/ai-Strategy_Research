# Web 运行存储与轨迹追溯修复

Status: partial — F01 closed（2026-10-01）；其余 20 项进度见 issues/ 与报告 §8
Type: repair-spec
Date: 2026-09-29

用户要求将本次发现整理为后续修复报告，未要求本轮实施修复或迁移数据。
后续用户明确要求存储位置不合理时在此次修复一并改正：F01 已升级为必交付范围，
具体新路径、历史迁移和回退验收见报告 v1.4。2026-09-30 起进入实施：报告 §8 记录已实现项与证据，
F01 于 2026-10-01 完成并关闭；其余未完成项见 §8「仍未完成」。

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

Status 行遵循仓库 triage labels；各工单已分诊（F01 于 2026-10-01 closed），不代表可无人值守迁移生产数据。
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
- 2026-09-30：**F10/F11 修复完成**。F10（`runs.ts` + `statusbar.ts`）：按轮保存文本、回放的整轮记录**替换**该轮而非被跳过（缺字可被完整副本修复，且重复回放幂等），usage 计量移到文本判定之前**独立处理**，`reconcile` 新增 `usageTotalsFrom()` **替换**总量而非累加。F11（`runs.ts`）：订阅代次 `generation`（`watch`/`reset` 递增），`reconcile` 在 `await` 后校验 runId+代次并丢弃过期响应；摘要失败时给可见「待核实」提示，不凭 EOF 推定成功。证据：既有 `audit/frontend-audit.mjs` 的 F10×3、F11×1 由 **failed 全部转 passed**（连同 F09 共 **5/5**），负向对照逐项确认（回放改追加 → 文本断言失败；`reconcile` 改累加 → `20 !== 10`；禁用回放用量 → `0 !== 10`；移除代次校验 → 旧摘要覆盖）。回归：`vue-tsc --noEmit` 0 错误、前端单测 **66/66**、`vite build` 通过、F05 审计仍通过。**未完成**：真实浏览器端到端（断线重连缺字补齐、切换 Run/登出/重试期间的迟到响应）。工单 [10](issues/10-replay-text-usage.md)、[11](issues/11-watch-generation.md) 维持 `ready-for-human`。
- 2026-09-30：**F01 容器侧配置与文档已同步**`deploy/Dockerfile.web` 移除源码树内的 `VOLUME ["/app/server/runs","/app/uploads"]`（会静默创建匿名卷）；`deploy/docker-compose.yml` 增加 `SERVER_RUNS_ROOT=/var/lib/frontier-agent/web/runs` 并把 `agent_data` 卷挂到 `/var/lib/frontier-agent/web`（保留卷名以维持卷身份）；`deploy/README.md` 与 `docs/tech-stack.md` §7.1 更新为已对齐；`.env.example` 补 `SERVER_RUNS_ROOT` 说明。验证：`docker compose config --quiet` 退出码 0，`--profile full config` 解析出正确挂载点与变量。容器从未部署过（`agent_data` 卷不存在、无 Web 容器），故为纯配置改动、无数据迁移。**未完成**：容器实测（镜像无法构建，registry 不可达）、WSL 663 条与 /tmp 85 条历史兼容、活动 Run 跨根保护；工单 [01](issues/01-storage-roots.md) 维持 `ready-for-human`。
- 2026-09-30：**F01 本机 Windows 目录迁移完成**（范围经用户确认：仅本机，WSL 不动）。`server/config.py::runs_root` 默认移到源码树外（Windows `%LOCALAPPDATA%\frontier-agent\web\runs` / POSIX XDG，保留 `SERVER_RUNS_ROOT` 覆盖），移除无消费者的 `uploads_root` 与空 `uploads/` 目录；`scripts/run_retention.py migrate-runs-root` 迁移本机 4 个 run 目录 + 同步 DB `run_dir` 6 条 + 清理 99 个孤儿磁盘目录；`server/runs` 103→0，迁移后轨迹 `state: complete` 可读，回归 80/80。**未完成**：容器卷/Dockerfile VOLUME 同步、WSL 663 条与 /tmp 85 条历史兼容、活动 Run 跨根保护、环境样例同步；工单 [01](issues/01-storage-roots.md) 维持 `ready-for-human`。
- 2026-09-30：**T6 第 1 步已完成（处置已执行）**。口径由用户确认：517 条无 session 的 runs 删除（二次校验 turns=0/artifacts=0）、17 runs+18 sessions+29 audit_log 挂占位 user、11 条无 run 的 turns 解除悬挂引用（`run_id=NULL`，不制造占位 run）。执行前取 pg_dump 快照（容器内 `/tmp/apodex-pre-t6.dump`，回滚唯一依据），单事务执行。处置后 `check` 为 **verdict clean**（七类全 0），runs 1271→754、users 28→29，turns/artifacts/audit_log 一条未丢。**恢复演练复演通过**：`pg_restore` 零错误、外键 **9/9**（此前 4/9）、7 表行数逐一一致 → T5 完成标准「恢复演练成功、行数一致」达成。遗留：运维备份脚本与异地存放、联合恢复演练、T6 第 2/3 步（会话删除语义、ON DELETE 迁移）。另发现容器 /tmp 有 9/15、9/23 的历史 dump（既有，含真实数据且随容器重建丢失，不能当备份）。
- 2026-09-30：**T6 第 1 步的统计/导出部分已执行**（只读，未动存量数据）。`scripts/run_retention.py orphans` 导出 `audit/f07-orphan-inventory.json`（20,967 B，仅标识符与时间戳）：合计 **592 条孤儿行** —— runs→缺失 session **517**（**连带 turns 0 / artifacts 0，即空壳 run**）、runs→缺失 user 17（连带 21 turns）、sessions→缺失 user 18（连带 18 runs + 24 turns）、turns→缺失 run 11、audit_log→缺失 user 29，另两类为 0。**关键**：517 条与另外两类性质不同，不可套用同一处置口径。每类附三项候选处置（挂占位 / 删除 / 保留但标记），**处置决策与执行待人工确认**，脚本只读不执行。测试 22/22 通过。
- 2026-09-30：**F07 执行完成（部分），并得出对 F01 有直接影响的结论**。① 真实恢复演练（E2：只读业务库 + 同实例独立库 `apodex_f07_restore`，演练后已 DROP、dump 未落宿主）：`pg_dump -Fc` 225,999 B → `pg_restore` **7 表行数逐一一致**，但**恢复库只建成 4/9 外键**，5 个 `ADD CONSTRAINT` 被孤儿行阻断 → **备份存在 ≠ 可恢复，F01 迁移前必须先处置孤儿（T6）**。② 孤儿已量化并可复跑：`scripts/run_retention.py check` 实测 runs→session **517**、runs→user 17、sessions→user 18、turns→run 11、audit_log→user **29**、artifacts→run 0；`turns.run_id IS NULL` 的 45 条合法不计入。③ 文件侧工具 `scripts/run_retention.py`：`manifest`/`plan`（默认 dry-run，缺失≠过期）/ `verify` / `check`。证据：`tests/test_web_f07_retention.py` **20/20 通过**，负向对照（禁用活动保护与缺失区分）**5 条失败**，文件侧 CLI 演练四类 run 正确。T5/T6 在 web-platform-hardening.md 已更新为「部分完成 / 进行中」。**未完成**：运维备份脚本与异地存放、联合恢复演练、孤儿处置决策与 ON DELETE 迁移、保留期定值；工单 [07](issues/07-retention-recovery.md) 维持 `ready-for-human`。
- 2026-09-30：**F06 执行完成（部分）**。先冻结耐久级别：承诺「已写轮次记录可读 + 缺口有显式状态 + 关闭时 fsync 屏障」，明确不承诺未完成流式 delta、失败尝试记录与断电/硬件保证。实现：新增 `server/trajectory_status.py` 判定 `complete`（有终端 `{"t":"end"}`）/ `partial`（无终端标记，取消与 SIGKILL 均不写）/ `unavailable`，末尾半行单独标记且不掩盖前序有效行；`/trace` 返回 `completeness`，历史页在记录旁告警（partial 仍可读，不替换记录）；`TrajectoryFileObserver._close_jsonl` 关闭前 fsync（framework 最小范围例外，失败吞掉）。证据：`tests/test_web_f06_trace_completeness.py` **10/10 通过**（负向对照：判据恒为 complete → 2 条失败），共享 observer 回归 **21/21**，`vite build` 通过。`tech-stack.md` 四处「完整轨迹 / SIGKILL 安全」已收窄为「进程被杀后已写记录仍可读（非断电保证）」。**未完成**：真实故障注入（SIGKILL/取消/磁盘写满/断电耐久）、请求尝试身份、流式检查点、浏览器验证；工单 [06](issues/06-trace-completeness.md) 维持 `ready-for-human`。
- 2026-09-30：**F05 执行完成（部分）**。修复前为源码事实：`RunDetailView.vue::shortResult` 固定 300 字符静默截断、`llm` 模板从不读 `thinking`。实现：展示逻辑抽到 `web/src/utils/traceView.ts`（依赖自由可审计），推理按轮折叠且仅散文型可展示（absent/empty/restricted 各有文案，加密签名块绝不冒充可读解释），工具结果改为「预览 + 继续读取」有界解锁并显示剩余/总数，切片按 code point，切换 Run 重置展开；`types.ts` 补 `thinking?`/`thinking_blocks?`；F03 脱敏边界未移动。证据：新增 `audit/frontend-f05-audit.mjs` **10/10 通过**（负向对照 3 条失败）、`tests/test_web_f05_trace_projection.py` **4/4 通过**（`/trace` 保留 thinking、不扁平化 thinking_blocks、仍脱敏）、`vite build` 通过。**未完成**：浏览器 DOM 层验收（刷新/切研究/长文本/无推理/权限失败/键盘操作）——本机未装浏览器自动化依赖；工单 [05](issues/05-history-trace-ui.md) 维持 `ready-for-human`。
- 2026-09-30：**F09 前端游标语义修复完成**（工单 09 的最后一项缺口）。后端 `Orchestrator.steer` 的 `steer_queued` 由 `seq` 改为独立字段 `steer_seq`（HTTP 响应体 `body["seq"]` 保持不变，那是 API 契约）；前端 `web/src/sse.ts` 新增 `CONTROL_EVENT_TYPES`，控制帧不再推进轨迹游标。前端审计 `F09_steer_sequence_is_not_trajectory_cursor` 由 failed(10!==0) → **passed**（修复前结果另存 `frontend-results-before-f09-cursor.json`）；双向负向对照（移除前端守卫 / 还原后端 `seq=`）均使断言回归失败；`tests/test_web_f09_stream_termination.py` 4/4 无回归。**仍未验收**：真实浏览器下 steer 后重连不跳行；工单 [09](issues/09-stream-replay-contract.md) 维持 `ready-for-human`。另：`test_steer_route_*` 3 条失败于 F16 外键启用后 fixture 缺父行，与本次无关（负向对照前后均失败）。
- 2026-09-30：**F02 执行完成（部分）**。修复前用合成 sentinel 在临时构建目录复现（运行数据确实进入镜像内容，整 context 探针命中 6 处）→ 修根 `.dockerignore`：排除 `server/runs/`、`uploads/`、`data/`、`server/*.db`、前端产物与本地大目录；附带修 `**/__pycache__/`（原规则只匹配根级）与惰性 `web/.dockerignore`（前端以仓库根为 context，该文件从不生效，规则已镜像到根）→ 修复后真实仓库 context 33.18 MB / 1110 文件，运行数据与本地大目录全 absent、构建输入全 present，`COPY server ./server` 成功（30 个 `.py`，无 runs/uploads/pyc）；回归 `tests/test_build_context_ignore.py` **40 通过**，负向对照（移除 `server/runs/` 后 4 条失败）确认非空测试。**未完成**：真实 `deploy/Dockerfile.web` 镜像构建（registry 不可达），工单 [02](issues/02-build-context.md) 维持 `ready-for-human`。依据是 `FROM scratch` 探针，不是真实镜像层。
- 2026-09-30：**F09 回溯核查完成，状态收口**。后端盲区（结束于其它进程的运行，`run_events` 仍订阅死队列）已按权威状态修复：`Orchestrator.has_worker` + `server/routes/runs.py::_live_queue_for`，本进程无 handle 且行状态非 queued/running → `sse_for_run` replay-only；本进程结束的流仍由 `_closed_stream_ids` 兜底。当日重跑三项证据：隔离审计契约 **24/24 通过**（独立报告 `audit/f09-recheck-results.json`，不覆盖 `post-fix-results.json`）、盲区回归 `tests/test_web_f09_stream_termination.py` **4/4 通过**、前端审计 `F09_steer_sequence_is_not_trajectory_cursor` **仍失败**（10 !== 0，`frontend-results.json` 已刷新）。结论：F09 后端=已修复并有动态证据，前端游标语义=未动，工单 [09](issues/09-stream-replay-contract.md) 维持 `ready-for-human`。本轮回溯未修改运行代码。
- 2026-09-30：**F01 WSL 侧目录迁移完成（口径经用户确认）**。核查纠正前提：所谓"663 条 run 在 `/home/administrator/FrontierAgent`"实为 DB `run_dir` 行数（=663），磁盘仅 **244 个在位、419 个已缺失**（全盘 find 无果）；该根下共 837 个磁盘目录，另 **593 个不被 DB 引用**（含 09-23 后 386 个）。用户确认口径：**孤儿一律不删**、**缺失行保持指向旧根不改写**。改动 `scripts/run_retention.py`：`migrate-runs-root` 新增 `--keep-orphans`（不再 `rmtree` 未引用目录）与 `--only-moved`（仅为真正移动的 run 改写 `run_dir`），`_apply_root_migration(..., remove_orphans=, only_moved=)`，**默认行为不变**。验证：`ruff check` 通过、`tests/test_web_f07_retention.py` **22/22 通过**、一次性库 `apodex_f01_sim`（已 DROP）端到端对照——`--keep-orphans --only-moved` → moved 3/missing 1/**removed 0** 且缺失行未改写；默认 → **removed 2** 且缺失行被改写（旧行为未回归）。
  迁移前备份（F07 依赖，仓库外、非容器 `/tmp`）：`~/.local/share/frontier-agent/backups/f01-wsl-20260930/` —— `apodex-pre-f01.dump` 183,697 B（`pg_restore --list` 61 项、含 `runs` TABLE DATA）、`server-runs-pre-f01.tar.gz` 7,451,755 B、`SHA256SUMS`。
  执行：`migrate-runs-root --old-root <repo>/server/runs --apply --yes --keep-orphans --only-moved` → **moved 244 / already missing 419 / removed 0**。守恒：目录 593+244=**837**、文件 3459+1688=**5147**（与基线一致，零丢失）；DB `run_dir`：新根 **244**、旧根 **419**（未改写）、`/tmp/x` 85、Windows `C:\…` 6 均未触碰。`SERVER_RUNS_ROOT=/home/administrator/.local/share/frontier-agent/web/runs` 写入 `.env`（与 `--new-root` 默认一致），API 重启（旧 64560 → 新 49379，`/healthz` 200，启动日志无 error）。
  **历史兼容实测（无需改代码）**：`inspect_trajectory` 对 `/tmp/x`（14f0f50d…）与 419 缺失（108cb00e…）均返回 `unavailable`（"轨迹文件不存在"），已迁移 run（3bc0621f…）返回 `complete` —— F06 三态已覆盖三类，不会渲染为空轨迹。证据落盘 `audit/f01-wsl-migrate-dryrun.txt`（663 行）与 `audit/f01-wsl-orphan-dirs.json`（593 条）。孤儿已归档：593 个（19.4 MB / 3459 文件）整体移到仓库外 `~/.local/share/frontier-agent/archive/f01-orphans-20260930/runs/`（附 `MANIFEST-orphans.json`），`server/runs` 现为 **0**，源码树不再残留运行数据。**未完成**：容器实测、活动 Run 跨根保护仍未做；工单 [01](issues/01-storage-roots.md) 维持 `ready-for-human`。
- 2026-09-30：**F01 回退演练完成（隔离复演，生产全程未触碰，已清理）**。在独立库 `apodex_f01_rollback` + 临时根重建迁移前状态（`pg_restore` 零错误、7 表行数与外键 **9/9** 吻合；tar 解包 **837** run 目录 / 5147 文件），再模拟 **3** 条"切换后新写入"（2 completed + 1 running）并留存 post 快照。**负向对照**：仅把 `SERVER_RUNS_ROOT` 切回旧根 → 3/3 新写入 `dir_exists=False`、`unavailable`；仅恢复 pre 业务库 → 新写入 3 行**归零**——"只改根目录变量"被证伪。**正向四步**：恢复业务库 + 文件回位 + 合并切换后行 + **重定位 `run_dir`**。终验全过：文件守恒 **840 目录 / 5168 文件**、切换后文件 sha256+size **21/21**、引用完整性 **247 可解析 / 510 缺失**、轨迹三态 post `complete`/`partial`/`complete`、外键 9/9。机理：读取侧一律走 `run_dir_for(id)` 而非表中存储的 `run_dir`（`orchestrator._read_run_summary(row.run_dir)` 与 `routes/runs.py` 响应除外，故合并后必须重定位）。证据 `audit/f01-rollback-drill.json`。**未完成**：容器实测、活动 Run 跨根保护；工单 [01](issues/01-storage-roots.md) 维持 `ready-for-human`。
  另需留痕（越界操作）：演练清理时误删容器内 `/tmp/apodex-pre-t6.dump`（T6 处置前 pre 快照，工单 07 原记"保留"）。该文件位于容器 `/tmp`，按原口径本随容器重建丢失；F01 备份（宿主侧、仓库外）完好，F01 回退能力不受影响，但该 T6 回滚点已不可恢复。已记录于工单 [07](issues/07-retention-recovery.md)。
- 2026-09-30：**F01 活动 Run 跨新旧根保护完成（拒绝式，口径经用户确认）**。根因：`_plan_root_migration` 不区分状态，`_apply_root_migration` 会搬走 queued/running 的目录并改写 `run_dir`，而 worker 的绝对路径在 spawn 时从旧根烘焙、读取侧一律走 `run_dir_for`（当前根）→ 同一条 run 一半写旧根一半读新根。口径：不"跳过/延后"（延后是同一分裂反过来的形态），而是**整体拒绝**、不做部分迁移。实现 `scripts/run_retention.py`：`RunMigration.status`、纯函数 `active_migrations()`、`_refuse_active_migrations()`，`_apply_root_migration` 在移动前守卫并以 `SystemExit` 退出 1；dry-run 标 `ACTIVE-REFUSED` 并打印 `REFUSES TO APPLY`。证据：`tests/test_web_f07_retention.py` **27/27**（新增 5 项；负向对照注释守卫后该用例 `DID NOT RAISE` 失败）；一次性库 `apodex_f01_active`（已 DROP、临时目录已删、业务库未触碰）端到端——活动 run 存在时 `--apply` 拒绝且零移动，改终态后 `moved 2 / run_dir` 全部改写；真库干跑无回归（419 条 / 0 孤儿 / 无拒绝）。**未完成**：仅容器实测（见工单 02）。工单 [01](issues/01-storage-roots.md) 维持 `ready-for-human`。
- 2026-10-01：**F01 迁移冲突处理完成**（报告要求「发现新旧同 ID 文件冲突时停止该项并报告，不覆盖未知内容」，上一轮列为未修）。根因：`_apply_root_migration` 对已存在目标无检查，`shutil.move(src, dst)` 在 `dst` 已是目录时会把 `src` 移进 `dst` 之内并仍改写 `run_dir`（若 `dst` 是文件则覆盖）。实现：`RunMigration.target_exists`；apply 在移动前按活文件系统复核 `dst.exists()`，命中即计入 `conflicted` 且**不移动不改写**、其余照常，返回值扩为 `(moved, missing, removed, conflicted)`；dry-run 标 `TARGET-EXISTS`/`WILL SKIP`，apply 打印 `CONFLICT`。证据：`tests/test_web_f07_retention.py` **30/30**（负向对照短路 `if False` 后冲突用例失败）；一次性库 `apodex_f01_conflict`（已 DROP、临时目录已删）端到端 `moved 1 / CONFLICT 1`、目标目录零嵌套零覆盖、冲突行 `run_dir` 不动。
- 2026-10-01：**F01 容器实测完成（首次），并暴露一个致命部署缺口**。此前记录的 registry 阻断为**瞬时故障**：本轮 `docker pull python:3.12-slim` 成功、容器内 `apt-get` 直连 `deb.debian.org` 正常，`docker build -f deploy/Dockerfile.web -t frontier-agent-web:verify .` **exit 0**（1.64 GB / 18 层，runtime stage `python:3.12-slim`，`uv sync` 各 extra 全部完成）。**卷落点**：compose 等价容器内 `runs_root=/var/lib/frontier-agent/web/runs`、`run_dir_for()` 落该根、`ensure_dirs()` 在卷内建出 `runs/`，两种 id 写法解析到同一目录；负向对照——不设 `SERVER_RUNS_ROOT` 时容器读到挂载 `.env` 的**宿主 WSL 路径**，证明该 env 行必需。**重建后可读**：卷内 seed 1 条 completed run → `docker rm -f` + 同卷重启 → 轨迹与 `summary.json` sha256 **逐字节一致**、`inspect_trajectory` 仍可读、DB 行完好、`/healthz` 200。**新缺陷（致命）**：`deploy/docker-compose.yml` 覆盖了 `CORPUS_DSN` 却未覆盖 `SERVER_DATABASE_URL`，而 `server/config.py` 的 `env_file=/app/.env`（compose 已挂载）→ 容器内解析为 `…@localhost:5432/apodex`，实测 `ConnectionRefusedError` → `/healthz` **503 `storage_unavailable`**；且默认指向**生产库名**（因不可达才未误连）。**镜像层核对（闭合工单 02 遗留项）**：真实镜像内 `server/runs`、`uploads`、`data`、`.git`、`.venv`、`.scratch`、`web/node_modules`、`web/dist` 全 absent、`*.pyc` 0、无 `server/*.db`，关键源码全 present。隔离与清理：一次性库 `apodex_f01_container` 已 DROP（仅剩 `apodex`）、临时卷与两个测试容器已删、业务库未触碰。**未完成**：修 `SERVER_DATABASE_URL` 容器覆盖（待确认口径）。工单 [01](issues/01-storage-roots.md) 维持 `ready-for-human`。
- 2026-10-01：**F01 致命部署缺口已修 + 工单 01 关闭**（口径经用户确认：比照 `CORPUS_DSN`）。上条暴露的 `SERVER_DATABASE_URL` 容器覆盖缺口：`deploy/docker-compose.yml` 的 `api.environment` 增 `SERVER_DATABASE_URL: ${SERVER_DATABASE_URL_DOCKER:-postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/apodex}`；仓库根 `.env` 与 `.env.example` 各增 `SERVER_DATABASE_URL_DOCKER`（注明容器内须用宿主地址、scheme 必为 `+asyncpg`、业务 `apodex` ≠ 语料 `postgres`）；`deploy/README.md` 增「数据库连接（业务库 / 语料库）」一节并修正备份说明（原「数据库与 trace 在 `../data`」不实——`../data` 只放语料）。**验证**：`docker compose --env-file ../.env --profile full config` 现解析出 `SERVER_DATABASE_URL`（修复前缺失）、exit 0；隔离库 `apodex_f01_dbfix` 端到端——`host.docker.internal` → `/healthz` **200 `{"status":"ok"}`**，负向对照 `localhost` → **503 `storage_unavailable`**；回归 `tests/test_web_f07_retention.py` **30/30**。隔离资源全清理，生产 `apodex` 未触碰。**工单 [01](issues/01-storage-roots.md) `ready-for-human` → `closed`**。附观察（既有前提，未修）：`host.docker.internal` 在原生 Linux 引擎需 `extra_hosts: host-gateway`，`CORPUS_DSN` 同此前提，Docker Desktop（WSL2/Windows）不受影响。
