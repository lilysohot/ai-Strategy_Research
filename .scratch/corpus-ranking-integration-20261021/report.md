# 正文排序接入真实检索入口：验收记录

日期：2026-10-21。数据库：`vector_pilot_clean7_20261021`。

> **用户验收：通过，保留已知问题（2026-10-21）。** 用户已明确确认“验收，并回填相应主文档”，
> 当前隔离语料上的检索优化接入任务据此收尾；默认开关仍关闭。
> 下列数据为已完成的验证记录，本次仅回填验收决定，没有重新实验。
> 范围、保留问题及后续阶段以[主方案 §29](../../docs/plan/corpus-contextual-vector-retrieval-pilot.md#29-本轮验收结论与收尾2026-10-21)为准。

已把上一轮验证的实体覆盖、明确来源角色及保守年份信号接入
`CorpusService.search_with_coverage`，通过 `CORPUS_RETRIEVAL_RANKING=body-constraints-v1`
显式启用。业务路径从当前 PG 发布内容构造特征，不再依赖实验导出的文件或排序补丁。
本轮为接入验证，没有新增召回收益；默认开关仍关闭，实际 `.env` 未修改。

## 结果

| 项目 | 结果 |
|---|---|
| 正式入口与上一轮最佳实验 | 32/32 题最终锚点、分数、范围和顺序一致 |
| 对照关闭新开关 | 32/32 题恢复原始混合检索结果 |
| 约束输出 | 32 题查询约束及 265 个最终锚点诊断与已验证实验一致 |
| 正例首条正文覆盖 | 保持 24/24；原始混合为 22/24，改进仍来自先前 p13/p16 排序 |
| 旧标注块覆盖 | 保持 38/39；只看已更新来源为 34/34 |
| 原始返回范围 | 32/32 题保持；不保证所有新问题范围不变 |
| PG 生命周期 | 活动版本、撤回、机构/原文件名变更触发重新加载；并发连接快照隔离通过 |
| 回退 | 向量目标不匹配时原有词法回退正常，新排序报告未启用 |
| 代码回归 | 133 项通过，另 1 项真实 PG 生命周期测试通过 |
| 仓库门禁 | import stage 1：406/406；stage 2：455/455；symbols：504 文件零缺失；Ruff、两个新模块 Pyright、preflight 通过 |
| 新增 embedding 调用 | 0；复用既有真实查询向量。preflight 另有一次普通模型调用 |

已知缺口保持原状：n01 仍可能返回其他公司的近似内容；n02/n04 可标记缺所问年份，
n03 可标记预测线索，n07 可标记来源不符。以上状态不自动删除内容，也不验证事实正确性。
38/39 中未返回的旧标注块仍受现有输出预算影响，本轮没有通过扩大预算掩盖它。

## 实现位置

- `plugins/corpus/retrieval/ranking.py`：纯正文评分、别名出处、请求局部约束与保守排序。
- `plugins/corpus/retrieval/ranking_pg.py`：同事务加载权威正文及来源，最多两个特征快照缓存。
- `plugins/corpus/retrieval/hybrid.py`：候选快照内加载特征，来源内实体加分。
- `plugins/corpus/service.py`：隔离库开关、选带后的来源/年份顺序、`coverage.ranking` 状态。
- `plugins/corpus/preparation/read_pg.py`：抽出 `fetch_bands_on`，复用权威文本及跨边界逻辑。

缓存签名每次从候选事务读取，包含数据库身份、版本、generation、准入状态、来源文件名、
机构及元数据哈希；不缓存候选结果。版本键同时包含 build 和 chunk，查询状态不进入共享缓存。
缓存假设构建内容遵守项目不可变约束；冷加载仍校验权威单元哈希。
发布或撤回提交后的新查询重新读取新签名；已经开始的查询按自己的数据库快照完成。
现有后续表头及种类读取仍是独立读取，未把整个服务和后续 fetch 重构为统一长事务。

生命周期测试通过回滚事务模拟指针切换和撤回，不是一次新的正式发布。
没有修改清洗、切块、向量索引、生产 publication，也没有放行两份图像缺口构建。

## 耗时观察

- 启用后首题冷加载：782.6 ms。
- 启用后其余 31 题特征缓存命中，中位：336.7 ms。
- 关闭新排序的 32 题中位：306.8 ms。

两组为分开执行的小样本记录，不是严格交错压测；查询向量均已缓存，不含外部 embedding
网络延迟。没有观察到提速。当前冷加载构造全部活动语料的正文特征，尚未验证 500 份规模。

## 使用与回退

在 WSL 的项目目录执行（沿用 `.env` 中的凭据，仅修改该命令进程的目标）：

```bash
CORPUS_VECTOR_TARGET_DB=vector_pilot_clean7_20261021 \
CORPUS_RETRIEVAL_RANKING=body-constraints-v1 \
CORPUS_RETRIEVAL_RANKING_TARGET_DB=vector_pilot_clean7_20261021 \
uv run python -m plugins.corpus.retrieval.cli query --mode hybrid --query '你的研究问题'
```

排序目标只允许显式匹配的 `vector_pilot_*` 库，且必须使用 hybrid。
设置 `CORPUS_RETRIEVAL_RANKING=off` 恢复原路径，不需重建或重嵌入。
CLI 负责进程内设置正确 DSN；普通服务进程须另外配置一致的读库和 hybrid 模式。

后续更有价值的是固定这套实现，在更多已发布研报上观察来源混淆、多实体覆盖和
最终输出截断损失；当前不建议直接增加硬过滤。主 agent 消费不属于此次验收。

## 可复核材料

- [正式路径逐题记录](live-verification.json) / [关闭开关对照](default-verification.json)
- [约束与代码哈希核验](verification.json) / [回退记录](fallback.json)
- [真实 PG 生命周期](lifecycle.log) / [回归测试](tests.log) / [耗时原记录](latency.json)
- `live/` 下每题包含公开命中、覆盖诊断及完整检索轨迹；原题和金标未修改。
- [主方案与执行链路图](../../docs/plan/corpus-contextual-vector-retrieval-pilot.md#28-真实检索入口接入与版本缓存验证2026-10-21)
