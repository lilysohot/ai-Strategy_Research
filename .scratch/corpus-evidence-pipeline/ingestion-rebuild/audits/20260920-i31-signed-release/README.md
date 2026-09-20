# I3-1 签署采纳与真实发布（i0c-r37）

四份具名签署内容已收到，审核人为 xyl。此次没有要求再次签名，也没有改写用户原文件。
原填写字节另保存在 `submitted/`；可执行凭证是 `review-*.json`，规范化过程与引用依据
记于 [precheck.json](precheck.json)。

## 结果

| 来源 | 人签缺口 | 正式门 | 结果 |
|---|---:|---|---|
| 华创·贵州茅台 6f14cc14 | 1 | 通过 | 已登记、已发布 |
| 长江·化工十问十答 174b6462 | 10 | 通过 | 已登记、已发布 |
| 光大·美国非农 793b3967 | 1 | 通过 | 已登记、已发布 |
| 国信·光力科技 dddc7cd0 | 1 | 页级坐标拒绝 | 人签已收、未登记放行、未发布 |

原批准 8 份现发布 **7/8**：company **2/3**、industry **3/3**、macro **2/2**，
**per_class_min_2=true**。格式覆盖 PDF **5/6**、DOCX **1/1**、MD **1/1**，格式门 true。
公司和行业计数各含原批准 dev lane 材料，材料类型没有改成生产研报。
8 份既有 build 的解析/切块阶段均成功。真实六组 search/fetch/verify 全过、每组有命中，
被拒句柄 0、audit_corpus_chain 冲突 0。完整证据见 [release-e2e.json](release-e2e.json)。

12 处人工确认缺口的 lifecycle 变为 acknowledged；默认 disposition 仍为 blocking，
原 quality_report、units/chunks 和 claimed 范围未改。13 处原阻断缺口都在台账里，
其中光力 p7 的 1 处仍 blocking。coverage 如实为 scoped，availability 为 unknown。

I3-1 的数量、格式和本轮真实 E2E 门通过；不代表全部来源无阻断，更不代表 M6 或 I4 放行。

## 签署内容的机器转写

1. 原 reviewer、逐缺口 rationale、scope_rationale 保留；原自然语言 attestation 全文
   收入规范化凭证的 scope_rationale，原始文件原文另存。
2. 人签明确引用 `evidence-targets-approved.json` 的 approved_required/supplementary；
   机器字段完整展开该来源在这两组的所有页码，引用携带冻结文件 SHA-256。
   没有因缺口位置删目标。茅台实际展开为 p1/p3/p7，保留原签文字中未逐一列举的 p7。
3. `2026-09-20 12:00:00` 按本会话 Asia/Shanghai 转为
   `2026-09-20T12:00:00+08:00`，没有改变用户填写的年月日或钟点。
4. 已签署的自然语言不相交确认转写为既有机器枚举
   `human_verified_complete_scope_and_nonintersection`，由正式门独立判定是否可证。
   光力的同页区域声明没有被当作页级不相交放行。
5. 逐份核对原始来源 SHA-256、当前 build 全字段指纹和当前准入决定，均符合签署绑定。

## 光力 p7：后续是程序坐标能力

已在原 i3-e2e 守卫下读取哈希相符的原 PDF p7，图像框为
`[56.7600, 334.8000, 532.8000, 726.2400]`；持股比例标题/正文文字块在其上方，
相关完整正文块 y 范围约 `114.6735–179.7602`。与人签“证据文字位于图像上方”一致；
人签估计 y=85–155 未覆盖整个正文块，因此保留实测完整框，不把 155 当成硬边界。

现有 gap key 为 `issue:image_region_unreadable:page:7`，验证器只处理页/字符级坐标。
签署已完成。要发布此来源，需要把可复验的区域框证明正式接入发布门并做反例测试及新修订，
不能删掉必需证据 p7，也不能把这一份记为已发布。该限制不再阻断当前每类≥2计数。

## 历史与冻结

用户是在 r36 的 `unsigned-*.json` 原路径填写的。为保留用户原路径签署：r37 对这四条
路径绑定当前具名内容；r36 的空模板在 `r36-template-recovery/` 单独保存并逐字节匹配
r36 原哈希。恢复方法有明确记录，**不冒充“最新用户修改前已归档”**。

任务台账、总计划、验证器、索引在本轮编辑前经 archive_first 归档，记录在 archives.json。
r36 JSON 及其父链、守卫、gold、准入政策、生产实现与测试源码均未改变。
`release.py --publish` 使用既有 i3-e2e 守卫和隔离 PG，未触及生产数据库或调用模型。
