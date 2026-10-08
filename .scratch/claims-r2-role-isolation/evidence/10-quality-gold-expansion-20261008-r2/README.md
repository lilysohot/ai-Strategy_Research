# 非表格真实开发金标修订 r2

用户已于 2026-10-08 以 `xyl` 身份签认本有限目标集；本目录保留签认时审阅稿，正式金标写入
相邻的 `10-quality-gold-freeze-20261008-r2/` 追加式冻结包。r1 与此前质量冻结包保持原样。

## 本次修订

- Claims 20、material_items 48、material_relations 24，共 92 条待审记录。
- R02/R17 的系统推断关系退出必答分母；I18 合并至唯一止损动作 I16，R09 重连。
- I13/I42/I43 保留观察仓的三条可选条件及具体门槛；I17 保留 6.99% 基期、下降超过
  1 个百分点及公司改口的合取条件。原文公司改口子项的顿号未给出明确内部逻辑，保留 unknown。
- C11—C13 与 I45—I47 明示“被转述且受到质疑”；I44 与三条 challenges 边保存讲者立场。
- I37/I38/R19 保留 800G“超预期”的自我修正；I41 补总体持有＋观望观点；I48 和 R26
  补被反驳的税负转嫁观点。R10/R20 改为条件关系。
- R12 改用新增 I49“MEMS主要要用300”的原文明示理由，避免把相邻的客户状况当作论据。
- I05/I11/I21/I26 收紧到单一命题；行为标明 intent；71/80 的 blanket critical 标记已改成
  带具体理由的关键项。风险/条件按角色报告，不冒充独立风险场景计数。

## 审阅文件与范围

- [gold-review.md](gold-review.md)：由 JSON 生成，显示来源名称、引文、完整必要语境、关系端点和裁定提示。
- [gold-review-candidates.json](gold-review-candidates.json)：逐条标注的唯一编辑入口。
- [scoring-contract.json](scoring-contract.json)：24 个非表格正文单元的候选输入范围、目标集合口径和匹配规则。
- 正文权威导出继续引用 r1 的 `source-prose-units.json`，来源字节哈希现场复核；不重写历史。

本包是 **selected-target recall**，并非整篇穷尽标注。所有范围内候选都须逐条裁定，额外正确项
记 correct_extra，不记 FP、不事后加入已冻结召回分母；未裁定项非零时 precision 为 N/A。
不同角色及 raw/validated 分开计数。目标投影 precision 不作完整抽取 precision。

候选接收指定正文，不得接收金标、目标 ID 或审阅规则。数值/区间可确定性归一化；自由文本同义和
归属、条件、关系须具名裁定并保留原始候选，不能从金标反填缺失字段。关系端点先一对一对应，
再判类型及方向。两份内部材料只证明有限开发样本的忠实提取，不保证外部数据真实性。

## 人工签认

逐条填写 `review_status` 为 accepted、edited 或 rejected，并在 `adjudication` 填写审核人、
理由及 decision；edited 附 before/after/reason。裁定范围包括 scoring-contract.json 的规则。
生成器会如实显示终态；被拒绝项不计入可用数量，依赖被拒绝端点的关系必须重裁。
人工签认完成后另建追加式冻结包，本工具从不自动声明金标已冻结或质量门通过。

## 复验

从仓库根目录运行（零模型、零数据库）：

```bash
uv run python .scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/review_pack.py
uv run python .scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/review_pack.py --check
uv run pytest .scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/test_review_pack.py -q
```

机械校验验证精确偏移、引文/来源哈希、枚举、数值/期间归一化、声明的条件约束及关系端点，
另用错误年份、错误数值、遗漏门槛、推断关系、重复动作等反例防退化。它不证明任意语义蕴含，
`valid_review_draft` 仅表示草案内部和原文坐标一致。测试只在内存中修改副本，原始资产不被修改。
