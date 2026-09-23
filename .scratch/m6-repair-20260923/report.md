# M6 三项 P1 整改与真实产品重验

用户授权：根据上轮审核方案执行修复。修复范围预先记录于 [spec.md](spec.md)。

**结论：三项实现缺陷已修复并通过对应回归；正式产品验收仍未通过，不能重新宣告 M6 完整达标。**
本轮以 `authority-context-2`、`i0c-r5d` 冻结新实现和实测失败证据。历史 r5c 签认、旧评分
报告、旧最终 manifest 和全部既有快照保留原字节。新修订没有代替用户作业务放行签认。

## 已实施修复

1. **S1 补充单元完整性**：标题、续句和来源注释进入权威正文前，统一由 `verified_unit`
   复算 SHA-256。坏哈希直接返回完整性错误，不退回到缺少上下文的正文，也不冒充无命中。
   三种反例在修复前均失败，修复后均通过；隔离 PG 另验证正式工具和 batch 路径都拒绝坏哈希。
2. **F1 正式取证闭合**：`fetch_verbatim` 和 `fetch_bands` 共用授权/主单元校验、上下文聚合及
   text/spans 装配；每次读取的权限、主单元和补充单元处在同一 REPEATABLE READ 只读事务内。
   返回 `authority_rev=authority-context-2` 与 `context_unit_ids`，明确补充单元来源；
   `source_ranges` 仍解释原 chunk 投影，不伪造补证区间。未知句柄、跨 build、撤销和坏哈希拒绝门保留。
   先前失败的 company-007/e1、company-008/a-1、industry-008/a-3、industry-008/a-5
   已由实际注册 `corpus_fetch` 全部取回。见 [4 目标回环](target-roundtrip.json)。
3. **F2 验收路径**：新增 `tools/corpus_product_observations.py`。采集器只接收 query ID/text，
   对正负例执行同一路径，调用实际注册 search/fetch，限制为公开工具的 1..20；记录真实响应。
   只有成功搜索的空 hits 记 NO_MATCH；工具失败或身份错配记 FAILED。没有 gold 决定的分支，
   不补入工具未返回的块或文本，不虚构行列标签。评分在收集完成后才读取预期并映射来源身份。
   历史 `i37_score.py` 和 `m6_rescore.py` 作为冻结实验保留，不再用其结果声明当前产品通过。

## 真实产品结果

使用未修改的冻结 30 题、评分器、top_k=5 与逐类 95% 门槛；工具 limit 是 chunk 数，不能与文档
top_k 混用。主验收是产品默认配置。显式 OR 只作为事前声明的统一诊断策略，不声称产品默认会改写。

| 配置 | 实际执行 | QueryPass | EvidencePass | 负例误报 | 工具失败 |
| --- | --- | --- | --- | --- | --- |
| 原题干，limit=10，abstain=off（主验收） | 30/30 | 0/24 | 0/24 | 0/6 | 0 |
| 所有题统一词元 OR，limit=20，abstain=off（诊断） | 30/30 | 22/24 | 13/24 | 6/6 | 0 |
| 原题干，limit=10，abstain=on（既有限制复验） | 30/30 | 0/24 | 0/24 | 0/6 | 0 |

OR 诊断的三类 EP：company 3/8、industry 4/8、macro 6/8。评分器对负例返回的引用另记
“伪造引用”6 条；这是冻结评分器对负例证据输出的判定，**不等于本轮观察到模型编造回答**。
本轮模型调用为 0。默认全部空命中也不能被零误报掩盖。

见 [汇总](product-evaluation-summary.json)、[默认报告](product-default.txt)、
[默认逐调用轨迹](product-default-trace.json)、[OR 报告](product-explicit-or-diagnostic.txt)、
[OR 逐调用轨迹](product-explicit-or-diagnostic-trace.json)、
[abstain 轨迹](product-known-abstain-limit-trace.json)。评测入口
[run_product_eval.py](run_product_eval.py) 在默认业务门失败时以非零退出。

这关闭的是“验收采集失真”缺陷，未把检索能力不足变成通过。剩余工作应单独定义统一的查询/拒答策略、
chunk 预算与文档覆盖、原生表格证据接口，再以同一真实路径重验；不能靠 gold 分支、提高到 limit=2000、
猜测表格标签或只跑正例达标。本轮没有扩大到检索策略设计、阈值修改或留出调参。

## 回归验证

| 检查 | 结果 |
| --- | --- |
| 全仓 tests + apodex/tests | **2912 passed / 2 failed / 49 skipped** |
| 新增采集器单测 | 13 passed（包含于全仓） |
| 补充单元完整性 + selection | 41 passed（包含于全仓） |
| M4 plain / i1 | 各 320 passed / 7 skipped |
| dev / search-live / fullchain | 9 / 11 / 12 passed |
| M5 hermetic / D2D6 | 76 / 73 passed；hermetic 新增 2 条真实 PG 回归 |
| 沙箱前后重建 | 两次 8/8 published+active，build ID 确定性复现，临时 D2D6 库已删除 |
| Ruff（CI 范围含 server） | 全通过 |
| Pyright | 0 errors / 0 warnings |
| import_smoke stage 1 / stage 2 | 365/365、414/414 |
| check_symbols | 464 文件，0 missing-symbol |

组间有重叠，不累计通过数。无 DB 全仓中的相关 skip 由隔离 PG lanes 补测，其余 skip 不宣称通过。
全仓两项失败与修复前一致，未改动相关实现或测试：

- `test_market_hit_rate_is_100_percent`：2026-09-09 固定 as_of 已超过新鲜度阈值。
- `test_react_profile_binds_the_finance_tools`：旧测试仍从已转为 workflow 分派的 profile factory
  取工具；真实 TUI workflow 中的金融工具仍在。

日志：[全仓](full-pytest.log)、[PG 电池](i37-tests-results.json)、[静态检查](ruff.log)、
[类型检查](pyright.log)、[坏哈希修复前反例](red-integrity.log)。

## 冻结与范围

新修订只绑定本轮改动、归档、测试证据和当前状态，不改旧快照。旧验证器中固定断言历史
read_pg/service 字节的三处检查改读已校验哈希的 pre-repair 归档；新实现由 r5d 当前绑定及
新回归验证，不删除旧检查，不把历史签名移用给新代码。

三个冻结验证器均 exit 0，运行结果存于 `freeze-i0c.log`、`freeze-i1.log`、`freeze-i32.log`。
内存故障注入的三项负控（当前代码篡改、历史归档篡改、伪造业务通过）全部以 exit 1 拒绝，
未修改任何被测磁盘文件，见 `freeze-negative-controls.json`。
新 [repair-manifest.json](repair-manifest.json) 记录代码哈希、
不变资产、实际结果以及 `business_accepted=false`。冻结验证通过仅代表版本和证据一致。

写库限于 127.0.0.1:543 测试沙箱与临时测试库，测试后恢复；生产 5432、模型 preflight、
模型答案语义测试、留出材料、I4 迁移/清理均未执行，不包含在通过数中。
用户原有 `.codebuddy/memory/MEMORY.md` 修改保留；未提交 git。
