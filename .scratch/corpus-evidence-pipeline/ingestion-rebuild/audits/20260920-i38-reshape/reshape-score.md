语料检索评分：未通过（top_k=5，门槛 ≥95.0%）

逐类指标（判定按类逐项，不用总体平均掩盖弱类）
  [company] 有答案题 8 | DocRecall@5 宏平均 100.0%（满分 8/8） | QuestionPass 8/8=100.0% | EvidencePass 6/8=75.0%
  [industry] 有答案题 8 | DocRecall@5 宏平均 100.0%（满分 8/8） | QuestionPass 8/8=100.0% | EvidencePass 6/8=75.0%
  [macro] 有答案题 8 | DocRecall@5 宏平均 100.0%（满分 8/8） | QuestionPass 8/8=100.0% | EvidencePass 8/8=100.0%
  [合计] 类间宏平均（各类等权） DocRecall 100.0% | QuestionPass 100.0% | EvidencePass 83.3%
         题数汇总（非类间平均） QuestionPass 24/24、EvidencePass 20/24
  负例误报 0 条、伪造引用 0 条（另计，不混入召回分母）

阻断项（存在即不得宣告通过）
  below_threshold:company:evidence_pass=75.0%
  below_threshold:industry:evidence_pass=75.0%
  critical_failed:company-007:EvidencePass 未过
  critical_failed:company-008:EvidencePass 未过
  critical_failed:industry-002:EvidencePass 未过
  critical_failed:industry-003:EvidencePass 未过

未通过逐题
  [company-007] 关键题 evidence_target_missing:e1
  [company-008] 关键题 evidence_target_missing:a-1
  [industry-002] 关键题 evidence_target_missing:e2
  [industry-003] 关键题 evidence_target_missing:e2
