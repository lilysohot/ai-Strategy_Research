# 资料库检索与 Agent 上下文接线

| 项 | 内容 |
|---|---|
| 版本 / 状态 | **v1.0 · 当前检索事实真源** |
| 更新日期 | 2026-09-23 |
| 上游需求 | [产品需求基线](product-requirements.md) · [业务流程](business-process.md) |
| 实现位置 | `plugins/corpus/` · `plugins/tools/corpus_*.py` · `frontier_agent/core/runtime/loop/agent_loop.py` |
| 目的 | 说清资料如何入库、Agent 如何检索、原文如何进入上下文，以及 CLI/TUI 与 Web 的真实接线状态 |

> 本文是“当前怎样运行”的单一入口。历史 SQLite/FTS5/BM25 施工规格、
> Discord/IMA/向量检索远期探索和早期 Web 接入方案只解释设计演进，不得用来推断当前能力。
> 产品范围仍以 `product-requirements.md` 为准，代码与测试是实现现状的最终依据。

## 1. 当前事实

| 问题 | 当前结论 |
|---|---|
| 语料存在哪里 | 独立 PostgreSQL 18.6 语料库，与 Web 业务库分开 |
| 中文如何检索 | `zhparser` + `zhcfg` 生成列/GIN 索引 |
| 如何排序 | `ts_rank` + 标题 5× 加权 + AND→OR 兜底 + 去重 + 时效偏置 |
| 是否在用 BM25 | **否**。BM25 是历史 SQLite FTS5 基线；PostgreSQL 当前使用校准后的 `ts_rank` 方案 |
| 是否在用向量 | **否**。`pgvector` 扩展已安装但未建 embedding 列，当前不是混合检索 |
| Agent 是否直连数据库 | **否**。Agent 只看到受控工具，数据库访问收口在 `CorpusService` |
| 引用是否可直接用搜索摘要 | **否**。`corpus_search` 只定位，必须用 `corpus_fetch` 取回逐字原文 |
| Claim 是否已是在线 Agent 的默认检索入口 | **否**。Claim/EvidenceRun 已有离线治理能力，在线入口仍是 `corpus_search → corpus_fetch` |
| CLI/TUI 是否接通 | Stateful ReAct `tui` profile 已绑定语料、市场、仓位和校验工具 |
| Web 是否接通 | **未接通**。Web `profile_overrides` 目前覆盖了 `tui` 中的金融工具列表，也未注入投研纪律提示词 |

## 2. 从资料到可引用证据

### 2.1 离线准备链

```text
合法源文件
→ 来源登记与准入决定
→ 保真解析与结构清洗
→ unit/chunk 构建
→ 候选 build
→ 核验并发布
→ PostgreSQL 活动 build + 全文索引
```

文件复制进 `data/corpus/` 不等于可检索；只有经过准备、审核和发布的 build
才进入在线读链。基础链必须是确定性处理，不用 LLM 生成或补写原文。

### 2.2 在线 Agent 链

```text
用户研究问题
→ data_coverage：探测语料/行情/财务来源
→ corpus_search(query, limit)：返回截断 snippet + doc_id/locator
→ Agent 选择真正相关的句柄
→ corpus_fetch(doc_id, locator)：返回逐字原文和精确定位
→ runtime 把工具结果追加为 ToolMessage
→ Agent 基于原文组织结论和 evidence
→ strategy_lint / verify 执行证据、算术与 schema 校验
```

这是**工具驱动检索**，不是服务端在每次 Run 开始前自动把整个资料库塞进 prompt。
模型上下文中只保留当前问题所需的少量命中与原文，较旧的工具结果可由现有上下文
压缩机制处理。

### 2.3 失败与降级

| 结果 | 含义 | Agent 行为 |
|---|---|---|
| `available` | 已验证来源有可用资料 | 继续 search/fetch，保留版本与定位 |
| `absent` | 已成功查询且确认没有满足条件的数据 | 转向其他允许来源，不重复搜索 |
| `unknown` | 超时、无权限、故障或处理覆盖未验证 | 报告“覆盖未验证”，不得写成“没有资料” |

当前 `data_coverage` 还在返回 `full/partial/research_only/none`，上表是已批准的目标语义；
实现完成前不得把 `none` 直接宣传为来源确定不存在相关资料。

## 3. 上下文的四条独立通道

Agent 不应把所有“记忆”交给同一种检索算法：

| 上下文 | 事实来源 | 召回方式 | 禁止行为 |
|---|---|---|---|
| 最近对话 | `Turn` | 有界会话历史 | 不从对话推断最新持仓或买入价 |
| 用户投资约束 | 未来的 `InvestmentPlan` / Run 快照 | 服务端精确 SQL + 类型化 `investment_context` | 不用 FTS/向量搜索从聊天文本猜数值 |
| 研究资料 | corpus 活动 build | `data_coverage → corpus_search → corpus_fetch` | 不直接引用 snippet |
| 行情/财务 | 市场数据 Adapter | 按标的和时点精确调用 | 不用研报数字静默补行情缺口 |

用户的计划买入价、实际成交均价和 Agent 建议价是三种不同的事实，必须分别保存来源、
时间和状态。这类业务数据不进入语料 RAG，也不由 Agent 直连数据库。

## 4. 当前检索能力的边界

当前在线工具界面仅暴露：

```python
corpus_search(query: str, limit: int = 10)
corpus_fetch(doc_id: str, locator: str)
```

因此：

- 精确关键词、标的、数字与单位检索已有校准基线；
- 观点改写、同义表达和跨文档概念召回仍主要依赖模型生成的查询词；
- Claim/EvidenceRun 中已有的 `semantic_type` / `value` / `unit` / 时间等字段，尚未通过在线工具
  作为结构化过滤界面提供给 Agent；
- 文档增长时不应盲目开启向量库。先为“观点/数值/时间/标的”提供结构化过滤，
  再用真实黄金题比较 FTS-only 与混合检索。

启用向量通道的判据必须至少包含：观点改写题的 Recall@k 持续不达标，且结构化过滤、
查询扩展和排序校准无法修复。启用后应在 `CorpusService` 内部实现，对 Agent 继续保持稳定的
search/fetch 界面，不让调用方理解 `ts_rank`、向量距离或融合算法。

## 5. CLI/TUI 与 Web 接线状态

| 接线点 | CLI/TUI | Web | 目标 |
|---|---|---|---|
| 工具注册 | 已完成 | 已注册 | 保持单一 allowlist |
| 有效 profile 工具列表 | `tui` 已暴露 | **Web override 未暴露** | 服务端明确解析当次 Run 的研究能力 |
| 投研纪律提示词 | `react.yaml` 已注入 | **worker 未注入** | 复用同一 `RESEARCH_DISCIPLINE_ADDENDUM` |
| `CORPUS_DSN` | 由环境提供 | Compose 已显式传入 | 启动/健康检查失败时可操作地报错 |
| 工具结果进上下文 | 已完成 | 公共 runtime 已支持 | 无需新建第二套 RAG 消息通道 |
| 证据 UI | 文件/文本 | 只有通用工具活动 | 结构化显示 evidence，支持按句柄查看原文 |

Web 的接线 seam 应只暴露一个小界面：根据用户、Run 与 `corpus_scope` 解析出可用工具、
受信提示词和结构化业务上下文。调用方不应分别拼工具列表、提示词和数据库查询，
否则 CLI/TUI 与 Web 会再次漂移。

## 6. Web 打通的最小验收

1. Web 有效工具列表包含 `data_coverage` / `corpus_search` / `corpus_fetch` 及已批准的
   market/sizing/lint 工具，并用真实 Run 验证，不只测 registry。
2. Web worker 与 CLI/TUI 注入同一份 `RESEARCH_DISCIPLINE_ADDENDUM`。
3. 有覆盖样本实际走完 `coverage → search → fetch`，且 `evidence.quote` 能在
   `fetch.text` 中逐字命中。
4. 无覆盖、连接故障、无权限分别进入 `absent` / `unknown` 或当前实现的明确兼容态，
   不编造研报。
5. `corpus_scope=off` 时工具不可见；限定标的/来源时在工具层执行，不只写提示词。
6. 用户结构化投资约束以 Run 快照进入 `investment_context`；不从历史聊天或语料检索中猜值。

## 7. 历史文档的正确读法

| 文档 | 现在的用途 |
|---|---|
| [P0 实施规格](p0-implementation-spec.md) | 历史机制验收与算法记录；SQLite/FTS5 不是当前存储方案 |
| [多源资料库设计](corpus-ingestion-architecture.md) | Discord/IMA/向量/信号层远期探索，不是施工基线 |
| [PostgreSQL 迁移报告](corpus-pg-migration-report.md) | 2026-09-08 迁移与排序校准的验证记录，其 17 份/298 块不是当前库容量承诺 |
| [Web 语料库接入方案](plan/web-corpus-integration.md) | 历史需求输入；当前缺口以 `PR-DATA-04` 和本文 §5–6 为准 |
| [召回校准教程](guide-recall-calibration.md) | 解释迁移时的检索原理和实验，不定义产品状态 |

