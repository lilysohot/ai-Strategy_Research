# 非表格真实开发金标正式冻结 r2

本目录是 `10-quality-gold-expansion-20261008-r2/` 经用户签认后的追加式正式冻结包。

- 签认人/争议裁定人：`xyl`（此前对话指定为许永立）
- 签认日期：2026-10-08
- 金标：Claims 20、material_items 48、material_relations 24，共 92 条
- 范围：两份已批准开发材料的 24 个非表格正文单元；selected-target recall，不宣称整篇穷尽
- 已知歧义：NT-I17 的公司改口子项内部 AND/OR 不明，按签认稿保留 unknown
- 状态：金标与评分口径已冻结；尚未产生本包候选评分，质量门仍未通过

`frozen-gold.json` 是正式金标；`freeze-state.json` 记录状态和授权边界；`freeze-manifest.json`
绑定签认稿、评分口径、正文导出、来源字节及冻结输出。冻结后发现错误必须新建后继版本，禁止覆盖。

复验：

```bash
uv run python \
  .scratch/claims-r2-role-isolation/evidence/10-quality-gold-freeze-20261008-r2/freeze_signed_gold.py \
  --verify
```

该命令只读，不调用模型、不访问数据库或留出。
