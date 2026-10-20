# V14 S4 发布候选冻结记录

冻结时间：2026-10-20 10:45:34 +08:00  
状态：`RELEASE_CANDIDATE_FROZEN_NOT_DEPLOYED`

## 冻结结论

S4 已冻结为发布候选，但尚未部署或切换生产。候选来源提交为
`288711846b2af754b891120f0d58a7e2f7feab37`；冻结时集成 HEAD 为
`d06ad598d64ced3052da383a12f3ad5101491a63`。候选提交是当前 HEAD 的祖先，二者的
`plugins/corpus` 整棵 Git 树以及 `corpus_search.py`、`corpus_fetch.py` Git 对象一致。

工作区中存在 4 个其他任务的未提交文件，但语料关键路径干净。这些文件已在机器清单中列为排除项，
不得混入本候选。

## 冻结内容

- S0–S4 的结构契约、PDF 表关系、引文送达、分页完整性和来源级候选排序实现。
- `v14_s2_quote_corpus` 中 12 个已验证活动来源及其精确 build ID。
- S4 零模型结果：51/51，required 36/36，supplementary 15/15，零既有通过项回归。
- S5 的 204 次原始结果与人工例外收口；原始 Judge 失败结论继续保留。
- 关键代码、候选构建、验证报告、全量矩阵与收口记录的 SHA-256。

完整 build 映射和文件哈希见
[机器可读冻结清单](v14-s4-release-candidate-manifest.json)。
冻结清单 SHA-256 为
`5951a6e9328d4ce889f3cbf351c0f3159b5c4f5bce23f71c2332e0a5d8eba823`，另见
[校验文件](v14-s4-release-candidate-manifest.sha256)。

## 不在本次冻结中的内容

- OCR、向量检索和新的 clean/chunk 策略。
- Claims 与 R2 items 结构化提取。
- 当前生产环境实际指针、生产备份及生产回滚快照。
- 生产部署授权。

## 下一门禁

候选冻结已经完成。进入生产切换前仍需读取并冻结当前生产状态，形成精确的切换与回滚 runbook，
同时定义上线监控阈值。该步骤只准备可审查方案，不自行切换生产。
