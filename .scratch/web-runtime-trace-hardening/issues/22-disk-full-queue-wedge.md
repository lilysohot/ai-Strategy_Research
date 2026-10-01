# 22：满盘时提交的运行永久卡在 queued（磁盘写满的运行级收口缺口）

Status: ready-for-human
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
- 2026-10-01（修复）：三处缺陷已修，回归 `tests/test_web_f22_disk_full.py` **6/6 通过**。
  - **F06-RUN-1**：① 提交路径消费数据根探针——[server/routes/runs.py](../../../server/routes/runs.py)
    的 `submit_run` 在**任何副作用前**调用 `probe_data_root()`，满/只读时 503「运行数据根不可写」，
    不再接受无法持久化的运行（测试 `test_submit_rejected_when_data_root_unwritable`）；
    ② 启动失败即收口——[server/store.py](../../../server/store.py) 新增
    `mark_run_failed_if_active`（仅当 run 仍在 `ACTIVE_RUN_STATUSES` 时写 `failed`+`error`+`finished_at`，
    终态 run 绝不覆盖），[server/orchestrator.py](../../../server/orchestrator.py) 的
    `_drain_session` 捕获 `_spawn` 异常后调用 `_mark_launch_failed` 落终态（测试
    `test_launch_failure_closes_run_instead_of_wedging` / `..._never_overwrites_terminal_run`）。
  - **F06-RUN-2**：干净完成的 run 若其 `react_agent.jsonl` **存在但 0 字节**（写失败签名，
    区别于「配置关闭→无文件」），在助手轮追加可见标记
    `_[存储降级：轨迹未落盘，用量不可统计]_`——`orchestrator._backfill_assistant_turn` +
    `_trajectory_degraded`（测试 `test_clean_completion_with_empty_trajectory_gets_degradation_marker`、
    `test_clean_completion_with_records_gets_no_degradation_marker`、
    `test_missing_trajectory_file_is_not_marked_degraded`）。`/trace` 与 usage 的
    `unavailable/partial` 信号维持不变。
  - **F06-RUN-3**：[server/worker.py](../../../server/worker.py) 的 `summary.json` 改为
    **tmp+`os.replace` 原子写**且失败只告警不遮结果；[trajectory.py](../../../frontier_agent/components/observers/trajectory.py)
    的 `_flush_json` 在 `_write_envelope`/`os.replace` 失败时清理残留 `.tmp`，
    `_close_message_spool` 在 spool 为 0 字节时删除（无任何可恢复内容）。
  - 证据链：`uv run pytest tests/test_web_f22_disk_full.py -q` 6/6；
    F19/F06/orchestrator/framework 轨迹套件 71/71；全量 `tests` 相对 HEAD 无新增失败
    （`test_web_p2_files.py` 6 错误与 corpus/research 3 失败为 HEAD 既有、环境相关，已复跑确认）。
  **验收**：F06-RUN-1/2/3 的契约均达成；「满盘提交 → 503」与「启动失败 → run 有终态」
    有回归守护。业务库 schema 未动（0002）。`Status 维持 ready-for-human` 待浏览器/部署复核。
- 2026-10-01（真实注入复验 + 镜像重建）：按工单验收要求对**修复后镜像本体**重跑运行级注入
  （隔离库 `apodex_f22_verify` + `--tmpfs /data/runs:size=2m`，`frontier-agent-web:head`
  重建为 `b903e9e28900`，镜像内断言 submit 门禁/`mark_run_failed_if_active`/
  `_mark_launch_failed`/`_trajectory_degraded` 均存在）：
  空盘基线提交 **202** → `dd` 填满至真实 ENOSPC（df 100%，`/readyz` 503 `data_root_unwritable`）→
  满盘提交 **503** `{"detail":"运行数据根不可写（磁盘满或只读），无法持久化新的运行"}`，
  被拒请求**零副作用**（turns 仍为基线 1 条，无新 run 行）——「满盘不再 202、不再永久 queued」成立。
  清理：容器 `f22v` 移除、隔离库 DROP、业务库 `apodex` 复核仍 `0002_run_usage`。