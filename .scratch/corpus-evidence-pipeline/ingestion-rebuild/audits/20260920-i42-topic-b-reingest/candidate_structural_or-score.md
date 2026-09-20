语料检索评分：未通过（top_k=5，门槛 ≥95.0%）

逐类指标（判定按类逐项，不用总体平均掩盖弱类）
  [company] 有答案题 8 | DocRecall@5 宏平均 81.2%（满分 6/8） | QuestionPass 6/8=75.0% | EvidencePass 3/8=37.5%
  [industry] 有答案题 8 | DocRecall@5 宏平均 100.0%（满分 8/8） | QuestionPass 8/8=100.0% | EvidencePass 3/8=37.5%
  [macro] 有答案题 8 | DocRecall@5 宏平均 100.0%（满分 8/8） | QuestionPass 8/8=100.0% | EvidencePass 6/8=75.0%
  [合计] 类间宏平均（各类等权） DocRecall 93.8% | QuestionPass 91.7% | EvidencePass 50.0%
         题数汇总（非类间平均） QuestionPass 22/24、EvidencePass 12/24
  负例误报 6 条、伪造引用 6 条（另计，不混入召回分母）

阻断项（存在即不得宣告通过）
  below_threshold:company:doc_recall=81.2%
  below_threshold:company:question_pass=75.0%
  below_threshold:company:evidence_pass=37.5%
  below_threshold:industry:evidence_pass=37.5%
  below_threshold:macro:evidence_pass=75.0%
  critical_failed:company-003:DocRecall 未满分
  critical_failed:company-003:QuestionPass 未过
  critical_failed:company-003:EvidencePass 未过
  critical_failed:company-004:EvidencePass 未过
  critical_failed:company-005:EvidencePass 未过
  critical_failed:company-007:EvidencePass 未过
  critical_failed:company-008:DocRecall 未满分
  critical_failed:company-008:QuestionPass 未过
  critical_failed:company-008:EvidencePass 未过
  critical_failed:company-009:负例被断言命中
  critical_failed:company-010:负例被断言命中
  critical_failed:industry-001:EvidencePass 未过
  critical_failed:industry-002:EvidencePass 未过
  critical_failed:industry-003:EvidencePass 未过
  critical_failed:industry-004:EvidencePass 未过
  critical_failed:industry-008:EvidencePass 未过
  critical_failed:industry-009:负例被断言命中
  critical_failed:industry-010:负例被断言命中
  critical_failed:macro-002:EvidencePass 未过
  critical_failed:macro-003:EvidencePass 未过
  critical_failed:macro-009:负例被断言命中
  critical_failed:macro-010:负例被断言命中
  false_positives:6>0
  fabricated_citations:6>0

未通过逐题
  [company-003] 关键题 doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:e3；evidence_target_missing:e4；evidence_target_missing:e5；evidence_target_missing:e6
  [company-004] 关键题 evidence_target_missing:e2；evidence_target_missing:a-2；evidence_target_missing:a-3
  [company-005] 关键题 evidence_target_missing:e2；evidence_target_missing:e3
  [company-007] 关键题 evidence_target_missing:e1
  [company-008] 关键题 doc_recall_incomplete:1/2；question_rule_unsatisfied；evidence_target_missing:a-1；evidence_target_missing:a-2；evidence_target_missing:a-3；evidence_target_missing:a-4；evidence_target_missing:a-5
  [company-009] 关键题 no_answer_false_positive；fabricated_citation:62
  [company-010] 关键题 no_answer_false_positive；fabricated_citation:59
  [industry-001] 关键题 evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:e3；evidence_target_missing:a-4；evidence_target_missing:a-5
  [industry-002] 关键题 evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:a-3；evidence_target_missing:a-4
  [industry-003] 关键题 evidence_target_missing:e1；evidence_target_missing:e2
  [industry-004] 关键题 evidence_target_missing:a-1；evidence_target_missing:a-2
  [industry-008] 关键题 evidence_target_missing:a-2；evidence_target_missing:a-3；evidence_target_missing:a-5
  [industry-009] 关键题 no_answer_false_positive；fabricated_citation:55
  [industry-010] 关键题 no_answer_false_positive；fabricated_citation:55
  [macro-002] 关键题 evidence_target_missing:e4
  [macro-003] 关键题 evidence_target_missing:a-2；evidence_target_missing:a-4
  [macro-009] 关键题 no_answer_false_positive；fabricated_citation:55
  [macro-010] 关键题 no_answer_false_positive；fabricated_citation:56
