# I2 全链路整改清单（2026-09-18）

| 项 | 内容 |
| -- | -- |
| 状态 | **draft · 待 U/任务所有者核定**。本清单不是执行授权，不新增/降低阶段门，不改任务编号 |
| 日期 | 2026-09-18 |
| 上游依据 | 同目录 [review.md](review.md)（F1—F4）；[tasks.md I3-1 / I2-4](../../../../../docs/plan/corpus-ingestion-rebuild-tasks.md)；[架构 §7.3 / §9](../../../../../docs/plan/corpus-ingestion-rebuild-architecture.md) |
| 编号空间 | 本清单用 **`RM-FC-*`**（full-chain）。与 `RM-1`～`RM-13`（I2-5 轮）、`RM-I28-*`（I2-8/I2-4 轮）**分属三个独立命名空间**，不得混引 |
| 进度真源 | [总计划 · 台账](../../../../../docs/plan/claims-market-closed-loop-plan.md)；本清单只列动作与关闭判据，裁决回填总台账 |
| 纪律 | tasks.md §5：改动影响运行即建新冻结修订，不覆盖历史；生产库 I4 前零写入；PG 门不得 skip；缺口不得回退为「静默丢弃」 |

## 0. 放行口径与本次判定

- I2 主体（I2-1～I2-8）**按任务完成、未偏离目标**：官方六族真库门 71 passed 零 skip，链不变量 9/9 成立。
- **F1（`RM-FC-1`）不计入 I2 门的失败，但计为 I3 的前置阻断**：I3-1 要求三类材料各 ≥2 份走完到 `publish`，在 F1 闭环前有实质性不可达风险。
- **F2（`RM-FC-3`/`RM-FC-4`）为 I2-4 的收口项**：架构 §9 已规定 `corpus-status` 的缺口职责，属未落地而非新需求。
- 环境纪律：一切真库动作在 `i2-verify` 守卫 env、目标 `i2_sandbox_corpus`；统一 `env -u PYTHONPATH`。
- 回路基线：`review.md` §9 命令当前预期 **10 passed / 2 failed**（2 红＝ F2 契约断言）。
- **裁定前置**：`RM-FC-0` 未决时，`RM-FC-1`/`RM-FC-2` 只列备选方案，不选型实施。

## 1. 整改项总表

| ID | 对应 | 严重度 | 摘要 | 阻断 | 状态 |
| -- | -- | ---- | ---- | -- | ---- |
| RM-FC-0 | §7 裁定项 | — | 裁定缺口口径（disposition 裁决 / §7.3 scoped 放行）与 F4 命名对齐方向 | 是（前置） | open |
| RM-FC-1 | F1 | **P1** | §7.3 的 `scoped` 在实现上不可达：任何缺口恒阻断发布，无裁决出口 | **I3-1** | open |
| RM-FC-2 | F1-C | P2 | 缺口坐标化：合成缺口区域补 page/char span，使 scope 可裁决 | `RM-FC-1` 前提 | open |
| RM-FC-3 | F2 | P2 | `corpus-check` 拒绝时无机器可读缺口清单（实测红） | I2-4 收口 | open |
| RM-FC-4 | F2 | P2 | `corpus-status` 未显示缺口与可执行恢复路径（架构 §9，实测红） | I2-4 收口 | open |
| RM-FC-5 | F3 | P3 | `DocumentEvidence.text` 拼接语义未文档化（非字节还原） | 否 | open |
| RM-FC-6 | F4 | P3 | CLI 参数命名与架构 §9 表不一致（`--build` vs `--job`） | 否 | open |
| RM-FC-7 | 提升建议 | P2 | 可发布性预检前移到 `corpus-plan`，避免 build 成本已花才发现 | 否（I3 效率） | open |
| RM-FC-8 | 收口 | — | 全链路回路纳管（I3-7 复用）+ 重冻 + 台账回填 | 是（收口动作） | open |

## 2. 整改项明细

### RM-FC-0（前置）口径裁定

- 待裁三项：
  1. **缺口与发布的关系**：A = 每缺口带 `disposition`（`blocking` / `acknowledged` + 依据 + 记录人）；B = 按 §7.3 分离「缺口记账」与「发布阻断」，in-scope 子集无未决即允许 `scoped` 发布。
  2. 若选 B，是否接受 `RM-FC-2`（缺口坐标化）为其**必要前置**（否则 `scoped` 仍无法自证）。
  3. **F4**：改实现（对齐 `--job`）还是改规格用词（对齐 `--build`）。
- 产出要求：裁定结论写入 tasks.md 对应验收门与架构 §7.3/§9 用词；本清单据此进入实施。
- 依据：architecture §344/§372/§531；`engine._apply_scope_to_clean` 的明文不变式；`clean._SYNTHETIC_ISSUE_STATUS` 的 9 码映射。

### RM-FC-1（P1）缺口与发布门的解耦

- 位置：[engine.py `_verify_publication_ready`](../../../../../plugins/corpus/preparation/engine.py)、[clean.py `_SYNTHETIC_ISSUE_STATUS`](../../../../../plugins/corpus/preparation/clean.py)、[engine.py `_apply_scope_to_clean`](../../../../../plugins/corpus/preparation/engine.py)。
- 现状（已实测）：受批 DOCX 夹具（cell 图 → `unreadable_element`）`build` 成功、`publish` 两次均 exit 4；缺口区域 `ordinal=None` 不参与 scope 判定 → 任何获准范围都无法发布。
- 整改要求（按 `RM-FC-0` 选型）：
  1. 缺口**必须仍然可见**：无论 A/B，`quality_report` 保留缺口明细，并进 `coverage.reason_codes` 与 `status` 输出；
  2. 缺口**不再无条件阻断**：A 走 `disposition` 裁决（`acknowledged` 须留依据与记录人）；B 走 §7.3 的 in-scope 无未决判定；
  3. `blocking` 类缺口（如 `table_extraction_failed`）与可接受类（如 `empty_page`）的**默认分级**须写进规格，不得在代码里隐含。
- 必须新增/转正的回归用例：
  - 含 `empty_page` 的 PDF：按裁定路径可发布 → `coverage.processing ∈ {scoped, full}` 且 `reason_codes` 含该缺口；
  - 含 `table_extraction_failed` 的 PDF：按默认分级仍被拒（且拒绝原因机读）；
  - `acknowledged` 路径必须记录依据/记录人，审计可追溯；
  - 撤销后缺口处理不得绕过既有 fail-closed（不变量 5 不得回归）。
- 不动项：缺口码词表与 `UnitStatus` 映射的「不无记录消失」语义；`_verify_publication_ready` 的其余四项检查（阶段完成、quality_report 形状、unit_refs 闭合、KEPT 全覆盖）。

### RM-FC-2（P2）缺口坐标化

- 现状：合成缺口区域 `ordinal=None`，无 page/char span → scope 无法判定其在请求范围之外。
- 整改要求：reader 给出的缺口位置（DOCX `body:p[i]`/cell、PDF `page:N`）保留为结构化坐标，`CleanRegion` 承载可判定区间；无法给出坐标的缺口显式标 `unlocatable`（进裁决流程，不静默）。
- 必须新增的回归用例：`char:` scope 收窄到缺口之外的区间 → 缺口可被判为 out-of-scope（或显式 `unlocatable`），不再恒阻断。
- 依赖：`RM-FC-1` 选 B 时本项为必要前置。

### RM-FC-3（P2）`corpus-check` 输出机器可读缺口

- 位置：[cli.py `_cmd_check`](../../../../../plugins/corpus/cli.py)。
- 现状（实测红）：拒绝时 emit `{"ok": false, "command", "error"}`，无 `gaps` 字段。
- 整改要求：被拒时输出结构化缺口（码、坐标、状态、建议动作），退出码仍为 4；`error` 文案保留给人工。
- 必须转正的回归用例：`test_gap_rejection_exposes_machine_readable_gaps_in_check` 由红转绿。
- 不动项：退出码映射（`RM-I28-10` 已统一）。

### RM-FC-4（P2）`corpus-status` 显示缺口与可执行恢复路径

- 位置：[cli.py `_cmd_status`](../../../../../plugins/corpus/cli.py)；依据架构 §9 CLI 表。
- 现状（实测红）：载荷无 `gaps`，`next` 为通用文案。
- 整改要求：`status` 输出每阶段状态 + 结构化缺口 + **可执行恢复路径**（例如「补 OCR 后重跑 CLEANED」「该来源转 `review_required`」）；与 `RM-FC-1` 的裁定结果保持一致。
- 必须转正的回归用例：`test_status_shows_gaps_per_cli_contract` 由红转绿；含缺口/无缺口/已撤销三种情形的载荷对照。
- 不动项：`status` 对 `--build` 的语义（除非 `RM-FC-6` 裁定改命名）。

### RM-FC-5（P3）文档级拼接语义落文档

- 位置：[read_pg.py `DocumentEvidence` / `fetch_document`](../../../../../plugins/corpus/preparation/read_pg.py)。
- 整改要求：在模块 docstring 与 `DocumentEvidence` 上写明「`text` 为单元 `raw_text` 的确定性 `\n` 拼接，**不是原文字节还原**；跨单元引文须按单元取证」；或返回带分隔证据的结构。
- 必须新增的回归用例：断言拼接语义（`text == "\n".join(units)`）并在文档中固定该契约，避免使用方误当字节还原。
- 不动项：块级 `ChunkEvidence` 的既有语义（已文档化）。

### RM-FC-6（P3）CLI 参数命名对齐

- 按 `RM-FC-0` 第 3 项裁定：改实现（`status --job <build>:<stage>`）或改架构 §9 用词（`--build`）。
- 必须新增的回归用例：与裁定一致的参数解析与退出码用例。

### RM-FC-7（P2）可发布性预检前移到 `corpus-plan`

- 位置：[cli.py `_cmd_plan`](../../../../../plugins/corpus/cli.py)（现仅校验清单格式/非空/大小，无 PG 无模型）。
- 动机（codebase-design：把 seam 放到链更早的位置）：当前不可发布材料要等 `build` 把归档与 DB 都写完、在 `publish` 才暴露，成本已花。
- 整改要求：`plan` 增加**轻量可读性探测**（读文件、跑 reader 的缺口记账，不解析全量为宜），输出每份材料的预计缺口类别与「按当前缺口口径是否可发布」的**预判**；纯只读、无 PG 写入、无模型。
- 必须新增的回归用例：plan 对含缺口材料给出预判；预判与后续 `check` 的实际判定一致（口径同源，不得各算一套）。
- 不动项：`plan` 的只读与无模型性质。

### RM-FC-8（收口）回路纳管、重冻与台账回填

- 整改要求：
  1. **全链路回路纳管**：把 `test_fullchain_probes.py` 的 9 条不变量按 I3-7「全链重验」的复用清单登记（去重后作为 E2E 基线），缺失的 2 条契约断言在 `RM-FC-3`/`RM-FC-4` 转绿后再并入；
  2. 全部改动完成后新建冻结修订，绑定当前实现/测试/守卫/文档 + 本轮重跑命令与输出，`validate_i0c_freeze.py` 须 exit 0；
  3. 台账回填：I2 行标注本复核链接与 F1—F4 处置；I2-4 行标注 F2 收口项；**I3-1 行的前置条件加入 F1 闭环**；
  4. 不覆盖历史快照字节。
- 关闭判据见 §5。

## 3. 建议执行顺序与依赖

```text
阶段 0（裁定）
  RM-FC-0 ─┬─→ 解锁 RM-FC-1（P1，I3-1 前置）
           ├─→ 解锁 RM-FC-6（命名对齐）
           └─→ 决定 RM-FC-2 是否为 RM-FC-1 的必要前置
阶段 1（可见性与可用性，可与阶段 0 并行备料）
  RM-FC-3 / RM-FC-4（check/status 缺口可见性，转红为绿）
  RM-FC-5（文档级语义落文档）
阶段 2（缺口口径落地）
  RM-FC-2（坐标化，若选 B 则必做）→ RM-FC-1（缺口与发布门解耦）
阶段 3（效率与收口）
  RM-FC-7（预检前移，建议与 RM-FC-1 同批，二者共用缺口口径）→ RM-FC-8（回路纳管 + 重冻 + 回填）
```

- `RM-FC-1` 与 `RM-FC-7` **必须共用同一缺口分级/口径来源**，否则会出现「plan 预判可发布、publish 仍拒」的二次口径分裂。
- `RM-FC-2` 是 `RM-FC-1` 选 B 的必要前置；选 A 时可独立并行。
- 任一必需用例 skip/环境缺失 → 该环节未通过，不得以「官方 71 passed」代替新增契约面。

## 4. 明确不做（防范围膨胀）

- 不推翻 I2 已成立的 9 条链不变量、官方 71 passed 与前三轮整改的结论。
- 不把缺口回退为「静默丢弃」——这是 `_apply_scope_to_clean` 明文禁止的，任何整改方案都必须保持缺口可见。
- 不修改缺口码词表与 `UnitStatus` 语义；不改 `_verify_publication_ready` 的其余四项检查。
- 不换模型、不新增研报、不改金标/冻结参数；不改写历史冻结快照字节。
- 不动生产库与 `apodex`/`i0b2_verify_*`；写入仅限 `i2_sandbox_corpus`。
- 不在本清单内推进 I3 校准、评分器冻结与留出评测（另属 I3-0/I3-2/I3-7）。
- 不代做 M5 放行裁决（本复核不改 M5 结论）。

## 5. 关闭判据（Definition of Done）

1. `review.md` §9 的全链路回路在当前工作区从 **10 passed / 2 failed** 转为**全 passed**，且 9 条不变量无回归；
2. F1 按 `RM-FC-0` 的裁定闭环：含 `empty_page` 类缺口的材料能按其路径发布并使 `coverage.processing` 与 `reason_codes` 如实反映；`blocking` 类缺口仍被拒且原因机读；
3. `check` 与 `status` 输出结构化缺口与可执行恢复路径（`RM-FC-3`/`RM-FC-4` 由红转绿）；
4. `corpus-plan` 的预判与 `check` 的实际判定**同口径**（`RM-FC-7`）；
5. 冻结链：新修订绑定当前字节 + 本轮命令与输出，`validate_i0c_freeze.py` exit 0；
6. 总台账与任务清单已回填，且 I3-1 行已登记 F1 前置；
7. 回退纪律：整改后 i2-verify 守卫 env 下官方六族仍 **零 skip 全 passed**（不因新增缺口路径放宽既有门）。

## 6. 复现（当前基线）

```bash
# 全链路回路：当前预期 10 passed / 2 failed（2 红＝F2 契约断言）
env -u PYTHONPATH \
  CORPUS_GUARD_PHASE=i2-verify \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json \
  CORPUS_I2_DSN="postgresql://postgres:***@127.0.0.1:543/i2_sandbox_corpus" \
  uv run pytest .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i2-fullchain-review/test_fullchain_probes.py \
  -q -p plugins.corpus.preparation.guard_pytest --noconftest -c /dev/null --tb=short

# 官方 I2 六族：当前预期 71 passed 零 skip
env -u PYTHONPATH \
  CORPUS_GUARD_PHASE=i2-verify \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json \
  CORPUS_I2_DSN="postgresql://postgres:***@127.0.0.1:543/i2_sandbox_corpus" \
  uv run pytest tests/test_corpus_preparation_publication_pg.py tests/test_corpus_preparation_repository_pg.py \
    tests/test_corpus_consumers_pg.py tests/test_corpus_cli_pg.py \
    tests/test_corpus_authority_pg.py tests/test_corpus_cli_isolation.py -q \
  -p plugins.corpus.preparation.guard_pytest --noconftest -c /dev/null

.venv/bin/python .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py   # 预期 exit 0
```
