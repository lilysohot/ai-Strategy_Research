# I2-8 / I2-4 独立复核（2026-09-18）

| 项 | 内容 |
| -- | -- |
| 状态 | **independent review · 结论 F1—F11；I2-8 建议 `partial`、I2-4 建议 `complete（两项一致性收口）`；M5 不可放行** |
| 日期 | 2026-09-18 |
| 审核对象 | `plugins/corpus/preparation/read_pg.py`、`plugins/corpus/cli.py`、`plugins/corpus/service.py`（读侧）、`plugins/tools/corpus_search.py`、`plugins/tools/corpus_fetch.py`、`plugins/corpus/audit.py`、`plugins/tools/data_coverage.py` |
| 裁决依据 | [tasks.md I2-8/I2-4 验收门](../../../../../docs/plan/corpus-ingestion-rebuild-tasks.md)、[架构 §7.2/§7.3/§9](../../../../../docs/plan/corpus-ingestion-rebuild-architecture.md)、[design-review](../../design-review.json) `i0c_4.consumer_migration_matrix`（13 行）与 `i0c_1_branch.reset_scope_candidates` |
| 执行方证据 | [audits/20260918-i2-8-i2-4/verification-matrix.txt](../20260918-i2-8-i2-4/verification-matrix.txt)（四族真库 50 passed、语料全量 424 passed、冻结 i0c-r9/r10）——**本复核不推翻该记录，只界定其证明边界** |
| 方法 | 最小失败信号 + **阳性对照**；反例落点 [test_review_probes.py](test_review_probes.py) |
| 纪律 | 只写 `i2_sandbox_corpus` 的 `corpus` schema（目标双校验）；零模型；不读来源正文；生产库与 `apodex`/`i0b2_verify_*` 零触碰 |

## 1. 结论

**两项都已实现，但都未达整项验收。** 台账现记「I2-1/2/3/5/7/8 与 I2-4 完成」属超前宣告。

- **I2-8 建议 `partial · 独立复核待整改`**：主体接线成立（版本句柄、块级跨发布取证、旧句柄拒绝、撤销拒绝、audit 缺口检测均真库实测），但存在 **1 项 P1 偏离**（跨发布时文档级读取静默换正文并错标出处）与 5 项欠交付。
- **I2-4 建议 `complete（两项一致性收口）`**：六职责齐备、复用正式门、操作者/generation 有实测；遗留为纪律性与一致性项，非功能阻断。
- **M5 不可放行**：除 I2-6 未完成外，F8（legacy 读路径口径）直接触及 M5「不接受旧 search/fetch 仍读旧 blocks」的定义，F1 影响 verify 溯源闸。

判定口径：`partial` 为有交付但未达整项验收。本复核不宣告任何门通过。

## 2. 实际审核范围与方法

本轮做的是**真库复核**（与 I2-5 轮的只读审核不同），因此先声明边界：

**做了**：在 `i2-verify` 守卫 env + `CORPUS_I2_DSN` → `i2_sandbox_corpus` 下运行自写探针（含阳性对照）；复跑官方真库族；读实现、冻结绑定与 design-review 矩阵做交叉核对；跑冻结验证器。

**没做**：未调模型；未读 `data/corpus` 来源正文与留出；未触碰生产库、`apodex`、`i0b2_verify_*`；未跑 engine 全链 E2E；未修改实现、正式测试、台账或既有冻结文件。

**数据副作用声明**：探针与官方族均含 `TRUNCATE`（九表），作用于 `i2_sandbox_corpus`，与既有测试族相同纪律；清理前做 `current_database` 与「含 apodex 库即判生产实例」双校验。

**方法约束**：每个反例断言的是**契约要求**（tasks.md / 架构 / design-review 明文），失败即偏离证据；末尾对照项必须通过，否则红灯不构成证据。

## 3. 本轮执行结果

| # | 命令/对象 | 结果 |
| - | ------- | ---- |
| 1 | 探针（i2-verify 守卫 env） | **5 failed / 1 passed**（对照通过 → 红灯成立） |
| 2 | `tests/test_corpus_consumers_pg.py tests/test_corpus_cli_pg.py`（同 env） | **15 passed**，无 skip |
| 3 | `validate_i0c_freeze.py` | **exit 0**（r10→…→i0a5 血缘完整） |
| 4 | `i0c-r9` 绑定清单核对 | 见 §6.2：`data_coverage.py`、`verify.py` **未进入绑定** |

第 2、3 项与执行方声明一致；第 1 项是新增发现——**官方门全绿而探针 5 红**，即既有测试未覆盖以下契约面。

## 4. 已成立的部分（不作否定）

以下为真库实测通过、本复核确认有效，不需推翻：

- 版本句柄 `cv2:<build_id>` + `chunk:<chunk_id>` 由 `corpus_search` 产出、`corpus_fetch` 消费，块级取回**逐字** `corpus_units.raw_text`；
- **块级**跨发布取回原 build（发布 B 后，`cv2:<A>` 仍返回 A 的正文，`active=False`），检索只服务活动 build；
- 未发布 build 不进候选；跨 build / 非十六进制句柄拒绝；
- 旧句柄 `LegacyHandleError`（`archive_required`），不拿新链正文顶替；
- 撤销准入后句柄 `WithdrawnError`、读侧零候选；
- `audit_corpus_chain` 检出「已排除决定但活动指针未撤下」；
- I2-4 六职责全部复用正式门（`plan_builds`/`execute_builds`/`check_build_publishable`/`publish_build`），`publish` 强制 `--operator`，操作者与 generation 落 PUBLISHED 检查点，`--dsn` 不隐式连库，拒绝非隔离目标。

## 5. 发现

### F1 · P1：文档级读取静默换正文，且出处标注与正文来源不一致

位置：[read_pg.py:212-252](../../../../../plugins/corpus/preparation/read_pg.py#L212-L252)（`_DOC_SQL` + `fetch_document`），经 [service.py:998-1006](../../../../../plugins/corpus/service.py#L998-L1006) `document_text` 与 [service.py:1767](../../../../../plugins/corpus/service.py#L1767) `source_resolver` 外露。

现状：`_DOC_SQL` 取 `corpus_publications.active_build_id`，即**活动版本**；但返回的 `DocumentEvidence.build_id` 仍填句柄解析出的 build_id。

证据（探针实测）：同一句柄 `cv2:<A>`（A 已非活动、B 为活动版本）——
- `fetch_verbatim` 返回 A 的正文（正确）；
- `document_text` 返回 **B 的正文**（`石英股份新版产能 120 万吨`），而 `DocumentEvidence.build_id == A`。

裁决依据：tasks.md I2-8 验收门为「新句柄可跨发布取回原版本」「未知/旧句柄不静默换正文」。design-review 对「文档级 / 活动版本 / document_text / source_resolver」**零明文裁决**（全库检索命中 0），故当前语义不是获准例外，而是实现自选。

影响：`verify` 的溯源闸经 `source_resolver` 读取；跨发布后旧引文会被拿去与**新正文**比对，可能把过期证据误判为通过，或给出误导性不符结论。

现有测试为何漏掉：`test_old_handle_reads_original_build_after_new_publish` 只测 `fetch_verbatim`；`source_resolver` 与 `document_text` 的用例都只在**单 build / 活动版本**下调用，从未构造「句柄 ≠ 活动版本」的文档级读取。

整改方向：择一并写进规格——(a) 文档级读取遵循句柄版本（与块级同语义）；(b) 保留活动版本语义，但 (i) 在 §7.2/tasks.md 显式写明文档级例外，(ii) `build_id` 必须填**实际读取的 build**。无论哪条，须补「跨发布 + 文档级读取」回归。

### F2 · P2：撤销后文档级读取返回空串，与块级拒绝语义不一致

位置：[read_pg.py:246-252](../../../../../plugins/corpus/preparation/read_pg.py#L246-L252)。

现状：来源撤销后 `active_build_id` 为空 → `_DOC_SQL` 零行 → 返回 `text=""`。块级路径抛 `WithdrawnError`。

证据（探针实测）：撤销后 `service.document_text("cv2:<build>")` 返回 `""`。

影响：空串使「已撤销」与「合法空文档」不可区分。verify 路径上表现为「引用不符」（fail-closed，但原因误导），调用方无法定位真实原因；若未来有消费方把 `""` 当作有效正文（例如空摘要），即为 fail-open 面。

现有测试为何漏掉：`test_withdrawn_source_handle_refused` 只断言 `fetch_verbatim` 抛 `WithdrawnError` 与 `search == []`，未测文档级。

整改方向：与 F1 一并决定文档级语义；撤销必须给出可区分的信号（拒绝或显式 `None`），不得返回空串。

### F3 · P2：coverage 缺 §7.3 必带字段 `publication_snapshot_ref`

位置：[read_pg.py:275-338](../../../../../plugins/corpus/preparation/read_pg.py#L275-L338)。

依据：架构 §7.3 明文「coverage 必带 `requested_scope_ref/effective_scope_ref/publication_snapshot_ref/reason_codes` 及来源数、已发布数、排除数、待复核/失败数」；design-review `consumer_migration_matrix[11]` 亦列该 ref。

证据（探针实测）：`coverage_snapshot` 返回键为 `requested_scope_ref`、`effective_scope_ref`、`processing`、`query_status`、`availability`、`reason_codes`、`counts`——**无 `publication_snapshot_ref`**。

影响：§7.3 要求「检索并发发布时的结果和覆盖元数据读取同一数据库快照」；缺快照引用，该约束无法自证，消费方也无法把 coverage 与具体发布时点绑定。

现有测试为何漏掉：`test_corpus_consumers_pg.py` 只断言 `processing`/`query_status`/`availability`/`reason_codes`/`counts`，未断言三 ref 齐全。

### F4 · P2：consumer matrix [11] `data_coverage.py` 未按 action 落地，且未进冻结绑定

位置：[data_coverage.py:143-173](../../../../../plugins/tools/data_coverage.py#L143-L173)。

依据：design-review `migrate` 清单明列「corpus_search/corpus_fetch/verify/**data_coverage**/metadata（读路径全部迁新句柄与 coverage 对象）」，矩阵 [11] action = 「§7.3 coverage 三轴对象（requested/effective/publication_snapshot/counts）」，stage=I2-8。

证据：该文件 `coverage` 仍只返回 `research/quote/financials/web` 旧结构；`research` 计数虽已走 `corpus_service().search()`（新链），但 §7.3 三轴对象**完全未透出**（`svc.coverage()` 未被调用）。交叉证据：`i0c-r9` 的 `implementation` 绑定 9 个文件，**不含 `data_coverage.py`**；执行方证据矩阵亦未提及该文件。

影响：I2-8 的「消费者接线」在该行未完成，且因为是「遗漏」而非「失败」，官方门不会变红。

### F5 · P2：`corpus_fetch` 未透出 span，与 consumer matrix [4] 不符

位置：[corpus_fetch.py:71-94](../../../../../plugins/tools/corpus_fetch.py#L71-L94)。

依据：矩阵 [4] action = 「fetch 校验 chunk∈build，返回原文片段+**span**/cell」；架构 §4.2 要求引用区间用权威原文 code point 偏移。

证据（探针实测）：工具载荷键为 `active/build_id/chunk_id/doc_id/hint/kind/locator/ok/source_id/text/units`——无 `source_ranges`/`span`。底层 `ChunkEvidence.source_ranges` 已计算并被 `read_pg.fetch_verbatim` 填充，只是未透出。

影响：`evidence` 的坐标溯源粒度退回「unit 级 page/element」（cell 有），跨 unit 的精确区间无法从工具层获得。

### F6 · P2：「旧引用归档策略」未成文、无产出定义

依据：tasks.md I2-8 关键步骤明列「旧引用归档策略」；design-review `i0c_1_branch.reset_scope_candidates[0].retained_semantics` 定义保留件为「导出件（**doc_id→source_id 映射 manifest 供旧引用解释**）」；§7.2 亦指向「历史引用由离线归档解释」。

证据：全仓检索无任何生成该 manifest 的代码、无字段定义、无产出时点与所有者；现状只有 `archive_required` 拒绝路径（[corpus_fetch.py:48-60](../../../../../plugins/tools/corpus_fetch.py#L48-L60)、[read_pg.py:95-104](../../../../../plugins/corpus/preparation/read_pg.py#L95-L104)）。

影响：策略缺口使「旧引用如何被解释」在切换期无据可依；若该件实际属 I4（design-review 该候选 precondition 为「新链重建并核对后」），则 I2-8 需明确标注顺延，不得留白。

### F7 · P3：golden 顺延未登记为 carry-over

依据：矩阵 [6] `plugins/corpus/golden.py` stage = **`I2-8/I3-5`**，action = 「I3-5 由 U 圈定范围后同口径重评或退役；迁移前不作为新链验收依据」。

现状：完全顺延至 I3-5，属**有据顺延**；但 I2-8 的交付说明与证据矩阵未把它登记为显式 carry-over 项，读者无法从 I2-8 交付判断该项存在。

### F8 · P2（需裁定，M5 阻断候选）：`CORPUS_READ_CHAIN` 保留旧 blocks 读路径

位置：[service.py:772-791](../../../../../plugins/corpus/service.py#L772-L791) `read_chain()`，legacy 分支见 [service.py:851-880](../../../../../plugins/corpus/service.py#L851-L880)（`_SEARCH_SELECT` 读旧 `blocks/documents`）。

依据：tasks.md §3.5 明文「**M5 不接受『新 CLI 通过，但旧 search/fetch 仍读旧 blocks』**」；I2-8 口径为「该实验目标无 legacy fallback」。

现状：`CORPUS_READ_CHAIN` 取 `new|legacy|auto`，`auto`（默认）按目标库是否含 `corpus.corpus_publications` 决定；运行期可由环境变量切到 `legacy`。官方测试用 `monkeypatch.setenv("CORPUS_READ_CHAIN", "new")` 钉住，**未覆盖** legacy 分支，守卫也未拒绝该配置。

影响：这是一条可切换的静默降级路径。M5 需要「无 legacy fallback」可自证，当前证据不足。

整改方向：明确口径二选一——(a) 演练目标下 legacy 分支必须不可达（守卫/启动校验拒绝）；(b) 允许存在但须证明在目标库上不可触发，并补齐反证用例。

### F9 · P2：CLI 复制引擎公式（违反「CLI 不复制规则」）

位置：[cli.py:370-378](../../../../../plugins/corpus/cli.py#L370-L378) vs [engine.py:779-781](../../../../../plugins/corpus/preparation/engine.py#L779-L781)。

现状：CLI 内联 `canonical_fingerprint([revs["parse_rule_rev"], source.source_id, extractor_rev_for(source.format)])`；引擎写入 build 时用 `reader_result.extractor_rev`。二者当前同源等价（`extractor_rev_for` 与 reader 常量一致），故现有测试（MD 夹具）下 `rebuild-plan` 判定正确。

影响：引擎若改变 parse_rev 组成（新增规则分量、改用实际 reader 返回的 rev），CLI 会**静默**给出错误的复用判定，而不会报错。

整改方向：把期望 parse_rev 的计算下沉为引擎公开 API（如 `engine.expected_parse_rev(source)`），CLI 只调用；补非 MD 格式与「规则分量变化」用例。

### F10 · P2：同一前置条件映射到两个退出码

证据（探针实测）：`check --build <不存在的 build>` → **4**（gate）；`status --build <不存在的 build>` → **5**（unavailable）。二者均为「目标 build 不存在」。

影响：I2-4 验收门要求「错误退出码」可用；调用方（脚本/web）无法用统一码判定「目标不存在」，只能按命令分别处理。

整改方向：统一「目标不存在」语义（或明确 4 与 5 的差别并写入文档串与测试），避免同因异码。

### F11 · P3：`argparse` 错误不经 `main()` 返回码

位置：[cli.py:470-491](../../../../../plugins/corpus/cli.py#L470-L491)。

现状：缺必填参数时 `parse_args` 抛 `SystemExit(2)`，`main()` 未捕获。文档承诺「exit 2 输入非法」仅在进程级成立；程序化调用者（含测试）拿到异常而非返回值。

## 6. 覆盖核对

### 6.1 consumer matrix（`i0c_4.consumer_migration_matrix`，stage 含 I2-8 的行）

| 行 | 消费者 | stage | 达标 | 判定依据 |
| -- | ---- | ----- | -- | ------- |
| [3] | `plugins/tools/corpus_search.py` | I2-8 | ✅ | 句柄 + coverage 对象 + 空命中改述，真库实测 |
| [4] | `plugins/tools/corpus_fetch.py` | I2-8 | ⚠️ | 句柄校验/旧句柄拒绝达标，**缺 span（F5）** |
| [5] | `plugins/corpus/verify.py` | I2-8 | ⚠️ | `source_resolver` 走新链已实测，但受 **F1/F2** 影响，且该文件未进 `i0c-r9` 绑定 |
| [6] | `plugins/corpus/golden.py` | I2-8/I3-5 | ⚠️ | 有据顺延 I3-5，未登记 carry-over（F7） |
| [7] | `plugins/corpus/audit.py` | I2-8 | ✅ | `audit_corpus_chain` 缺口检测真库实测 |
| [11] | `plugins/tools/data_coverage.py` | I2-8 | ❌ | **未按 action 落地（F4）** |
| [12] | `tests/test_corpus_*`（13 文件） | I2-8/I3-7 | ✅ | 本族测试已进 `i0c-r9` 绑定 |

合计：**明确达标 3 / 7；含缺陷达标 2；未落地 1；顺延未登记 1。**

### 6.2 冻结绑定交叉核对（`i0c-r9`）

`implementation` 绑定 9 文件：`cli.py`、`audit.py`、`service.py`、`read_pg.py`、`search_pg.py`、`engine.py`、`repository_pg.py`、`corpus_search.py`、`corpus_fetch.py`。

**未绑定**：`data_coverage.py`（F4 的独立佐证）、`verify.py`、`metadata.py`、`golden.py`。`tests` 绑定 4 文件含 `test_corpus_consumers_pg.py`；`docs` 绑定 2 份计划文档；验证器 exit 0。绑定清单本身即说明「哪些消费者本轮实际被触碰」——与 §6.1 的判定互为印证。

### 6.3 tasks.md 验收门逐条

**I2-8**：「真实 corpus_search/corpus_fetch、verify、golden/日期调用方与批处理迁移」→ verify 达标但受 F1/F2 影响；golden 顺延未登记；**批处理调用方（`scripts/`）未在本轮证据中出现**，亦未在任何清单登记。 「精确版本句柄」ⓘ 块级达成、文档级未达成（F1）。「coverage/hint」ⓘ hint 达标、coverage 缺 ref（F3）。「旧引用归档策略」❌ 未成文（F6）。

**I2-4**：「CLI 不复制规则」❌ 违反（F9）。「错误退出码」⚠️ 存在同因异码（F10）与 `SystemExit` 路径（F11）。「操作者/generation」✅ 实测。 「精确目标与阶段守卫有效」✅ 实测（拒绝非隔离目标）。「这些为拟新增命令」✅ 六条齐备。

## 7. 需裁定项（不由本复核单方决定）

1. **R1/F1 的文档级读取语义**：遵循句柄版本，还是保留活动版本语义并写入规格？后者必须同时修正 `build_id` 标注。
2. **F8 的 legacy 读路径口径**：演练目标下是否必须不可达？这直接决定 M5 能否按「无 legacy fallback」自证。

## 8. 本轮未覆盖、仍需补的真库验收

- **engine 全链（plan→execute→publish）与 CLI 的联合恢复**：本轮 CLI 只走通/失败路径，未注入阶段失败与断线。
- **`document_text`/`source_resolver` 的跨发布与撤销组合**（F1/F2 的正式回归）。
- **批处理调用方**（`scripts/corpus_holdout_eval.py`、`scripts/truncation_ab.py`、`scripts/corpus_evidence_pilot.py`）是否需迁移、归 I2-8 还是 I3-5，须裁定后补测。
- **`data_coverage` 三轴**（F4）迁移后的契约测试。
- **legacy 分支反证**（F8）：守卫或启动校验拒绝 legacy 的负例。

## 9. 反例复现命令

仓库根执行；当前预期 **5 failed / 1 passed**（对照通过）。仅写 `i2_sandbox_corpus`。

```bash
env -u PYTHONPATH \
  CORPUS_GUARD_PHASE=i2-verify \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json \
  CORPUS_I2_DSN="postgresql://postgres:***@127.0.0.1:543/i2_sandbox_corpus" \
  uv run pytest .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i2-8-i2-4-review/test_review_probes.py \
  -q -p plugins.corpus.preparation.guard_pytest --noconftest -c /dev/null --tb=short
```

官方门复跑（本轮实测 15 passed，无 skip）：

```bash
env -u PYTHONPATH \
  CORPUS_GUARD_PHASE=i2-verify \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json \
  CORPUS_I2_DSN="postgresql://postgres:***@127.0.0.1:543/i2_sandbox_corpus" \
  uv run pytest tests/test_corpus_consumers_pg.py tests/test_corpus_cli_pg.py -q \
  -p plugins.corpus.preparation.guard_pytest --noconftest -c /dev/null
```

## 10. 与 I2-5 轮复核的关系

两份复核方法一致（最小失败信号 + 阳性对照 + 观测/推理分离），差别在证据条件：I2-5 轮冻结前置门未过故**未跑真库**；本轮冻结自洽（exit 0），故实际复跑了真库门并新增探针。I2-5 轮的 F1—F3（`finish_job` 终态短路、发布断线恢复、引擎短路绕过准入）**本轮未复查、状态不变**，其整改见 [../20260918-i25-review/remediation-checklist.md](../20260918-i25-review/remediation-checklist.md)。

整改落点见同目录 [remediation-checklist.md](remediation-checklist.md)（编号 `RM-I28-*`，与前一轮 `RM-*` 分属两个命名空间）。

## 11. 声明与证据边界

- 本报告由独立复核方出具，**不改写**执行方的历史证据与冻结快照；两方结论冲突时按 tasks.md §12.4/§5 建新修订，不追改历史字节。
- 探针为**合成数据 + 真 PG**，证明的是 Store/读侧/工具层契约行为；不构成 engine 全链 E2E 验收。
- F1 的文档级语义、F8 的 legacy 口径属**规格问题**，本复核只给出偏离证据与选项，裁定权在 U/任务所有者。
- 本轮所有结论均可由 §9 命令独立复现。
