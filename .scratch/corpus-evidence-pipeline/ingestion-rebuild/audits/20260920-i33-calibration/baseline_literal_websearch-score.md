语料检索评分：未通过（top_k=5，门槛 ≥95.0%）

逐类指标（判定按类逐项，不用总体平均掩盖弱类）
  [company] 有答案题 8 | DocRecall@5 宏平均 0.0%（满分 0/8） | QuestionPass 0/8=0.0% | EvidencePass 0/8=0.0%
  [industry] 有答案题 8 | DocRecall@5 宏平均 0.0%（满分 0/8） | QuestionPass 0/8=0.0% | EvidencePass 0/8=0.0%
  [macro] 有答案题 8 | DocRecall@5 宏平均 0.0%（满分 0/8） | QuestionPass 0/8=0.0% | EvidencePass 0/8=0.0%
  [合计] 类间宏平均（各类等权） DocRecall 0.0% | QuestionPass 0.0% | EvidencePass 0.0%
         题数汇总（非类间平均） QuestionPass 0/24、EvidencePass 0/24
  负例误报 0 条、伪造引用 0 条（另计，不混入召回分母）

阻断项（存在即不得宣告通过）
  below_threshold:company:doc_recall=0.0%
  below_threshold:company:question_pass=0.0%
  below_threshold:company:evidence_pass=0.0%
  below_threshold:industry:doc_recall=0.0%
  below_threshold:industry:question_pass=0.0%
  below_threshold:industry:evidence_pass=0.0%
  below_threshold:macro:doc_recall=0.0%
  below_threshold:macro:question_pass=0.0%
  below_threshold:macro:evidence_pass=0.0%
  critical_failed:company-001:DocRecall 未满分
  critical_failed:company-001:QuestionPass 未过
  critical_failed:company-001:EvidencePass 未过
  critical_failed:company-002:DocRecall 未满分
  critical_failed:company-002:QuestionPass 未过
  critical_failed:company-002:EvidencePass 未过
  critical_failed:company-003:DocRecall 未满分
  critical_failed:company-003:QuestionPass 未过
  critical_failed:company-003:EvidencePass 未过
  critical_failed:company-004:DocRecall 未满分
  critical_failed:company-004:QuestionPass 未过
  critical_failed:company-004:EvidencePass 未过
  critical_failed:company-005:DocRecall 未满分
  critical_failed:company-005:QuestionPass 未过
  critical_failed:company-005:EvidencePass 未过
  critical_failed:company-006:DocRecall 未满分
  critical_failed:company-006:QuestionPass 未过
  critical_failed:company-006:EvidencePass 未过
  critical_failed:company-007:DocRecall 未满分
  critical_failed:company-007:QuestionPass 未过
  critical_failed:company-007:EvidencePass 未过
  critical_failed:company-008:DocRecall 未满分
  critical_failed:company-008:QuestionPass 未过
  critical_failed:company-008:EvidencePass 未过
  critical_failed:industry-001:DocRecall 未满分
  critical_failed:industry-001:QuestionPass 未过
  critical_failed:industry-001:EvidencePass 未过
  critical_failed:industry-002:DocRecall 未满分
  critical_failed:industry-002:QuestionPass 未过
  critical_failed:industry-002:EvidencePass 未过
  critical_failed:industry-003:DocRecall 未满分
  critical_failed:industry-003:QuestionPass 未过
  critical_failed:industry-003:EvidencePass 未过
  critical_failed:industry-004:DocRecall 未满分
  critical_failed:industry-004:QuestionPass 未过
  critical_failed:industry-004:EvidencePass 未过
  critical_failed:industry-005:DocRecall 未满分
  critical_failed:industry-005:QuestionPass 未过
  critical_failed:industry-005:EvidencePass 未过
  critical_failed:industry-007:DocRecall 未满分
  critical_failed:industry-007:QuestionPass 未过
  critical_failed:industry-007:EvidencePass 未过
  critical_failed:industry-008:DocRecall 未满分
  critical_failed:industry-008:QuestionPass 未过
  critical_failed:industry-008:EvidencePass 未过
  critical_failed:macro-001:DocRecall 未满分
  critical_failed:macro-001:QuestionPass 未过
  critical_failed:macro-001:EvidencePass 未过
  critical_failed:macro-002:DocRecall 未满分
  critical_failed:macro-002:QuestionPass 未过
  critical_failed:macro-002:EvidencePass 未过
  critical_failed:macro-003:DocRecall 未满分
  critical_failed:macro-003:QuestionPass 未过
  critical_failed:macro-003:EvidencePass 未过
  critical_failed:macro-005:DocRecall 未满分
  critical_failed:macro-005:QuestionPass 未过
  critical_failed:macro-005:EvidencePass 未过
  critical_failed:macro-006:DocRecall 未满分
  critical_failed:macro-006:QuestionPass 未过
  critical_failed:macro-006:EvidencePass 未过
  critical_failed:macro-007:DocRecall 未满分
  critical_failed:macro-007:QuestionPass 未过
  critical_failed:macro-007:EvidencePass 未过
  critical_failed:macro-008:DocRecall 未满分
  critical_failed:macro-008:QuestionPass 未过
  critical_failed:macro-008:EvidencePass 未过

未通过逐题
  [company-001] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e4；evidence_target_missing:a-2
  [company-002] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:e3
  [company-003] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:e3；evidence_target_missing:e4；evidence_target_missing:e5；evidence_target_missing:e6
  [company-004] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e2；evidence_target_missing:a-2；evidence_target_missing:a-3
  [company-005] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e2；evidence_target_missing:e3
  [company-006] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:e3
  [company-007] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1
  [company-008] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/2；question_rule_unsatisfied；evidence_target_missing:a-1；evidence_target_missing:a-2；evidence_target_missing:a-3；evidence_target_missing:a-4；evidence_target_missing:a-5
  [industry-001] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:e3；evidence_target_missing:a-4；evidence_target_missing:a-5
  [industry-002] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:a-3；evidence_target_missing:a-4
  [industry-003] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:a-3
  [industry-004] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:a-1；evidence_target_missing:a-2
  [industry-005] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e2
  [industry-006] answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:a-1；evidence_target_missing:a-2；evidence_target_missing:a-3
  [industry-007] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:e3
  [industry-008] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/2；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:a-2；evidence_target_missing:a-3；evidence_target_missing:a-4；evidence_target_missing:a-5
  [macro-001] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:a-3
  [macro-002] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e3；evidence_target_missing:e4
  [macro-003] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:a-2；evidence_target_missing:a-3；evidence_target_missing:a-4
  [macro-004] answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:a-1；evidence_target_missing:a-2；evidence_target_missing:a-3；evidence_target_missing:a-4；evidence_target_missing:a-5；evidence_target_missing:a-6
  [macro-005] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:a-2
  [macro-006] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:a-3
  [macro-007] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:e3
  [macro-008] 关键题 answer_expected_but_no_match；doc_recall_incomplete:0/1；question_rule_unsatisfied；evidence_target_missing:e1；evidence_target_missing:e2；evidence_target_missing:a-3
