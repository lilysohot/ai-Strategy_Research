# R2 P3-S 人工原子分母复核说明

本复核只回答一个问题：**系统提出的35个最小节点，是否各自构成一条完整、可核验且没有混入无关
命题的研究材料 item。** 它不要求审阅人判断观点真假、投资价值或模型字段，也不批准表格语义。

## 谁来复核

由一名能读懂研报、电话纪要和交易复盘的人工审阅人完成。审阅人不需要修改代码，但不能由生成
节点的 agent 代签。可以由项目负责人本人完成，也可以指定研究员或数据标注负责人。

## 使用文件

冻结模板：[r2-p3s-denominator-review-template.json](r2-p3s-denominator-review-template.json)。
请复制一份为 `r2-p3s-denominator-review-completed.json` 后填写，不要覆盖冻结模板。

模板共有35条记录。每条已经给出：

- `source_quote`：冻结的来源原文；
- `generated_scope_ids`：P3-S生成的完整研究范围身份；
- `proposed_clause_nodes`：P3-R提出的最小节点、坐标、文本和哈希；
- 四个待填写的检查项及人工裁决字段。

## 每条记录怎么判断

四个检查项必须分别填 `true` 或 `false`：

1. `one_research_statement`：节点是否只承载一条可独立记录的事实、预测、观点、问题、回答或行为；
2. `necessary_condition_or_attribution_retained`：去掉的上下文是否不会丢失必要条件、否定、时间、对象、
   说话人或引用归属；
3. `no_unrelated_claim_merged`：节点是否没有把另一条独立命题合并进来；
4. `source_quote_and_locator_sufficient`：现有原文、范围和坐标是否足以回取并复核该节点。

然后填写：

- `human_decision`：只能是 `approve`、`reject`、`needs_split`、`needs_merge`；
- `human_reason`：必须写明理由，不能留空。

裁决口径：

- `approve`：四项检查都为 `true`；
- `needs_split`：节点仍包含两条或更多独立命题；
- `needs_merge`：节点缺少相邻条件、否定、对象、时间或归属，单独记录会改变原意；
- `reject`：该内容不应进入研究 item 分母，或现有证据不足以判断。

全部完成后填写顶层 `reviewer_name`、ISO 8601格式的 `reviewed_at`，并把顶层
`approved_records` 改为实际 `approve` 数量。

## 如何校验填写完整性

在项目根目录运行：

```bash
uv run python .scratch/corpus-evidence-pipeline/p3s_review.py \
  --validate-human .scratch/corpus-evidence-pipeline/r2-p3s-denominator-review-completed.json
```

校验器会检查35条身份是否齐全、是否重复、决定值是否合法、理由是否填写、四项检查是否全为布尔值，
以及 `approved_records` 是否与实际决定一致。它不会替审阅人改变或解释裁决。

## 裁决后的处理规则

- 35条全部 `approve`：人工分母门通过，才可以评审是否冻结P4有限模型预算；仍不是自动放行。
- 任一 `needs_split` / `needs_merge`：只在development修订P3-R/P3-S并零模型复验，不调用模型。
- 任一 `reject`：先修订固定分母及理由；禁止通过删除失败样本提高通过率。
- 任一来源坐标不足：P3-S退回blocked，先修scope-provider，不进入P4。

7个公司表格packet本轮只验证了类型和完整覆盖，未纳入这35条人工分母。若后续产品要求表格claim，
必须另立table item契约与人工样本，不能把本次prose审阅当作表格语义验收。
