# 10 DATA-15 分阶段联合验收与成本（server-side DATA 部分）

Type: task
Status: resolved
Blocked by: 09

## 目标

- **可控模型端到端联合验收**：真 PG + 真实 worker 子进程 + MockLLMServer，覆盖
  提交（PG 快照冻结）→ outbox 派发 → worker 执行 → 轨迹/产物/diff 文件链路 →
  Run 终态与用量计量 → 快照不变（AC-06）；生成物直接通过 DATA-14 恢复核对
  （AC-18 在活体数据上复核）。
- **成本计量汇总**（AC-20）：`server/usage.py::usage_summary_for_runs` 对一组 Run
  汇总模型调用、输入/输出、**缓存读写分列**（不只命中率）与墙钟延迟，供同一组
  任务的正确率/费用比较报告使用；缓存读写分列以合成轨迹锁定。
- **AC/场景映射**：把 DATA-15 要求逐条映射到既有证据（test_run_dispatch 租约回收 =
  领取后崩溃及恢复、所有者隔离、监控零模型与预算、幂等重放等），缺口如实登记。

## 验收

- 真 PG 联合测试全过（真实 worker 链路 + 用量计量 + 快照不变 + restore_check）；
  门禁全过；证据脱敏存档 `evidence/data15-pg.log`。
- 未通过项/范围外项登记为缺口：UI-11 浏览器完整流程（UI 任务侧）、真实供应商
  协议/行情时效受控试运行（需真实凭据，随部署执行）、AC-20 输入正确率比较
  （需真实任务集）、重复规则/冷却（D 阶段扩展，C 阶段仅 single 模式）。

## 契约要点

- 用量真源是轨迹文件（`react_agent.jsonl` 的 `t=="llm"` 行），终态一次性聚合回写
  Run 行；汇总函数只读不改写。
- 本批不新增业务表与迁移；不承诺尚未实测的节省比例；模拟行情/模型通过不宣称
  生产实时性/计费已验收（PRD §10 明示）。

## Comments

2026-10-07：DATA-14 收口后开始。UI-11 浏览器流程不属本仓库 server 批次，交接 UI 任务清单。

## Resolution（2026-10-07）

**实现**

- `server/usage.py::usage_summary_for_runs(runs)`（AC-20）：对一组 Run 汇总模型调用、
  输入/输出/总量、**缓存读写分列**、reasoning 与墙钟延迟（started_at→finished_at）；
  未计量 Run 以 0 值可见，不静默丢弃；只读不改写。聚合真源仍是轨迹文件
  （终态一次性回写 Run 行，`usage_json.status` 区分 complete/partial/unavailable，
  不确定的 LLM 尝试如实计量——F06 attempt 身份行可对账）。
- `tests/pg/test_data15_joint.py`（3 项）：
  1. **真实 worker 端到端**：路由提交（PG 快照冻结）→ outbox 领取 → 真实
     `Orchestrator` 派发真实 worker 子进程（用户 LLM 配置走真实解密注入链到
     MockLLMServer）→ 轨迹/diff/目录树落盘 → 终态（mock 纯文本收尾 =
     `stopped_by="no_tool"` → "stopped" + 完整 final_answer，T2.8 映射）→ 用量
     计量（llm_calls/prompt/completion/usage_json.status=complete）→ 快照不变
     （AC-06）→ 活体生成物通过 DATA-14 恢复核对（AC-18）→ 汇总口径核对。
  2. **AC-20 缓存读写分列**：新旧 usage 别名（cached_tokens/cache_creation_tokens）
     分别归入 read/write，两个来源相加后仍分列（120/55），不塌缩成单一 "cached"。
  3. **零用量 Run 可见**：无轨迹的失败 Run 在汇总中以 0 值出现。
- 终态与用量是两个写入点（result 先、usage 后），测试等待两者齐备再断言。

**验收与既有证据映射**（DATA-15 要求 → 证据）

| DATA-15 要求 | 证据 |
|---|---|
| 真 PG 并发版本、唯一约束、事务、迁移 | DATA-02—14 各批 PG 测试（202 项，含迁移降/升级往返与不可变触发器） |
| 可控模型验证真实 worker、调度与文件链路 | 本批端到端 + DATA-08 worker 上下文注入 e2e |
| 可控行情验证判定链路 | DATA-10/11 固定时钟行情序列（穿越/乱序/重放/断线/预算） |
| 直接 API 越权/绕过 | test_business_routes/write、watch、restore 各文件所有者隔离与归属校验用例 |
| 提交前后、派发前后、领取后崩溃及恢复 | test_run_dispatch：原子提交、租约过期回收未启动 Run、已启动不重投、孤儿对账 |
| 防重复监控/冷却 | C 阶段 single 模式防重复唤醒（DATA-10/11）；持久布防/冷却属 D 阶段（未实施，如实登记） |
| 成本比较口径 | 本批 `usage_summary_for_runs` + 缓存读写分列测试 |
| 记录版本/批次/脱敏证据 | 环境基线 §4.11；`evidence/data15-pg.log` |

**验收**：全套 tests/pg **202 passed**（原 199 + 本批 3）；Ruff、Pyright（本批文件
0 错误）、import smoke 386/386、symbol closure 484 文件、`git diff --check` 通过。

**登记缺口（不宣称已通过，随后续阶段/部署执行）**

- UI-11 浏览器完整用户路径（UI 任务侧）。
- AC-20 输入正确率比较与真实费用：需真实任务集与真实供应商凭据的受控试运行；
  模拟模型通过不等于生产实时性/计费已验收（PRD §10 明示）。
- 实际供应商协议/行情时效实测：需真实行情接口凭据。
- 重复规则/多规则配置、冷却与重新布防：D 阶段扩展，C 阶段仅 `trigger_mode=single`。
- 业务数据（快照/审计/事件/版本）保留期限与物理删除流程未定义：DATA-13 转出项，
  发布前冻结归属 DATA-14（见 issue 09 补记），本批未承接，随发布前定值收口。
