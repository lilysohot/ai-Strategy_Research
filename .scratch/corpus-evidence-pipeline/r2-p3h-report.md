# R2 P3-H：人工分母裁决应用与定向修订

日期：2026-09-14。结论：**首轮人工文件有效；4条非批准意见已形成可审计修订，5条替代项等待
人工复核。P4仍未授权。**

## 人工提交核验

用户提交文件SHA-256为
`e171ce7b02bb11b77a86d08a0880d9d42da7990fedf94b3976fe931b5c79a609`，审阅人Xyl，时间
2026-09-14 16:40:00。校验器确认35条身份完整、无重复，决定、理由、四项检查和批准总数一致：

| 决定 | 数量 |
|---|---:|
| approve | 31 |
| needs_split | 2 |
| needs_merge | 1 |
| reject | 1 |

用户直接填写了冻结模板路径。为同时保留人工证据和恢复冻结基线，原文件已移动为
`r2-p3s-denominator-review-completed.json`，内容和提交SHA不变；冻结空模板已按原生成过程恢复，
SHA重新匹配P3-S清单的`443d6136...f6d59`。没有覆盖或改写人工决定。

## 修订内容

冻结的v1 development gold没有修改。新增 amendment overlay，绑定base gold和人工提交哈希：

1. 公司评级：原“目标价+评级”复合item替换为独立 `“强推”评级`；
2. 行业回答：把“关注供需改善”与不完整的“价差扩张”合为一条回答，原两条answers关系合为一条；
3. 铜箔总结：拆为“国产替代阶段”“泰金增长潜力”“表处理设备增量”三条；
4. 听音检查：从item删除，加入 `human_rejected_call_setup_not_research_item` 排除项。

首轮31条approve中，“关注供需改善”因参与合并，其旧批准不能自动继承；所以只有30条原item批准
可安全carry forward。修订新增5条替代item，全部为`proposed_not_approved`。

修订后的有效分母为6个微范围、35个item、16个正关系、8个负关系、6个排除片段。item数量仍为
35不是为了维持旧分数，而是“删除1、合并2为1、拆分1为3、替换1为1”的自然结果。正关系由17
变16是因为两个重复answers端点随合并变为一个。

## 零模型重放

amendment应用后，35/35 item分别映射到35个不同的唯一最小子句节点，并全部落在唯一全文范围；
16个正关系和8个负关系端点均可引用。公司短评级在全文其他位置重复，评估时使用冻结微范围内
其他目标的共同位置消歧；该信息只用于评估，不进入scope-provider或planner生成interface。

基础gold对象在内存应用前后hash一致，磁盘gold未改。P3-R和P3-S冻结源码、生产模块、模型、PG、
入库、市场及holdout均未触碰。

## 门禁

| 门 | 结果 |
|---|---|
| H0 人工提交有效 | passed |
| H1 amendment确定性与base不可变 | passed |
| H2 有效分母计数、节点、范围和端点 | passed |
| H3 30条不受影响批准安全继承 | passed |
| H4 5条替代item人工批准 | not_evaluated |
| H5 生产及旧流程隔离 | passed |

P3-H新增18项测试，与P1/P2/P3/P3-R/P3-S组合共293项通过；Ruff通过、目标Pyright为0错误，
import smoke为339/339与388/388，symbol closure为438文件0缺失，P2保护校验仍为2336个旧文件
不变及3个登记私有模块哈希一致。H4不是模型任务，agent不能根据首轮理由自动代签新措辞。未通过
H4前不能评审P4预算。

## 需要人工做的最后一步

只复核 [5条替代项模板](r2-p3h-remediation-review-template.json)，不是再审35条。每条继续填写四个
布尔检查、`approve/reject/needs_split/needs_merge`及非空理由，并填写审阅人、时间和批准总数。
请另存为 `r2-p3h-remediation-review-completed.json`，不要覆盖空模板。

完成后可运行：

```bash
uv run python .scratch/corpus-evidence-pipeline/p3h_review.py \
  --validate-remediation .scratch/corpus-evidence-pipeline/r2-p3h-remediation-review-completed.json
```

5条全approve后，30条carry forward + 5条新批准才构成35条人工分母通过；仍只进入P4预算评审，
不会自动调用模型。任一非approve则继续development零模型修订。

交付包括 [amendment](r2-p3h-denominator-amendment-v1.json)、[重放清单](r2-p3h-inventory.json)、
[5条模板](r2-p3h-remediation-review-template.json)、[执行与校验器](p3h_review.py)及
[18项测试](test_p3h_review.py)。冻结清单外部SHA记录在issue 20最新执行项。
