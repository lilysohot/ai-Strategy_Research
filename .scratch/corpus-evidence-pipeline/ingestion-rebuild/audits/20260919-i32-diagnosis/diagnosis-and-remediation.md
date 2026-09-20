# I3-2 当前卡点与整改方案

核查日期：2026-09-19。基线：当前工作区、i0c-r26、今天已生成但未冻结的 P1—P4。
本次只新增诊断材料，未修改正式金标、评分器、审批件或冻结链；无模型调用、无 PG 连接，未读取留出原文。

## 结论

I3-2 当前处于“证据审批完成、评分输入草稿可用、实验起点尚未闭环”的阶段。
主要卡点是批准产物没有接成正式评分入口、旧基线未完成可追溯的用例映射、初始版本未形成可执行冻结包。
继续泛化修改候选映射规则，不能解决这三个问题。

任务边界以 `docs/plan/corpus-ingestion-rebuild-tasks.md:321` 为准：在候选业务结果可见前冻结预期、
旧基线、阈值/关键题/负例、评分器和试验初始版本。I3-1 才运行开发 E2E，I3-5 才验证非回归，
I3-7 才重验最终版本并支持 M6。I3-2 不需要先取得这些后续业务通过结果。

## 已核实的进度

| 项目 | 现状 | 判断 |
|---|---|---|
| source gold / 证据审批 | r26；批准门重新执行 ready=true，0 blocker，20 warning | 已有可用审批链 |
| 评分器 | 原有评分器、审批契约与 I3-0 复核探针共 88 passed | 无证据表明需重写评分器 |
| 冻结链 | `validate_i0c_freeze.py` exit 0，包含 r26 校验 | 历史链完整不等于 I3-2 全部完成 |
| 正式 query gold | 30 题均未写 targets；其中 24 道有答案题缺必需 targets | 正式评分输入仍阻断 |
| P1 草稿 | 30 题，79 必需 + 20 补充目标；原字段保持不变；合成输入评分通过 | 材料化工作已经完成，待正式接线 |
| P2 | 文件记录 2026-09-19 U 已确认默认阈值、28/30 关键题、6 负例全 critical | 继续沿用已记录决定；无需重开同一选择题 |
| P3 | 对账草稿存在；7 类旧基线的用例、资产、范围仍不齐 | 当前最大实质性资料缺口 |
| P4 | `draft_pending_signoff`；同时列旧正式 gold 与 P1 草稿 | 有草稿，尚无唯一生效评分输入与完整运行版本 |

旧 `inventory.md` / memory 有两处应在下一次台账更新时纠正：

- “阈值未确认、试验初始版本无产物”已落后于今天 P2/P4 的文件状态。
- “30 题全部因为缺 targets 不能评分”不准确：缺 targets 阻断的是 24 道有答案题；6 道负例不需 targets。

## 本次复现证据

可重跑命令（仓库根目录，使用现有 uv 管理的虚拟环境）：

```bash
.venv/bin/python -B .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/diagnose.py --require-current-ready
```

本次 exit 1，表示正式输入尚未就绪；去掉该参数只输出诊断。脚本先安装既有 i3 守卫，无文件写入。
完整输出保存于同目录 `probes.json`。

| 探针 | 实测结果 | 证明范围 |
|---|---|---|
| 正式 gold + 理想合成观测 | 24 个 `evidence_targets_absent`；总 blocker 49 | 缺目标是实际评分路径的阻塞；49 含派生的关键题/阈值阻断，并非 49 个独立缺陷 |
| P1 gold + 完全相同观测 | 0 blocker，passed=true | P1 能满足评分输入契约，不证明真实检索/取证质量 |
| 当前审批件重新 evaluate | ready=true，20 warning | 当前审批完整性门有效 |
| 仅在内存中将审批应用器的 gold 路径指向 P1 | ready=false，`based_on.query_gold_sha256` 过期 | 直接覆盖正式 gold 的方案会破坏已有审批绑定；未实际覆盖文件 |
| 仅清空非关键题 macro-004 的合成证据 | `below_threshold:macro:evidence_pass=87.5%` | 非关键标记不会豁免领域阈值 |

已有回归重跑：

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  CORPUS_GUARD_PHASE=i3 \
  CORPUS_GUARD_CONFIG="$PWD/.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3.json" \
  .venv/bin/python -B -m pytest --noconftest -c /dev/null \
  -p no:cacheprovider -p plugins.corpus.preparation.guard_pytest \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remediation/test_approval_contract.py \
  tests/test_corpus_scoring.py \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i30-review/test_review_probes.py \
  -q --tb=short
```

输出：`88 passed in 0.26s`。冻结校验命令为：

```bash
.venv/bin/python -B .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py
```

输出末段：`r26 I3-2 adoption verified (... gate ready=true, approved projection 79+20)`，exit 0。
未跑含真实模型调用的 preflight：本轮诊断不涉及产品代码提交，也不以真实模型结果调整预期。

## 卡点 1：评分输入与审批原件共用路径，导致“补字段即审批过期”

`i3s2_apply_decisions.py:247` 起直接校验当前 query gold 文件哈希。裁决绑定 `6f6c5a25…`，
P1 草稿为 `1b018ceb…`。这使“把 P1 写回原路径，再运行审批门”无法直接成立。

**推荐整改：新增正式评分输入派生件。**

1. 保留 r26 的 query gold、候选、裁决、批准投影不变。
2. 将 P1 确定性材料化结果落为新的正式 `query-gold-scoring-v1.jsonl`（建议路径，当前未创建）。
3. 新增派生 manifest，绑定原 query gold、source gold、批准投影、裁决、材料化程序、输出文件的哈希。
4. 验证每题原字段不变；24 题的 required 与批准投影一致，20 条 supplementary 不进入必需集合；
   6 道负例没有必需 targets；每条 quote/source/locator 可回链，target_id 至少题内唯一。
5. 评分入口只接收初始实验 manifest 指定的评分输入路径，禁止依赖旧默认路径或选择“最新文件”。

验收：已有审批仍 ready；正式派生输入合成契约通过；任意上游哈希或目标集合改变都使派生校验失败。
这是一份新的正式评分输入版本，仍需作为 I3-2 完成包的一部分冻结和签认。

若必须覆盖旧路径，应归档旧字节并建立新的候选/裁决/投影及相应签认版本；不能只把旧审批件的哈希改成新值。
当前推荐新增派生件，因为它保留已经完成的审批证据，改动面更小。

## 卡点 2：旧基线有汇总数字，缺完整、可执行的对照身份

`baseline-bindings.json` 已在 r1 绑定；被引用的 `i0a4-candidates-v3-20260915.json` 未在冻结链绑定。
P3 的“drift=0”仅说明被检查的少数资产未漂移，不等于 7 类用例均齐备或非回归通过。
只给 v3 文件补哈希也不够：文件内部分引用依旧是散文。

| 类别 | 应完成的具体工作 |
|---|---|
| legacy_retrieval_golden | 从已知 golden 固定适用题号、旧 any/all 口径和来源范围，记录旧锚点到新 source/locator 的映射；检索入口/参数作为 I3-5 重验契约 |
| old_doc_kind_review_export | 索引其实已有候选 CSV 路径和 SHA；P3 将其归为“纯描述”混淆了资产存在与权威版本确认。先查既有决定是否已指定该候选；仍无决定才提出针对这一文件的确认，勿把 88 个工件重新交给用户筛选 |
| financial_controlled_recalc_57 | 绑定 57 个字段用例及预期、来源、期间、单位、容差；为已存在的 machine_record 补哈希；登记隔离重验入口，不能直接执行写原库的旧入口 |
| formula_7 | 显式列 7 个公式 case_id、输入字段、公式、预期和容差；共享父项文件可以，但须有稳定 JSON pointer/selector 和父件哈希 |
| customer_table_12 | 将历史 run `0a1dbf39…` 与 12 个单元格预期明确绑定，补独立重验入口契约；先处理来源属于 holdout_protected 的范围冲突，不能在开发校准中读取其原文 |
| prose_numbers_3 | 固定 3 个具体用例及来源跨度、期间、单位、数值和质量门；区分历史 2/2 与最终 3/3 的集合关系，不能用散文数字拼成 3 个用例 |
| macro_legacy_fields_0_of_3 | 保留 actual/consensus/previous 的旧失败用例及失败原因；标为历史 0/3，不将缺入口记作通过；检查所涉来源与留出范围的关系 |

统一记录建议字段：`case_id / category / expected_asset(path, sha256, selector) / source_id /
old_anchor / new_locator_or_mapping_rule / historical_status / historical_record_ref /
applicability / rerun_contract(entry, params, side_effects, required_environment) / validation_stage`。

整改取舍：I3-2 冻结“将来用哪些用例、按什么预期比较”，运行状态保持 `not_run`；I3-5/I3-7 再执行。
旧原库写入口须迁移到已核验隔离目标，不能因补基线而解除生产库限制。
留出相关历史基线单列为历史非回归范围；若以后获准重验，也不能据此声称新的独立留出评估。
范围冲突在冻结前明确，不能直接删除这些旧失败或旧通过用例。

验收：7 类全部有明确适用结论；适用用例可定位且预期固定；无未冻结的必要外部指针；
资产缺失或范围未决显式阻断，不以“drift=0”代替完整性判断。

## 卡点 3：P4 绑定了评测材料，却还不能唯一重建实验起点

P4 同时列正式/草稿 gold，只写评分函数入口；未完整指定后续实际执行命令、初始检索/切块配置、
依赖与运行代码版本，也没有供执行器唯一选取的评分输入。部分资产可能已在历史链中，
应强引用对应修订和哈希，不必重复复制。

整改为一个明确的初始实验 manifest：

- 评分输入：唯一正式派生 gold + 上游 lineage；source gold / 审批投影 / 约束投影。
- 评测规则：评分器、P2 的显式 policy、关键题/负例名单；运行时显式构造 policy，避免只依赖默认值。
- 旧基线：完成 P3 后的 case manifest 与各必要资产引用。
- 初始执行版本：代码修订和必要工作区差异哈希、`uv.lock`、开发范围、准入/解析/清洗/切块/检索初始参数。
- 接线契约：chunk 按来源归并成文档 Top-k、真实 build_id、fetch/verify 结果、故障与 no_match 的转换规则。
- 运行计划：可核验的命令/入口、预期输入输出、环境和阶段；尚未实现的入口明确登记为 I3-1 前置，不能写成已可执行。
- 守卫：I3-2 仍使用原 i3 守卫；实际 I3-1 前单独准备并验证 i3-e2e 配置及精确隔离目标，不改当前守卫。

P2 的实际含义必须落纸：每类 10 题中 2 道负例，QuestionPass/EvidencePass 分母是 8；
95% 意味着这两项必须 8/8。DocRecall 为文档集合召回的宏平均，应按其自身分母计算。
非关键的 `industry-006`、`macro-004` 不受关键题否决，但仍受领域阈值约束。本轮不更改已确认阈值。

## 卡点 4：局部绿灯与阶段完成没有统一区分

目前有审批门 ready、冻结链通过、P1 自洽、P2 已确认等局部状态，尚无一个判定 I3-2 完成的入口。
加上旧台账仍写待裁决，容易反复回到已经完成的事项。

建议建立 `validate_i3_2_completion.py`（待实现），输出逐项 `pass/fail/not_run/not_applicable`，
至少覆盖：上游审批有效、正式评分派生件一致、P2 值与清单一致、旧基线身份/范围闭环、
初始 manifest 必要字段齐、全部必要资产哈希入链。
它调用已有评分/审批/冻结校验，不新增另一套评分算法。

## 执行顺序与验收

| 顺序 | 工作包 | 主责 | 完成标准 |
|---|---|---|---|
| 1 | 确认 r26 + 今天 P1/P2 为工作起点，整理统一状态表 | Agent | 历史问题/现存问题分开；不重复要求 P2 决策 |
| 2 | 新增正式评分输入派生件和 lineage 校验 | Agent | 原审批不失效；24 道题有 79 必需目标；20 补充隔离；6 负例保持；合成契约及变异反例通过 |
| 3 | 补齐 7 类旧基线的 case manifest | Agent 整理；用户只处理仍无依据的权威版本/范围决定 | 每项都有具体资产/缺口和建议；适用范围无待定；不读取保护的留出正文、不跑原库 |
| 4 | 完成唯一初始 manifest 和阶段完成门 | Agent | 用显式路径/policy 消费正式输入；版本/范围/基线均可追溯；缺任一必需项返回失败 |
| 5 | 有针对性的复核与最终差异包 | 复核者 + 用户阶段签认 | 只审新增派生关系、基线范围与初始版本；复用已有审批，20 条同义 warning 保留可追踪 |
| 6 | 追加 r27（若届时编号已使用则取下一号），更新两份台账并复跑门 | Agent | 历史快照不改；冻结链、阶段完成门、受影响回归全部通过；I3-2 状态可签认 |
| 7 | 进入 I3-1 的环境预检与 E2E | Agent 按已授权范围执行 | 独立通过隔离 PG/来源/守卫与必要预算检查；真实结果另记，不能复用合成分数 |

步骤 2、3 的资料准备可独立推进；步骤 4 依赖它们完成，步骤 6 必须使用最终固定字节。
最终签认针对已完成、可审阅的差异包，不把尚未整理好的技术缺口交给用户选择。

20 条人工同义 warning 和 macro-004 的候选 machine blocked 当前已由正式审批承载，
重算审批门确为 ready=true；它们应作为语义审计风险保留，不能单凭旧 machine 状态再次宣称审批阻断。
若针对性审计发现实质缺证，才重新打开相应用例。mapping-7 自动规则优化没有必要成为本轮默认前置。
M5 F3 的旧 I1 验证器问题单列跟踪，不与本次已通过的 I0-C 当前冻结链混为同一故障。

**建议下一项具体工作：正式评分派生件 + 7 类旧基线用例清单，完成后统一冻结；先不启动真实 E2E。**
