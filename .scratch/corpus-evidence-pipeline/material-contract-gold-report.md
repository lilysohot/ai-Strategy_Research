# R1 最小材料契约与联合金标冻结报告

日期：2026-09-13  
结论：**R1 完成并按用户新增纪要修订；契约、样本、联合金标、阈值、预算和停止条件已冻结。R2 后续已执行但开发门禁失败。**

## 交付物

- 稳定契约：[材料理解最小契约 v1](../../docs/corpus-material-understanding-contract.md)
- 私有联合金标：`data/corpus/.audit/r1_material_gold_v1_20260913.json`
- 确定性校验：[verify_material_gold.py](verify_material_gold.py)
- 金标修订版 SHA-256：`e8b541a6557189898bd8b86beab66af4b294cec19bc89c7d81e069f70ff0ac1b`
- 上一修订 SHA-256：`38782fb0fa36c13973c1c08c87f7e524e60e690c884289f1b23aa92a06b4b23a`
- 初次冻结 SHA-256：`0fe2eacdf43623cc5b30e59d357ffa57a72072c8f3a7dde0227fa9e7e998ca7c`

私有金标放在仓库已忽略的 `data/` 目录，因为其中包含本地材料路径和短原文摘录；不把研报原文
提交进 Git。样本均来自当前项目的本地 corpus，可用于本项目内处理；来源文件未携带可再分发许可，
因此本轮不复制原文件、不声称拥有对外再分发权。

## 样本盘点与隔离

| 样本 | split | 材料类型 | 研究领域 | 冻结 locator | 既有使用历史 |
|---|---|---|---|---:|---|
| 华创贵州茅台中报点评 `6f14cc14` | development | research_report | company | 1 | 旧 pilot / C1 审计 |
| 长江化工十问十答 `174b6462` | development | research_report | industry | 3 | C1 审计；只是问答体研报 |
| James Bulltard 9/3 复盘 `810ef870` | development | post_trade_review | multi_asset | 5 | C1 审计 / 检索校准 |
| 5月：锂电铜箔和电子铜箔 `80b5a290` | development | conference_minutes | industry | 行 18、24、26、36、182、256、272、274、284、286 | 用户新增；未入库；按设计只作开发样本 |
| 国联民生 CIOE 周报 `8158cbb9` | holdout | research_report | industry | 1 | 未进入旧 C1、pilot、expanded holdout |
| James Bulltard 9/10 盘面回顾 `c46618ab` | holdout | post_trade_review | multi_asset | 1、3、4 | 未进入旧 C1、pilot、expanded holdout |

两个留出 source revision 与旧 87-block 审计的 source revision 交集为 0。开发集与留出集没有相同
文件、相同 hash 或同一页拆分冒充独立样本。

用户新增文件可根据主持人、专家和投资者的连续问答结构认定为 `conference_minutes`，并已补入开发
正样本。“十问十答”仍明确标为 `research_report` + 问答结构，不冒充电话会议。新增文件只有“5月”
而无年份、精确会议日期和参与者实名，因此这些字段保留 unknown；行 256 与 284 的同一行多人话轮
也显式作为分段歧义保留。当前仍没有 `earnings_call` 样本，也没有独立的电话会议/纪要留出样本。
冻结页还发现一处既有标注越界：行业研报第 3 页本身不能支持作者“马太”的身份，已按 unknown 修正，
没有用页外信息或模型输出补齐。

## 联合金标范围

- 37 个目标 item：behavior 8、fact 4、forecast 11、opinion 9、unknown 5。
- 34 个关键 item；表达者、视角、否定/条件、风险、行为状态和 unknown 均进入关键门禁。
- 7 条来源显式关系：4 条 `answers`、2 条 `motivates`、1 条 `supports`；同一 locator 共现不建关系。
- 44 处 item/关系短引文均绑定 sample 级 source hash + PDF 页码或 Markdown 行号，并在冻结 locator
  中唯一回取；
  R2/R3 的运行时输出仍须在每条 evidence 上显式携带 `source_rev`。
- 无数字定性预测保留 `value=null` 与 `unknown_fields`，未因数值 schema 被排除。
- 个人行为统一标成来源 `claimed_executed`，并区分 `contemporaneous` / `retrospective`；成交核验
  保留 unknown。

## 运行前门禁

指标和阈值已在契约与金标中冻结：总体 item 召回至少 90%，关键 item、归属、否定/条件/风险、
行为状态、唯一引文和 unknown 诚实率均为 100%；来源显式关系 precision 为 100%、recall 至少 90%。
全拒绝不能通过召回门禁。

预算为开发集基线 + 最多 2 次规则修订，每文档每次最多 2 个正文调用；留出每文档只运行 1 次、
最多 2 个正文调用。总上限 28 个正文模型调用。留出结果不得继续用于调规则。

停止条件为 source hash/引文失败、留出泄漏、关键归属/否定/行为/关系错误、调用或超时预算耗尽、
以及目标页需要当前不可用的 OCR。遇到停止条件必须报告失败与遗漏，不改金标迎合输出。

## 确定性验证

执行：

```bash
.venv/bin/python .scratch/corpus-evidence-pipeline/verify_material_gold.py
```

结果：`passed`；4 development + 2 holdout、37 items、34 critical items、7 relations、44 aligned
quotes，holdout prior-audit collisions = 0、prior-manifest collisions = 0，model calls = 0。

PDF 目标页另经 Poppler 渲染人工核对，页码、版面与提取短引文一致。新增 Markdown 在不入库的
前提下经现有 `parse_evidence` 只读解析成功（`doc_id=undated_80b5a290`，1 个逻辑页、6 个 packet），
并由校验器按项目 `source_rev`、完整文件 SHA-256、行号和逐字短引文复核。确定性校验均不产生
模型调用。

## 边界与下一任务

本轮没有调用同花顺、没有运行 LLM、没有全库重抽，没有修改数据库、提示词、工具注册或生产门禁。
R1 只完成“先定义再实现”；新增纪要只建立了电话交流纪要的开发正样本。R2 随后实现并执行，
但开发门禁失败，详见 [R2 开发验收](material-semantics-report.md)；R3、电话会议类型独立泛化及全部
PR-DATA-09/10、PR-OUT-06/07 均未验收。
