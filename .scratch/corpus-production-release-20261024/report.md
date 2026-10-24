# 上下文检索与 search/fetch 契约正式发布

状态：**已发布，本轮优化结束**。2026-10-24 09:36:40（Asia/Shanghai）。用户授权：“开始正式发布，结束本轮优化”。

## 实际发布范围

- 本机 `/home/administrator/FrontierAgent` 的 8000 API，代码 `7653973e61c6052d6f8747997c0d34b7975ae193`。本轮没有新增生产算法改动；102 个冻结文件哈希一致。
- `.env` 只修改三项：`CORPUS_NATIVE_INDEX` 指向 `data/corpus-native-context/20261023/manifest.json`，`CORPUS_VECTOR_INPUT_VARIANT=contextual-note-v1`，`CORPUS_NATIVE_SNIPPET_BLOCKS=2`。
- 正式目标仍为 `postgres`，读链 `new`、native `release`。范围 23 来源，585 原生块，585 块向量就绪。包 profile 为 `d7e561d49b7a5d75066be40a089113c986b8d246885a8b6f85dedb2e86b1176b`。
- 使用冻结的来源提纯、问题要点覆盖及两块正文展示规则。search 实际交付且有标记的原文可以直接作为证据；fetch 用于补齐缺失内容。未加入目标价专用修复，也未继续收紧过滤。
- 未执行数据库迁移、重建向量、重写原文或重新发布来源。前端无需变更；监控 worker 负责行情收集和入队，研究任务由 API 派生进程执行，因此未重启监控服务。

## 服务切换

切换前 queued/running 用户任务为 0，健康和就绪均为 200。旧 PID 568838 正常 SIGTERM 退出，新 PID 1332234 启动，切换至就绪耗时 1.6 秒。新 API 环境包含当前配置，后续研究 worker 继承该环境。

原 `.env` 与旧进程初始环境备份到 `data/corpus-native-context/20261024-release-backup/`，目录权限 0700、文件权限 0600；备份含凭据，不进入报告。公开的旧三项配置见 [settings-before.json](settings-before.json)，切换记录见 [runtime-activate.json](runtime-activate.json)。

## 验证

- 185 项上下文检索、展示、提纯、证据契约及原生工具测试通过（1.61 秒）。冻结校验 102 文件通过。
- 真实模型 preflight 通过；framework import smoke 419/419、eval 468/468；517 文件符号闭合检查 0 缺失。
- 正式认证 HTTP 和实际 `corpus_search.ainvoke` / `corpus_fetch.ainvoke` 分别验证茅台双锚定价、光模块 NPO/CPO 两题。最终两条路径均为 hybrid；HTTP 活跃索引与按正式 PG 快照刷新后的上下文包一致。
- 工具证据契约为 `native-search-evidence-v1`；两题分别解码 6、2 个证据片段。逐片段按 member 取对应句柄，检查原文区间、整块哈希及引文哈希；全部一致。HTTP 每题补读 2 个成员，实际工具 compact fetch 亦通过。
- 2026-10-22 发布记录中的 2 个历史句柄仍可读取。健康和就绪终检均为 200。

最终成功探针耗时如下，包含真实网络和 PG 路径。HTTP 茅台查询已经过前面的探针，不能称冷启动；工具查询运行在另一进程，不能视作同一次端到端作答。

| 查询 | HTTP search | HTTP fetch（2 成员合计） | 工具 search | 工具 fetch（1 成员） |
|---|---:|---:|---:|---:|
| 茅台双锚定价 | 1693 ms | 41 ms | 1929 ms | 64 ms |
| NPO/CPO | 1869 ms | 40 ms | 1883 ms | 24 ms |

完整数据见 [smoke.json](smoke.json)，实际结果见 [茅台](query-1.json)、[NPO/CPO](query-2.json)。

初版发布探针将种子 manifest 哈希误当成动态索引 ID，已按 `native_live.refresh` 的实际口径修正。随后发现独立实时查询的成员排序并不保证相同，且一次工具请求发生 `embedding_provider_transport_uncertain` 降级；保留 [降级记录](probe-transport-fallback.json)。最终探针分别核验每条路径返回的真实映射，没有以跨进程排序恒等代替证据校验。此过程只修改发布探针，未修改生产代码。不能据此声称任意两次独立检索的结果顺序恒定。

## 已知局限与结束决定

用户拒绝进一步针对性修复后，发布当前冻结版本。`贵州茅台2026目标价` 的直接答案仍可能被背景内容挤掉；2030 金额误识别为年份、标题占位等诊断保留，尚未修复。已有盲测不证明全面质量提升，也未证明端到端 fetch 次数减少。

查询 embedding 的 15 秒超时及同范围关键词降级保持原设置。此次独立工具探针确实观察到一次降级；不能把成功样本约 2 秒的耗时当作所有请求的上界。更广泛的时间/数值识别及长尾性能属于后续独立工作，不继续纳入本轮。

## 回退

在仓库目录执行：

```bash
PYTHONPATH=. uv run --no-sync python .scratch/corpus-production-release-20261024/runtime.py rollback
```

脚本先要求现有 API 就绪且无 queued/running 任务，再恢复旧索引路径、旧向量输入 variant，以及未设置的 snippet override，正常重启并检查健康。它保留当前代码，所以不撤销正文选择和新工具契约，也不删除资料。正式环境没有为验证额外执行一次回退；完整代码回退需另行选择兼容版本，不能描述成已演练。

本次没有创建新代码提交或推送远端；正式运行基线已有提交，其他工作区修改保留。发布操作是当前本机正式 API 的配置切换与重启，不代表部署到未指定的远端环境。
