# [历史方案] 研报数据三层架构

| 项 | 内容 |
|---|---|
| 状态 | **已被替代，不作为当前架构或需求依据** |
| 历史范围 | 原文层 / 检索层 / 数值层的早期 SQLite + NPZ 方案 |
| 当前入口 | [产品需求](../product-requirements.md) · [业务流程](../business-process.md) · [数据层架构](../plan/data-layer-architecture.md) |

本文原方案用于早期验证“检索只定位、取证回原文、数字不经 LLM 改写”三项原则。原则仍然有效，但实现基线已经变化：

1. 语料存储已从 SQLite/FTS5/NPZ 方案迁移到 PostgreSQL 18.6、zhparser 中文全文检索，并保留 pgvector 扩展位；当前事实见
   [data-layer-architecture.md](../plan/data-layer-architecture.md)。
2. 当前在线证据入口是 `corpus_search → corpus_fetch`；D2 Claims 是独立的离线抽取与治理链，不能把两者写成一个“三层查询工具”。
3. 市场数据通过 `plugins/market` 的按需工具链进入，不与语料原始表混合；目标比较层使用只读的 `ComparableObservation`。
4. 当前产品业务流程已经包含 Web Run、SSE、停止、插话、审批、附件、产物和回滚，不能再用单一 ReAct 查询图代表完整平台。

仍有效的设计红线：

- 检索结果只用于定位，证据必须回到逐字原文或精确市场调用；
- 数字保留原始表述、单位、来源和时点；
- fact、forecast、opinion 与 previous 不得混用；
- 模型摘要和模型心算不得成为证据或确定性数值来源。

完整的旧方案可通过 Git 历史查看。保留本路径仅为兼容已有链接；新文档不得引用它作为当前方案。
