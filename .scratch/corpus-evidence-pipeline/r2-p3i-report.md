# R2 P3-I 字段契约桥接报告

日期：2026-09-14  
状态：**零模型投影与反例门通过；桥接规则待人工复核；P4预算未冻结**

## 结论

P3-I 在 evaluation seam 新增一个 development-only 深模块，把既有35条人工批准原子分母投影到
P1十字段轴。模块只有两个外部动作：`build()` 生成完整投影与精简复核接口，`validate_review()`
验证人工结果。生产 `plugins/corpus/_r2_plan.py`、`_r2_audit.py`、`_r2_runtime.py` 均未修改。

用户允许本阶段使用模型，但评分契约必须前瞻冻结，故本阶段实际模型调用为0；没有让模型决定自己的
验收标准。PostgreSQL、holdout、relation、入库均为0。

## 投影规则

- `speaker_ref`：由 `scope_id + speaker_role + identity_status` 生成稳定不透明引用；registry保留
  角色与身份状态，可逆检查通过。35条item去重为8个speaker entry。
- `value`：27条保持显式unknown；5条为来源规范化字面子串；3条只允许使用命名、白名单转换规则，
  不存在通用自由改写。
- `unit`：仅在source quote明确出现`元`或`$`时提出；复合value与单值分开标记。不存在单一明确
  scalar unit的3条保持unknown，不猜测shares、ratio或评级单位。
- `unknown_fields`：49个不确定性逐个映射为`unknown_field:<name>`约束，无丢失、无去重冲突。
- 完整35条投影仅供 evaluator 使用，明确禁止进入模型prompt，防止金标泄漏。

## 结果

| 项 | 结果 |
|---|---:|
| item projection | 35 |
| speaker registry | 8 |
| 非空value | 8 |
| source-observed value | 5 |
| allowlisted transform | 3 |
| unknown value | 27 |
| unknown constraints | 49 |
| 测试 | 21 passed |
| Ruff | passed |
| Pyright | 0 errors |

I0—I5通过；I6人工桥接批准仍为`not_evaluated`。空模板不会被代理自动签名。

## 人工复核范围

人工不需要重审35条原子性或全部直接语义轴。只需：

1. 批准或修订1组全局规则；
2. 批准或修订8个去重speaker映射；
3. 批准或修订8条value/unit投影，重点关注3个白名单转换。

全部批准后保存为`r2-p3i-field-review-completed.json`。校验器要求逐项理由、布尔检查与三个汇总
数量一致；任何`needs_revision/reject`均保持P4关闭，仅回到development零模型修订。

## 冻结绑定

- change scope：`a419d459d7da44c367c4b85337f9c4b24d885ad68c7a7f0c3857442f9083218c`
- bridge module：`27f189d937017b8e279bd64b99af85796137836b60f0af656d2ea8ffef6232fe`
- tests：`1e525e68f67eb7b8811669c1e487a9a69201a56d044f5b3c83879758b1b2dcea`
- projection inventory：`b2632e12ad5421721538587a159fdac2f5b8f08007e21c6c196e9ac1c33e483d`
- human template：`0111c5bc62fd695f8105db5b38282a80cfa0d48a4c50e44cbd9efa44fe566230`

## P4出口

I6全通过后仍需先实现并反例验证P4 scratch runtime/scorer对三条获批transform、speaker registry及
unknown constraints的执行语义，然后冻结绑定runner/scorer/prompt/model/config的单轮预算。
预算上限保持35 item、5个批次、5次总调用（首次兼作provider连通性检查）、0重试；关系、holdout、
PostgreSQL、入库为0。P4模型输出的text/constraints忠实度仍需结果后人工裁决。
