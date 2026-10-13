# Claims/items 范围发布结果

2026-10-13：已完成文件工件试点的 publish 与 positive_query；没有执行真实 delivery/context_use/report_reference。

用户授权依据：本轮「那么按任务帮我完成发布」。新增模型调用 0，生产 PG 访问 0。

共发布 52 条 Claims、227 条 items，279 条记录，5 个独立快照。主批次两份共 261 条，其余 18 条来自独立范围快照。不同快照即使 source/build 相同也使用不同 store root，不混合或覆盖。

| 范围 | Claims | items | 查询根目录 |
|---|---:|---:|---|
| 工业富联主快照 | 32 | 86 | `/home/administrator/FrontierAgent/.local/claims-r2-publication-20261013/stores/d6546966ac517902659ed66c4fbdc7efd8512725a0ba1ef9d507844718bac055` |
| 光模块主快照 | 15 | 128 | `/home/administrator/FrontierAgent/.local/claims-r2-publication-20261013/stores/7d8f27c875796ee3ace724131f2e8f7d3c5bf08ea85b919e6fe5b722a7fa7195` |
| 光模块 Claims 增量快照 | 5 | 0 | `/home/administrator/FrontierAgent/.local/claims-r2-publication-20261013/stores/100ace654a6ea2419a18d25cb56367727a72faad16bbf6b0c4480e84386e9ce0` |
| 工业富联 NT-I06 补跑快照 | 0 | 11 | `/home/administrator/FrontierAgent/.local/claims-r2-publication-20261013/stores/b005ba70ff7abe21b43e5679355b7dd6c60f0426a03fc4444d40658e71b3cbbb` |
| 工业富联 base 补跑快照 | 0 | 2 | `/home/administrator/FrontierAgent/.local/claims-r2-publication-20261013/stores/3740f63e5f94063785fd2f79a53bb01f369bb478c9872979a52ef31a4a2e9fef` |

## 使用已发布结果

完整 source/build/publication ID 与 root 见 [publication-result.json](publication-result.json)，可直接复用 [verification.json](verification.json) 中的注册工具查询参数。

从仓库根目录执行（工业富联主快照示例）：

```bash
uv run python -m plugins.corpus.structured.cli query \
  --source-id f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb \
  --build-id f16e7fde95537f0656a69cb1547232ca26a0347b3823d0dc1844dbf798149314 \
  --purpose cite --limit 20 \
  --store-root /home/administrator/FrontierAgent/.local/claims-r2-publication-20261013/stores/d6546966ac517902659ed66c4fbdc7efd8512725a0ba1ef9d507844718bac055
```

研究进程通过 `CORPUS_STRUCTURED_ROOT` 选择其中一个精确快照的根目录；本次没有更改全局 `.env` 或默认生产入口。顶层目录是发布目录集合，不是可查询 store。

## 发布边界

- O1 显式缺口：原 RoleArtifact/MaterialRun/EvidenceRun 字节不变；原 failed/outcome_unknown/review_required 状态保留。
- 内容寻址的 `corpus-publication-selection-v1` 选择清单由现有 manifest.reason_codes 的 `SCOPED_RECORD_SELECTION_V1:<sha256>` 绑定，包含选中/排除记录、未完成槽位、遗漏 unit、原执行/协议/质量状态；原 v1 Schema 未改。
- manifest 为 published + review_required，已发布角色覆盖为 partial；查询携带 CS_PUBLICATION_EXPLICIT_GAPS。items 保留 review_required；A4 只在选中、证据完整且真实送达时允许 cite，并保留缺口标记。
- 非选中记录不进入查询；未裁定、错误、重复、out_of_scope、未完成槽位与无引用许可分别记录，明细见 release-plan.json。
- 补跑评分记录使用 slot#ordinal，部分没有逐字等价的正式 item 载体；仅精确文本与 semantic_type/statement_role/polarity 一致且唯一者进入发布。没有从评分表反填或合成生产条目。
- 227 条已发布 items 不等于质量门的 240 条合格评分候选，更不代表 48 条金标全部命中。查询 no_match 不表示整篇没有该事实。

## 验证

- 407 项 structured 测试通过，含 8 项新发布边界回归；tests.log 保留实际输出。
- 新进程 cwd=/tmp，5/5 发布回读，279/279 记录逐页查询，286/286 原文区间核对，7/7 分角色注册工具正向查询；SQLite 主文件与源工件哈希不变。
- 定向 Ruff、Pyright（0 错误）、git diff --check 通过；framework import 390/390，symbol closure 0 missing / 488 files，证据守卫 violations 0。
- eval import 为 437/438，唯一失败是环境未安装 harbor，与本次改动路径无关；未执行真实模型 preflight（本票模型额度为 0）。

## 剩余工作

真实 M_main delivery/context_use/report_reference、主计划阶段验收与生产化仍未完成；评分器读取契约阈值仍归 Issue 41。
