# 23 · Relation 语义边界更正与零调用敏感性复评

Status: complete
Execution: zero model calls; gold-v2 signed by xyl; signed P11 v1 preserved; 44/44 audited, 6 excluded, 2 corrected, 1 model error retained
Type: task
Parent: [22 · Doubao Seed 2.1 Lite 供应商上限能力复验](22-doubao-lite-provider-ceiling.md)
Model attempt ceiling: 0
Production database access: 0

## 目标

区分 Issue 22 的七个签认样本错误中哪些是明确模型错误、哪些来自关系定义边界、哪些因
question/item 原子端点本身不可独立裁定。不得原地修改已签认 P11，也不得用结果反推新门槛。

## 更正口径

- `answers` 继续要求直接解决问题谓词；仅提供收入计算因子或 make-versus-buy 背景仍为 absent。
- 兼容的不同维度事实不是 `challenges`。
- 缺少指代对象的泛化问题、以及只被原因部分支持的复合 target，标记为
  `exclude_unscorable`，不得继续算作模型错误或正确。
- 更正只形成 agent addendum；在独立签名前不能替换 P11 signed-v1，也不能改变 Issue 22 的冻结失败终态。

## Evidence

- `../evidence/23-relation-adjudication-correction-20261010/r0-zero-call/`

## 复评结果

- 4 条 endpoint-incomplete 候选标记为不可评分：泛化问题缺指代、复合 supports target、
  产能/产品结构缺主体范围、交付/回款缺主体对象。
- 2 条 answers 从 absent 更正建议为 present：扩产意愿是 make-versus-buy 回答的互补原因；
  半年更换频率是专家明确提供的收入换算因子。
- 1 条维持 absent：`6–8 微米 < 4.5 微米 < 3.5 微米以内` 是兼容排序，不构成 challenge。
- reviewed-error sensitivity 为 39/40；已知错误 9/9、旧正确回退 1、target 4/4、
  supports/conditions 回退 0，全部达到等比例门。
- 该结果是看到错误后的复核，不能直接把 Issue 22 改写为通过；必须对全部 44 条统一做端点完整性
  审计并独立签认，才能冻结 gold-v2。

## 全量统一审计

- 已按同一规则审计 P11 全部 44 条，不按模型正确/错误筛选；原 signed-v1 文件保持不变。
- 除先前 4 条外，新增识别 2 条不可评分端点：`不一定全部` 缺少宾语，`还是什么？` 缺少问题谓词
  和指代对象。gold-v2 草案因此保留 38 条、排除 6 条，并维持 2 条 answers truth 更正。
- 对 Issue 22 已有响应进行零调用重算：37/38，等比例最低门 35/38；已知错误 9/9、旧正确回退 1、
  target 4/4、supports/conditions 回退 0。唯一剩余语义错误仍为兼容厚度排序被判 challenge。
- `full-cohort-audit.agent-draft.json` 逐条记录 44 项；`gold-v2.agent-draft.json` 已由 xyl 于
  2026-10-10 签认并冻结。P11 保留为 signed-v1，Issue 22 历史失败终态不变；本签认只授权进入
  relation 协议修复和零调用验证，不自动授权真实模型复验。
