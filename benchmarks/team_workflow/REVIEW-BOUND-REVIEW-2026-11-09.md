# 绑定证据核验回归用例审核稿

状态：**pending_review**。本稿尚未登记到 `cases.json`，不计入正式 benchmark
数量或通过率。当前正式集仍为 83 个案例。上一轮 P59/P60 仍待审核；本稿拟用
P61–P63，避免覆盖既有编号。原问题、资料、rubric、提示词 A 与预算保持不变。

| 拟编号 | 输入与操作 | 必须满足 | 反向控制 | 回归选择器 |
|---|---|---|---|---|
| P61 | 给已注册核验检查附加自由研究任务和研究型角色提示，通过真实 AgentBus 派发 | 实际模型调用只收到当前绑定检查、原始问题和证据索引；自由指令留在审计元数据；核验无开放 corpus/web 获取工具，提供快照读取工具 | 同一会话前后研究任务保留全文获取能力；检查标准不得因工具收窄而放宽 | `test_bound_review_cannot_inherit_unbound_research_instructions`、`test_research_session_keeps_full_acquisition_capability` |
| P62 | 绑定多个长原文记录，派工后改变来源元数据；按页或精确 locator 补读快照 | 重建绑定时的原文，无实时后端读取，每页序列化结果 ≤6000 字符；绑定后修改不污染快照；错误绑定、来源、位置被拒绝；定位某条不强迫遍历其他条目 | 绑定与快照复制之间发生版本改变须拒绝；补读明确标识历史观察，不能称为新鲜性检查或全文覆盖证明 | `test_bound_snapshot_pages_reconstruct_original_without_any_live_read`、`test_source_changes_between_binding_and_snapshot_are_rejected`、`test_targeted_snapshot_read_does_not_force_enumeration_and_rejects_unknown_sources` |
| P63 | 核验缺少必要原文，随后研究取得缺失原文并重新绑定；同时传递全文页回执 | 先 unchecked 并记录缺口，再允许新证据版本继续核验；回执保留来源覆盖 unknown，不将报告文字视为全文证明 | 原标准不改变；只换回执别名不得重置复核预算，真实覆盖变化可继续；不把工具读到等同模型已读到或原 PDF 全量 | `test_missing_evidence_can_be_acquired_and_rebound_without_waiving_check`、`test_document_read_receipt_survives_source_handoff_without_claiming_pdf_coverage`、`test_new_coverage_can_unlock_recheck_but_new_receipt_alias_cannot` |

选择器均位于 `tests/test_team_bound_review.py`。P63 最后一项参数化为两个执行
样本；P62 另包含 `test_snapshot_keeps_web_extraction_and_partial_coverage_limits`，
要求网页模型提取的 `content_kind`、部分获取状态、覆盖限制与说明原样保留，不能
在快照读取中被提升为完整原文。合计 10 项实现回归已执行，回归通过不表示草案
已经获准登记。

真实模型仍用既有 F18/F19/F20/F24：分别检验足够证据停止、局部补读、明确全文
需求及全文中途撤销。只约束核验的工具和证据版本，不证明模型已会判断任务充分性。
本轮凭据恢复后模型为 `glm-5.3-flash`；上一轮为 `deepseek-v4-1-flash-261017`，
跨轮差异混合了模型变化与代码变化，不能作为修复的独立因果效果。
