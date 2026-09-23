# M6 独立复核报告（I3-6 冻结版本 × I3-7 最终重验）

| 项 | 内容 |
|---|---|
| 复核对象 | I3-6 最终冻结版本（i0c 链头 **i0c-r4z**，绑定修订 i0c-r5a → **i0c-r5b**）及 I3-7 最终重验全部产物 |
| 复核日期 | 2026-09-23 |
| 复核方法 | 独立探针（**不 import i37_score.py / i37_rebuild.py**，全新 harness 只复用冻结库代码）+ 哈希重算 + DB 直读 + git 历史取证 |
| 纪律 | 零模型；沙箱 127.0.0.1:543/i2_sandbox_corpus **只读**；生产库 5432 零触碰；留出零读取（守卫 forbidden_roots）；产物 write-once；git 零提交 |
| 结论 | **复核通过**：I3-7 全部结果与冻结版本一致，独立重证无任何反例。M6 放行待 **U 具名签认**（本报告不代签、不自行放行） |

## 0. 独立性声明

- 本轮探针均为新写脚本（`m6_hashes.py` / `m6_rescore.py` / `m6_dbcheck.py`，同目录），未
  import 被复核的 I3-7 脚本；仅复用冻结字节库代码（`plugins/corpus/scoring.py` 等）与冻结
  输入（scoring-input-manifest / calibration-plan-v2 / gold），并在导入前 fail-closed 校验
  其哈希与 `i3-final-freeze-manifest.json` 冻结值一致。
- 逐类聚合、别名解析、基线对照、prune 对照、abstain 诊断、authority 探针样本（macro-008，
  与 i37 的 company-001 不同）均为独立实现/自选；对账目标 `i37-score-results.json` 只作
  参照账本逐字段比对。
- 冻结哈希（导入前置校验）：scoring.py `f61573d7…`、calibration-plan-v2 `b82c8d94…`、
  守卫 `3faac9e0…`——全部与冻结清单一致，否则拒绝运行。

## 1. 三门验证器（exit code 重录）

| 验证器 | exit | 记录 |
|---|---|---|
| `freezes/validate_i0c_freeze.py` | 0 | validator-validate_i0c_freeze.py.log（r5b 语义门 + 全链血缘 i0c-r1→…→i0a5(M1) 全过） |
| `freezes/validate_i1_freeze.py` | 0 | validator-validate_i1_freeze.py.log |
| `freezes/validate_i3_2_completion.py` | 0 | validator-validate_i3_2_completion.py.log（i3_2_complete=true） |

## 2. 链绑定与冻结资产哈希（独立重算）

`m6-hashes.json`：**13 项绑定对账 + 62 项冻结资产重算全部一致，零漂移**。

- i0c-r5b 绑定八件（I3-7 重验证据五件 + tasks.md + 验证器 + parent i0c-r5a）逐一 vs 声明哈希：一致；
- r5a 绑定终态核对：i3-final-freeze-manifest.json 现字节 = r5a 绑定 `4152179f…`（r5b 未触碰，符合其 rebind_scope）；tasks.md/验证器已按 r5b 声明演进（`3e2413be…` / `1e1b63ec…`）；
- freeze-manifest.json 中 i0c-r5a / i0c-r5b 条目哈希 vs 实际字节：一致；
- final manifest chain_head：i0c-r4z 文件哈希 `c0950bf7…` 一致；
- **chain_manifest 演进实证**（非漂移）：声明值 `419ad0f5…` 在 git 历史 commit `8ec0cb6`
  精确复得（61 快照 = I3-6 冻结时点字节）；当前 63 快照 = 冻结面**前缀逐字段相等** + 仅追加
  i0c-r5a/i0c-r5b 两条 + 非快照字段零改动——追加式索引纪律成立；
- 冻结时点验证器值 `817b7779…`（final manifest 内）vs 现值 `1e1b63ec…`：属 r5a/r5b 绑定修订
  的预期演进（由 r5b 绑定承接并经门 1 核验），非资产漂移；
- **tasks.md 双态**：工作区 `3e2413be…`（= r5b 绑定）≠ git HEAD `fd254523…`（= r5a 绑定）
  ——**当前盘面未 commit**。若签认轮再改 tasks.md，archive-first 必须取当前盘面字节
  （断言 == r5b binding.chain_rebind_evidence.tasks.md 哈希），不得照抄 gen_i0c_r5a.py 的
  `git show HEAD` 模式。

## 3. 独立重评分探针（30 题三指标逐字段对账）

`m6-rescore.json`：**all_match = true**，与 `i37-score-results.json` 零差异。

- QuestionPass **24/24**、EvidencePass **24/24**；逐类（company/industry/macro 各 8/8）
  QuestionPass/EvidencePass **8/8**、DocRecall **=1**（均值口径与冻结评分器一致）；
- per_question 30 行（question_pass/evidence_pass/doc_recall/failures/critical/negative/domain）
  逐字段对账：**0 差异**；per_class 逐字段对账：**0 差异**；
- 评分层 **FP=0、伪引用=0**；关键题 22 题、零失败；
- b5 盘点基线对照：**零回退**（三类逐指标独立重比）；prune on/off：on **零回退**、
  改善名单 `["company-003"]` 与 i37 完全一致；
- abstain=on（产品形态 raw 题干）：负例 **6/6 拒答**（冻结口径达成）；正例拒检 **24/24 独立复现**
  （pending 项，见 §6）；
- authority 回环（探针自选样本 macro-008）：句柄格式 / locator round-trip（build_id、chunk_id、
  units 非空、文本非空）/ 未知句柄拒绝，全过；
- scoring-input-manifest 现字节 `bbacb85e…` 与链上最新绑定（i0c-r4x）一致（r42 旧值 `ab1730b2…`
  已按 supersession 承接）。

## 4. DB 直读独立核验

`m6-dbcheck.json`：**all_ok = true**。

- 指针态：active publications **8/8**，source_id 与 active_build_id 均唯一；规模清点
  sources/builds/chunks/units 全部非空；
- **i2_% 库清单 = ["i2_sandbox_corpus"]**——独立确认 I3-7 宣称的第三库 `i2_d2d6_corpus` 已 DROP；
- revs 库级重算：8 个活动 build 的 parse/clean/chunk/index rev 按冻结常量 + 冻结组装公式
  （canonical_fingerprint + reader._extractor_rev 三格式分派）现算，**逐 build 全对**；代码
  REV 常量与冻结清单 runtime_configuration 一致；rev 集合与 rebuild-report.json 三向一致；
- 独立 search→fetch 回环 ×3（corpus_units 直取真实单元 → zhcfg 词元 OR 检索 → 命中含该源 →
  fetch_verbatim 逐字非空且 build_id 与活动 build 一致）：**3/3 过**（不含 i37 组装路径）。

## 5. 纪律审计与静态门

- **零模型**：探针运行前装载 `guards/i3-e2e.json`（model.blocked_modules 含 openai/anthropic/
  material_semantics/_r2_*，OPENAI_*/ANTHROPIC 环境投毒）；探针不构造任何模型客户端；
  冻结评分器为纯函数（无 I/O 无模型）；model_calls=0。
- **网络**：守卫 allowlist 仅 `127.0.0.1:543`；三探针 DSN 构造均 fail-closed 断言
  （host=127.0.0.1 / port=543 / db=i2_sandbox_corpus）+ `search_pg._check_target` 双保险；
  **生产库 5432 零触碰**（无任何代码路径指向 5432）。
- **留出零读取**：探针文件读取面 = 冻结清单资产 + gold/校准/manifest 配置 + dev-scope-manifest
  8 份授权来源路径；守卫 forbidden_roots 5 份留出文件**零读取**；`guards/i3-e2e.json` 现字节
  与冻结值一致（读面未被扩权）。
- **只读复核**：全程 SELECT / 检索 / fetch，corpus schema 零写入；`guosen_maotai` 10 格等
  held-out 未读。
- **静态门独立复跑**：`ruff check`（CI 范围）**0 err**；`tools/import_smoke.py --stage 1`
  **exit 0**（365/365）；`uv run pyright` **exit 0**。

## 6. 待 U 裁决项（签认包必读，均不阻塞复核结论）

1. **abstain=on 正例误拒（pending，本轮独立复现为 24/24）**：AND 预检要求单单元同时含全部
   实质词元，真实语料归零；band 检索靠 OR+带聚合仍可命中，故**评分层 24/24 不受影响**；
   负例 6/6 为冻结口径且已达成。S1「正例不误拒」设计宣称未获正例证据——非 I3-7 门。
   处置选项：(a) 接受现状并关闭 S1 宣称（登记为已知限制）；(b) 立整改任务（预检口径改造，
   另走版本冻结 + 重验）；(c) 暂缓，与 I4 一起处置。
2. **prose 重抽取 2 例**：not_run（待预算授权）；真实答案语义测试：not_run（待授权）；
   留出 10 格（含 guosen_maotai）：held_out（守卫保护）——均为既定另立授权型，无冻结必需待定项。
3. **D2/D6 偏差与守卫 Popen 注入**：复核确认为冻结 fail-closed 行为 + 运行纪律（非产品缺陷），
   与 I3-7 登记一致。

## 7. 宣称 vs 产物一致性

`20260923-i37-final-reverify/README.md` 与 `tasks.md` §0/I3-6/I3-7 行全部宣称逐项对账本报告
§1—§5：8/8、index-4-zhcfg-2、24/24、DocRecall=1、关键 22/22、FP=0/伪引用=0、b5 零回退、
prune on 非劣化、负例 6/6、authority 回环、测试电池九门（m4-plain/i1 各 320、dev 9、
search-live 11、fullchain 12、hermetic 74、d2d6 73、恢复确定性、指针严格）、legacy 同口径
（财务 47/47 + 公式 7/7、客户表 12/12、正文 2/2、宏观 0/3 保留、golden 19/19、契约门 32
passed）、静态门 0 err、pending 登记——**一致，无夸大、无隐瞒**；「M6 须独立复核 + U 具名
签认」的口径在 tasks.md/README/快照中三处一致。

## 8. 结论与放行请求

- **复核结论**：I3-7 重验结果与 I3-6 冻结版本（i0c-r4z，经 i0c-r5a/r5b 入链）完全一致；
  独立重证（评分、DB、哈希、回环、纪律）**未发现任何反例**。
- **M6 放行三要件**：① I3-7 通过（已达成）；② 本独立复核（本文，通过）；③ **U 具名签认**
  （待办理）。
- ③ 完成前**不视为 M6 放行**；签认后按 r30 先例把签认记录（reviewer 具名）入链新修订
  i0c-r5c 并回填 tasks.md M6 行（注意 §2 的 archive-first 警告：tasks.md 未 commit，
  归档须取当前盘面字节）。

**签认请求**：请 U 对以下事项具名裁决——

1. 是否认可本独立复核结论与 I3-7 全部结果（M6 放行 / 维持不放行 / 有条件放行）；
2. §6.1 abstain=on 正例误拒的处置选项（a/b/c）；
3. 签认人姓名与日期（将按 r30 先例具名入链 i0c-r5c，不代签）。

## 9. 复核产物清单（本目录，write-once）

| 文件 | 内容 |
|---|---|
| `m6_hashes.py` → `m6-hashes.json` | 链绑定 13 项对账 + 62 资产零漂移 + chain_manifest 演进实证 + tasks.md 双态 |
| `m6_rescore.py` → `m6-rescore.json` | 独立重评分 30 题 + 逐字段对账 + abstain 复证 + authority 回环 |
| `m6_dbcheck.py` → `m6-dbcheck.json` | DB 直读指针态/revs 重算/三回环/d2d6 已 DROP |
| `validator-validate_i0c_freeze.py.log` 等 ×3 | 三门验证器重跑日志（exit 0） |
| `import-smoke-stage1.log` | 静态门 import_smoke 重跑日志（exit 0） |
| `review.md` | 本报告 |
