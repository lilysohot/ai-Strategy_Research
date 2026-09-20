# P2 确认单：阈值 / 关键题 / 负例（U 已裁决，未落正式）

- 裁决：**P2 按默认 + 关键题维持 28/30 + 负例全 critical**（U，2026-09-19）
- 评分器：`plugins/corpus/scoring.py` `bf9c8b80d7a9…`（绑定 i0c-r19 / i0c-r21）

## P2-1 阈值（按默认确认）

| 取值 | 冻结值 |
|---|---|
| `top_k` | `5` |
| `min_rate` | `19/20` |
| `require_critical_all_pass` | `True` |
| `max_false_positives` | `0` |
| `max_fabricated_citations` | `0` |

- min_rate 用 Fraction(19,20)=95%，10 题则要求 10/10（精确比较，无浮点漂移）
- 任意领域 DocRecall/QuestionPass/EvidencePass 低于 95% ⇒ below_threshold blocker
- 关键题未全过 ⇒ critical_question_failed blocker
- 误报、伪造引用上限均为 0（超出即 blocker）

## P2-2 关键题（维持 28/30）

- 关键题 28 题（清单哈希 `1f68cd98d774…`）
- 非关键 2 题：industry-006、macro-004
- 口径不变：`require_critical_all_pass=True` ⇒ 任一关键题未过即否决

## P2-3 负例（6 道全 critical）

- 负例题号：company-009、company-010、industry-009、industry-010、macro-009、macro-010（清单哈希 `422ae264af37…`）
- answer_existence=no_answer ⇒ _evidence_required=False、is_evidence_question=False ⇒ EvidencePass 不计入负例
- max_false_positives=0：把无答案题答成有答案即 blocker
- 负例另设 require_critical_all_pass 项：负例答错同样否决

> 三项均**不改评分器、不改金标**：只把取值/清单/口径固化记录，随 P1 落正式时一并进 r27 绑定。
