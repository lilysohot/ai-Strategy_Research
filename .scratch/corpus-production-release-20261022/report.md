# 混合检索正式库发布记录

2026-10-22。状态：**已发布并启用**。用户授权：“可以直接发到正式库中”。

本次代码已单独提交为 `2d5ef279`（`feat: release native hybrid retrieval to production corpus`）；提交只包含本次检索代码、测试、配置模板及发布说明，保留工作区其他并行修改，未推送远端。

## 实际发布

目标为现有 `localhost:5432/postgres`，不是业务库 `apodex`，不是另一个端口上的 `corpus-db` 实例。当前本机 API 运行在 `/home/administrator/FrontierAgent`，端口 8000。

发布前正式库仅有 8 个活动来源；试验库有 25 个。此次按已验证的原生范围包晋升 23 个来源，排除 2 个 OCR 派生来源：新增 15 个正式来源、更新 6 个已有来源的活动 build、2 个已有来源维持原 build。正式发布代次通过原有 `publish_build` 生成，没有照搬试验库 generation。

| 项目 | 结果 |
|---|---|
| 正式活动来源 | 8 → 23 |
| 正式历史构建 | 14 → 35，旧构建保留 |
| 正式原文单元 | 7,128 → 13,150 |
| 正式检索块（含历史及非原生投影） | 1,214 → 1,964 |
| 当前 native 检索投影 | 585 块 |
| 复用的文档向量 | 575 个唯一精确输入 |
| 发布新增文档 embedding 请求 | 0 |
| 重复同步 | 请求 0、导入 0、缺口 0 |

资料、构建及索引变更在单事务中完成。已有不可变构建、原文单元和检索块逐项比较；全文生成列由正式库重算并与试验值核对。发布前运行正常的阶段、准入、质量缺口、范围和租约检查，不放宽图表缺口规则。原生投影只输出可逐字核对的正文。

原始文件按哈希复制到 `data/corpus-archive`；范围包位于 `data/corpus-native-release/20261022`。完整库备份位于 `data/corpus-native-release/20261022-backup/postgres-before.dump`，哈希、大小、原配置备份和归档核对清单见 [backup.json](backup.json)。备份目录可由 pg_restore 读取；本轮未进行完整备份恢复演练。

## 正式代码与配置

新增 `release` 模式及 `native-evidence-release-1` 范围包。正式目标要求 `CORPUS_TARGET_DB` 与 `CORPUS_NATIVE_TARGET_DB` 显式匹配，实际连接仍检查 `current_database()`；检索另外校验向量模型空间和目标库。`pilot` 模式继续限制为 `vector_pilot_*`。

已修改实际 `.env`：native 开关为 `release`，三个目标库配置均为 `postgres`，读链为 `new`，范围包绑定本次发布。查询 embedding 超时为 15 秒。底层原策略保留 `CORPUS_RETRIEVAL_MODE=lexical`，关闭 native 后恢复关键词检索；当前 native 开启时返回的是混合检索。

HTTP 既有 `limit=50` 合约可继续使用，但 native 总正文仍最多20块／16,000字符。此项有新增回归测试和实际 HTTP 探针。

确认 queued/running 用户任务为0后，向旧 API 发 SIGTERM 并正常重启。旧 PID 34178，新 PID 844002，启动检查耗时1.6秒；切换后健康和就绪均为200。服务启动记录见 [runtime-release.json](runtime-release.json)。

## 验证结果

1. **57题真实工具回归**：使用冻结的旧32＋新25题、原评分函数和缓存查询向量，实际执行搜索、12,000字符搜索消息压缩、默认6,000字符取证分页。最终选中块及逐字原文与原试验一致，无新增证据丢失、无整条命中被预算删除。
2. **原文交付**：共983页，单题最多20块、15,998原文字符。旧29处可覆盖历史标注及新26个证据组均保留。旧24正例严格历史口径仍为15/24，新22正例仍为22/22，11道诊断题不计为回答准确率。
3. **关闭和降级**：另跑57题关闭回归，与正式库原服务路径一致；native历史句柄在关闭状态可读。模拟查询embedding失败后，同范围关键词降级并可完整取证。
4. **历史引用**：发布前8个活动build各取一个旧句柄验证，全部可回读，6个标为非活动版本、2个仍活动。所有原历史构建保持存在。
5. **正式HTTP路径**：认证搜索“DeepSeek通过哪些训练和推理设计降低计算成本？”返回 `hybrid`、23来源范围、7条命中、15,987正文字符；两条原文回读成功。新进程冷查询2,330ms，同问题缓存查询1,552ms，`limit=50`保持20块上限。见 [http-smoke.json](http-smoke.json)。
6. **工程检查**：173项针对性测试通过，8项需要单独PG测试配置的用例跳过；实际正式库验证由本次57题脚本执行。Ruff、定向Pyright（0错误）、diff检查通过。import smoke为framework 412/412、eval 461/461，check_symbols 510文件无缺失；通用LLM preflight通过。

57题查询向量全部复用，未调用embedding；数据发布与索引同步也没有新模型请求。实际HTTP冷查询经过真实embedding供应商，第二次同问题复用进程缓存；另有一次通用LLM预检。不能把整轮描述为所有模型请求均为0。

正式库回归搜索加完整fetch的缓存口径耗时p50为2,467ms，p95为2,923ms。这与HTTP单次搜索的时间口径不同，不代表模型回答耗时或并发吞吐。

## 回退与范围

常规回退：将 `CORPUS_NATIVE_RETRIEVAL=off` 并正常重启。目标绑定和引用解码保留，关闭不删除文档、不清空向量、不撤销本次资料发布。可使用 [runtime.py](runtime.py) 的 `rollback` 子命令；它先检查活动用户任务，再重启并检查健康。正式服务没有为演练额外来回重启，关闭行为是在同一正式库的验证进程中测试。

新增来源仍需要更新明确的范围包；现有来源的新版本按实时PG状态读取，缺向量先降级，手动同步后恢复。上下文增强、OCR、完整Agent作答评价及全库吞吐均不在此次发布范围内。旧题标签局限和既有相关性问题保留。

## 证据和执行脚本

- [发布前清单](inventory.json)、[回滚预演](rehearsal.json)、[实际晋升记录](promotion.json)
- [最终审计](final-audit.json)、[工具审计](audit.json)、[逐题结果](cases.json)、[完整工具输出](results.json)
- [关闭57题](off-cases.json)、[故障降级](fallback.json)、[正式同步](sync-release.json)
- [只读盘点脚本](inspect_target.py)、[版本晋升脚本](promote.py)、[正式库回归脚本](verify_production.py)、[HTTP探针](http_smoke.py)
- [正式操作说明](../../docs/corpus-native-release.md)

最初预演暴露了jsonb数组适配、生成列不可直接插入及种子包额外诊断字段的比较问题，均在回滚事务中修正后重新预演通过；这些失败未提交到正式库。之后实际迁移和最终验证通过。
