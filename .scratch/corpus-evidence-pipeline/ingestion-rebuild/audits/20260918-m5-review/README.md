# M5 独立复核包（I2 PG 门 → M5 放行裁决）

| 项 | 内容 |
|---|---|
| 日期 | 2026-09-18（v2 修订同日，见 §10） |
| 性质 | **申请方备料，非复核结论**。本包只定义复核对象、放行条件、命令矩阵、交叉核验清单与预期结果；复核执行与 M5 裁决由独立复核人完成，最终放行由 U 在总台账签认 |
| 复核对象 | I2 当前候选快照 [freezes/i0c-r15.json](../../freezes/i0c-r15.json)（直接父快照 i0c-r14，血缘 r15→r14→r13→r12→…→r1→i1-r4→i1-r3→i1-r1→i0a5(M1)） |
| 申请方自证留痕 | [audits/20260918-i2-6/verification-matrix.txt](../20260918-i2-6/verification-matrix.txt)、[audits/20260918-i2-8-i2-4-remediation/verification-matrix.txt](../20260918-i2-8-i2-4-remediation/verification-matrix.txt)、[audits/20260918-i2-fullchain-review/](../20260918-i2-fullchain-review/)、总台账 2026-09-18 各回填条目——均为申请方留存结果，**不冒充本轮独立执行** |
| 复核人 | 待定（应使用全新会话，未参与 I0—I2 制备）；实际执行者与其独立性偏差由复核报告 §独立性声明 首段记录 |

## 1. 本次复核裁决什么

唯一裁决项：**M5 是否放行**。通过条件（任务清单 §2 M5 行原文）：

> M3、M4 与 I2 全部完成，旧消费者在隔离目标接线；publication_pg/authority/cli_isolation 实测含租约接管，核心 PG 门不得 skip。

不在本轮裁决范围（复核人不得要求补做，也不得宣称已通过）：I3（三类 E2E/校准/最终重验）、I4（切换与清理）、I5（增量与退役）、R2 语义链与模型预算、真实模型调用、留出（holdout）正文读取、性能改造（连接池/分区/LIMIT 下推）。

## 2. 复核对象与版本锚点

| 锚点 | 值 | 核验方式 |
|---|---|---|
| i0c-r15 快照（当前候选） | 见 evidence/freeze-hashes.log | `sha256sum` + `validate_i0c_freeze.py` |
| i0c-r14 / i0c-r13（父快照链） | 见 evidence/freeze-hashes.log | 同上（血缘要求逐级匹配） |
| i0c-r12 / i0c-r11 | `66c8080ccccc104e…` / `79ad48a12dd1c2fa…` | 同上 |
| i0c 冻结验证器 | 见 evidence/freeze-hashes.log | 同上；含 r1..r15 全链核验 |
| 守卫 guards/i2-verify.json | `f47ce4569e81088d…` | `validate_i0c_freeze.py`（r9 绑定组）+ sha256sum |
| i2-verify 守卫自检报告（历史） | `26212d2f698a80a6…` | 本包另跑一次 selfcheck 到 evidence/（write-once） |
| r15 绑定面 | implementation 5（gaps/clean/engine/read_pg/cli）+ tests 1（gap_dispositions）+ docs 3 + review_evidence 3 + validator/generator 各 1，全 SHA-256 | `validate_i0c_freeze.py` 全量核验（latest-revision-wins 合并 i0c-current） |
| 演练目标 | `i2_sandbox_corpus`（corpus-db 容器 host 543）；生产库 `127.0.0.1:5432` 与 `apodex`/`i0b2_verify_*` 只读不触碰 | 前置门 target-guard（见 §4） |

血缘语义：r15.parent = r14（I2 全链路复核整改：缺口裁决/坐标/CLI 可见性/coverage scoped）；
r14 = M5 复核包备料修订；r13 = I2-6 交付（authority + cli_isolation）；r12 仅重绑
`data_coverage.py` 类型收窄；r11 = I2-8/I2-4 复核整改；r9/r10 = I2-8/I2-4 首轮交付与计数修正。
历史字节一律不改写。

## 3. M5 放行条件核对清单（复核人逐项记录证据）

**A 前置与冻结链**
- A1 `validate_i0c_freeze.py` exit 0：索引 ID 唯一、i0c-r1 绑定、r2..r15 合并绑定（latest-revision-wins）与 i1-r4 supersession、血缘 r15→…→i0a5(M1)、design-review 已签认
- A2 §2 快照哈希命中；r15 绑定面与文件实际字节一致（只读复算）
- A3 上游门已有独立证据且未被本轮改动推翻：M3（I0-C 冻结 i0c-r1）、M4（M4 复核放行）——本轮只核验其**在链条上仍可追溯**（§5 交叉核验）

**B 阶段守卫与零模型**
- B1 guard selfcheck（i2-verify 配置，合成反例，write-once 落 evidence/guard-selfcheck.json）`passed=true` 且 24/24
- B2 守卫 env（`env -i` + `guard_pytest`，守卫先于测试收集装载）下 §4 行为矩阵通过
- B3 guard 测试 19 项在**受控普通环境**独立通过（不与守卫 env 混跑）
- B4 复核全程零模型：子进程 cli_isolation 块内 `openai` import/构造被拒（真实验证，非声明）
- B5 复核全程未读留出正文、未触碰生产库/`apodex`/`i0b2_verify_*`（守卫 env 结构性保证：目标 allowlist 仅 127.0.0.1:543 + 前置门 target-guard）

**C I2 必需测试族（架构 §12.2；括号内为每文件用例数，总计 102 真库/链级 + 188 守卫业务 + 19 守卫测试）**
- C1 `publication_pg`：**17**（双 worker 并发 acquire/register/过期接管、真实停顿越过 TTL 的接管、陈旧 token 迟到提交、提交丢响应幂等、取消与接管、max_attempts 三条路径、并发发布与 retire 竞态、失败恢复、index_rev 升级；**核心 PG 门不得 skip**）
- C2 `repository_pg`（Isolation 存储 + FTS 读侧）：**18**（幂等/冲突/指针只进不退/fencing 四态/租约接管/发布 gen/领域+日期过滤/活动范围先筛后排名）
- C3 `authority`：**8**（同一权威 Interface 逐项对照 ground truth；坏哈希/篡改正文、引用悬空、错 cell、跨 build/坏/旧句柄、清洗视图与检索展示非权威、JSONB 副本与权威指纹不符拒绝、审计检出悬空引用）
- C4 `cli_isolation`：**5**（真实 CLI 子进程 build→check→publish→status、重启续跑幂等、退出码 2/3/5、模型客户端拒绝、网络允许清单、旧句柄拒绝）
- C5 消费者接线：`consumers_pg` **19** + `cli_pg` **4**（版本句柄、跨发布取回、撤销信号、coverage 三 ref 与同快照、data_coverage 三轴、fetch span、legacy 口径反证、CLI 退出码一致与引擎单一来源）
- C6 复核探针（I2-8/I2-4 轮独立复核方所写，本轮**转正为放行前置**）：**6**（5 反例 + 1 阳性对照）
- C6b **链级契约面**（I2 全链路复核方所写，r15 起纳管；六族只做 store/service 级操作，链不变量
  只有这两个文件守得住）：全链路回路 **12**（9 链不变量 + `check`/`status` 缺口契约 + 阳性对照，
  **write-once 不修改**）+ 缺口裁决 `tests/test_corpus_gap_dispositions.py` **13**（默认分级表逐项锁定、
  坐标解析、scope 归属、`acknowledged` 放行留痕、`blocking` 仍拒、plan 与 check 同口径、文档级拼接语义）
- C7 i1 守卫 env 业务套件（preparation 11 文件）：**188 passed**（I1/M4 面在 I2 改动后无回归）
- C8 守卫测试（普通环境）：**19 passed**

**D 消费者接线与「旧来源路径不能兜底」**
- D1 目标库含 corpus schema 时，`CORPUS_READ_CHAIN=legacy` 请求被拒（`tests/test_corpus_consumers_pg.py::test_read_chain_legacy_refused_on_migrated_target`）——"新库静默降级读旧 blocks"这条路径不存在
- D2 无 corpus schema 的库请求 `new` 同样 fail-closed（`test_read_chain_new_refused_without_corpus_schema`）
- D3 旧句柄（非 `cv2:`）在工具层/读侧一律 `archive_required`，不拿新正文顶替
- D4 消费者读出的 build 与实际发布指针一致（consumers_pg/authority_pg 断言 `build_id`/活动范围，非只断言"工具可调用"）

**E 已知未覆盖（如实声明；不阻断 M5，但复核报告不得宣称已通过）**
- I3 三类开发材料 E2E 与指标、I3-5 旧检索 golden（含 `plugins/corpus/golden.py` 的 carry-over）、I3-7 最终版本重验
- 批处理 eval 脚本（`scripts/corpus_holdout_eval.py`、`truncation_*.py`、`corpus_evidence_pilot.py`）归属 I3-5/I5-3，未迁移
- 旧引用 `doc_id→source_id` 归档 manifest 顺延 I4（本轮只交付 `archive_required` 拒绝路径）
- 真实模型调用、R2 语义链、独立留出验收
- 性能标定（解析耗时/索引大小/查询 P95、连接池/分区/LIMIT 下推）

## 4. 命令矩阵与预期结果

执行方式（仓库根目录；**前置：`CORPUS_I2_DSN` 指向隔离演练库，且 corpus-db 容器在运行**）：

```bash
export CORPUS_I2_DSN="postgresql://postgres:***@127.0.0.1:543/i2_sandbox_corpus"
bash .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/run_matrix.sh
```

**执行模型（三段式）**：

1. **前置门（失败即停，exit 2）**：冻结验证器 → 快照哈希留痕 → **目标双校验**（`current_database == i2_sandbox_corpus` 且实例不含 `apodex`）→ 守卫自检。任一失败不进入行为矩阵。
2. **行为矩阵 + 静态检查（失败继续收集证据）**：所有 pytest 块产出 JUnit XML；守卫 env 块在 `env -i` 下先装载守卫再收集并显式传 DSN；受控普通环境同样 `env -i` 最小继承 + 禁用插件自动加载与 conftest（**普通环境 ≠ 允许连 PG/公网/模型**）。随后运行后门重跑冻结验证器（**绑定零漂移检查**，失败 exit 2）并留痕脚本/冻结/探针哈希。
3. **汇总核对（`verify_matrix.py`）**：按 JUnit XML 精确核对每块 tests/failures/errors/skipped 计数，日志块核对内容命中，产出机器可读 `evidence/matrix-summary.json`。

**退出码语义**：0 = 矩阵与预期一致；1 = 存在 MISS（发现候选）；2 = 前置门或运行后门失败。**退出码只表示「矩阵与预期一致」，不构成 M5 裁决**；预期不符按 §8 记录，不得修改预期凑结果。

| 阶段 | 块 | 环境 | 预期 |
|---|---|---|---|
| 前置门 | freeze-validator | 受控最小 | exit 0：`i0c freeze chain verified`（索引唯一、r1..r15 合并绑定、血缘至 i0a5(M1)、design-review 签认） |
| 前置门 | freeze-hashes | 受控最小 | exit 0；§2 各锚点哈希写入 evidence/freeze-hashes.log |
| 前置门 | target-guard | 受控最小 + DSN | exit 0：`TARGET_OK i2_sandbox_corpus`（且 echo 无 `apodex` 库） |
| 前置门 | guard-selfcheck | 受控最小 | exit 0；`passed=true` 且 24 项 case 全过（write-once 落 evidence/guard-selfcheck.json） |
| 行为矩阵 | publication-pg | 守卫 env（i2-verify） | JUnit：tests=17 failures=0 errors=0 skipped=0 |
| 行为矩阵 | repository-pg | 守卫 env | JUnit：18/0/0/0 |
| 行为矩阵 | authority-pg | 守卫 env | JUnit：8/0/0/0 |
| 行为矩阵 | cli-isolation | 守卫 env | JUnit：5/0/0/0 |
| 行为矩阵 | consumers-pg | 守卫 env | JUnit：19/0/0/0 |
| 行为矩阵 | cli-pg | 守卫 env | JUnit：4/0/0/0 |
| 行为矩阵 | i28-i24-probes | 守卫 env | JUnit：6/0/0/0 |
| 行为矩阵 | i2-fullchain-probes | 守卫 env | JUnit：12/0/0/0 |
| 行为矩阵 | i2-gap-dispositions | 守卫 env | JUnit：13/0/0/0 |
| 行为矩阵 | i1-business-guard-env | 守卫 env（i1 配置） | JUnit：188/0/0/0 |
| 行为矩阵 | guard-tests-normal-env | 受控最小 | JUnit：19/0/0/0 |
| 静态 | ruff-check | 受控最小 | `All checks passed!` |
| 静态 | ruff-format-check（I2 改动文件） | 受控最小 | `already formatted` / 无 reformat |
| 静态 | pyright-i2-scope | 受控最小 | exit 0 + `0 errors` |
| 静态 | import-smoke-stage1 | 受控最小 | exit 0 + `N/N modules imported`（判据：分子=分母＝导入闭合；r15 时点 359/359） |
| 运行后 | postflight-freeze-revalidate | 受控最小 | exit 0：绑定零漂移；postflight-hashes.txt 生成 |
| 汇总 | verify_matrix.py | 受控最小 | 20 块全部 ok → exit 0 |

## 5. 交叉核验清单（reviewer 独立复算，详见 [cross-check.md](cross-check.md)）

复核人**须独立完成**（不得只采信申请方数字）：

1. 快照哈希逐字节复算 + 血缘 r13→r12→…→i0a5 逐级核验（含 i1-r1 历史字节与 freeze-manifest 条目一致性）；
2. r13 绑定面**逐文件** sha256 复算（implementation/tests/docs/validator），并核对「绑定清单」与"本轮实际改动的消费者"是否一致（漏绑即发现）；
3. 每个真库块用 `--collect-only` 复核用例数与 JUnit 计数一致（防止"少收集"掩盖失败）；
4. 守卫对抗探针：留出读取/未清单来源/受保护写入/模型 import/非允许网络/Python 子进程继承，逐项复跑拒绝；
5. **write-once 拒绝路径**实测（重跑冻结生成器 / 矩阵 evidence 目录已存在 → 拒绝且非零退出）；
6. **legacy 反证**独立复现：目标库上 `CORPUS_READ_CHAIN=legacy` 与无 schema 库 `new` 均被拒；
7. **同快照不变量**独立复现：并发发布循环下 `hits 非空 ⇒ coverage.counts.published ≥ 1`；
8. **零模型**独立复现：子进程 `import openai` / `OpenAI()` 被拒；
9. 目标 fail-closed 独立复现：DSN 指向非演练库时 `PgStore`/CLI 拒绝（exit 3）；
10. **缺口裁决面**独立复现（r15 新增，详见 cross-check.md X11—X14）：词表外/不可解析缺口键仍被拒；
    无 scope 时缺口不得被判 `out_of_scope`；活动 build 有缺口 ⇒ `coverage.processing=scoped` +
    `gap_regions_present`；`check` 的 `blocking` 计数与发布门判决同源；
11. **文档级拼接语义**（r15 新增，X15）：`fetch_document().text` 不等于源文件字节、不含源文件空行
    分隔，但逐行均逐字出自源文件——即"单元级逐字、非字节还原"。

## 6. 已知口径差异（复核人注意，非缺陷）

- **守卫 env 与受控普通 env 不可互换**：业务/真库块须在守卫 env（i2-verify/i1）下跑；guard 测试须在普通环境单独跑（子进程在已装守卫时拒绝换配置重装）。
- `env -i` 会丢弃宿主注入的 `PYTHONPATH`（含 IDE shim）——这是**去污染**，不是放宽守卫；真库块通过 `CORPUS_I2_DSN` 显式传入目标。
- **legacy 读路径不是"永远可用"**：仅在**不含 corpus schema 的旧库**上允许（未迁移库过渡兜底）；迁移目标上显式请求即拒绝。
- **文档级读取遵循句柄 build**（RM-I28-1 裁定 A）；撤销后文档级返回 `None`，零单元 build 才是 `""`。
- `golden.py` 顺延 I3-5、归档 manifest 顺延 I4、批处理脚本归 I3-5/I5-3（design-review 消费者矩阵）。
- `publication_pg` 与 `repository_pg` 历史计数：I2-2 首轮 15 + I2-3 增 3 = 18（repository_pg）；I2-5 首轮 13 + 复核整改 RM-4/5/6/8 增 4 = 17（publication_pg）。差异为新增用例，非口径变更。
- i0c-r12 仅重绑 `data_coverage.py` 一处类型收窄（pyright）；i0c-r10 仅修正台账测试计数（423→424）。两者均为**字节级修订**，不含行为变更。
- **缺口裁决是 r15 引入的新口径**（架构 §7.3 裁定 RM-FC-0）：`acknowledged` 缺口（如 PDF 空白页）
  允许发布但保持可见，`blocking` 缺口仍拒。复核人不得把「含缺口仍可发布」当作放宽——判据在
  `gaps.DEFAULT_GAP_DISPOSITION`（架构 §7.3 同源表），且 `blocking`/词表外/键不可解析一律拒绝。
- `import-smoke` 的模块计数随新增模块增长（r15 新增 `gaps.py`：358→359）；判据是**导入闭合**
  （分子=分母），不是固定数字——固定数字会迫使复核人改预期凑结果。
- 既有状态（非 r15 引入）：`freezes/validate_i1_freeze.py` 对 i1-r3 的工作区绑定自 I0-C/I2 起已失配；
  本矩阵**只**以 `validate_i0c_freeze.py` 为冻结门。

## 7. 备料自检（申请方演练记录，2026-09-18）

矩阵经申请方以 `M5_REVIEW_EVIDENCE_DIR=<临时目录>` 完整演练一次：

- 前置门 4 项全过（`freeze-validator` / `freeze-hashes` / `target-guard=TARGET_OK i2_sandbox_corpus` / `guard-selfcheck passed=true cases=24`）；
- 行为矩阵 9 块 JUnit 计数全部命中（publication-pg 17、repository-pg 18、authority-pg 8、cli-isolation 5、consumers-pg 19、cli-pg 4、i28-i24-probes 6、i1-business-guard-env 188、guard-tests-normal-env 19），**零 failure / 零 error / 零 skip**；
- 静态 4 块 exit=0；运行后零漂移门通过；`verify_matrix.py` **18 块 MATRIX OK**、脚本总退出码 0；
- 装置自证：`verify_matrix.py --self-test` → `SELFTEST_OK`（篡改副本被判 2 项 MISS：伪造退出码 + 改 JUnit 计数）；
- write-once 拒绝路径实测：重跑矩阵 `exit=2`；重发冻结生成器 `exit=1`；
- 交叉核验抽查命令（X4 留出读取 / X6 legacy 双向 fail-closed / X8 零模型子进程 / X9 目标 fail-closed）逐条实跑命中预期。

演练证据在临时目录、**已删除**，不构成证据也不替代独立复核；正式复核一律使用默认 `evidence/` 落盘。

**v2 修订后的二次演练（申请方，2026-09-18）**：`M5_REVIEW_EVIDENCE_DIR=/tmp/m5-drill-1` 完整跑一次，
19 块中 18 块与预期一致、1 项 MISS——`import-smoke-stage1: 日志未命中 '358/358'`（实际 359/359，
因 r15 新增 `gaps.py`）。该 MISS 属**备料预期过时**而非实现缺陷：据此把 import-smoke 判据改为
「导入闭合」正则、把 r15 锚点与两个链级块并入矩阵（本 v2），**未修改任何既有块的计数期望**
（六族计数 17/18/8/5/19/4、i28-i24 探针 6、i1 业务 188、guard 19 全部保持）。二次演练证据同样在临时
目录、已删除。历史 MISS 与处置一并登记在 §10。

## 8. 发现记录模板（reviewer 填写）

| ID | 严重度(P1/P2/P3) | 定位 file:line | 复现命令+最小输入 | 预期 | 实际 | 对 M5 的影响 |
|---|---|---|---|---|---|---|
| | | | | | | |

## 9. 复核纪律与判定输出

复核人必须：
- 全新会话执行；`run_matrix.sh` 逐块实跑并保留 `evidence/` 原始输出、退出码、环境记录；预期不符 → 最小复现 → 发现记录。
- 按 §3 清单逐项给出证据引用；完成 §5 交叉核验（记录命令与输出）。
- 报告落本目录 `review.md`（若另建目录须回告路径）。

复核人不得：
- 修改 `freezes/`、`plugins/`、`tests/`、历史审计目录、总台账（M5 裁决由 U 签认后回填）。
- 访问留出正文、触碰生产库/`apodex`/`i0b2_verify_*`、调用业务模型。
- 以「脚本退出码 0」单独作为 M5 放行依据——退出码只表示矩阵与预期一致。

判定结论只有两种：**M5 放行** / **M5 阻断（列最小收口项）**；部分通过不是结论。
放行后由 U 在总台账签认 M5；I3 启动仍另需 I3-2（预期与评分器冻结）等阶段前置，本复核不代替。

复核报告的**首段必须**写明实际执行者及其独立性状态（是否满足本节「全新会话」要求）。
若 U 显式指令由制备方会话代执行，报告中必须显著标注该偏差，并由 U 在签认时明确接受；
报告不得以「脚本退出码 0」或「制备方演练通过」替代独立执行。

## 10. 包修订记录（申请方）

| 版本 | 日期 | 变更 | 原因 |
|---|---|---|---|
| v1 | 2026-09-18 | 初版：锚点 i0c-r13，18 块矩阵 | I2-6 完成后备料 |
| v2 | 2026-09-18 | 锚点改为 i0c-r15；`freeze-hashes` 纳入 r14/r15；新增 `i2-fullchain-probes`（12）与 `i2-gap-dispositions`（13）两块；`import-smoke` 判据由固定数字改为导入闭合正则；`I2_CHANGED_FILES` 增 `gaps.py`/`clean.py`/缺口测试；§5 增 X11—X15 | **I2 全链路复核整改（RM-FC-0～8）变更了 engine/clean/cli/read_pg 的实现字节**并新增 `gaps.py`，v1 的 r13 锚点已不是当前修订；二次演练暴露 import-smoke 预期过时；RM-FC-8 要求把链级回路与缺口契约并入放行前置 |

v1/v2 均为备料，不构成复核结论；历史 v1 的演练记录（§7 前段）保留不改写。
