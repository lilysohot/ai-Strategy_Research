# Copper selector live-plan freeze

这是 Issue 18 在所有零调用门通过后冻结的唯一 copper-only selector 计划。计划阶段没有发出模型请求，
也没有写生产数据库、发布或消费语义数据。

- batch: `batch:98f02adad93998b0d87a7c5d21d3d8dd10631c09fca64974bcb4c43d3754af4c`
- items: `material-atomic-selector-jsonl-v1`，最多 23 calls，24 slots / 64 items / 8192 estimated tokens
- relations: `material-relations-selector-jsonl-v1`，最多 4 calls
- dependency: `complete_parent`；items 不是 `succeeded / valid / accepted` 时 relation calls 必须为 0
- total ceiling: 27 calls；Claims 为 0
- gold: 复用既有 11 items / 4 relations 金标与阈值，不重标

`plan.json` 只冻结 `env:STRUCTURED_EXTRACTION_API_KEY` 引用，不包含内联 credential。下一动作是显式执行
该计划；在 items 达到 487/487 终态完整、0 partial 前，不裁定 relations、不发布、不 query、不 delivery、
不 context use。
