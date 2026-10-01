# 06：定义并落实中断后的轨迹完整性

Status: ready-for-human
Priority: P1
Type: task
Requirements: PR-RUN-02, PR-GOV-02, PR-BIZ-05

## 问题与范围

见[报告 F06](../../../docs/plan/web-runtime-trace-repair-report.md#f06中断后的轨迹完整性契约不足)。
涉及共享记录器、worker/bridge、读取状态及架构文档；先明确耐久级别，不默认承诺每 token 永久保存。

## 修复前提与验收

- 定义 complete/partial/unavailable 与请求尝试身份；写入失败及未完成响应有可见缺口。
- 若要求恢复已显示片段，实现有边界的流式检查点；不另造互相冲突的轨迹真源。
- 隔离进程测试正常结束、取消、SIGKILL、磁盘错误、半行恢复；不得杀真实运行。
- 配置关闭必需 JSONL 时可检测；说明 flush 与物理持久的区别，修正文档过度保证。
- 对共享 observer 做 CLI/工作流回归，并记录失败尝试是否纳入本轮契约。

## Comments

- 2026-09-29：已确认轮次级记录与非持久 delta 的边界，尚未做故障注入。
- 2026-09-30：**先冻结耐久级别，再实现**（报告 F06 要求）。本轮承诺的最低级别：
  ① 已写入的**轮次级**记录可读并可知是否完整；② 缺口有显式状态；③ 关闭时有一次 `fsync`
  写入屏障。**明确不承诺**：未完成流式 delta 的持久化、每次失败/重试尝试的记录、断电或硬件
  故障下的绝对保证。
- 2026-09-30：**契约与判定**（只读，不依赖任何内存态——崩溃后内存态本就不存在）。
  新增 [server/trajectory_status.py](../../../server/trajectory_status.py)：
  `complete` = 存在终端 `{"t":"end"}` 记录；`partial` = 有记录但无终端标记（`on_loop_cancelled`
  与 SIGKILL 都不写它）；`unavailable` = 文件缺失/为空/不可读。末尾半行单独标记为
  `trailing_partial_line`，**不掩盖其之前的有效行**；中间的损坏行计入 `corrupt_lines` 而非致命。
- 2026-09-30：**暴露与展示**。`/trace` 响应新增 `completeness` 字段；
  [RunDetailView.vue](../../../web/src/views/RunDetailView.vue) 在 `partial`/`unavailable` 时于
  记录**旁**显示告警（不替换记录——partial 轨迹仍然可读）；`types.ts` 加 `TraceCompleteness`。
- 2026-09-30：**写入屏障（framework 最小范围例外）**。`TrajectoryFileObserver._close_jsonl` 在
  关闭前 `flush()` + `os.fsync()`，失败吞掉——屏障不能反而弄丢已写记录。只改这一处，不动
  调用协议、不改其他观察器。回归：
  `tests/test_compaction_observability.py`、`test_trajectory_recovery_handle.py`、
  `test_shared_fan_in_and_trajectory.py` **21/21 通过**。
- 2026-09-30：**证据**。新增 [tests/test_web_f06_trace_completeness.py](../../../tests/test_web_f06_trace_completeness.py)
  **10/10 通过**，覆盖：正常结束→complete、取消（无 end）→partial 且已写记录仍可读、
  文件缺失/为空→unavailable、末尾半行→标记且不掩盖前 2 条有效行、中间损坏行计数不致命、
  `as_dict()` 键形状稳定（前端依赖）、关闭 jsonl 格式时不落盘（配置缺失可检测）、
  fsync 屏障不抛错且不丢记录。负向对照：把判据改为「恒为 complete」→ **2 条断言失败**。
  前端 `vite build` 通过。
- 2026-09-30：**文档收窄**（F06 验收项）。[tech-stack.md](../../../docs/tech-stack.md) 顶部核查提示
  更新为「完整性可判定 + 仍需限定的三件事」；§5.2 表格「SIGKILL 后仍可回放」限定为已写入轮次；
  flush 段补 F06 边界说明（flush≠fsync、已加关闭时 fsync、非断电保证）；v1.2 修正 1、事件持久化行、
  §5.2 理由、ADR-4 四处「完整轨迹 / SIGKILL 安全」改为「进程被杀后已写记录仍可读（非断电保证）」。
- 2026-09-30：**仍未验收（故维持 ready-for-human）**：
  ① 真实故障注入未做——本轮用**合成文件**模拟崩溃留下的形状，未对真实 worker 执行
  SIGKILL / 取消 / 磁盘写满 / 断电，也未注入真实磁盘错误；
  ② 真实断电耐久需存储级验证，不能用进程 kill 测试替代；
  ③ **请求尝试身份**（失败/重试是否纳入契约）本轮未实现——已确认现状是「只保存已返回轮次」；
  ④ 流式检查点（恢复已显示文本）未实现：产品若要该能力需另立范围，本轮不承诺；
  ⑤ 前端提示未在浏览器验证（与 F05 同一限制）。
- 2026-10-01：**第 ⑤ 项完成**（隔离栈 + Playwright/Edge，记录见
  [e2e/f05e2e/e2e-record.md](../e2e/f05e2e/e2e-record.md)）：partial → warning alert
  「运行未正常结束，已保存的记录可读，但可能缺少最后一部分内容」且 9 条记录全部可读
  （告警在记录旁，不替代记录）；文件删除 → unavailable 文案 + 空态；complete → 无告警。
  过程中发现并修复 `RunDetailView.vue` 的条件链缺陷（已结束 Run 时间线不渲染，详见
  [工单 05](05-history-trace-ui.md) 2026-10-01 条目）。
  **仍未验收**：①② 真实故障注入（SIGKILL / 取消 / 磁盘写满 / 断电耐久）与
  ③ 请求尝试身份维持不变。`Status 维持 ready-for-human`。
- 2026-10-01：**SIGKILL 真实故障注入完成（WSL，真实 worker/真实链路）**（批次
  [e1-wsl-batch-registry.json](../audit/e1-wsl-batch-registry.json)）：mock 模型 25s 延迟制造
  流中窗口，`kill -9` worker 后——API `/healthz` 200 存活；Run **立即**收口
  `stopped/stopped_by=killed` 且 `finished_at` 落账（无需等重启 reconcile）；
  `/trace` 返回 `completeness={state:"partial", valid_lines:1, trailing_partial_line:false,
  corrupt_lines:0}`，reason 文案「运行未正常结束，已保存的记录可读，但可能缺少最后一部分内容」
  正确，已存 `t=start` 行可读。协作式取消（user_stop/no_tool 路径）已在本批 Run1/Run2 真链路
  再证。**仍未完成**：磁盘写满时的轨迹写入行为未做运行级注入（就绪门禁层面的磁盘满已在
  issue 19 覆盖）；断电耐久属存储级验证（维持不做）；请求尝试身份与流式检查点维持原范围决定；
  浏览器提示未验。
- 2026-10-01（下午）：**运行级磁盘写满注入完成（WSL，隔离库 + tmpfs，真实链路全跑）**（批次
  [e1-wsl-batch-registry.json](../audit/e1-wsl-batch-registry.json)，证据
  [f06-run-disk-full.json](../audit/f06-run-disk-full.json)）。隔离库 `apodex_f06_mem` + 容器
  `f06run`（`/data/runs` 用 `size=2m` tmpfs）+ 本地 mock（`MOCK_MODE=tool, DELAY=30s`），在 run
  在飞期间 `dd` 填到真实 ENOSPC（后续 1 字节写返回 0）。
  **结论**：① **在飞 run 不挂起**——ENOSPC 被非 critical observer 隔离吞掉（`trajectory.py` 各
  hook WARNING 一次后转 DEBUG），run 仍正常收口 `stopped/no_tool`、`finished_at` 落账；
  `/trace` 完整性判定**不误报**（真失败的读 `unavailable`、幸存的读 `complete`）。
  ② 但**发现三处新缺陷**（详见工单 [22](22-disk-full-queue-wedge.md)）：
  **F06-RUN-1（高）**：满盘时**新提交**的 run 返回 202 `queued` 后**永久卡在 queued**——
  [orchestrator.py](../../../server/orchestrator.py#L877-L880) `history_path.write_text` 抛 ENOSPC，
  被 [`_drain_session`](../../../server/orchestrator.py#L578-L590)（F15 路径）吞掉并 "continuing queue"，
  run 行**无终态**（`finished_at=None`），释放空间后仍 queued，只有重启孤儿清扫才关闭；根因是
  提交路径不消费 `/readyz`（此时 `/readyz` 正确 503 `data_root_unwritable`）。
  **F06-RUN-2（中）**：轨迹/用量丢失**静默无运行级信号**——run 行呈现为正常 `stopped` 且
  `final_answer` 非空，但 `react_agent.jsonl` 0 字节、`/trace` `unavailable`、usage
  `{llm_calls:0,status:unavailable}`（模型实际被调 2 次），原因只在 engine.log 留一条 WARNING。
  **F06-RUN-3（低）**：部分写入留下陈旧/孤立 0 字节侧车（`react_agent.json` 停在 start 快照、
  `.json.tmp`、`.messages.spool`、`summary.json` 0 字节——`server/worker.py` 的 summary 写未加保护）。
  **仍未完成**：断电耐久（存储级，维持不做）、请求尝试身份、流式检查点、真实供应商格式差异；
  F06-RUN-1/2/3 已于同日修复（见工单 [22](22-disk-full-queue-wedge.md)，回归
  `tests/test_web_f22_disk_full.py` 6/6）。`Status 维持 ready-for-human`。
