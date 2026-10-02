# 05 · 调度、持久执行账、原子预算与只读核查

Status: needs-triage
Execution: 未开始
Type: task
Plan: W2/W3；R2-S2/S3
Blocked by: 04
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

提供显式计划/执行/核查入口，保证每次真实请求只能经预留入口发出；在中断和并发下保持可对账，而不建设第三条处理链。

## 前置与外部门

04 已验收；01 已选定持久账的事务方案和 CLI 契约。复用 _r2_runtime/_r2_audit 的经验不等于把其私有 fake/replay 路径直接宣称为生产实现。

## 范围与预期文件

- 调度/持久账固定落在 `plugins/corpus/structured/ledger.py`，CLI 固定为
  `plugins/corpus/structured/cli.py`；按需复用 plugins/corpus/_r2_plan.py、_r2_runtime.py、
  _r2_audit.py 的逻辑，不污染旧实验协议。持久账为根目录 `index/structured.sqlite3`，使用
  WAL + `BEGIN IMMEDIATE` 原子预留，不得使用 no-op EventStore。
- tests/test_corpus_structured_execution.py、tests/test_corpus_structured_cli.py。
- 计划记录初始任务、关系派生规则/上限及角色配置；计划生成不发模型请求。
- 真实并发默认 1；假响应覆盖并发竞争。账目只写指定临时/实验根目录，不使用 no-op EventStore 做持久化。

## 验收条件

- [ ] 角色与批次预算在一个事务内检查/预留；最后一个额度并发争用只能批准一个 attempt。
- [ ] task、attempt、batch 身份稳定；关系依赖就绪后先登记派生任务再调用，恢复不重复登记逻辑任务。
- [ ] 预留后中断、收到响应但未落盘、协议失败等结果保留真实状态，未知 outcome 不自动重发、不回收为确定零成本。
- [ ] 每次兼容请求/获准重试都独立获准留账；SDK 无隐藏请求；费用按模型/供应商/价格/币种分项，缺项为未知。
- [ ] 只读核查覆盖计划—任务—请求/响应—产物引用；不补发、不改账、不替语义质量打分。
- [ ] CLI plan/check/replay/execute 的已冻结行为、参数校验和退出码有进程级测试；配置失败先于请求，查询没有 execute 副作用。
- [ ] 取消/截止、恢复、无候选、未就绪、关系关闭和超预算分别可辨；不以缺日志断言进程死亡。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_execution.py tests/test_corpus_structured_cli.py -q
uv run ruff check plugins/corpus tests/test_corpus_structured_execution.py tests/test_corpus_structured_cli.py
```

测试含独立进程中断恢复及并发预留；真实网络/模型在测试中拒绝。进程级调用固定为：

```bash
uv run python -m plugins.corpus.structured.cli plan --snapshot SNAPSHOT.json --out PLAN.json
uv run python -m plugins.corpus.structured.cli execute --plan PLAN.json --store-root ROOT --allow-model
uv run python -m plugins.corpus.structured.cli replay --plan PLAN.json --responses RESPONSES --store-root ROOT
uv run python -m plugins.corpus.structured.cli check --batch-id BATCH_ID --store-root ROOT
```

## 非目标

不启动常驻监控，不自动修复，不引入模型复判，不把统一计账解释为统一模型或统一 token 单价。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
