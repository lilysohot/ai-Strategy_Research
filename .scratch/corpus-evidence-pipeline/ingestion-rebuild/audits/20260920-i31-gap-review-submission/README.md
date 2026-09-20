# 四份人工判级填写件：预检与下一步

当前四份文件都有 reviewer=xyl、reviewed_at=2026-09-20，但其余人工核验字段为空。
正式 GapReview 解析四份均拒绝，尚未登记凭证或发布任何 build。

用户填写的原始字节保存在 [submitted-originals](submitted-originals/)，逐份哈希记录在
[submission-precheck.json](submission-precheck.json)。之前 unsigned-*.json 是 r36 冻结空模板，
本次先完整复制用户填写件，再恢复与 r36 哈希逐字节相符的原模板；历史修订没有重写。

## 请填写以下新稿

已从 source-gold-frozen.jsonl 的 must_preserve 条目和 evidence-targets-approved.json 的
approved_required 目标合并页码，并填入来源文件与 SHA-256 引用。页码未根据缺口位置筛选。
这部分是已冻结证据的客观整理，仍须审核人确认它覆盖该 build 的完整目标范围。

| 补全稿 | 所需证据页码（待确认完整性） | 与缺口页码重叠 |
|---|---|---|
| [review-6f14cc14.json](review-6f14cc14.json) | 1、3、7 | 无 |
| [review-174b6462.json](review-174b6462.json) | 10 | 无 |
| [review-793b3967.json](review-793b3967.json) | 1、3 | 无 |
| [review-dddc7cd0.json](review-dddc7cd0.json) | 1–11、20 | 第 7 页 |

每份新稿需要补充：

1. `reviewed_at`：实际审核时间与时区，格式为 `YYYY-MM-DDTHH:MM:SS+08:00`。
   当前只有日期，校验器不接受；不要为满足格式编造审核时间。
2. `scope_rationale`：确认上述目标证据集合完整，并说明采用这些范围的依据。
3. `gaps` 下每一项的文字：该区域实际是什么内容，为什么不影响本 build 所需证据。
   这 13 条实际核验理由不能由代理凭空代填。
4. 完成核验且不相交条件成立后，将 `attestation` 填为
   `human_verified_complete_scope_and_nonintersection`。

光力 p7 当前不能填写“不相交已成立”的声明：缺口和必需证据同为 page:7，现有验证器
会拒绝。若人工看到它们在同页不同区域，需要另行提供可追溯的精确坐标并完成坐标机制
修订，或修复读取缺口；不能删除金标 p7 或仅凭签名放行。

其它三份涉及 12 处缺口，可在补齐实际核验记录后先做登记及发布预检。页码不重叠只是
其中一个前提，仍须校验当前 build 指纹、证据保留和其余发布门。

## 补齐后的执行顺序

在已有 i3-e2e 守卫下核对当前 build → 登记具名凭证 → check → publish →
对原批准的 8 份材料复跑逐类计数、格式门、coverage 与取证审计 → 归档并建立下一修订。
以实跑结果判断 I3-1 是否收口；本预检没有宣称任何真实缺口已获放行。

也可以在会话中提供实际核验时间、范围完整性说明和逐处理由，再由代理整理写入新稿。
