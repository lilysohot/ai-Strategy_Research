# I2-8 / I2-4 整改清单（2026-09-18）

| 项 | 内容 |
| -- | -- |
| 状态 | **draft · 待 U/执行者核定**。本清单不是执行授权，不新增/降低阶段门，不改任务编号 |
| 日期 | 2026-09-18 |
| 上游依据 | 同目录 [review.md](review.md)（F1—F11）；[tasks.md I2-8/I2-4](../../../../../docs/plan/corpus-ingestion-rebuild-tasks.md)；[架构 §7.2/§7.3/§9](../../../../../docs/plan/corpus-ingestion-rebuild-architecture.md)；[design-review](../../design-review.json) `i0c_4.consumer_migration_matrix` |
| 编号空间 | 本清单用 **`RM-I28-*`**；与 [../20260918-i25-review/remediation-checklist.md](../20260918-i25-review/remediation-checklist.md) 的 `RM-1`～`RM-13` 是两个独立命名空间，不得混引 |
| 进度真源 | [总计划 · 台账](../../../../../docs/plan/claims-market-closed-loop-plan.md)；本清单只列动作与关闭判据，完成/放行裁决回填总台账 |
| 纪律 | tasks.md §5：改动影响运行即建新冻结修订，不覆盖历史；生产库 I4 前零写入；PG 门不得 skip |

## 0. 放行口径与本次判定

- 现状：I2-8、I2-4 均已实现，**整项验收未达标**。
  - **I2-8 → `partial · 独立复核待整改`**：`RM-I28-1`（P1）未闭环前不得记 `complete`。
  - **I2-4 → `complete（两项一致性收口）`**：`RM-I28-9`/`RM-I28-10` 为非阻断收口项。
- **M5 维持 `not_declared`**：除 I2-6 未完成外，`RM-I28-1`（影响 verify 溯源闸）与 `RM-I28-8`（legacy 读路径口径）直接触及 M5 定义。
- 环境纪律：一切真库动作在 `i2-verify` 守卫 env、目标 `i2_sandbox_corpus`；统一 `env -u PYTHONPATH`（去宿主注入，非放宽守卫）。
- 反例基线：`review.md` §9 探针当前预期 **5 failed / 1 passed**（2026-09-18 实测一致）。
- 裁定前置：`RM-I28-0`（两项规格裁定）未决时，`RM-I28-1`/`RM-I28-8` **只能备选方案，不能定稿实施**。

## 1. 整改项总表

| ID | 对应 | 严重度 | 摘要 | 阻断 I2-8/I2-4 | 状态 |
| -- | -- | ---- | ---- | ----------- | ---- |
| RM-I28-0 | §7 裁定项 | — | 裁定文档级读取语义（F1）与 legacy 读路径口径（F8） | 是（前置） | open |
| RM-I28-1 | F1 | **P1** | 文档级读取静默换正文且 `build_id` 标注与正文来源不一致 | **是** | open |
| RM-I28-2 | F2 | P2 | 撤销后文档级返回空串，与块级 `WithdrawnError` 语义不一致 | 否 | open |
| RM-I28-3 | F3 | P2 | coverage 缺 §7.3 必带 `publication_snapshot_ref` | 否 | open |
| RM-I28-4 | F4 | P2 | consumer matrix [11] `data_coverage.py` 未按 action 落地，且未进冻结绑定 | 否 | open |
| RM-I28-5 | F5 | P2 | `corpus_fetch` 未透出 span，与 consumer matrix [4] 不符 | 否 | open |
| RM-I28-6 | F6 | P2 | 「旧引用归档策略」未成文，无 manifest 定义/产出时点/所有者 | 否 | open |
| RM-I28-7 | F7 | P3 | golden 顺延 I3-5 未登记为 carry-over | 否 | open |
| RM-I28-8 | F8 | P2 | `CORPUS_READ_CHAIN=legacy` 保留旧 blocks 读路径，与 M5 口径冲突 | **是（M5 认定）** | open |
| RM-I28-9 | F9 | P2 | CLI 内联复制引擎 parse_rev 公式，违反「CLI 不复制规则」 | 否 | open |
| RM-I28-10 | F10 | P2 | 同一「build 不存在」在 `check`/`status` 映射到 4/5 两个退出码 | 否 | open |
| RM-I28-11 | F11 | P3 | `argparse` 错误抛 `SystemExit(2)`，不经 `main()` 返回码 | 否 | open |
| RM-I28-12 | 收口 | — | 重冻当前实现/测试/结果 + 台账与清单回填结论 | 是（收口动作） | open |
| RM-I28-13 | — | — | 批处理调用方（`scripts/`）归属裁定与登记 | 否 | open |

## 2. 整改项明细

### RM-I28-0（前置）规格裁定

- 待裁两项：
  1. **文档级读取语义**：遵循句柄版本（与块级同语义），还是保留活动版本语义并写入规格（§7.2/tasks.md 显式例外）。
  2. **legacy 读路径口径**：演练目标下是否必须不可达（守卫/启动校验拒绝），还是允许存在但须证明不可触发。
- 产出要求：裁定结论写入 tasks.md 对应验收门 + 架构 §7.2（用词与现有条目一致）；未裁定前 `RM-I28-1`/`RM-I28-8` 按「备选方案 A/B」并列，不选型实施。
- 依据：design-review 对「文档级/活动版本/document_text/source_resolver」零明文裁决（检索命中 0）；tasks.md §3.5 对 legacy 有明文但未落到实现约束。

### RM-I28-1（P1）文档级读取语义与出处标注

- 位置：[read_pg.py:212-252](../../../../../plugins/corpus/preparation/read_pg.py#L212-L252)；外露路径 [service.py:998-1006](../../../../../plugins/corpus/service.py#L998-L1006)、[service.py:1767](../../../../../plugins/corpus/service.py#L1767)。
- 现状（已实测）：句柄 `cv2:<A>`（A 非活动）时 `fetch_verbatim` 返回 A 的正文，`document_text` 返回活动版本 B 的正文，且 `DocumentEvidence.build_id == A`。
- 整改要求（按 RM-I28-0 裁定选一，但**第 3 条无条件成立**）：
  1. 方案 A：`_DOC_SQL` 改用句柄绑定的 `build_id`（与块级同语义）；
  2. 方案 B：保留活动版本语义，但在 §7.2 与 tasks.md I2-8 明写「文档级读取服务活动版本」的例外；
  3. **无论 A/B**：返回对象的 `build_id` 必须等于**实际读取的 build**，不得回填句柄值。
- 必须新增/转正的回归用例（真 PG）：
  - 发布 B 后，`document_text("cv2:<A>")` 的正文与 `build_id` 自洽（方案 A：均为 A；方案 B：均为 B 且显式标注活动版本）；
  - `source_resolver("cv2:<A>")` 在上述两种方案下行为与 `document_text` 一致（现状二者同源，须一并钉住）；
  - 单 build（句柄＝活动版本）时的既有行为不得回归。
- 不动项：块级 `fetch_verbatim` 的跨发布语义（已实测正确，不得改动）。

### RM-I28-2（P2）撤销后的文档级信号

- 位置：[read_pg.py:246-252](../../../../../plugins/corpus/preparation/read_pg.py#L246-L252)。
- 现状（已实测）：来源撤销后返回 `text=""`；块级抛 `WithdrawnError`。
- 整改要求：文档级不得用空串表达「不可服务」——按 RM-I28-0 的裁定统一为拒绝或显式 `None`，并与块级语义对齐说明。
- 必须新增的回归用例：撤销后 `document_text`/`source_resolver` 的信号与块级一致（不接受「空串 + 调用方自行判断」）；空库合法空文档与撤销必须可区分。
- 不动项：块级 `WithdrawnError` 类型与文案。

### RM-I28-3（P2）coverage 三 ref 齐全

- 位置：[read_pg.py:275-338](../../../../../plugins/corpus/preparation/read_pg.py#L275-L338)。
- 现状（已实测）：缺 `publication_snapshot_ref`；§7.3 与 matrix [11] 均列为必带。
- 整改要求：补 `publication_snapshot_ref` 并给出其定义（当前发布时点/`generation` 的稳定引用），且与 `requested_scope_ref`/`effective_scope_ref` 同一查询快照内取值（§7.3「同一数据库快照」）。
- 必须新增的回归用例：三 ref 齐全；并发发布期间检索时，coverage 的快照引用与命中结果来自同一快照。
- 不动项：`processing`/`query_status`/`availability` 的既有判定次序（`failed` 恒 `unknown`、`no_match` 不转 `absent`）。

### RM-I28-4（P2）data_coverage 迁移 + 证据补登

- 位置：[data_coverage.py:143-173](../../../../../plugins/tools/data_coverage.py#L143-L173)。
- 现状：`coverage` 仍为 `research/quote/financials/web`；§7.3 三轴对象未透出；`svc.coverage()` 未被调用；该文件未进 `i0c-r9` 绑定，执行方证据矩阵未提及。
- 整改要求：
  1. 按 matrix [11] 透出 §7.3 三轴对象（requested/effective/publication_snapshot/counts），**不得破坏**市场侧 `verdict`/`guidance` 语义；
  2. 语义边界写清：研报覆盖度用新链三轴，市场数据结构化覆盖沿用原有字段（两者不混用同一 `coverage` 键或明确分层）；
  3. I2-8 证据矩阵补登该文件与用例，冻结绑定补入。
- 必须新增的回归用例：三轴对象字段齐全；无研报覆盖时 `query_status=no_match`、`availability=unknown`；市场接口不可用与研报不可用分别可辨。
- 不动项：`verdict`/`guidance` 四态与 `GUIDANCE_*` 文案；市场端点调用方式。

### RM-I28-5（P2）corpus_fetch 透出 span

- 位置：[corpus_fetch.py:71-94](../../../../../plugins/tools/corpus_fetch.py#L71-L94)。
- 现状（已实测）：载荷无 `source_ranges`/`span`；`ChunkEvidence.source_ranges` 已计算。
- 整改要求：按 matrix [4]「原文片段+span/cell」透出区间（字段名与 `ChunkEvidence.source_ranges` 一致或明确映射），并说明偏移口径＝权威原文 code point（§4.2）。
- 必须新增的回归用例：span 与 `units[].raw_text` 拼接可复算出 `text`；空 `unit_refs` 的 chunk 不得伪造区间。
- 不动项：`text` 必须逐字来自 `corpus_units.raw_text`（已实测正确）。

### RM-I28-6（P2）旧引用归档策略成文

- 依据：tasks.md I2-8 明列该步；design-review `reset_scope_candidates[0].retained_semantics` 定义保留件为「doc_id→source_id 映射 manifest」。
- 现状：全仓无生成代码、无字段定义、无产出时点与所有者；仅 `archive_required` 拒绝。
- 整改要求（二选一并落文档）：
  1. 保留在 I2-8：定义 manifest 字段（旧 `doc_id` → `source_id`/新句柄/生成时点/校验和）、产出时机与所有者，并补生成脚本与用例；
  2. 判定属 I4：在 tasks.md I2-8 与总台账显式登记为顺延项，注明依据（design-review 该候选 precondition 为「新链重建并核对后」）。
- 关闭判据：任一路径都必须让「旧引用如何解释」有文档可依，不接受留白。

### RM-I28-7（P3）golden carry-over 登记

- 现状：matrix [6] stage 为 `I2-8/I3-5`，实际整体顺延 I3-5，未在 I2-8 交付登记。
- 整改要求：在 I2-8 交付说明与证据矩阵中登记为 carry-over（含依据、责任、目标轮次），不改 golden 代码。

### RM-I28-8（P2，M5 阻断候选）legacy 读路径口径

- 位置：[service.py:772-791](../../../../../plugins/corpus/service.py#L772-L791)、legacy 分支 [service.py:851-880](../../../../../plugins/corpus/service.py#L851-L880)。
- 现状：`CORPUS_READ_CHAIN` 支持 `new|legacy|auto`，默认 `auto` 按目标库结构决定；运行期可切 `legacy`。官方测试用 `new` 钉住，未覆盖 legacy 分支，守卫未拒绝。
- 整改要求（按 RM-I28-0 裁定）：
  1. 方案 A：目标库为演练目标时，legacy 分支不可达（启动校验或守卫拒绝 `legacy`），并补拒绝负例；
  2. 方案 B：保留但须证明在演练目标上不可触发（构造反证：目标库含 corpus schema 时任何配置都不得走旧 `blocks`）。
- 必须新增的回归用例：对 `new|legacy|auto` 三种取值，断言演练目标下的实际读取对象（表名/`build_id`），而不只断言工具可调用；M5 评审可直接引用该用例。
- 不动项：`auto` 的探测逻辑可作为非演练目标的兜底，但需在文档写明适用范围。

### RM-I28-9（P2）CLI 不复制引擎公式

- 位置：[cli.py:370-378](../../../../../plugins/corpus/cli.py#L370-L378) vs [engine.py:779-781](../../../../../plugins/corpus/preparation/engine.py#L779-L781)。
- 现状：CLI 内联 parse_rev 公式；引擎用 `reader_result.extractor_rev`。当前等价（同源常量），测试仅覆盖 MD。
- 整改要求：把「期望 parse_rev」的计算下沉为引擎公开 API（如 `engine.expected_parse_rev(source)`），CLI 只调用；`current_revs()` 与之一并作为唯一来源。
- 必须新增的回归用例：非 MD 格式（PDF/DOCX）的 `rebuild-plan` 复用判定；引擎侧改变 parse_rev 分量时 CLI 判定同步变化（用参数化/替身证明「不是各算一套」）。
- 不动项：`rebuild-plan` 的输出结构与 hint 文案。

### RM-I28-10（P2）退出码一致性

- 现状（已实测）：`check --build <不存在>` = 4；`status --build <不存在>` = 5。
- 整改要求：统一「目标不存在」的语义（或明确区分并在文档串 + 测试中固定差异），使调用方能用单一判定处理「目标不存在」。
- 必须新增的回归用例：同一前置条件跨命令的退出码对照表（含不存在、未决、门未过、目标拒绝四类）。
- 不动项：成功路径退出码 0；拒绝非隔离目标仍为 3。

### RM-I28-11（P3）`argparse` 错误路径

- 现状：缺必填参数抛 `SystemExit(2)`，不经 `main()` 返回码。
- 整改要求：二选一并固化——(a) `main()` 捕获 `SystemExit` 归一到 `EXIT_INPUT`；(b) 文档串明确「参数错误由 `argparse` 直接退出进程，不经 `main()` 返回」。选 (a) 时同步补用例。

### RM-I28-12（收口）重冻与回填

- 整改要求：
  1. 全部改动完成后新建冻结修订，绑定当前实现/测试/守卫/文档与**本轮重跑命令 + 输出**；`validate_i0c_freeze.py` 须 exit 0；
  2. 台账回填：I2-8 改 `partial · 独立复核待整改`；I2-4 标注两项收口；链接本复核与整改清单；M5 维持 `not_declared`；
  3. 证据矩阵补登 `data_coverage.py`（RM-I28-4）与探针命令/结果。
- 备注：2026-09-18 已核验冻结链 exit 0（r10 血缘完整）；本项是「整改后」的重冻，不是修复既有冻结。
- 不可做：改写历史快照哈希、覆盖 `i0c-r9`/`i0c-r10` 原始字节。

### RM-I28-13（P3）批处理调用方归属

- 现状：`scripts/corpus_holdout_eval.py`、`scripts/truncation_ab.py`、`scripts/corpus_evidence_pilot.py` 在 I2-8 证据中未出现，亦未在 consumer matrix 单列。
- 整改要求：裁定其归属（I2-8 迁移 / I3-5 golden 同批 / I5-3 退休核验），登记到 tasks.md 与台账；属 I2-8 则补迁移与用例。

## 3. 建议执行顺序与依赖

```text
阶段 0（裁定，前置）
  RM-I28-0（文档级语义 + legacy 口径）
      ├─→ 解锁 RM-I28-1（P1，唯一阻断 I2-8 的代码项）
      └─→ 解锁 RM-I28-8（M5 认定项）
阶段 1（代码与本轮同源改动，可并行）
  RM-I28-2 / RM-I28-3 / RM-I28-5   （读侧 与 工具层）
  RM-I28-4                          （consumer matrix [11] + 绑定补登）
  RM-I28-9 / RM-I28-10 / RM-I28-11  （I2-4 收口）
阶段 2（文档与归属）
  RM-I28-6（归档策略成文或顺延登记）
  RM-I28-7 / RM-I28-13（carry-over 与批处理归属登记）
阶段 3（收口）
  RM-I28-12（重冻）→ 台账回填
```

- `RM-I28-4` 与 `RM-I28-12` 存在绑定依赖：先迁移再重冻，不得先冻后改。
- `RM-I28-1`/`RM-I28-2` 共用 `read_pg` 文档级路径，建议同一批次提交，避免二次返工。
- 任一环节必需用例 skip/环境缺失 → 该环节未通过，不得以「官方门 15 passed」代替新增契约面。

## 4. 明确不做（防范围膨胀）

- 不推翻 I2-8 已成立的块级句柄、跨发布取证、旧句柄拒绝、撤销拒绝、audit 缺口检测与 I2-4 的复用纪律。
- 不推翻 I2-5 轮的 `RM-1`～`RM-13` 结论，也不把两套 RM 编号混用；I2-5 的 F1—F3 本轮未复查、状态不变。
- 不换模型、不新增研报、不改金标/冻结参数、不改 `i0c-r9`/`i0c-r10` 历史字节。
- 不动生产库（`127.0.0.1:5432`）与 `apodex`/`i0b2_verify_*`；写入仅限 `i2_sandbox_corpus` 的 `corpus` schema。
- 不在本轮引入性能改造（连接池/分区/GIN 批量维护/LIMIT 下推）与 engine 全链 E2E 重构（另立需求与实测标定）。
- 不提前放行 M5，不代做 I2-6（authority + cli_isolation）。

## 5. 关闭判据（Definition of Done）

1. `review.md` §9 探针命令在当前工作区从 **5 failed / 1 passed** 转为**全 passed**（或等价正式回归替代），且 F1—F11 对应正式测试转正；
2. 真库门复跑：`test_corpus_consumers_pg.py + test_corpus_cli_pg.py + 新增用例` **全 passed、零 skip**，覆盖跨发布文档级读取、撤销文档级信号、coverage 三 ref、data_coverage 三轴、fetch span、legacy 反证；
3. i1 守卫 env 与普通 env 定向回归无新增失败；`ruff` / `pyright` / `import_smoke --stage 1` 全绿；
4. `RM-I28-0` 两项裁定已写入 tasks.md 与架构 §7.2，且实现与规格一致；
5. 新建冻结修订绑定当前字节 + 本轮命令与输出，`validate_i0c_freeze.py` exit 0；
6. 总台账与任务清单已回填，I2-8 状态与 M5 声明按 §0 口径更新。

不在 1—6 全部满足前，**不得**将 I2-8 记 `complete`、不得宣告 M5。

## 6. 反例复现（当前基线）

在仓库根执行，当前预期 **5 failed / 1 passed**（对照项通过；仅写 `i2_sandbox_corpus`）：

```bash
env -u PYTHONPATH \
  CORPUS_GUARD_PHASE=i2-verify \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json \
  CORPUS_I2_DSN="postgresql://postgres:***@127.0.0.1:543/i2_sandbox_corpus" \
  uv run pytest .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i2-8-i2-4-review/test_review_probes.py \
  -q -p plugins.corpus.preparation.guard_pytest --noconftest -c /dev/null --tb=short
```

官方门复跑（2026-09-18 实测 15 passed，无 skip）：

```bash
env -u PYTHONPATH \
  CORPUS_GUARD_PHASE=i2-verify \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json \
  CORPUS_I2_DSN="postgresql://postgres:***@127.0.0.1:543/i2_sandbox_corpus" \
  uv run pytest tests/test_corpus_consumers_pg.py tests/test_corpus_cli_pg.py -q \
  -p plugins.corpus.preparation.guard_pytest --noconftest -c /dev/null
```

冻结链核验：

```bash
.venv/bin/python .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py   # 预期 exit 0
```
