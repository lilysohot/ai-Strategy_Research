# Claim 正式入口收敛验收

日期：2026-09-12
结论：本次 service / CLI 接线任务通过；不代表全库、全文、宏观计算或 Web 接入已完成。

## 改动

- CorpusService.extract_claims 默认接受明确源文件，调用已有 EvidenceRun 链路并保存，不再默认写 v1。
- claims_of / claim_observation_projection 读取指定 run_id，返回来源与解析版本、处理范围、质量、用途、分页和覆盖状态。
- cite、compare、calculate 分别使用现有用途门禁；audit 显式查看非合格记录。
- 旧校验版本可回溯，但不能自动继承新版计算许可；后一次失败也不借用前次成功记录。
- derive_claims 从相同数据库证据版本复算；CLI 增加 claim-runs、claim-evidence、derive-claims。
- v1 的 extract_legacy_claims / legacy_claims_of 与 v2 显式入口保留兼容，旧错峰脚本须 --legacy。
- 旧模块中共享的模型调用与规范化仍被复用；没有文件拼接、重复实现新规则或删除历史表。

## 小范围真实数据验收

机器记录：[完整结果](claims-entry-27dfab4cb9a97cf8ad72d269039d822afc3f39631601d76c0bed1b87645c0cb3.json)。
可复跑脚本：[verify_claims_entry.py](verify_claims_entry.py)。

| 样本 | 冻结字段通过 | 正式查询及取证 | 公式复算 |
|---|---:|---:|---:|
| 茅台财务预测页 | 32 | 368 条事实 | 7 |
| 广立微财务表 | 15 | 50 条事实 | — |
| 国信茅台留出页 | 10 | 50 条事实 | — |
| 合计 | 57 | 468 条事实 | 7 |

468 条证明正式接口能回取原文，不是 468 条全部字段均经人工金标验收。
三份源文件均只选定页面，正文预算为 0，所以 selected_scope_complete=false；不得称全文完成。

宏观复用了正文修复最终版本 552942996489beb4f1f44b66d2ab944a48b1d5b9ff2e81ef59b6c61c71c65fbf，
正式查询读回 NFP actual 16.2 万人、consensus 5.6 万人两个冻结目标。
两者仍仅可引用；比较投影返回 0，不把 quality=ok 误当成可计算。
该部分是已保存模型结果的读取回归，不是新的独立抽取质量试验。

旧库前后计数相同：documents=87，blocks=1096，claims=1318，claims_v2=0。
新写入只涉及 corpus_evidence_runs；源 PDF 与旧表未迁移或删除。

## 自动验证

- tests/test_corpus*.py：197 项通过，包含 29 项新接口用例和 PostgreSQL 隔离 schema 保存/恢复回归。
- 修改模块 Ruff 通过；service、evidence_pipeline、pilot、offpeak 的 Pyright 0 错误。
- import_smoke：framework 330/330、eval 379/379；check_symbols：429 文件、0 缺失符号。
- preflight：通过；额外 1 次最小模型连通性调用（1.67 秒），不是正文抽取。
- JUDGE_API_KEY / JUDGE_BASE_URL 未配置有警告；本次使用冻结值和确定性测试，没有模型裁判。
- git diff --check 无空白错误。
- 尝试 tests -k corpus 时仍会收集其他测试：Web 可选依赖 sqlalchemy/argon2 缺失，产生 19 个收集错误。
  随后按 test_corpus*.py 明确选取专项并全部通过；全仓测试未验收，不为此扩展安装依赖。

## 后续边界

1. 所有活跃调用方切换和回滚验证完成后，再移除旧兼容抽取实现；历史数据归档另行确认。
2. 暂不自动选择“最新/最佳”运行，防止部分范围、失败重跑和不同版本混用。
3. 分页目前在单个已加载 EvidenceRun 内完成，尚未建设大规模事实查询索引。
4. 原净利率口径差异、宏观计算契约、OCR 和全库覆盖任务未被此次入口收敛解决。

使用方式见 [接口迁移指南](../../docs/corpus-claims-interface.md)。
