# Issue 23 · 44 条关系金标全量统一审计

Status: human signed by xyl; gold-v2 frozen
Model calls: 0

## 结果

- 全量审计：44/44。
- 可评分：38；不可评分：6；truth 更正：2。
- 零调用敏感性：37/38；等比例最低门：35/38。
- 剩余语义错误：pair_4adac65ac8099417。
- 本结果不能回写 Issue 22 的历史失败终态；gold-v2 已由 xyl 独立签认并冻结。

## 不可评分候选

- `pair_75e57fa1a91444d1`：The generic request '请您介绍一下' contains no retained referent or question predicate.
- `pair_accf55e14399b995`：The target combines external procurement and Taijin share while the source supports only the whole-solution rationale.
- `pair_cd8df0324de3133f`：The target '不一定全部' omits what is incomplete; the frozen pair window does not restore the object.
- `pair_af4a1d9299403d27`：The isolated capacity and product-mix endpoints lack a complete shared subject, scope and period binding.
- `pair_0cc897a5c1f55daf`：The delivery and acceptance-payment endpoints omit the required subject, object and payment ownership bindings.
- `pair_d7b6eabfa488078d`：The question fragment '还是什么？' retains neither a referent nor a predicate to answer.

## Truth 更正

- `pair_1a9d24af1bf7107f`：absent → present（收入计算的更换频率组成答案）。
- `pair_dc4f0640ec6b4b11`：absent → present（make-or-buy 回答的互补原因）。

## 冻结规则

gold-v2 已签认，不得根据模型结果调整。只有原文、候选身份或证据绑定错误，才允许通过独立签认的 addendum 更正。
