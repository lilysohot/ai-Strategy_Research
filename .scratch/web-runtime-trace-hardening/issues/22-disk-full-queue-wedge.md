# 22：满盘时提交的运行永久卡在 queued（磁盘写满的运行级收口缺口）

Status: ready-for-agent
Priority: P1
Type: bug
Requirements: PR-RUN-02, PR-GOV-02
Depends on: 06, 19

## 问题与范围

2026-10-01 的 **F06 运行级磁盘写满注入**（证据
[f06-run-disk-full.json](../audit/f06-run-disk-full.json)，批次
[e1-wsl-batch-registry.json](../audit/e1-wsl-batch-registry.json)）暴露三处缺陷。范围是
「运行数据根满时，提交/收口/可观测性」的行为，不含断电耐久（属存储级验证，维持不做）。

## 缺陷

- **F06-RUN-1（高）**：运行数据根满时**新提交**的 run 被接受（`POST /api/runs` → 202 `queued`）
  后**永久卡在 `queued`**：run 行无终态（`finished_at=None`、`error=None`），释放空间后仍 queued，
  仅重启后的孤儿清扫才会关闭。触发点
  [orchestrator.py](../../../server/orchestrator.py#L877-L880) `history_path.write_text(history)` 抛
  `OSError [Errno 28]`，被 [`_drain_session`](../../../server/orchestrator.py#L578-L590)（F15 路径）
  捕获后只记日志「continuing queue」，**未给该 run 写任何终态**。根因是提交路径不消费 `/readyz`
  门禁——此时 `/readyz` 已正确返回 503 `data_root_unwritable`，但提交仍被接受。
- **F06-RUN-2（中）**：轨迹/用量丢失**静默无运行级信号**。run 行呈现为正常的 `stopped` 且
  `final_answer` 非空，但 `react_agent.jsonl` 为 0 字节、`/trace` 读 `unavailable`、usage 为
  `{llm_calls:0,status:unavailable}`（模型实际被调用 2 次）；原因只在 `engine.log` 留一条 WARNING。
- **F06-RUN-3（低）**：部分写入留下陈旧/孤立的 0 字节侧车（`react_agent.json` 停在 start 快照、
  `react_agent.json.tmp`、`react_agent.messages.spool`、`summary.json` 0 字节——`server/worker.py`
  的 summary 写未加保护）。

## 修复前提与验收

- F06-RUN-1：捕获处为该 run 写明确终态（如 `error`/`failed` 并记 `finished_at` 与原因），
  使「启动失败」不再等价于「永久 queued」；并让提交路径消费就绪门禁（满盘时拒绝提交或返回可读错误）。
- F06-RUN-2：磁盘写失败须产生**运行级**可见缺口（例如写入 run 行/摘要的降级标记），
  不能只留在 engine.log；不得反过来让写失败中断已能完成的运行。
- F06-RUN-3：清理/避免 0 字节侧车与陈旧快照，`summary.json` 写失败应可控。
- 回归：真实故障注入（tmpfs 满盘）复现 F06-RUN-1 不再发生；新增隔离用例覆盖
  「`_launch` 写 history 失败 → run 有终态」与「提交在未就绪时被拒」。

## Comments

- 2026-10-01：运行级磁盘写满注入发现上述三处缺陷（真实链路 + tmpfs 硬 ENOSPC）。
  在飞 run 本身**不挂起**（正常收口 `stopped/no_tool`），`/trace` 完整性判定**不误报**；
  缺口集中在「满盘时**新提交**的收口」与「写失败的**可观测性**」。证据见上。尚未修复。