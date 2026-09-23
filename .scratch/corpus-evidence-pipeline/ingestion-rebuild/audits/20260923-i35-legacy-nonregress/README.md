# I3-5 开发非回归复跑（旧检索 golden / 财务 / 公式 / 客户表 / 正文 / 宏观 / 负控 / 审批契约门）

- 日期：2026-09-23；零模型；原库（5432/postgres）**零写入**；留出原文零读取
- 入口：`i35_replay.py`（确定性单次执行）；机读结果：`i35-results.json`（write-once）
- 依据：任务清单 §3.6 I3-5 行 + `baseline-bindings.json` + `i0a4-candidates-v3` baseline_bindings_v3
  + r27 冻结的 7 类旧基线清单（`audits/20260919-i32-diagnosis/baseline-case-manifest.md`）

## 结果

| 类别 | 冻结目标 | 实测 | 判定 |
|---|---|---|---|
| financial_controlled_recalc_57（开发口径） | 47/47（茅台 32 + 广立微 15） | 47/47（tolerance=0 规范化精确） | PASS |
| formula_7（financial 子节点） | 7/7（tolerance 1e-6，residual 0） | 7/7 | PASS |
| 负控 image_only_source（高盛 p1） | expect_unknown | packet status=unknown | PASS |
| guosen_maotai_holdout（国信茅台 10 格） | 留出 | **held_out_not_run_in_dev**（I3-7 口径） | 按冻结登记 |
| customer_table_12 | 12/12 | 12/12（冻结 run 0a1dbf39 复验） | PASS |
| prose_numbers_3（冻结 2 例） | 2/2 | 2/2（冻结 run 5529429964 复验） | PASS |
| prose_numbers 重抽取（4 次模型调用） | 另立预算授权 | **not_run_pending_budget** | 按冻结登记 |
| macro_legacy_fields | 0/3 保留不伪装 | 机器 2 targets 仍 0 calculate-ready，previous 移出分母 | PRESERVED |
| legacy_retrieval_golden | 19 题（O6 留出排除） | **19/19**（数字 8/8、观点 5/5、对比 3/3、时效 3/3） | PASS |
| 零模型审批/投影契约门 | test_approval_contract.py | 32 passed，exit 0 | PASS |

golden 逐题口径 = 逐题通过（含 require_all），在**旧库 5432/postgres**（89 documents）经当前
`CorpusService` legacy 读链只读重评（`read_chain()=="legacy"` fail-closed 断言通过）；
`O6` 锚点文档（华泰 d571f138）为守卫留出，按 r27 冻结排除。无 skip 机制，失败题零删除。

## 绑定资产哈希核验（全部 match）

`pilot_manifest.json` 691581a5…、`plugins/corpus/golden.py` e983b391…、
`verify_claims_entry.py` e2c52d9e…、`claims-entry-27dfab4c…`（内容寻址文件名即哈希）、
`c1_full84_doc_kind_review_20260912.csv` d69bbb1d…（old_doc_kind_review 权威版本，冻结身份核验，无需重跑）。

## 偏差登记（较冻结契约更收敛，不宣称等同契约执行）

冻结契约入口 `verify_claims_entry.py` 的副作用为"向原库写 corpus_evidence_runs 新行"。
I2-7（R1）后 canonical `extract_claims` 改由同源 `corpus_units` 投影，而 pilot 三份源
（e034bdac / b6beb6ee / 高盛）不在 i0a2 批准开发集（批准 6 份已入库源之外的文件入库需新增
准入决定），冻结契约不可原样执行。本轮按冻结 pilot 断言等价的库级路径
`build_evidence_run` 复验（同 `field_checks`/`calculations` 冻结函数、同 gold、同容差），
**任何数据库零写入**。持久化 round-trip（claims_of/fetch_evidence/derive_claims）由 I2/M5
既有门覆盖（consumers-pg 真库 20 passed 等）。

## 客户表 12 格口径

绑定明确"独立复现脚本需**从冻结 run 重建**"：12 格预期取自
`semantic-repair-runs/report-d46896….json`（corpus-expanded-holdout-1 冻结 manifest），
对冻结 run `0a1dbf39…` 的 12 条 customer facts 按 行/列/值（r27 规范化）/单位 精确匹配。
原文贝特利 PDF 在 `guards/i3.json` forbidden_roots，开发期不读原文（source re-parse
登记 not_run_holdout_protected，留待 I3-7/授权）。

## not_run 汇总（未授权不计作通过）

1. prose_numbers 重抽取（含模型调用，r27：复跑须另立预算授权）。
2. guosen_maotai_holdout 10 格（守卫留出，I3-7 最终重验口径）。
3. customer_table 原文 re-parse（holdout_protected）。
4. 真实答案语义测试（任务行明示：另定输入/人工判据/有限预算，未授权前 not_run）。

## 冻结链收尾（i0c-r4z 台账回填入链）

tasks.md §0/§3.6 状态回填使 i0c 链对 `docs/plan/corpus-ingestion-rebuild-tasks.md` 的
r42 绑定（14006ef8…）失配，按今日 r4x/r4y 先例立修订 **i0c-r4z**（parent=i0c-r4y，
`audits/20260923-r4z-tasksmd-rebind/`）：archive-first 归档改前字节（tasks.md 取自 git HEAD，
sha256==r42 绑定；validator 取自改块前盘面，sha256==r4y 绑定 6031239c…）→ 验证器追加 r4z
语义门块（tasks.md 须携带 I3-5 回填与证据指针）→ 快照 `i0c-r4z.json`（sha c0950bf76d06…）
入 freeze-manifest。**三门验证器 exit 0**（i0c/i1/i3_2）；r29 NOTE 为既有非失败项。

## 卫生与工具

`i35_replay.py` / `gen_i0c_r4z.py` 留 .scratch 原字节（ruff 仅 3 处纯风格提示
SIM108/UP034/I001；.scratch 不在 CI lint 范围，且 replay 脚本已产出 write-once 结果，
就地改写会造成脚本-结果字节脱钩）。本轮触及的仓库字节仅 tasks.md（markdown，pyright 不适用）。

## 纪律核对

零模型（全程未构造 LLM 客户端）；原库只读（仅 load 冻结 run + 检索）；沙箱库
`i2_sandbox_corpus` 未触碰；不 commit / 不 publish / 不重摄入；金标/评分器/阈值零改动；
触及字节 = tasks.md §0/§3.6 回填（经 i0c-r4z 入链重绑）+ 本审计目录 + 冻结链文件
（i0c-r4z.json / freeze-manifest.json / validate_i0c_freeze.py）。
I3-5 不是最终版本放行（I3-6/I3-7 另做）。
