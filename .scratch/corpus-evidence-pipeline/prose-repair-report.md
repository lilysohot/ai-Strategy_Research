# 07 正文抽取修复与真实验收

日期：2026-09-12。状态：最小正文抽取→校验→保存→取证闭环通过。原来两个非农目标从 0/2 变为修复后 4 次真实调用均 2/2；没有替换原样本、修改原金标或换模型。全库完整性和宏观自动推导不在本次放行范围内。

## 1. 已确定的原因

### 模型请求配置与输出预算不匹配

保持原模型 glm-5.3-flash、600 字证据包、4096 输出预算、60 秒超时，增加安全诊断后复现：耗时 51.656 秒，completion_tokens=4096，reasoning_tokens=4085，content_chars=0，finish_reason=length。失败在事实解析之前。

只加入 reasoning_effort=low 后，同一 prompt（937 tokens）19.517 秒完整返回，completion_tokens=2316，reasoning_tokens=0，finish_reason=stop，得到 18 条候选。这是本次端点反馈，不应解释为所有平台 low 都等于关闭推理。

这个结果与模型方的约束相符：[官方思考模式文档](https://docs.z.ai/guides/capabilities/thinking-mode)说明 GLM-5.3/Flash 不能关闭思考；[官方模型卡](https://huggingface.co/zai-org/GLM-5.3-Flash)说明可选 low/high/max，未指定默认 max。代码原先默认尝试 disabled，被拒绝后移除，但没有指定 effort。

### 后处理的两个独立问题

- `subject_raw=美国`、`metric_raw=新增非农就业` 优先用于派生，但缺少受控映射，因此有效内容没有落到金标的 US/NFP 坐标。现在只映射明确的完整别名，原始字段保留，不接受模型任意身份覆盖。
- 模型将原文 `16.2\n万人` 写成 `16.2万人`，直接逐字匹配误拒。现在只允许空白差异的唯一对齐，恢复到原始子串并记录 packet 内起止偏移、模型引文、源引文和匹配方式。数字校验在恢复后的原始文本上执行，因此源 `1 20` 不能被当作 `120`。

未用增加输出预算或缩小金标来掩盖错误。

## 2. 代码落地

| 边界 | 变更 | 回归保证 |
|---|---|---|
| SDK 调用 | 字符串兼容的 LlmResponse 携带允许记录的诊断；LlmCallError 仅保存异常类型/状态/耗时 | 不保存凭据、请求全文、推理正文或服务端错误原文 |
| 模型配置 | 仅 corpus 对已知 GLM-5.3 / Flash 默认 low，省略不支持的 disabled | 非该模型维持兼容行为；工作流与全局模型不改 |
| 响应判定 | finish_reason=length 优先判失败，即使文本恰好是 [] | 空响应、截断、格式错误、无效记录分别可见；合法 []+stop 才是空成功 |
| 字段派生 | 原始名称受控映射、原值/原单位保留 | 不把 US 改写到任意国家或行业主体 |
| 证据与期间 | 空白差异回取原文；本包没有期间锚点时清空规范化期间、保留模型原期间并标 review | 不靠文件名静默补年份，不猜原值 |
| 运行版本 | evidence-pipeline-5，corpus-chat-3，extractor=3a1f06510fd3 | 历史 pipeline 1—4 的内容 hash 契约兼容，篡改仍拒绝 |
| preflight | 使用现有 load/create_react 与 load/create_swarm facade，支持登记 pipeline 名 | 默认入口真实调用通过；有明确超时，不再卡在旧函数名 |

代码位置：`plugins/corpus/claims.py`、`claims_v2.py`、`evidence_pipeline.py`、`scripts/corpus_evidence_pilot.py`、`tools/preflight.py`。

## 3. 原样本真实调用记录

原金标仍是 US / NFP / 2026-08-31：actual=16.2 万人、consensus=5.6 万人，清单 hash 仍为 `06d40b371a4744a6fb8631e5e17d308365a9db948e45117d8d37a50935b5178f`。

| 轮次 | 单次结果 | 耗时 | completion tokens | 目标验收 |
|---|---|---:|---:|---:|
| 诊断基线，默认 effort | length、正文为空 | 51.656 秒 | 4096 | 0/2 |
| 仅改 low | stop、18 条候选；映射/空白问题仍在 | 19.517 秒 | 2316 | 0/2 |
| 修复名称与证据对齐 | stop、17 条候选 | 14.390 秒 | 2197 | 2/2 |
| 使用代码默认配置重复 | stop、17 条候选 | 14.238 秒 | 2187 | 2/2 |
| 加强期间拒绝后重复 | stop、17 条候选 | 14.299 秒 | 2202 | 2/2 |
| 最终 schema/版本回归 | stop、17 条候选 | 13.969 秒 | 2188 | 2/2 |

后 4 次不是 8 个不同事实，只是同两个目标的重复稳定性观察；也不是严格统计意义上的可用率估计。最终金标检查要求 quality_status=ok、期间有来源锚点、精确引文仍在证据包，并输出匹配 fact IDs。其他 15 条候选未全部人工标注，不能据此宣称它们全部准确。

完整页面仍有 3 个正文包 deferred，每轮只调用第一个包，document.complete=false。报告 overall_pass 仅指冻结目标与负控全部通过，不等于全文抽取完成。

## 4. 未调参留出：数字取值与时间负控

来源为天风证券《非农清障，通胀定调》第一页，文件后缀 `5520fab6.pdf`，source_rev=`d441478b684f27af`。按 PDF 技能视觉核对完整原页后，在模型调用前单独冻结 [prose_holdout_manifest.json](prose_holdout_manifest.json)。

原段落的 actual=16.2 万人、consensus=5.5 万人，与开发样本的预期 5.6 万人不同；未把两个来源合并或把 5.5 改为 5.6。正文只写“8 月”，因此冻结预期是正确取值，同时规范化期间为空、quality=review、不得计算。

真实调用：12.645 秒，925 prompt tokens、1527 completion tokens，stop，12 条候选。两个目标及缺年份负控 **2/2 通过**。这是引用级取值和拒绝错误放行的验收，**不是具有完整时间坐标的宏观观察正例**。

本轮共 7 次 corpus 模型调用：6547 prompt tokens、16713 completion tokens；另有 1 次通用 preflight 调用，用量不计在上述 corpus 统计。没有自动无界重试、换账户或改全局模型。

## 5. 回归与数据库

- `pytest tests/test_corpus_*.py -q`：168 passed。新增回归先复现失败再修复，覆盖 SDK 诊断、截断空数组、非法 JSON 元素/记录、空白数字拼接拒绝、缺年份拒绝和历史版本 hash。
- Ruff、Pyright：通过；修改文件 diff 空白检查通过。
- import_smoke：stage 1 为 330/330，stage 2 为 379/379；check_symbols 为 429 文件、0 missing-symbol。
- 通用 preflight 通过真实调用，耗时约 1.33 秒。judge 配置缺失仍有提示，这不影响本轮人工金标验收，但不能据此开展独立模型评分。
- 最终每轮运行均已保存 PostgreSQL 并加载校验。另对当时全部 38 个历史及新运行执行 load+hash 验证，并检查 63 条已对齐引文的偏移都能回取到记录中的源引文。该专项检查发生在最后一轮模型验收之前；最后一轮另执行了自身的保存/加载校验。
- 原有 documents/blocks/claims 没有全库重建或切换；新增结果写入独立影子版本。

## 6. 复现与产物

现有依赖环境下，在仓库 Linux 根目录运行（只调用原宏观样本第一个候选包一次）：

```bash
uv run python scripts/corpus_evidence_pilot.py \
  --manifest .scratch/corpus-evidence-pipeline/pilot_manifest.json \
  --out data/corpus/.evidence/prose-repair --persist --prose-calls 1 --packet-chars 600
```

GLM-5.3 / Flash 无须临时设置环境变量即默认 low。其他端点需要时用 `CORPUS_LLM_REASONING_EFFORT` 显式配置，模型特定别名/端点 ID 不会被盲目识别为 GLM。`provider_default` 表示不发送 effort，用于受控对照。移除 `--persist` 则不写数据库。原文按用户任务范围发送给当前配置模型；诊断日志不包含原文或凭据。

最终报告：`data/corpus/.evidence/prose-repair/report-78a012e302a9a7fc38b79406b671a83e3402620abc30a38678ec0b036540630d.json`。

最终宏观 run_id：`552942996489beb4f1f44b66d2ab944a48b1d5b9ff2e81ef59b6c61c71c65fbf`。actual fact_id：`42b04a182c4ccac5b497d6df683751e91e2cc5c853be337f6373f21132ed0617`；consensus fact_id：`cd0719072fb92b9c8f316224a07b4eea74d0716576629743d0e99fe6ab1b78a8`。证据包 ID：`9f2a4c75ad6e0c7a132c2602ac435f17fd508e50149b093b3b5ad96a7184865f`。使用 service.load_evidence_run / fetch_evidence 可精确回取。

留出报告：`data/corpus/.evidence/prose-repair/report-1b6096bbf1cc0636bd05e74742b07126bf9c10633555359b15c7ee2c49c43b61.json`。基线与每次中间版本也保留在同目录，未覆盖失败记录。

## 7. 下一阶段边界

已完成：正文实际调用、确定性校验与原文回取的最小闭环。表格 57/57 字段与 7/7 复算维持通过。

尚未放行：全文全部包、更多正文类型、跨来源共识值合并、宏观指标计算、时点回测。NFP 的 usable_for 仍只有 cite，metric_not_registered 明确阻挡计算；缺年份留出仍 review。净利率 50.2% 与复算 49.1674% 的源口径差异不属于本次模型修复，继续由任务 08 处理。

合理的后续顺序：复核已知财务口径差异 → 扩大同类正文/表格留出集 → 明确宏观指标与 actual/consensus/previous 的计算契约。OCR 仍不阻塞当前受控文字数据试验。
