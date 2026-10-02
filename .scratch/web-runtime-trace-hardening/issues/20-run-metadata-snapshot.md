# 20：Run 模型快照与启动状态未接入持久化

Status: ready-for-human
Priority: P1
Type: task
Requirements: PR-GOV-01/03、PR-RUN-01

## 问题与验收

完整代码证据、复现边界、修复要求和验收见[报告 F20](../../../docs/plan/web-runtime-trace-repair-report.md#f20run-模型快照与启动状态未接入持久化)。
执行记录和覆盖矩阵见[存储链路复核](../../../docs/plan/web-storage-chain-audit.md)。

- 以隔离合成数据复现，不以真实账户/轨迹作为测试输入。
- 执行报告列明的正常、失败、恢复及兼容性验收。
- 未实现；相关失败断言是待修复证据，不能按“测试已执行”关闭。

## Comments

- 2026-09-29：全面存储复核新增，详见报告证据等级；运行代码尚未修改。
- 2026-10-02（复核补正）：登记此前漏记的**部分实现**（报告 §8 F20 行）——提交时落非密钥模型快照
  （`server/routes/runs.py` 调 `build_llm_snapshot`，`llm_snapshot_json` 不再为空）与 worker
  `run_started` 帧持久化 `running`/`started_at`；契约检查
  `test_submit_records_nonsecret_model_snapshot`、`test_run_started_event_updates_persistent_status`
  （`audit/test_storage_chain.py`）通过。
  **剩余验收缺口（未实现，故维持 ready-for-human）**：排队期间修改模型配置的语义未定义
  （快照取提交时配置还是实际执行配置）、默认连接失效/启动失败/重试下的归属准确性未端到端验收。
  更正口径：批次提交信息"剩余3项工单待决策是否实施"表述不准——本项主体已实现，剩余为上述语义与验收项。
