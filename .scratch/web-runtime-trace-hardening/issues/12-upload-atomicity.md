# 12：上传校验与运行创建缺少失败清理

Status: ready-for-human
Priority: P1
Type: task
Requirements: PR-GOV-01, PR-GOV-06

## 问题与验收

代码证据、影响、修复建议和完整验收见[报告 F12](../../../docs/plan/web-runtime-trace-repair-report.md#f12上传校验与运行创建缺少失败清理)。

- 实施前用隔离环境和合成数据固定触发条件，记录修复前行为。
- 按报告验收正常、失败和恢复路径，补充历史兼容性与回退影响。
- 只有动态验证通过才能关闭；源码检查不能替代端到端验收。

## Comments

- 2026-09-29：遗漏复核补充。源码路径已核对，动态复现与修复尚未执行。
- 2026-09-29 全面复核：ASGI 多文件上传批次被拒后残留首个文件已复现。 执行结果见 `audit/` 及全面复核记录，未修复。
- 2026-10-02（复核补正）：登记此前漏记的**部分实现**（报告 §8 F12 行）——
  `server/routes/runs.py` 上传批次改为**全或无**：首个文件写入后任何失败（字节超限/IO/后续文件超限）
  都会 `shutil.rmtree` 整个 per-run 目录，不再遗留无 Run 索引的孤儿；契约检查
  `test_f12_rejected_batch_leaves_no_uploaded_files`（`audit/test_storage_chain.py`）通过。
  **剩余验收缺口（未实现，故维持 ready-for-human）**：同名/扁平化冲突仍无处理——`_flatten_filename`
  只取 basename，两个同名上传后者 `dest.write_bytes()` 直接覆盖前者（工单验收要求的"拒绝冲突名或
  生成唯一存储名"未做）；分块限额写入暂存区、入队失败补偿契约亦未端到端验收。
  更正口径：批次提交信息"剩余3项工单待决策是否实施"表述不准——本项主体已实现，剩余为上述缺口。
