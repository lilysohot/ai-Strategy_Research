# B4.3 隔离发布与回滚演练报告（2026-09-29）

- 方案：[02-fragment-chunking.md §B4.3](../../docs/data_clean_dos/02-fragment-chunking.md#b43-发布与回滚演练)
- 脚本：[b43_publish_drill.py](./b43_publish_drill.py)
- 结果：[b43-publish-drill.json](./b43-publish-drill.json)
- 新产物归档：本目录 `archive/`（engine.ingest_source 内容寻址副本，6 份）

## 1. 目标与契约

按 §B4.3（L269-281）在**隔离环境**验证发布与回滚五项契约，不重建生产语料、不触碰生产库：

1. 新 build 的原文、结构、索引和引用校验通过，候选效果可复现。
2. 消费清单、缓存、游标及后续 Claims/R2 结果绑定 build 和内容身份；新旧版本不能错误复用。
3. 旧 build、兼容的代码/配置、索引访问能力和源访问权限均仍可用。
4. 对既有运行固定快照，新请求按发布策略选版本；旧游标不被静默升级。
5. 回滚时能够恢复完整兼容组合，并重放旧引用、检索和分页请求。

## 2. 隔离保证

| 维度 | 实现 |
|---|---|
| 模型 | `DenyModels` MetaPathFinder 拒绝 `openai`/`anthropic` 及 `plugins.corpus.material_semantics`/`_r2_` 前缀；`models_absent=true` |
| 源 | 只读 i3-1 e2e 审计归档副本 `ARCHIVE`（内容寻址，6 份 PDF） |
| 写目标 | 仅 `i2_sandbox_corpus`（127.0.0.1:543）九表 |
| 生产连接 | 显式 DSN + `SET default_transaction_read_only=on`；不装载 `.env` CORPUS_* |
| 新产物位置 | 本目录 `archive/` |

## 3. 方法

- **版本**：旧 build 从生产只读库逐字节复制（Source/ReviewedDecision/Admission/Build/units/chunks/缺口凭证），含旧 build 的 `human-gap-review:<build_id>` 检查点（§7.3 放行阻断缺口的唯一凭证）。新 build 由真实引擎 `reader-pdf-7` + `clean-3` + `chunk-4` 在沙箱重建，v1 准入政策（`admission-policy.json`，auto_decision 关闭）。
- **发布**：全部走 `engine.publish_build`（幂等短路 → `_verify_publication_ready` → PUBLISHED job 租约 → store.publish）。
- **回滚**：`store.retire` 撤下新 build → 操作者直接 SQL 复位 `corpus_sources.current_decision_id` 到旧决定 → `engine.publish_build` 重发旧 build（generation+1）。
- **检索**：`search_chunks`（`_SEARCH_SQL`：`active_build_id` INNER JOIN 收敛活动范围）。查询形态 = 产品候选查询 `retrieval_query(question)`（实质词元 OR，websearch 语法）——不用问题原文：`websearch_to_tsquery` 会把连续中文词合成邻接短语（`<->`），全题短语在真实语料中 0 命中（生产同）；B0 金标服务层走 `plainto_tsquery`（AND），产品候选查询与其同口径且命中非空（30 题 600 命中、6 来源全覆盖）。
- **操作者动作**：新 build 阻断缺口与旧 build 同码（`image_region_unreadable`/`table_lines_without_extraction`，均页级），真实发布流程须对新 build 指纹重签——演练由 `_ack_blocking_gaps` 按 §7.3 签署具名凭证（`required_locators` 选非缺口保留页、`gaps` 恰为全部阻断键），记入 phase2。

## 4. 执行结果（五项契约逐条）

| 契约 | 结果 | 证据 |
|---|---|---|
| 1 可复现 | **通过** | 真实引擎落库 6 来源 units/chunks/doc_norm_chars/kind_hist 与 B4.1 b1b3 期望**逐来源全等**（units 3711、chunks 299、0 mismatch）；`_verify_publication_ready` 在发布前校验通过 |
| 2 身份绑定 | **通过** | 新发布后 30 题检索命中 `hit_builds ⊆ 新 build 集` 且 `∩ 旧 build 集 = ∅`；旧句柄跨发布逐字取回 `build_id/text_hash` 全不变 |
| 3 旧 build 可用 | **通过** | 旧句柄 376 次 fetch 引用在新版活动期仍逐字返回旧 build 不可变正文（0 changed） |
| 4 旧游标不升级 | **通过** | 固定快照（30 题 × limit 20/5）先于发布取定；新发布后旧引用重放与旧快照逐条一致，无静默升级 |
| 5 回滚恢复兼容 | **通过** | retire→复位指针→重发旧 build（gen4）；重放检索 20/5、旧引用 fetch 与发布前旧快照**逐条全等**（search_diff=0、fetch_diff=0、page_diff=0） |

Generation 序列（每来源一致）：旧 gen1 → 新 gen2 → retire gen3 → 回滚旧 gen4。

## 5. 记录与限制

- **指针回退无正式 API**：`store.put_admission` 只前移 `current_decision_id`（F1/F2 同内容重放不回退），Store Seam 无回退接口。回滚以**操作者动作**（沙箱单行 SQL `UPDATE corpus.corpus_sources SET current_decision_id=旧决定`）复位指针，再走正式 `publish_build`。此限制已记入脚本 docstring 与本报告。
- **新 build 缺口须重签**：同一来源新 build 与旧 build 阻断缺口同码，发布前必须对新 build 指纹签署新的 `human-gap-review` 凭证；演练由操作者代签（4/6 来源有阻断缺口，2/6 全为非阻断 `image_region_small` 默认放行）。
- **查询形态**：契约第 4/5 项的快照比对基于产品候选查询（见 §3）。完整问题原文在 websearch 语义下不命中，非本次演练缺陷。
- **计数口径**：phase4b `old_handle_preserved.refs=376` 为去重前引用次数（跨查询重复命中），`fetch_old` 唯一键 235 条，逐条比对无差异。
- **只读源与产物**：仅读 i3-1 e2e 归档与生产 SELECT；新产物全部落在本目录 `archive/`。

## 6. 产物清单

- `b43_publish_drill.py` — 演练脚本（五阶段 + 五项断言）
- `b43-publish-drill.json` — 结构化结果（phases/old_world/summary/generation_sequence）
- `archive/` — 新 build 的内容寻址归档副本
