# Copper selector live-plan freeze

这是 Issue 18 在所有零调用门通过后冻结并执行的 copper-only selector 计划。计划阶段没有发出模型
请求；实际执行在 strict items gate 失败后停止，没有调用 relations，也没有写生产数据库、发布或消费
语义数据。

- batch: `batch:98f02adad93998b0d87a7c5d21d3d8dd10631c09fca64974bcb4c43d3754af4c`
- items: `material-atomic-selector-jsonl-v1`，最多 23 calls，24 slots / 64 items / 8192 estimated tokens
- relations: `material-relations-selector-jsonl-v1`，最多 4 calls
- dependency: `complete_parent`；items 不是 `succeeded / valid / accepted` 时 relation calls 必须为 0
- total ceiling: 27 calls；Claims 为 0
- gold: 复用既有 11 items / 4 relations 金标与阈值，不重标

`plan.json` 只冻结 `env:STRUCTURED_EXTRACTION_API_KEY` 引用，不包含内联 credential。执行完成 23 次
items 调用，顶层终态为 487/487，但 252 槽在严格语义/字段门失败，因此四个 packet 均 partial，relations
按 `complete_parent` 正确阻断为 0 calls。详见 `execution-summary.json` 和 `failure-analysis.json`。
