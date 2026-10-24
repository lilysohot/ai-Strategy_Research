# 原生正文混合检索正式发布

2026-10-24 更新：用户授权“开始正式发布，结束本轮优化”后，已在本机 8000 API 启用上下文索引、两块正文展示及 search/fetch 新证据契约。发布代码为 `7653973e`，102 个冻结文件哈希保持一致；185 项相关测试和发布检查通过。来源仍为 23 个、原生块及就绪向量覆盖均为 585。本轮未迁移资料、覆盖原文或改写句柄。

正式配置及执行证据见 [2026-10-24 发布报告](../.scratch/corpus-production-release-20261024/report.md)。下文数据迁移记录保留 2026-10-22 的历史操作；上下文增强现已启用，OCR 仍不在范围内。已知的目标价片段遗漏和 embedding 超时降级作为本轮已知局限保留，不将本次发布描述为所有问题质量均提高。

## 2026-10-22 首次发布结果（历史）

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
| `CORPUS_NATIVE_INDEX` | `/home/administrator/FrontierAgent/data/corpus-native-context/20261023/manifest.json` |
| `CORPUS_VECTOR_INPUT_VARIANT` | `contextual-note-v1` |
| `CORPUS_NATIVE_SNIPPET_BLOCKS` | `2` |
| `CORPUS_VECTOR_TIMEOUT_SECONDS` | `15` |
| `CORPUS_RETRIEVAL_MODE` | `lexical`，作为关闭 native 开关后的原策略 |
| `CORPUS_RETRIEVAL_RANKING` | `off`，旧的独立试验排序开关不参与此次发布 |

`CORPUS_NATIVE_RETRIEVAL=release` 优先选择已验证的混合检索链；上表中的 `CORPUS_RETRIEVAL_MODE=lexical` 不表示当前运行关键词检索。实际结果的 `coverage.retrieval_mode` 为 `hybrid`，发生故障才返回 `lexical` 和具体 `fallback_reason`。

三个目标库设置必须匹配实际连接的数据库。当前范围包使用 `native-evidence-contextual-1`，其向量输入必须匹配 `contextual-note-v1`；原包 `native-evidence-release-1` 保留。旧试验包仍只允许 `vector_pilot_*`。业务库 `apodex` 和 PostgreSQL 模板库不能成为 native 检索目标。

当前 search 仅将 `evidence_contract=native-search-evidence-v1` 的 `evidence_spans` 标记区间作为可引用原文。实际送达且足够支撑结论时无需例行 fetch；缺失限定条件、解释或其他正文时，使用同一命中的 `doc_id` 与对应 `context_locators` 补读。说明仅参与索引，不能当作原文证据。结果压缩仍需保留完整证据映射；摘要不能替代原文凭证。

仅回退本次上下文配置，可运行 `PYTHONPATH=. uv run --no-sync python .scratch/corpus-production-release-20261024/runtime.py rollback`：恢复切换前的三个配置项并正常重启 API，保留本轮代码和资料。脚本要求当前 API 就绪且没有 queued/running 用户任务。此操作未在正式环境来回演练；不是代码版本回退。

## 2026-10-22 数据发布操作（历史）

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
  --native-index data/corpus-native-context/20261023/manifest.json \
  --max-requests 0
```

`--max-requests 0` 仅检查及复用缓存；需要新向量时显式设置本次请求上限。新来源需要更新允许范围包，不会因入库自动加入当前 23 来源的策略。失败或结果不确定的向量任务不自动重试。

上下文说明绑定 build/chunk。新 build 缺少对应说明时不会借用旧 build 的说明；需要按 [上下文包流程](plan/corpus-contextual-vector-retrieval-pilot.md) 生成说明并构建新的版本化包，再校验切换。仅同步向量不会自动补出说明。

## 关闭与回退

将 `.env` 中 `CORPUS_NATIVE_RETRIEVAL` 改为 `off` 并重启服务，即恢复原关键词检索路径。保留目标库、范围包及历史数据，已经发出的 native 句柄仍能按原版本回读。关闭功能不撤销本次资料发布。

以下是 2026-10-22 的完整 native 功能关闭助手，会先检查没有活动用户任务，再修改开关并正常重启。仅撤销 2026-10-24 上下文配置应使用前文的新助手，不要混用：

```bash
PYTHONPATH=. uv run python \
  .scratch/corpus-production-release-20261022/runtime.py rollback
```

原库备份、配置备份及旧进程环境位于 `data/corpus-native-release/20261022-backup/`，配置备份权限为 0600。常规功能回退无需恢复数据库；完整备份用于数据故障恢复，恢复前须先保护发布后的新增数据。

## 验证边界

57 题是 2026-10-22 的开发／回归集。它们的工具输出与当时冻结结果一致，不能表述为 57 题全部回答正确。2026-10-24 的 185 项测试和两题正式接口探针证明工程链路可用，不构成全库质量、吞吐或延迟分位数结论。独立真实查询盲测及已知回退见本轮发布报告；扩大来源范围不在本次发布中。

## 上下文感知方案与范围

2026-10-22 已将讨论确认的上下文策略与执行安排补入 [混合检索方案 §30](plan/corpus-contextual-vector-retrieval-pilot.md#30-面向研究命题的上下文感知与执行安排)，内容交付配套见 [search/fetch 讨论稿](plan/corpus-search-evidence-delivery-redesign.md)。

截至 2026-10-24，片段说明增强索引、有界原文组装与缺失时 fetch 补读已正式启用。方案中的更广泛关系理解、Claims/items 等未因此全部实现；以当前发布报告中的明确范围为准。本轮优化已经结束。
