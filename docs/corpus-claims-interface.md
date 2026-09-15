# Claim 正式入口与兼容迁移

当前状态：默认 service / CLI 已接通 EvidenceRun。旧表不迁移、不删除；旧抽取仅保留显式兼容。
新业务只走以下接口，不再自行选择 claims 或 claims_v2。

2026-09-13 职责澄清：此入口属于研究材料证据链。目标覆盖研报、电话会议、个人交易及复盘中的
观点、论据、视角、条件风险和归属，完整非数值链路仍待 R1—R3 验收。
材料数字及下述财务复算是来源限定的论据/内部核对，不是同花顺数据层的实际观测；
未来跨层比较只读关联，不覆盖原文或自动把 Claim 晋升为行情、政府统计。
实现状态和下一步见 [统一总计划](plan/claims-market-closed-loop-plan.md)，本次说明不改变现有运行时能力。

## 正式接口

```python
from plugins.corpus.service import CorpusService

service = CorpusService()
run = service.extract_claims("report.pdf", pages=(3,), max_prose_calls=0)
result = service.claims_of(run_id=run.run_id, purpose="calculate")
evidence = service.fetch_evidence(run.run_id, result["items"][0]["packet_id"])
# 计算时按公式要求的顺序提供 result 中的 fact_id：
# service.derive_claims(run_id=run.run_id, formula="revenue_growth", input_ids=(current, previous))
```

- extract_claims 默认只处理一个明确源文件，保存到 corpus_evidence_runs；不写 claims / claims_v2。
- max_prose_calls 默认 0，表格确定性抽取，正文候选标记 deferred；需要正文时显式增加预算。
- persist=False 只返回 EvidenceRun，不保存；之后不能假定可通过数据库查询。
- claims_of 返回包含 items、total、offset、limit、has_more、版本和覆盖状态的对象，不再返回旧行列表。
- purpose=cite/compare/calculate 检查 usable_for；audit 可查看无用途许可的记录。
- quality_status 默认 ok。审计所有记录须同时 purpose="audit", quality_status=None。
- claim_observation_projection 固定 purpose=compare；quality=ok 本身不构成可比许可。
- derive_claims 从同一 run_id 加载输入，沿用已有公式、单位、期间、冲突检查。
- 缺失版本报错，绝不自动查询旧表或另一次成功运行。
- 历史 pipeline/extractor/lint 版本仍可审计和引用，但不继承当前比较/计算许可，须重新抽取验证。
- 数值以字符串保留 Decimal 精度；行级 source_rev 是原文件哈希，parse_rev 是解析版本。

## 范围与覆盖

run_id 是精确运行版本，不是“文档当前最佳结果”。claim_runs(doc_id=...) 用于发现可选版本，
不会自动挑选最新一次作为完整结果。分页针对已选版本中的匹配记录；本阶段会先加载整个版本。

complete 只描述 scope.locators 中的处理范围，不承诺全文、全库或指标体系完整。
有匹配记录时 coverage_status=available，但 complete 仍可能为 false；没有匹配且处理失败、
延后、待 OCR 或计算校验版本过期时为 unknown，不能解释成“源文件不存在该数据”。
absent 也只代表已处理选定范围内没有符合本次过滤和用途条件的记录。

## CLI

```bash
uv run python -m plugins.corpus.service extract-claims --source report.pdf --pages 3 --prose-calls 0
uv run python -m plugins.corpus.service claim-runs --doc DOCUMENT_ID
uv run python -m plugins.corpus.service claims --run-id RUN_ID --purpose calculate
uv run python -m plugins.corpus.service claims --run-id RUN_ID --purpose audit --quality all
uv run python -m plugins.corpus.service claim-evidence --run-id RUN_ID --packet-id PACKET_ID
uv run python -m plugins.corpus.service derive-claims --run-id RUN_ID --formula revenue_growth --inputs CURRENT_ID PREVIOUS_ID
uv run python -m plugins.corpus.service reconcile-claims --run-id RUN_ID
```

extract-claims 已保存但范围未完成时返回退出码 1，并输出 run_id 与包级状态；不要把 1 当成未保存。
禁止把旧 --doc/--limit/--dry-run 参数不加模式地用于新入口；默认不隐式全库跑批。

## 兼容调用迁移

| 旧调用意图 | 显式兼容入口 |
|---|---|
| v1 block 抽取 | extract_legacy_claims / CLI extract-claims --legacy |
| 读取 v1 表 | legacy_claims_of / CLI claims --legacy |
| v2 block 抽取与影子表读取 | extract_claims_v2 / claims_v2_of；CLI --v2 |
| v2 原有 ok 行投影 | legacy_v2_observation_projection，仅兼容，非新计算入口 |

旧无版本参数的 extract_claims / claims_of 调用需要迁移；不保留静默分流的重载。
仓库内旧回归测试已显式指向兼容方法；错峰脚本必须显式传 --legacy，防止默认继续旧写入。
旧规则冻结，新功能只进证据链。旧模块仍包含共享能力，因此本次没有机械合并或删除文件。

退役条件：活跃调用方完成切换、兼容对照与回滚验证完成、历史记录的保留策略确认。
未覆盖的旧记录继续只读保存，不能靠字段搬运升级质量状态。不要求此刻全库重抽。

## 验收与限制

见 ../.scratch/corpus-evidence-pipeline/claims-entry-report.md。
本次只完成 service / CLI 接线；未改 Agent 工具注册、检索排序、Web 界面或自动版本晋升策略。
宏观数据目前可能只能引用，净利率口径差异与 OCR 仍属独立后续任务。

财务口径复核更新：reconcile_claims / reconcile-claims 只读对照源净利率与明确选定的利润/收入公式。
数值吻合不证明作者定义；缺输入或口径歧义返回 unverifiable。evidence-pipeline-6 对未经定义验证的
源净利率仅保留 cite，历史版本不覆盖，明确金额输入的公式仍可复算。

## 语义门禁与覆盖状态（pipeline 7 / layout 3）

- 受控财务正文必须有同一原文事实中的指标、数值、单位、期间及实际/预测绑定。
  暂不支持的复杂语法、任意模型口径限定保持仅引用，不因各字段分别出现在同页就允许计算。
- 模型 known_at 不覆盖文档发布日期候选；不同值保留在 evidence_alignment.model_known_at 作审计，
  当前记录带 known_at_unverified_override，不允许计算。
- 文档发布日期仍是候选，不是已核验的历史公开时点；输出 point_in_time_verified=false。
  财务 source_reported/source_forecast 复算不等于允许事件回测。
- 身份涵盖 kind、qualifiers、单位、日期和引文；重复 ID 在读取与计算入口均拒绝。
  对同一个来源数值的冲突实际/预测分类，两条记录均隔离计算。
- derive 也直接检查当前校验版本，不能绕过 service 用历史许可计算。旧 run 可继续引用和审计。
- complete 仍是兼容的包执行状态；coverage_verified=false 明确不证明目标召回。
  没有结果且有预筛跳过时返回 unknown，不将跳过推断成源文件无数据。
- 客户表采用客户名称/销售额/占收入比例的显式列头恢复，保留年份标题、脚注及单元格坐标。
  行名进入 customer 限定，指标为客户销售额/客户收入占比；不冒充公司总收入，也不自动计算集中度。

材料下一阶段见 [统一总计划](plan/claims-market-closed-loop-plan.md) R1—R3；宏观数据接口和计算归 D1/D2，当前未注册宏观计算公式。
首份复核见 [.scratch 报告](../.scratch/corpus-evidence-pipeline/net-margin-review.md)：
目标字段抽取无误，作者口径未证实，未擅自更正源比率。
