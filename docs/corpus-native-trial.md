# 原生正文混合检索工具试用

2026-10-22。状态：代码接入和隔离库工具回归完成，默认关闭。本功能沿用已验证的“保留原首条＋全局块级RRF＋最多20块／16,000原文字符”，通过现有 `corpus_search → corpus_fetch` 调用，不新增Agent工具。

后续正式发布：用户已授权直接发布到正式库，`postgres` 已启用独立的 `release` 模式。本文保留试验模式操作；正式配置、数据迁移和回退见 [正式发布说明](corpus-native-release.md)。下文的试验库限制适用于 `pilot` 模式。

## 开关与使用

仅允许显式的 `vector_pilot_*` 库。环境变量说明已写入 `.env.example`；实际 `.env` 没有修改。

| 变量 | 值与用途 |
|---|---|
| `CORPUS_NATIVE_RETRIEVAL` | `off`（默认）或 `pilot`；开启后在新读链优先采用原生正文策略 |
| `CORPUS_NATIVE_TARGET_DB` | 必须与服务实际目标库一致 |
| `CORPUS_NATIVE_INDEX` | 已校验范围／向量种子包的 `manifest.json` 路径 |
| `CORPUS_VECTOR_TARGET_DB` | 必须与上述目标库一致；模型空间必须与种子包一致 |

当前操作包位于 `data/corpus-native-pilot/20261021/manifest.json`，包含23个明确允许的原生资料来源及已验证的缓存向量。运行代码不读取题号、答案、金标或 `.scratch` 排名。包中的旧正文仅用于文件完整性校验，候选正文、发布日期、准入和活动版本每次从PG读取。

在WSL项目目录单次检查服务路径：

```bash
CORPUS_VECTOR_TARGET_DB=vector_pilot_clean7_20261021 \
CORPUS_NATIVE_RETRIEVAL=pilot \
CORPUS_NATIVE_TARGET_DB=vector_pilot_clean7_20261021 \
CORPUS_NATIVE_INDEX=data/corpus-native-pilot/20261021/manifest.json \
uv run python -m plugins.corpus.retrieval.cli query \
  --mode hybrid --query 'DeepSeek如何降低训练成本？'
```

CLI在该进程内复用已有连接凭据并切换数据库名。实际CLI/TUI/Web服务进程也需配置匹配的 `CORPUS_DSN`、`CORPUS_TARGET_DB` 和 `CORPUS_READ_CHAIN=new`；不能仅修改一个库名开关却继续连接其他数据库。配置错误会明确失败。新查询向量未命中缓存时会调用现有embedding服务。

关闭试用设置 `CORPUS_NATIVE_RETRIEVAL=off`。后续搜索恢复原有服务选择策略；已发出的原生正文句柄仍能读取其原始版本和范围，不需要保持开关开启。资料撤销后这些句柄同样拒绝取证。

## 搜索与取证

搜索保持默认最多10条命中。同一build中选中的多个正文块合并成一条命中，取证计划包含完整的多个定位符。因此“10条命中”与“最多20个正文块”并不冲突；若调用方要求更小的命中数，尾部来源可能被省去，不能据此继承默认预算的覆盖成绩。

每条命中的 `snippet` 展示该命中内按融合名次的前 2 个块：每段以 `【序号/总块数｜页码】` 开头、只取块首约 180 字符，末尾注明还有多少块未展示。不同段来自不同位置，**不是连续原文**，仍只用于定位。

`corpus_search`只返回预览和取证句柄，预览不算证据。原生检索的命中只保留一份句柄数组：直接用同一命中的 `doc_id` 与完整 `context_locators` 调用 `corpus_fetch`，参数名用 `locators`，`view=compact`；参数使用`locators`时不要同时传`locator`。该路径不再返回与 `context_locators` 内容相同的 `fetch_plan`，以免重复占用返回预算。非原生路径仍保留 `fetch_plan`。

返回体超出工具预算时按**整条命中**让位，不再把每条 `snippet` 统一截短；`hits_elided` 给出被省去的命中数。`coverage.native.blocks_returned` 是本次实际合并进命中的块数，`blocks_ranked` 是参与排序的候选块数。

新句柄形如 `chunk:native1/<编码后的原chunk_id>/<内容及坐标摘要>`，与 `cv2:<build_id>`共同绑定。摘要取完整 sha256 的前 16 位（64 bit），用于确认补读到的是搜索时展示的那一份；`corpus_fetch` 仍按完整摘要比对前缀，早先发出的 64 位句柄继续可读。不要把它改写成普通chunk句柄；普通句柄仍保留原来的整块及上下文读取语义。

`corpus_fetch`原有单块、批量、分页接口保持不变。`text`或`items[].text`是实际原文；`native_slices`说明每段正文在权威单元中的字符区间、页码、原文哈希，以及在本次返回片段中的偏移。普通`source_ranges`不冒充这些新映射。多个不连续区间用换行分开，不把它们描述为源文档中连续的一整句。

16,000字符限制指一次搜索选出的全部正文，不包含JSON和定位元数据，也不是整次Agent任务的token上限。取证默认每页6,000序列化字符，必须续取`next_cursor`，直到`fetch_complete=true`。原生句柄使用带长度上限的压缩游标，校验和及原有绑定语义保持不变；旧游标仍可解码。

## 资料更新与向量同步

允许范围内来源发布新build后，下一次搜索从PG重新投影，不再召回其旧活动版本。来源撤销、文件名或日期变化也会重新读取。日期上限使用运行当天，题面明确“截至YYYY年M月D日”时进一步收紧；未知日期保留并单独标记。

范围仍是显式来源清单，不自动把新入库文件、扫描件或OCR派生来源加入试用。增加新的原生来源需生成并校验包含该来源的新范围包，再修改`CORPUS_NATIVE_INDEX`。已允许来源的版本更新不需要重做范围包。

按当前正文投影的精确输入哈希复用向量。新输入没有向量时，整次查询在**同一原生正文范围和同一预算**内降级为关键词检索，返回`fallback_reason=native_vectors_pending`；不会退回包含图表／OCR的全库路径。

手动同步命令默认零请求，可先导入已存在的缓存并检查缺口：

```bash
CORPUS_VECTOR_TARGET_DB=vector_pilot_clean7_20261021 \
uv run python -m plugins.corpus.retrieval.cli native-sync \
  --native-index data/corpus-native-pilot/20261021/manifest.json \
  --max-requests 0
```

确需生成新向量时，将`--max-requests`设为本次允许的请求数。命令只维护`corpus_retrieval.embeddings`，不修改资料发布指针；每个输入先落下任务状态，再请求模型。失败或结果不确定会停止本次同步，既有`running/failed/uncertain`不会自动重试，避免重复计费。`blocked_this_run`需结合原任务状态排查；本命令没有隐式清除这些状态的入口。

同步完成再次读取当前发布版本，避免网络调用期间版本变化却被标成全部就绪。向量完整后，后续搜索自动恢复混合检索。同步不是定时任务，不修改源PDF、清洗结果或OCR配置。

## 降级与拒绝

| 情况 | 行为 |
|---|---|
| 新正文向量未齐 | 同范围关键词降级，显式标记pending |
| 查询embedding失败／超时 | 同范围关键词降级，返回安全错误码 |
| 向量SQL失败 | 回滚该查询的保存点，保留正常的关键词结果 |
| 目标库／模型空间配置错误 | 明确失败，不查询其他库 |
| 读取过程中发布状态变化、原文哈希不符 | 明确失败，不拼接两个版本，也不伪装成“没有资料” |
| 来源已撤销 | 搜索排除，历史句柄取证拒绝 |
| 关闭试用开关 | 新搜索恢复原有策略，历史有界句柄仍按原范围读取 |

## 已验证范围

23份原生资料、585块、旧32题＋新25题。57题通过实际工具`ainvoke`，搜索消息经过12,000字符压缩，取证默认每页6,000字符；逐字重建的选中正文与此前冻结结果相同，旧题29处可覆盖标注及新题26组证据均保留。57题的消费账本范围均完整。关闭开关另跑57题，与原服务结果一致。

生命周期在真实PG的回滚事务中验证：活动build变更、旧句柄读取、撤销、新输入缺向量、模拟embedding补齐、重复同步、SQL故障与恢复。模型补齐使用测试向量，不计为真实供应商验证。另通过真实CLI把102条已有向量导入隔离库缓存，重复同步新增导入及模型请求均为0，发布指针未改。

这完成了本次受控工具试用接入，不代表默认生产切换、回答模型质量、未见问题泛化或500份资料吞吐已经验收。当前仍每次构建临时检索表并核验原文；新来源范围维护和大规模性能需要单独验证。

执行证据与检查状态见 [本轮报告](../.scratch/corpus-native-tools-20261022/report.md)。
