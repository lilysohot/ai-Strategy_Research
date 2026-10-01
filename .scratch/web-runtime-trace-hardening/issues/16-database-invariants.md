# 16：消息序号与关系约束不足

Status: closed
Priority: P1
Type: task
Requirements: PR-RUN-01、PR-GOV-01/06

## 问题与验收

完整代码证据、复现边界、修复要求和验收见[报告 F16](../../../docs/plan/web-runtime-trace-repair-report.md#f16消息序号与关系约束不足)。
执行记录和覆盖矩阵见[存储链路复核](../../../docs/plan/web-storage-chain-audit.md)。

- 以隔离合成数据复现，不以真实账户/轨迹作为测试输入。
- 执行报告列明的正常、失败、恢复及兼容性验收。
- 未实现；相关失败断言是待修复证据，不能按“测试已执行”关闭。

## Comments

- 2026-09-29：全面存储复核新增，详见报告证据等级；运行代码尚未修改。
- 2026-10-02（复核关闭）：验收条款逐条复核通过——每连接 `PRAGMA foreign_keys=ON`（test_sqlite_declared_foreign_keys_are_enforced）、
  turns 唯一索引（迁移 0003_turn_seq_unique）+ append_turn 冲突重试（test_concurrent_message_sequence_is_unique
  8 并发 seq 全唯一）均有契约断言；历史库盘点与迁移落地：2026-10-01 业务库迁至 0004 head
  （0003 迁移预检无重复 (session_id, seq)、迁移前 pg_dump 备份、迁移前后行数不变、/readyz 翻绿）；
  Run 与 Session 归属一致经服务准入（F08：E1-WSL B 账号越权提交 404 + 零副作用）与 PG 侧外键语义核验
  （f07-key-ondelete-drill：真实业务库 dump 隔离库 12 FK 全 NO ACTION、三路硬删全拒）；
  既有测试绕过约束的 fixture 惯例已按报告修正（补齐父行）。复跑隔离契约 24/24。转 closed。
