# I2 全链路独立复核（2026-09-18）

| 项 | 内容 |
| -- | -- |
| 状态 | **independent review · 结论 F1—F4；I2 主体未偏离目标、按任务完成；F1 为阻断 I3 的实质缺口** |
| 日期 | 2026-09-18 |
| 审核对象 | I2 全链：`cli.py` → `engine.py` → `repository_pg.py` → `search_pg.py` / `read_pg.py` → `service.py` → `plugins/tools/corpus_search.py` / `corpus_fetch.py` → `verify.py` / `audit.py` |
| 裁决依据 | [tasks.md I2-1～I2-8](../../../../../docs/plan/corpus-ingestion-rebuild-tasks.md)、[架构 §7.2/§7.3/§9](../../../../../docs/plan/corpus-ingestion-rebuild-architecture.md)、[design-review](../../design-review.json) `i0c_4.consumer_migration_matrix` |
| 执行方证据 | [audits/20260918-i2-6/verification-matrix.txt](../20260918-i2-6/verification-matrix.txt)、[audits/20260918-i2-8-i2-4-remediation/verification-matrix.txt](../20260918-i2-8-i2-4-remediation/verification-matrix.txt)、[audits/20260918-m5-review/](../20260918-m5-review/)（M5 申请方备料） |
| 回路落点 | [test_fullchain_probes.py](test_fullchain_probes.py)（12 项：9 链不变量 + 3 缺口语义探针，含阳性对照） |
| 纪律 | 只写 `i2_sandbox_corpus` 的 `corpus` schema（目标双校验）；零模型；不读来源正文与留出；生产库/`apodex`/`i0b2_verify_*` 零触碰 |

## 1. 结论

**I2 没有偏离目标，按任务完成了**：9 条链不变量全部成立，官方六族真库门 71 passed 零 skip，前三轮复核的整改探针现已全绿。I2 作为「隔离 PG 上的入库/发布/读侧」主体**可以认定交付**。

但有 **1 项会阻断下游 I3 的实质缺口（F1）**，且它不在任何 I2 模块的测试面内——只有跑全链路才照得出来：

- **F1（P1，契约偏离）**：架构 §7.3 为 `coverage.processing` 定义了 `scoped`（「只覆盖请求范围的一个明确且已获准的真子集，**子集内无未决必需区域**」），即**允许发布一个已获准的子集**。实现在任何情况下都不放行含缺口的 build，且缺口区域无坐标、不参与 scope 判定 → **`scoped` 在实现上不可达**。受影响类别含 PDF 空白页、扫描页、表格抽取失败与 DOCX 内嵌图片——真实研报普遍命中。tasks.md I3-1 要求「三类材料各 ≥2 份走完到 publish」，存在大面积失败风险。
- **F2（P2，契约偏离，实测红）**：架构 §9 的 CLI 表规定 `corpus-status` 须「显示阶段、失败、**缺口**与可执行恢复路径」；实测 `check` 与 `status` 都只在自然语言 `error` 里带缺口，无机器可读字段 → 脚本/CLI 消费者无法据此自动路由（例如把该来源转 `review_required`）。
- **F3（P3）**：`DocumentEvidence.text` 是单元拼接、不复现源文件空行，接口未文档化该语义。
- **F4（P3）**：CLI 参数与架构 §9 表的命名不一致（`--build` vs `--job`）。

判定口径：本复核**不否定** I2 的既有实测记录，只界定其证明边界并指出验收门与实现之间的口径差。M5 是否放行不属本复核结论。

## 2. 审核范围与方法

方法来自 `diagnosing-bugs`（紧回路、最小失败信号、阳性对照）与 `codebase-design`（seam 位置、接口不变量一致性）。

**回路设计**：与模块测试族的关键差别是**用上一步的真实产物驱动下一步**——`cli build` 产出的 `build_id` 去 `check`/`publish`，`publish` 产出的 `generation` 与活动指针去驱动句柄，检索命中的句柄去 `fetch`，全程不手工构造 Store 行、不替换被测层。因此它检验的是**链的不变量**，而不是单模块行为。

**做了**：在 `i2-verify` 守卫 env + `CORPUS_I2_DSN` → `i2_sandbox_corpus` 下运行自写全链路回路与官方六族；复跑前三轮复核探针；读实现与规格做交叉核对；核对冻结链。

**没做**：未调模型；未读 `data/corpus` 来源正文与留出；未触碰生产库；未跑 I3 的校准/评分器；未修改实现、正式测试、台账或既有冻结文件。

**数据副作用声明**：回路与官方族均含 `TRUNCATE`（九表），作用于 `i2_sandbox_corpus`，与既有测试族同纪律；清理前做 `current_database` 与「含 `apodex` 库即判生产实例」双校验。

**保证方法有效性的对照项**：回路含 `test_control_full_chain_reaches_reference_free_evidence`（阳性对照，必须通过）。若对照失败，其余绿灯不构成「链路成立」的证据。

## 3. 本轮执行结果

| # | 对象 | 结果 |
| - | ---- | ---- |
| 1 | 官方 I2 六族真库门（publication / repository / consumers / cli / authority / cli_isolation） | **71 passed，零 skip** |
| 2 | 本轮回合全链路探针 | **10 passed / 2 failed**（2 红＝ F2 的两条契约断言：`check.gaps`、`status.gaps`） |
| 3 | 前三轮复核探针（`audits/20260918-i2-8-i2-4-review/test_review_probes.py`，整改前 5 红） | **6 passed**（整改真闭环） |
| 4 | `validate_i0c_freeze.py` | **exit 0**（r14 血缘完整） |

第 1、3、4 项与执行方记录一致；第 2 项为本轮新增面——**官方门全绿而链的不变量仍有 2 条契约红灯**。

## 4. 已成立的链不变量（9 条，全部实测）

| # | 不变量 | 断言要点 |
| - | ---- | ------- |
| 1 | 端到端逐字性 | 取证返回的**每个单元** `raw_text` 都逐字出自源文件字节；`chunk.text == "\n".join(units.raw_text)` |
| 2 | 数字/百分比一致性 | `23.5%` / `82.3%` / `42.50` 跨「写侧归一化 → 检索归一化 → 取证」均命中，取证文本仍是**原样数字** |
| 3 | 发布闭合 | 发布后 9 个阶段无 `running`，PUBLISHED 为 `succeeded`（执行台账与上线事实一致） |
| 4 | 重跑幂等 | 同清单重跑得**同 build_id**；重复发布 `generation` 与 `activated_at` 均不变 |
| 5 | 撤销闭合 | 检索零候选 + 块级/文档级均 `WithdrawnError` + coverage 含 `withdrawn_sources` + 审计无冲突（**五处口径一致**） |
| 6 | 完整性 | 篡改 `corpus_units.raw_text` 后，块级与文档级读取均抛 `IntegrityError` |
| 7 | 降级不可达 | 新库上请求 `CORPUS_READ_CHAIN=legacy` 被拒绝（RM-I28-8 方案 A 生效） |
| 8 | 跨发布句柄稳定 | 第二份来源发布后，旧句柄仍返回原 build 正文，`build_id` 与正文自洽 |
| 9 | 同快照组合读取 | `search_with_coverage` 的命中与 `counts.published` 同源，且带 `publication_snapshot_ref` |

## 5. 发现

### F1 · P1：§7.3 的 `scoped` 语义在实现上不可达（缺口无出口）

**规格**（架构 §344）：`scoped` =「只覆盖请求范围的一个明确且已获准的真子集，**子集内无未决必需区域**；须返回剩余范围」。§372：「输出 scoped，不称全文完成」。§531（fidelity 测试）只要求缺口**可见**，未要求缺口阻断发布。

**实现**：[engine.py `_verify_publication_ready`](../../../../../plugins/corpus/preparation/engine.py) 为 `if gap_regions: raise`（无分级、无裁决出口）；[clean.py `_SYNTHETIC_ISSUE_STATUS`](../../../../../plugins/corpus/preparation/clean.py) 把 9 个读取缺口码映射为合成区域，其中 8 个为 `REVIEW_REQUIRED` / `NEEDS_OCR`；[engine.py `_apply_scope_to_clean`](../../../../../plugins/corpus/preparation/engine.py) 明文规定：「合成缺口区域（`ordinal=None`）保留原样：**质量门拦截**，不在此静默丢弃」。

**冲突点**：缺口区域 `ordinal=None` 即**无坐标**，既无法参与 scope 的 `char:` 区间判定，也不可能被证明「在请求范围之外」。于是 scope 机制与发布门形成死锁——**只要材料里有一个缺口，任何获准范围都无法发布**，`scoped` 永远不可达。

**受影响类别**（`_SYNTHETIC_ISSUE_STATUS` + 各 reader 的 `code=`）：

| 缺口码 | 含义 | 真实研报常见度 |
| ----- | ---- | ---------- |
| `empty_page` | PDF 空白页（分页/封底） | 极高 |
| `image_only_page` | 扫描页（无文字层） | 高 |
| `unreadable_element` | DOCX 段落内图片/文本框/OLE | 高 |
| `image_region_unreadable` | 混合页大图区未覆盖 | 中 |
| `table_extraction_failed` / `table_lines_without_extraction` | 表格抽取失败 | 中 |
| `unknown_body_element` | DOCX 未知正文元素 | 低 |
| `unterminated_code_fence` | MD 围栏未闭合 | 低 |

**证据**：
1. **实测（characterization）** `test_gapped_build_cannot_publish_and_stays_rejected_on_retry`：受批合成 DOCX 夹具（含 cell 图）`build` 成功（exit 0），`publish` 两次尝试均 exit 4，`error` 含 `gap_regions`。即缺口不因重试消失、无旁路。
2. **规格与实现的文本对照**：§344 允许 scoped 发布；`_apply_scope_to_clean` 明文让缺口绕过 scope 判定并交质量门拦截。**此项为代码/规格阅读，非实测**（按 M8「观测/推理分离」标注）。
3. 受影响类别来自 `_SYNTHETIC_ISSUE_STATUS` 与各 reader 的缺口码表（代码阅读）。

**影响**：tasks.md I3-1 要求三类材料各 ≥2 份走完 `登记→准入→解析→清洗→切块→build/check/publish→真实 search/fetch/verify`。若开发材料含图表或空白页（研报几乎必然），I3-1 无法通过；且本缺口**不会被任何单模块测试发现**——每个模块测试都正确断言「缺口被记账」，没有人断言「链最终能发布」。

**为何现有测试漏掉**：I1 的 fidelity 正例都是**无缺口**夹具；I1-9 的 DOCX 夹具被设计为**制造**缺口（嵌套表 + cell 图），其验收目标是「缺口被正确记账」，不含「该材料可发布」；I2 六族全部只做 `store`/`service` 级操作，不经过 `plan→execute→publish` 的完整链。

**整改方向（三选一或组合，须由任务所有者裁定）**：
- A：**给缺口一个裁决 seam**——每个缺口区域带 `disposition`（`blocking` / `acknowledged` + 依据 + 记录人），`acknowledged` 不阻断发布但必须进 `coverage.reason_codes` 与 `status` 输出；
- B：**按 §7.3 分离「缺口记账」与「发布阻断」**——in-scope 子集内无未决即允许输出 `scoped`，缺口计入 coverage 与 status；
- C（前置条件）：**缺口坐标化**——合成缺口区域补 page/char span，使 scope 能判定其在请求范围之外。

无论 A/B，**缺口必须仍然可见**（不得回到「静默丢弃」），C 是 B 能自证的前提。

### F2 · P2：`check` / `status` 未暴露机器可读的缺口（实测红）

- **规格**：架构 §9 CLI 表 —— `corpus-status --job ...` | 「显示阶段、失败、**缺口**与可执行恢复路径」。
- **实现**：`cli._cmd_check` 被拒时只 emit `{"ok": false, "command", "error"}`；`cli._cmd_status` 载荷键为 `admission / build_id / command / coverage / decision_id / failed_stages / jobs / next / ok / publication / source_id`——**无缺口字段**。`next` 提示为通用文案，不含「缺口在哪、如何消解」。
- **实测（红）**：
  - `test_gap_rejection_exposes_machine_readable_gaps_in_check`：`check` 拒绝时 `payload["gaps"]` 不存在（实际 keys 仅 `command/error/ok`）；
  - `test_status_shows_gaps_per_cli_contract`：`status` 返回 `ok=true` 但无 `gaps` 字段。
- **影响**：操作者/脚本无法据此自动路由（把来源转 `review_required`、或触发重解析/OCR）；与 F1 叠加时，唯一的信号是一句自然语言错误串，M5/I3 的「可执行恢复路径」无从自动化。
- **整改方向**：`status` 输出结构化缺口（码、坐标、状态、建议动作）；`check` 被拒时同样带结构化缺口。

### F3 · P3：文档级文本的拼接语义未文档化

- **现状**：[`read_pg.fetch_document`](../../../../../plugins/corpus/preparation/read_pg.py) 返回的 `DocumentEvidence.text` 是单元 `raw_text` 用 `"\n"` 拼接，**不复现源文件的空行分隔**（源 `A\n\nB` → 文本 `A\nB`）。
- **对照**：块级 `ChunkEvidence` 的 docstring 已明确写「`text` 是该 chunk 引用单元 `raw_text` 的逐字拼接」，文档级没有对应说明。
- **影响**：逐字性按单元成立（这点无问题），但文档级文本在单元边界有歧义——恰为 `A\nB` 形式的引文在源文件中并不存在，却能与文档级文本匹配。使用方（`verify.source_resolver`、归档导出）可能误当「原文字节还原」。
- **证据**：全链路回路中两条按「整块子串」写的断言先后红掉，改为按单元/按行核对后转绿——说明该语义**未在接口上被显式表达**，只能靠试错发现。
- **整改方向**：在 `read_pg` 模块 docstring 与 `DocumentEvidence` 上写明拼接语义与「非字节还原」，或返回带分隔证据的结构。

### F4 · P3：CLI 参数命名与架构 §9 表不一致

架构 §9 CLI 表写的是 `corpus-status --job ...`，实现为 `status --build <build_id>`。`status` 展示该 build 的全阶段，用 `--build` 语义上可接受，但与规格文本不一致，且 `--job` 在 `corpus-status` 语境下更贴近「阶段+attempt」的语义。须择一对齐（改实现或改规格用词）。

## 6. 覆盖核对

### 6.1 tasks.md I2 验收门 vs 全链

| 任务 | 验收门要点 | 全链判定 |
| ---- | ------- | ------ |
| I2-1 | 隔离 DDL fail-closed | ✅ |
| I2-2 | §8.1 全部规则、lease_lost 停写不发布 | ✅ 不变量 3/5 |
| I2-3 | index_rev 升级可重建、先筛后排名 | ✅ 不变量 2/9 |
| I2-4 | CLI 不复制规则、退出码、操作者/generation | ✅（F4 为命名不一致） |
| I2-5 | 强制场景、PG 不得 skip | ✅ 71 passed 零 skip |
| I2-6 | 消费者同权威、坏副本/跨 build/坏哈希/子进程 | ✅ 不变量 1/6 |
| I2-7 | 唯一日期落点、无 legacy fallback | ✅ |
| I2-8 | 跨发布取回原版本、未知/旧句柄不静默换正文 | ✅ 不变量 8 |
| 阶段门 M5 | publication/authority/cli_isolation 实测含租约接管 | ⚠️ 技术条件齐备；**F1 属 I3 阻断项而非 M5 门** |

### 6.2 架构 §9 CLI 六职责逐条

| 命令 | 规格职责 | 判定 |
| ---- | ---- | ---- |
| `corpus-plan` | 校验清单/版本/工作量；无模型无 PG 写入 | ✅ 但**不做可发布性预检**（见 RM-FC-7） |
| `corpus-build` | 执行归档与候选构建/恢复；不自动发布 | ✅ |
| `corpus-check` | 核验产物/索引/取证/状态 | ⚠️ 拒绝原因不可机读（F2） |
| `corpus-publish` | 检查门通过后切活动版本，记录操作者与 generation | ✅ |
| `corpus-status` | 显示阶段、失败、**缺口**与可执行恢复路径 | ❌ 无缺口字段（F2） |
| `corpus-rebuild-plan` | 比较版本、决定可复用阶段 | ✅ |

## 7. 需裁定项

1. **F1 的口径**：选 A（缺口 `disposition` 裁决）还是 B（按 §7.3 分离记账与阻断、允许 `scoped`）？若选 B，必须先做 C（缺口坐标化），否则 `scoped` 仍无法自证。
2. **I3-1 的材料前置条件**：在 F1 闭环前，I3-1 是否需要一份「材料可发布性筛选标准」（哪些缺口可接受、哪些必须换料）？
3. **F4**：改实现（`--job`）还是改规格用词（`--build`）。

## 8. 本轮未覆盖、仍需补

- **engine 全链故障注入**（阶段失败/断线后的恢复跳算）——本轮只覆盖正常链与撤销/篡改路径；I2-5 的 RM-2/RM-8 项仍属该面。
- **I3 校准与评分器**（I3-0/I3-2）——不在 I2 范围。
- **留出与真实开发材料**的可发布性——本轮只用受批合成夹具；6 份开发材料的缺口分布未测（受读边界限制，须由执行方在获批范围内自测）。
- **`data_coverage` 的市场侧**——回路未覆盖（需桩掉 `build_service`，见整改矩阵 §E 的口径说明）。

## 9. 复现命令

```bash
# 全链路回路（本轮基线：10 passed / 2 failed，2 红为 F2 契约断言）
env -u PYTHONPATH \
  CORPUS_GUARD_PHASE=i2-verify \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json \
  CORPUS_I2_DSN="postgresql://postgres:***@127.0.0.1:543/i2_sandbox_corpus" \
  uv run pytest .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i2-fullchain-review/test_fullchain_probes.py \
  -q -p plugins.corpus.preparation.guard_pytest --noconftest -c /dev/null --tb=short

# 官方 I2 六族（本轮实测 71 passed 零 skip）
env -u PYTHONPATH \
  CORPUS_GUARD_PHASE=i2-verify \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json \
  CORPUS_I2_DSN="postgresql://postgres:***@127.0.0.1:543/i2_sandbox_corpus" \
  uv run pytest tests/test_corpus_preparation_publication_pg.py tests/test_corpus_preparation_repository_pg.py \
    tests/test_corpus_consumers_pg.py tests/test_corpus_cli_pg.py \
    tests/test_corpus_authority_pg.py tests/test_corpus_cli_isolation.py -q \
  -p plugins.corpus.preparation.guard_pytest --noconftest -c /dev/null

# 前三轮复核探针（本轮实测 6 passed）
env -u PYTHONPATH \
  CORPUS_GUARD_PHASE=i2-verify \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json \
  CORPUS_I2_DSN="postgresql://postgres:***@127.0.0.1:543/i2_sandbox_corpus" \
  uv run pytest .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i2-8-i2-4-review/test_review_probes.py \
  -q -p plugins.corpus.preparation.guard_pytest --noconftest -c /dev/null

.venv/bin/python .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py   # 预期 exit 0
```

## 10. 与前几轮复核的关系

| 轮次 | 落点 | 与本轮的关系 |
| ---- | ---- | ------- |
| I2-5 复核 | [../20260918-i25-review/](../20260918-i25-review/) | RM-1/RM-13 状态不变；本轮不变量 3 是其「发布闭合」在链上的复核 |
| I2-8/I2-4 复核 | [../20260918-i2-8-i2-4-review/](../20260918-i2-8-i2-4-review/) | 其 F1—F11 已整改，本轮回路复跑 6 passed 确认闭环 |
| I2-6 执行 | [../20260918-i2-6/](../20260918-i2-6/) | 其 authority 族是本轮不变量 1/6 的模块级来源 |
| M5 申请方备料 | [../20260918-m5-review/](../20260918-m5-review/) | 本轮不改 M5 结论；F1 属 I3 阻断项，建议作为 M5 复核的「已知未覆盖」输入 |

整改落点见同目录 [remediation-checklist.md](remediation-checklist.md)（编号 `RM-FC-*`）。

## 11. 声明与证据边界

- 本报告不改写执行方历史证据与冻结快照；结论冲突时按 tasks.md §5 建新修订，不追改历史字节。
- **F2 为实测红灯**（两条契约断言）；**F1 的「scoped 不可达」为「实测 characterization + 规格/代码文本对照」**，已按 M8 标注证据类型——其实现行为（含缺口必被拒）是实测的，其与 §344 的冲突判断是阅读得出的。
- 回路使用**合成夹具 + 真 PG**，证明链级契约行为；不构成 I3 校准或 engine 全链故障注入验收。
- 阳性对照必须通过，否则本轮绿灯不构成证据（本轮回合对照通过）。
- 所有结论可由 §9 命令独立复现。
