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
