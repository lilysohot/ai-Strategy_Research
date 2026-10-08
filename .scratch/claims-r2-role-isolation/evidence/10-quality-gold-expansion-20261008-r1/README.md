# 非表格真实开发金标扩充 r1

状态：`draft_pending_human_review`。本目录不是正式冻结金标，也未授权运行候选模型。

## 范围

- 来源：已获 dev lane 准入的工业富联 Markdown 投委会报告、光模块 DOCX 纪要。
- 排除：贵州茅台已见候选材料、全部表格单元、所有留出材料。
- Reader：两份选中材料均无 reader issue；正文导出共 109 个单元、14,259 字。
- 审阅候选：Claims 20、material items 40、material relations 20；风险/条件标记 51。
- 当前终态：80 条全部 `pending`，审核人和裁定人均未写入，不能计入正式分母。

## 需要人工确认的文件

[gold-review.md](gold-review.md) 是人类可读审阅稿；机读原稿为
[gold-review-candidates.json](gold-review-candidates.json)。请逐条接受、修改或拒绝。只有全部记录都有
人工终态并完成签名后，才能创建新的追加式 freeze；不得修改
`../10-quality-freeze-20261008-r1/` 中的历史冻结工件。

## 机械复验

```bash
uv run python \
  .scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r1/validate_and_render_review.py \
  --review .scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r1/gold-review-candidates.json \
  --source-export .scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r1/source-prose-units.json \
  --validation-out .scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r1/validation-report.json \
  --markdown-out .scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r1/gold-review.md
```

当前 [validation-report.json](validation-report.json) 为 `valid_draft`、errors 为空，并验证引用精确落在
所列非表格正文单元、关系端点存在、三角色均达到至少 20 条。该机械结果不代替人工语义裁定。
