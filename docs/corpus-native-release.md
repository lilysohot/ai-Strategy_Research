# 原生正文混合检索正式发布

2026-10-22。用户明确授权“可以直接发到正式库中”后，已将当前已验收策略发布至 `postgres.corpus`，并在本机 8000 服务启用。上下文增强保持后续独立实验，OCR 不在此次发布范围内。

## 发布结果

- 正式活动来源由 8 个增至 23 个，包含已验证的旧资料和新增原生文字研报。原有历史 build 保留，既有原文不覆盖。
- 23 个活动来源对应 585 个原生正文投影，复用 575 个精确输入匹配的向量。正文及引用坐标仍以 PG 权威单元为准。
- 通过现有 `corpus_search → corpus_fetch` 和 HTTP 资料检索接口使用。沿用原首条保护、全局块级 RRF、最多 20 块／16,000 原文字符的策略。
- 实际 `.env` 已启用 `release`，API 已正常重启。新查询缺少向量缓存时调用现有 embedding 服务；查询超时设置为 15 秒，错误时在同一正文范围内降级关键词检索。
- 保留完整来源与构建的解析缺口记录。正文投影排除图表和 OCR 派生来源，并不声称全文或图像已经完整提取。

发布的源代码基线是 `e0456fcf`，本次增量增加正式目标绑定及发布包支持；完整执行证据见 [发布报告](../.scratch/corpus-production-release-20261022/report.md)。

## 当前配置

| 配置 | 当前正式值 |
|---|---|
| `CORPUS_TARGET_DB` | `postgres` |
| `CORPUS_READ_CHAIN` | `new` |
| `CORPUS_NATIVE_RETRIEVAL` | `release` |
| `CORPUS_NATIVE_TARGET_DB` | `postgres` |
| `CORPUS_VECTOR_TARGET_DB` | `postgres` |
| `CORPUS_NATIVE_INDEX` | `/home/administrator/FrontierAgent/data/corpus-native-release/20261022/manifest.json` |
| `CORPUS_VECTOR_TIMEOUT_SECONDS` | `15` |
| `CORPUS_RETRIEVAL_MODE` | `lexical`，作为关闭 native 开关后的原策略 |
| `CORPUS_RETRIEVAL_RANKING` | `off`，旧的独立试验排序开关不参与此次发布 |

`CORPUS_NATIVE_RETRIEVAL=release` 优先选择已验证的混合检索链；上表中的 `CORPUS_RETRIEVAL_MODE=lexical` 不表示当前运行关键词检索。实际结果的 `coverage.retrieval_mode` 为 `hybrid`，发生故障才返回 `lexical` 和具体 `fallback_reason`。

三个目标库设置必须匹配实际连接的数据库。正式范围包使用 `native-evidence-release-1` 并带 `release_id`；旧试验包仍只允许 `vector_pilot_*`。业务库 `apodex` 和 PostgreSQL 模板库不能成为 native 检索目标。

## 本次数据发布操作

1. 只读核对正式库和试验库的身份、来源、活动版本、扩展和原生范围包。
2. 在真实 PG 的回滚事务内预演资料迁移、现有发布检查、版本发布和向量复用；确认当前正文投影与冻结的 585 块一致。
3. 保存正式库完整逻辑备份、原配置及原发布清单；校验备份哈希和可读目录。原始文件按内容哈希复制到正式归档根 `data/corpus-archive`。
4. 在单个事务内导入缺失的来源、不可变构建、原文单元、检索块及审核／阶段记录。已有不可变构建逐项比对，不覆盖冲突内容。
5. 调用现有 `check_build_publishable → publish_build`，由正常租约及准入检查生成正式发布代次。没有直接复制试验库的 publication 指针或代次。
6. 初始化 `corpus_retrieval` 衍生表，导入精确哈希匹配的已有向量，生成绑定正式库的范围包。
7. 在正式库执行全部 57 题真实工具回归、关闭回归和故障降级探针。
8. 确认没有 queued/running 用户任务后，修改 `.env`、正常终止旧 API 并启动新进程；健康、就绪及认证 HTTP 搜索／原文回读通过。

核心数据库变更是原子事务；配置启用在回归通过之后执行。原有正式历史版本仍可取证。本次没有复制 OCR 派生来源，也没有重新调用模型生成文档向量。

## 后续更新

既有 23 个允许来源发布新 build 后，检索重新读取 PG 活动版本。缺少向量时先降级，手动同步后自动恢复混合检索：

```bash
uv run python -m plugins.corpus.retrieval.cli native-sync \
  --deployment release \
  --native-index data/corpus-native-release/20261022/manifest.json \
  --max-requests 0
```

`--max-requests 0` 仅检查及复用缓存；需要新向量时显式设置本次请求上限。新来源需要更新允许范围包，不会因入库自动加入当前 23 来源的策略。失败或结果不确定的向量任务不自动重试。

## 关闭与回退

将 `.env` 中 `CORPUS_NATIVE_RETRIEVAL` 改为 `off` 并重启服务，即恢复原关键词检索路径。保留目标库、范围包及历史数据，已经发出的 native 句柄仍能按原版本回读。关闭功能不撤销本次资料发布。

本次发布目录中的回退助手会先检查没有活动用户任务，再修改开关并正常重启：

```bash
PYTHONPATH=. uv run python \
  .scratch/corpus-production-release-20261022/runtime.py rollback
```

原库备份、配置备份及旧进程环境位于 `data/corpus-native-release/20261022-backup/`，配置备份权限为 0600。常规功能回退无需恢复数据库；完整备份用于数据故障恢复，恢复前须先保护发布后的新增数据。

## 验证边界

57 题是开发／回归集。它们的工具输出与冻结结果一致，不能表述为 57 题全部回答正确；旧历史标注缺口和信息不足题的口径没有改变。真实 HTTP 的一次冷／暖查询只证明发布路径可用，不构成全库吞吐或延迟分位数结论。上下文增强、独立题验证和扩大来源范围按后续工作推进。
