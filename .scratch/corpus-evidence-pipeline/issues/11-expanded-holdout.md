# 11 扩大留出测试

Status: completed
Execution: evaluation-complete — business acceptance FAILED
Priority: P1

新增三份未参与前期调规则的 PDF：IPO 客户表、华泰非农正文、中银非农同比正文。
冻结清单：[expanded_holdout_manifest.json](../expanded_holdout_manifest.json)。
12 个表格字段、3 个正文目标、6 项真实样本负控，以及 5 个已知语义反例和 1 个正控分别统计。
模型每份宏观页最多 2 个包，单次超时 60 秒；不为提高结果重跑，不改金标适应输出。
新运行走统一 service → 影子保存 → 加载 → audit → 证据回取；不改旧 claims/blocks。
整体验收失败必须保留，不将未抽取视为通过，不估算未经全标注的字段精确率。

结果见 [扩大留出报告](../expanded-holdout-report.md)：表格 0/12、正文数字 2/3、冻结规范字段 0/3，
已知语义反例错误放行 5/5；合法正控通过。实测交付完成不等于数据可用性通过。
评测器负控范围修正后仅重评分已存运行，不重调抽取规则、不重跑模型、不改金标。
