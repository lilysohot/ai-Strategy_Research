语料检索评分：未通过（top_k=5，门槛 ≥95.0%）

逐类指标（判定按类逐项，不用总体平均掩盖弱类）
  [company] 有答案题 8 | DocRecall@5 宏平均 87.5%（满分 7/8） | QuestionPass 7/8=87.5% | EvidencePass 5/8=62.5%
  [industry] 有答案题 8 | DocRecall@5 宏平均 100.0%（满分 8/8） | QuestionPass 8/8=100.0% | EvidencePass 4/8=50.0%
  [macro] 有答案题 8 | DocRecall@5 宏平均 100.0%（满分 8/8） | QuestionPass 8/8=100.0% | EvidencePass 8/8=100.0%
  [合计] 类间宏平均（各类等权） DocRecall 95.8% | QuestionPass 95.8% | EvidencePass 70.8%
         题数汇总（非类间平均） QuestionPass 23/24、EvidencePass 17/24
  负例误报 6 条、伪造引用 6 条（另计，不混入召回分母）

阻断项（存在即不得宣告通过）
  below_threshold:company:doc_recall=87.5%
  below_threshold:company:question_pass=87.5%
  below_threshold:company:evidence_pass=62.5%
  below_threshold:industry:evidence_pass=50.0%
  critical_failed:company-003:DocRecall 未满分
  critical_failed:company-003:QuestionPass 未过
  critical_failed:company-003:EvidencePass 未过
  critical_failed:company-007:EvidencePass 未过
  critical_failed:company-008:EvidencePass 未过
  critical_failed:company-009:负例被断言命中
  critical_failed:company-010:负例被断言命中
  critical_failed:industry-001:EvidencePass 未过
  critical_failed:industry-002:EvidencePass 未过
  critical_failed:industry-003:EvidencePass 未过
  critical_failed:industry-008:EvidencePass 未过
  critical_failed:industry-009:负例被断言命中
  critical_failed:industry-010:负例被断言命中
  critical_failed:macro-009:负例被断言命中
  critical_failed:macro-010:负例被断言命中
  false_positives:6>0
  fabricated_citations:6>0

未通过逐题
  [company-003] 关键题 doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:e3；evidence_target_missing:e4；evidence_target_missing:e5；evidence_target_missing:e6
  [company-007] 关键题 evidence_target_missing:e1
  [company-008] 关键题 evidence_target_missing:a-1；evidence_target_missing:a-2
  [company-009] 关键题 no_answer_false_positive；fabricated_citation:60
  [company-010] 关键题 no_answer_false_positive；fabricated_citation:59
  [industry-001] 关键题 evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:e3
  [industry-002] 关键题 evidence_target_missing:e1；evidence_target_missing:e2
  [industry-003] 关键题 evidence_target_missing:e1；evidence_target_missing:e2
  [industry-008] 关键题 evidence_target_missing:a-2；evidence_target_missing:a-3；evidence_target_missing:a-5
  [industry-009] 关键题 no_answer_false_positive；fabricated_citation:55
  [industry-010] 关键题 no_answer_false_positive；fabricated_citation:55
  [macro-009] 关键题 no_answer_false_positive；fabricated_citation:55
  [macro-010] 关键题 no_answer_false_positive；fabricated_citation:56
