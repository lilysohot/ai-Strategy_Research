# R2 P4 模型预算前置契约检查

日期：2026-09-14  
状态：**H4 通过；P4 模型预算未冻结、未消费；字段契约桥接阻塞**

## 1. 人工复核结果

- 提交者：Xyl；复核时间：2026-09-14 17:40:00。
- 5 条替代 item 均为 `approve`，四项检查均为 `true`。
- 提交时 `approved_records` 仍为模板默认值 0；该汇总字段由 5 条逐项决定机械推导为 5，未改变任何人工决定或理由。
- 规范化完成件经 `p3h_review.py --validate-remediation` 验证：5/5 approve，`all_approved=true`。
- 原始提交、规范化完成件与空白模板分别保存，未覆盖人工内容。

绑定：

- 原始提交：`a9f08727224242b6ef1da573c8b6a05c365e1d695d4e0591c169c865a9dfbab4`
- 规范化完成件：`5fe77427e1fc0727ccd16bc8542f26a0f9619161cfad40f1c22e3270a9f46275`
- 空白模板：`270c9c5801bc3383e1732cd63960d4894745fb4cd2caf694f3931e40477f8561`
- 有效 35-item 分母：`3f5e972425074dc3640be8f7b9d80617e7cd78d89034b75b089b03d3dea1577d`

## 2. P4 前置兼容性结果

P3-H 冻结的是原子 item、来源 quote、子句节点及人工原子性判断。P1/P2 的新 item wire/scorer
则要求以下十轴：

`semantic_type, speaker_ref, perspective, speech_role, polarity, behavior_status,
temporal_frame, value, unit, statement_role`。

当前有效微金标使用：

`semantic_type, speaker_role, identity_status, perspective, speech_role, polarity,
behavior_status, temporal_frame, value, statement_role, unknown_fields`。

全量只读检查结果：

| 检查 | 结果 |
|---|---:|
| 有效 item | 35 |
| 缺少 `speaker_ref` | 35/35 |
| 存在 `speaker_role` | 35/35 |
| 缺少 `unit` | 35/35 |
| 存在但新协议未单列的 `identity_status` | 35/35 |
| 存在非空 `unknown_fields` | 31/35 |
| 非空 `value` | 8/35 |

8 个 value 包含多值、数值与单位组合、非数值评级或自然语言比率，例如
`26-28年 67.74/70.77/73.84元`、`10,000 at 14.76`、`$150m`、`64开`。
P2 新运行时只允许经过来源字面绑定的单个 `value/unit`，且尚无获批转换规则；因此不能通过静默拆值、
把 `speaker_role` 政名为 `speaker_ref`、或丢弃 `identity_status/unknown_fields` 来制造 G3 通过。

相关冻结绑定：

- P2 evaluator：`2a6b138a7d3720335b585f4c0760c51f4768a571eca3652c538be759562c0aeb`
- 私有 runtime：`2f8f025177721b74038ea469ee34b55120ce7ac9bf7b35419b9d801f8bd0546b`
- 旧 item policy v2：`c0fed47f53ddc6b7966a32a30054e4a87c28914234077a0dc2b5122775473852`
- 微金标 v1：`214b1f49f82e36c7c2b59496ada20228730439d0bc4b6f17fc51ff87122077c5`

## 3. 归因与停止决定

这是 P1/P2 新协议与 P3 使用的既有语义金标之间缺少“字段契约桥”的流程遗漏，不是 5 条人工原子
复核失败，也不是模型能力失败。若现在运行 P4，G1 可能产生终态，但 G3 没有合法、前瞻冻结的分母；
运行结果必然处于不可验收状态。

因此执行 fail-stop：

- 真实模型调用：0；模型预算未冻结。
- relation、holdout、PostgreSQL、入库：0。
- 公共模块、`plugins/corpus/_r2_*.py`、旧材料流程及其他研报路径：不修改。
- 不复用旧 `r2-item-acceptance-policy-v2` 冒充新 wire 的验收器。

## 4. 推荐补齐项（P3-I）

在 P4 前增加一次零模型、development-only 的字段契约桥接：

1. 前瞻冻结 `speaker_ref` 与 `speaker_role + identity_status` 的表达关系，不能只改字段名。
2. 为 8 个非空 value 明确“原文复合值保留”或版本化 `value/unit` 转换规则；未获批转换保持 unknown。
3. 明确 `unknown_fields` 是顶层不确定性清单，还是逐轴 `unknown_reason`；不得丢轴。
4. 生成 35 条字段目标投影与人工复核模板，并用零模型反例验证缺字段、错单位、错归属、未知矛盾均会失败。
5. 仅在新投影、scorer、prompt、运行器、预算及旧流程隔离共同冻结后，启动原提案的 P4：35 item、最多 5 次批量调用、0 重试、单轮、首次调用兼作 provider 连通性检查。

P4 输出的自然语言忠实度仍需一次结果后人工裁决；字段目标批准不能替代对模型输出 text/constraints 的
结果复核。
