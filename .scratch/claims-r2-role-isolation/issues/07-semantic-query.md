# 07 · 只读语义查询、快照分页与完整证据交付

Status: needs-triage
Execution: 未开始
Type: task
Plan: W5 前置接线；R2-S2/S3
Blocked by: 06
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

通过生产调用方同一查询 Interface 返回可直接消费的证据单元，避免抽取正确但检索/分页/裁剪丢失必要限定。

## 前置与外部门

06 已验收；01 已固定工具名、输入/输出 Schema、错误码与游标契约。此票实现工具逻辑与裁剪接缝，产品 profile 启用和完整 loop 验收归 09。

## 范围与预期文件

- 语义查询固定落在 `plugins/corpus/structured/query.py::query_semantic`，只读工具名固定为
  `corpus_semantic_query`；返回 `corpus-semantic-query-page-v1`，首轮排序版本固定为
  `semantic-lexical-sort-v1`。
- plugins/tools/_overflow.py、workflows/stateful_react_agent/_runtime.py 的协议交付接缝；不在框架通用内核内硬编码业务。
- tests/test_corpus_structured_query.py、tests/test_corpus_structured_delivery.py；现有 test_corpus_fetch_paging.py 回归。
- 固定 source/build/发布版本、用途、检索与排序版本；首轮词法/字段检索，不增加 LLM 改写或重排。

## 验收条件

- [ ] 命中核心条目时必要条件/否定/表头/脚注/归属成组返回，即使依赖不含查询词；关联未知明确标缺口。
- [ ] 查询只读已发布范围，永不触发抽取/自动修复；返回记录 ID、语义版本与可解析原文句柄/区间。
- [ ] 未抽取、查询无匹配、有匹配但未翻页、已检查但未抽出支持条目可区分，均不能直接推出全文无风险。
- [ ] 游标绑定 query/排序/发布版本，跨页不混版；撤回/用途收紧使受影响续页明确失效，需显式重查。
- [ ] 必要证据单元放不下则少返回或给预算缺口，不发送裸数值作完整证据，不截断 JSON/游标。
- [ ] 工具层与运行时层重复裁剪均保护协议；在实际请求消息中核验内容，而不只看函数返回值。
- [ ] 独立风险/反方可检索，排序不只保留支持性观点；检索规则与响应预算纳入版本和 10 的交付召回验收。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_query.py tests/test_corpus_structured_delivery.py tests/test_corpus_fetch_paging.py -q
uv run ruff check plugins/corpus plugins/tools workflows/stateful_react_agent tests/test_corpus_structured_query.py tests/test_corpus_structured_delivery.py
```

测试默认拒绝模型调用；引用、缺口、预算错误都按正式返回协议验证。

## 非目标

不允许用户问题改变后台抽取范围，不新增 Agent 自主抽取工具，不把诊断 raw 响应公开成普通研究证据。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
