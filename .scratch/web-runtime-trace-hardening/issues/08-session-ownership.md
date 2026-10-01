# 08：提交 Run 缺少会话归属校验

Status: ready-for-human
Priority: P1
Type: task
Requirements: PR-GOV-06, PR-RUN-02

## 问题与验收

代码证据、影响、修复建议和完整验收见[报告 F08](../../../docs/plan/web-runtime-trace-repair-report.md#f08提交-run-缺少会话归属校验)。

- 实施前用隔离环境和合成数据固定触发条件，记录修复前行为。
- 按报告验收正常、失败和恢复路径，补充历史兼容性与回退影响。
- 只有动态验证通过才能关闭；源码检查不能替代端到端验收。

## Comments

- 2026-09-29：遗漏复核补充。源码路径已核对，动态复现与修复尚未执行。
- 2026-09-29 全面复核：双合成用户通过真实提交路由复现 202 和外部会话写入；现有外部 Run 读取保护仍通过。 执行结果见 `audit/` 及全面复核记录，未修复。
- 2026-10-01：**跨用户越权动态复验完成（WSL 真实 API + 业务库，E1 结转项）**（批次
  [e1-wsl-batch-registry.json](../audit/e1-wsl-batch-registry.json)）：专用账号 B 对账号 A 的
  session（`58855436-…`）提交 Run → **404 「会话不存在」**；零副作用核验——A 会话 turns=4 /
  runs=2 前后不变、无新 run 目录；B 省略 session_id 时会话列表为空（默认会话按用户命名空间
  隔离，`_session_uuid` 修复生效）。修复前行为（2026-09-29 隔离复现的越权写入）在新代码下不可复现。
