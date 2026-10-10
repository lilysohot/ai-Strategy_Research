# 27 · challenges 规则去“转折”触发条件 · 收紧为显式命题冲突

Status: completed
Type: task
Parent: [24 · Relation boolean 协议](24-relation-boolean-protocol.md)
Model attempts: 0（规则修订、冻结回放与测试均为零调用）
Production database access: 0

## 问题

`plugins/corpus/material_semantics.py` 的 `MATERIAL_RELATION_SELECTOR_PROMPT` 关系类型原子判定规则写：

> challenges 包括原文明示的反驳、限制、转折以及说话人对自己刚提出假设的显式修正；两个可同时成立的
> 不同维度事实不是 challenges。

该定义自相矛盾，并已产生真实假边：

- `pair_1f74637d78897251`（`rel_851e403cdfae400b`）：左端“22年到23年看报表是近几年比较好的业绩”
  （回顾，过去期间），右端“但今年到明年肯定更好”（展望，未来期间）。
- 二者针对不同期间、可同时成立，正确类型应为 `absent`（gold-v2 亦判 absent）。
- 但原文含显式转折词“但”，命中“转折”子句，模型据此判 `challenges`——**规则符合性行为，非模型偏离**。
- 该假边已被 Issue 25 保留进 213 条 relation 产物，并成为 Issue 26 Q4 的 harm 探针。

同类结构性问题在 Issue 25 失败集中占 4/8（challenges 字面/推断混杂）。

## 目标

消除“转折”作为独立触发条件导致的 `challenges` 假阳性，使 `challenges` 只在存在显式命题冲突时成立。

## 已执行修订

1. `challenges` 收紧为必须存在显式命题冲突：同主体 + 同谓词 + 同范围/期间，且含否定、反义或纠正。
2. “转折”从独立触发条件降级为“仅当转折后的命题与前命题构成命题冲突时才计入”。
3. 明确“可同时成立的不同维度事实不是 challenges”优先于“转折”子句（冲突时判 absent）。
4. 反例固定：`pair_1f74637d78897251` 必须判 `absent`。

## 边界与约束

- 不修改或取代已签认 gold-v2。
- 不复活 Issue 25 已关闭路线；本票只改规则定义，不改模型选型。
- 不发布，不写生产库。
- 修订后须零调用窄化归一 + 冻结样本回放验证，不得仅凭 prompt 文本变更即宣称修复。
- 反例须纳入测试文件并验证。

## 风险

- 收紧后可能误伤“原文明示的反驳/限制/自我修正”类真 challenges，需以既有 challenges 正例回归。
- “命题冲突”判定仍依赖模型语义，需给出可操作判据，避免引入新的模糊边界。

## 执行结果

- selector 与 question-group v1/v2 提示词均已删除“转折即 challenges”的含义，明确同主体、同谓词、
  同范围、同期间以及显式否定/反义/纠正要求。
- controller 增加高精度窄化门：仅有“但/然而/不过”的 positive terminal 归一为 absent；显式纠正、
  否定或自我修正词仍可保留。该门不改变候选生成，因此保留后续语义核验的召回入口。
- 固定反例 `pair_1f74637d78897251` 在零调用回放中从 present 降为 absent。
- Issue 25 冻结产物的 12 条 challenges 中，2 条保留、10 条降为 absent；这是对旧产物的反事实回放，
  未改写 Issue 25 存储或 gold-v2。
- `tests/test_corpus_material_semantics.py` 全量 88 项通过，包括固定反例与显式自我纠正正例。
- relation 抽取调用 0；publication/生产库访问 0。

## 关联

- 反例来源：Issue 25 `pair_1f74637d78897251`；探针：Issue 26 Q4。
- 规则文件：`plugins/corpus/material_semantics.py`（`MATERIAL_RELATION_SELECTOR_PROMPT`）。

## Evidence

- `../evidence/27-challenges-rule-20261010/r0-zero-call/`
