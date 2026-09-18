# M5 独立复核报告（2026-09-18）

| 项 | 内容 |
| -- | -- |
| 状态 | **技术面：M5 放行（放行条件逐项满足、矩阵 20 块全绿、X1—X15 全部符合预期）；程序面：独立性偏差已显著登记，须由 U 显式接受** |
| 日期 | 2026-09-18 |
| 复核对象 | **i0c-r16**（复核包 v2）+ 其绑定链：实现/测试/文档 = **i0c-r15**，包 = **i0c-r16**；父链 r16→r15→r14→r13→r12→…→i1-r4→i1-r3→i1-r1→i0a5(M1) |
| 报告冻结修订 | **i0c-r17**（本报告 + 矩阵证据 + 交叉核验原始输出 + F1 修复后的测试字节同版绑定；`validate_i0c_freeze.py` exit 0） |
| 裁决依据 | [tasks.md §2 M5 行](../../../../../docs/plan/corpus-ingestion-rebuild-tasks.md)、[本包 README §3 放行条件清单](README.md)、[架构 §8.1/§12.2](../../../../../docs/plan/corpus-ingestion-rebuild-architecture.md) |
| 执行证据 | [evidence/](evidence/)（矩阵 20 块原始产物，write-once）、[evidence-postfix/recheck.txt](evidence-postfix/recheck.txt)（F1 修复后复验）、[cross-check-evidence.txt](cross-check-evidence.txt)（X1—X15 逐条命令与输出）、[evidence-aborted-r15-pregate/](evidence-aborted-r15-pregate/)（首次调用被前置门拦下的原始产物） |
| 执行纪律 | 只对 `i2_sandbox_corpus` 运行；零模型；不读留出正文；未触碰生产库/`apodex`/`i0b2_verify_*`；未修改 `freezes/`、`plugins/`、历史审计目录（修复项 F1 仅改本轮新增的测试文件，见 §6） |
| 判定输出 | §9 |

## 0. 独立性声明（**必读，先于结论**）

- **实际执行者 = 本会话**，即 I0—I2 的制备方（含 I2 全链路复核整改 RM-FC-0～8）。
  **不满足**本包 §9 对复核人「全新会话、未参与 I0—I2 制备」的要求。执行方按 U 于
  2026-09-18 的明确指令（「独立复核 + U 签认」）代执行，并在此显著登记该偏差。
- **偏差的缓解**（不消除偏差，只说明结论不是自述）：
  1. 全部结论建立在**可复现命令 + 落盘原始产物**上（§7 复现；`evidence/` write-once）；
  2. 矩阵自带三重对抗装置：前置门（冻结/目标/守卫自检）失败即停、**绑定零漂移门**、
     **装置自证**（X10：篡改副本被判 2 项 MISS）；
  3. 复核过程自身**发现并登记 2 项缺陷**（F1 测试顺序依赖假红、F2 备料包锚点过时），
     且 F2 是**前置门主动拦下**的——说明复核不是走过场；
  4. 结论中的「实测」与「阅读/推理」按 M8 分离标注。
- **因此**：本报告的**技术判定**可用于 M5 裁决；但「独立复核」这一**程序要件并未真正满足**。
  若 U 不接受该偏差，M5 应回到 `not_declared`，另派全新会话复核人重做（重跑成本很低：
  `bash run_matrix.sh` + X1—X15，约 5 分钟，证据目录需另建）。

## 1. 结论

**M5 放行**（技术面）：放行条件逐项满足——M3/M4 在冻结链上可追溯、I2 全部交付、
旧消费者已在隔离目标接线、`publication_pg`/`authority`/`cli_isolation` 真库实测含租约接管、
**核心 PG 门零 skip**、矩阵 20/20 与预期一致、交叉核验 X1—X15 全部符合预期。

放行的**前置条件（程序）**：U 在总台账签认时**明确接受 §0 的独立性偏差**；否则本报告降级为
「制备方技术核验」，M5 维持 `not_declared`。

不影响本结论的已登记缺陷：F1（测试卫生，已修并复验）、F2（备料包锚点过时，已按 §10 重发）、
F3（i1 冻结校验器对工作区失配，既有状态，M5 矩阵不依赖）。

## 2. 复核范围与方法

**范围**：唯一裁决项 = M5 是否放行（README §1）。不含 I3—I5、R2/模型预算、留出正文、性能改造。

**方法**：
1. **矩阵实跑**（`run_matrix.sh`，三段式：前置门 → 行为/静态块 → 运行后零漂移门 + `verify_matrix.py` 精确核对 JUnit 计数），落默认 `evidence/`；
2. **交叉核验 X1—X15**（README §5 / cross-check.md）逐条独立执行并留痕，其中 X11—X15 为本轮针对
   **i0c-r15 的缺口裁决面**新增的对抗核验；
3. **缺陷驱动**：任何与预期不符 → 最小复现 → 发现登记（§6）→ 定级与 M5 影响判定。

**数据副作用声明**：真库块只操作 `i2_sandbox_corpus` 的 corpus schema（既有测试族自带 TRUNCATE 纪律
与 `current_database`/非生产实例双校验）；前置门 `target-guard` 独立复验目标。

## 3. 本轮执行结果

矩阵（`evidence/index.txt`、`evidence/matrix-summary.json`）：

| 阶段 | 块 | 结果 |
|---|---|---|
| 前置门 | freeze-validator / freeze-hashes / target-guard / guard-selfcheck | exit 0 / exit 0 / `TARGET_OK i2_sandbox_corpus` / `passed=true cases=24` |
| 行为矩阵 | publication-pg | **17 / 0 / 0 / 0** |
| 行为矩阵 | repository-pg | **18 / 0 / 0 / 0** |
| 行为矩阵 | authority-pg | **8 / 0 / 0 / 0** |
| 行为矩阵 | cli-isolation | **5 / 0 / 0 / 0** |
| 行为矩阵 | consumers-pg | **19 / 0 / 0 / 0** |
| 行为矩阵 | cli-pg | **4 / 0 / 0 / 0** |
| 行为矩阵 | i28-i24-probes | **6 / 0 / 0 / 0** |
| 行为矩阵 | **i2-fullchain-probes** | **12 / 0 / 0 / 0** |
| 行为矩阵 | **i2-gap-dispositions** | **13 / 0 / 0 / 0** |
| 行为矩阵 | i1-business-guard-env | **188 / 0 / 0 / 0** |
| 行为矩阵 | guard-tests-normal-env | **19 / 0 / 0 / 0** |
| 静态 | ruff-check / ruff-format-check / pyright-i2-scope / import-smoke-stage1 | `All checks passed` / `already formatted` / `0 errors` / `359/359`（导入闭合） |
| 运行后 | postflight-freeze-revalidate | exit 0（绑定零漂移） |
| 汇总 | verify_matrix.py | **MATRIX OK: 20 块全部与预期一致**（脚本 exit 0） |

**全矩阵零 failure / 零 error / 零 skip**（含全部 PG 门）；`verify_matrix.py` 计数为 JUnit XML 精确值。

## 4. 放行条件逐项核对（README §3）

| 项 | 判定 | 证据 |
|---|---|---|
| A1 冻结链 exit 0、血缘至 i0a5、design-review 签认 | ✅ | X1（validator 打印 lineage `i0c-r16->…->i0a5(M1) ok`，exit 0） |
| A2 锚点哈希命中、绑定面与实际字节一致 | ✅ | X1（r11—r16 哈希）+ X2（r16 自绑定 zero mismatch；r15 的 validator 一项由 r16 重绑，按 latest-revision-wins 由 X1 合并核验通过） |
| A3 上游门 M3/M4 在链上仍可追溯 | ✅ | X1 血缘（i0c-r1 的父 = i1-r4、design-review 签认）+ i1 业务套件 188 无回归 |
| B1 守卫自检 24/24 `passed=true` | ✅ | `evidence/guard-selfcheck.json`（24 case 全 passed，含模型 import/网络/留出读/受保护写/删改/未知来源/子进程继承/exec·system·posix_spawn/换配置重装拒绝/未知配置字段拒绝） |
| B2 守卫 env 下行为矩阵通过 | ✅ | §3（`env -i` + `guard_pytest`，守卫先于收集装载） |
| B3 guard 测试在受控普通环境独立通过 | ✅ | guard-tests-normal-env 19/0/0/0 |
| B4 零模型（真实子进程，非声明） | ✅ | X8：子进程 `import openai` → `child rc=1`、错误含 openai；守卫自检含 5 条模型相关反例 |
| B5 未读留出、未触碰生产库 | ✅ | X4（两份留出读取均 `REFUSED`）+ `target-guard` + `CORPUS_DSN` 投毒（守卫配置） |
| C1—C5 六族与消费者块 | ✅ | §3（17/18/8/5/19/4，全部零 skip） |
| C6 I2-8/I2-4 轮复核探针 6 | ✅ | 6/0/0/0 |
| C6b **链级契约面**（本轮纳管） | ✅ | i2-fullchain-probes 12/0/0/0 + i2-gap-dispositions 13/0/0/0（write-once 回路文件未被修改，哈希见 `evidence/postflight-hashes.txt`） |
| C7 i1 守卫业务套件 188 | ✅ | 188/0/0/0 |
| C8 守卫测试 19 | ✅ | 19/0/0/0 |
| D1 legacy 在迁移目标被拒 | ✅ | X6（`REFUSED StoreError 拒绝：目标库已承载新链（corpus schema），legacy 读路径不可达…`） |
| D2 无 schema 库请求 `new` 被拒 | ✅ | X6 反向（`…不得回退旧 blocks 冒充新链`） |
| D3 旧句柄不静默换正文 | ✅ | cli-isolation 5 项含旧句柄拒绝；authority 族含跨 build/坏/旧句柄 |
| D4 消费者读出的 build 与活动指针一致 | ✅ | consumers-pg/authority-pg 断言 `build_id`/活动范围（非"工具可调用"） |

## 5. 交叉核验 X1—X15 执行结果

| # | 项目 | 实际输出（关键行） | 判定 |
|---|---|---|---|
| X1 | 快照哈希与血缘 | r11 `79ad48a1…`、r12 `66c8080c…`、r13 `10af5ce6…`、r14 `4e1180a6…`、r15 `c88cfa88…`、r16 `76483697…`；validator exit 0 | ✅ |
| X2 | 绑定面逐文件复算 | r16 `MISMATCH: none`；r15 仅 `freeze_validator` 一项被 r16 重绑（latest-revision-wins，X1 合并核验通过）；**未发现漏绑**（r15 未绑的 `service.py`/`plugins/tools/*` 本轮确未改动，与 `git status` 对照一致） | ✅ |
| X3 | 用例数与 JUnit 一致 | `--collect-only` = **102** = 17+18+8+5+19+4+6+12+13，与 `evidence/*.xml` 之和一致；i1 块 188、guard 块 19 各自一致 | ✅ |
| X4 | 守卫对抗（留出/未清单来源/受保护写/模型/网络/子进程） | 两份留出 `REFUSED OSError … 禁止访问隔离路径`；自检 24 case 全 passed | ✅ |
| X5 | write-once 拒绝路径 | 重跑 i0c-r15 生成器 → `I0C-R15 FREEZE FAILED: 已存在（write-once）` exit 1；重跑矩阵（evidence 已存在）→ `拒绝：evidence 目录已存在` exit 2 | ✅ |
| X6 | legacy / 无 schema 双向 fail-closed | 两向均 `REFUSED`（见 D1/D2） | ✅ |
| X7 | 同快照不变量（并发发布 40 轮） | `1 passed` | ✅ |
| X8 | 零模型子进程 | `child rc= 1`、`contains openai: True` | ✅ |
| X9 | 目标 fail-closed | DSN 指向同容器非演练库 → `拒绝：current_database='postgres' ≠ 'i2_sandbox_corpus'`，`exit=3` | ✅ |
| X10 | 装置自证 | `SELFTEST_OK: 篡改副本被判 2 项 MISS`（伪造退出码 + 改 JUnit 计数） | ✅ |
| X11 | 缺口裁决不可绕过 | 缺 location / 词表外码 / 空码 → 均 `blocking=True`；仅合法 `empty_page:page:4:extra` → `acknowledged` | ✅ |
| X12 | 无 scope 时不得判 `out_of_scope` | 页/元素坐标在 scope 下仍 `['blocking','blocking']`；`char:600-` 在 `char:0-200` 外才 `out_of_scope` | ✅ |
| X13 | 活动 build 有缺口 ⇒ coverage `scoped` | 缺口 PDF 用例单独运行 `1 passed`（`processing=scoped`、`reason_codes=gap_regions_present`、`counts.published_with_gaps=1`） | ✅（修复后） |
| X14 | `check`/`plan` 同口径 | `check` 被拒 ⇔ `blocking ≥ 1`；`plan` 预检阻断键集合 == `check` 的 `gaps` 键集合 | ✅（修复后） |
| X15 | 文档级拼接语义（单元级逐字、非字节还原） | `1 passed` | ✅（修复后） |

## 6. 发现

| ID | 严重度 | 定位 | 复现（最小） | 预期 | 实际 | 对 M5 的影响 |
|---|---|---|---|---|---|---|
| **F1** | **P2（测试卫生，已修）** | `tests/test_corpus_gap_dispositions.py::TestI2GapCli` （修复前 `json.loads(capsys.readouterr().out)`） | `python -m pytest --noconftest -c /dev/null -q tests/test_corpus_gap_dispositions.py::TestI2GapCli::test_acknowledged_gap_publishes_and_coverage_is_scoped` | `1 passed` | `JSONDecodeError: Expecting value: line 1 column 1` —— pymupdf 在进程首次调用时向 stdout 打一次性提示行，使该用例**只在整文件运行（提示行已被更早的用例消费）时通过**，单独运行或被 `-k` 选中即**假红**（顺序依赖） | **无**（不影响 M5 判据；产品行为由 X11—X13 与六族独立支撑）。但属**假阴性风险**：任何按用例选择运行的门都会误报。已修：新增 `_cli_json()` 从首个 `{` 解析；修复后逐用例单独运行 + 整文件 13 + 组合面 96 全绿（[evidence-postfix/recheck.txt](evidence-postfix/recheck.txt)）。**登记偏差**：矩阵 `i2-gap-dispositions` 块（13/0/0/0）执行于修复前字节，修复仅改 stdout 解析、用例数与断言不变，修复后已重跑留证；该文件随 r17 重绑 |
| **F2** | **P3（备料缺陷，已修）** | M5 复核包 v1（锚点 i0c-r13、import-smoke 固定 `358/358`） | `bash run_matrix.sh`（v2 包字节未冻结时） | 前置门放行 | 前置门 `freeze-validator exit=1`（`review_package` 4 文件哈希失配）——**绑定零漂移门按设计生效**；另有 1 项 MISS：`import-smoke-stage1: 日志未命中 '358/358'`（实际 359/359，r15 新增 `gaps.py`） | **无**（装置正确拦下过时备料）。处置：包 v2（锚点改绑 r15、新增两个链级块、import-smoke 判据改「导入闭合」正则、**未放宽任何既有块计数**）+ i0c-r16 重绑；被拦产物保留在 `evidence-aborted-r15-pregate/` |
| **F3** | P3（既有状态，非本轮引入） | `freezes/validate_i1_freeze.py` | `.venv/bin/python …/validate_i1_freeze.py` | exit 0 | `13 error(s)`（i1-r3 绑定对工作区失配，含 I0-C/I2 期改动的 `chunk.py`/`repository.py`/测试等） | **无**（M5 矩阵只以 `validate_i0c_freeze.py` 为冻结门；i1 链的血缘由 i0c-r1 的父锚点独立核验）。建议 I3 前另立修订理顺 |

**未发现**其他偏离：矩阵预期零放宽，PG 门零 skip，无"少收集掩盖失败"（X3），
无 write-once 覆盖（X5），无装置无区分力（X10）。

## 7. 结论与放行

1. **M5 放行（技术面）**：README §3 A1—A3、B1—B5、C1—C8、D1—D4 逐项满足；矩阵 20 块全绿且零 skip；
   X1—X15 全部符合预期。
2. **程序前置**：U 须在总台账签认时明确接受 §0 的独立性偏差；否则 M5 维持 `not_declared`，
   另派全新会话复核人重做（材料即本目录，v2 包已可直接重跑）。
3. 放行**不代替** I3 前置：I3-2（预期与评分器冻结）等仍需另做（README §1）。
4. F1/F2 已在本轮闭环并留证；F3 建议随 I3 前置修订处理。

## 8. 未覆盖（如实声明，不阻断 M5）

继承 README §3-E：I3 三类 E2E 与指标、I3-5 旧检索 golden（`golden.py` carry-over）、I3-7 最终重验、
批处理 eval 脚本归属、旧引用归档 manifest（顺延 I4）、真实模型调用与 R2 语义链、独立留出验收、
性能标定（耗时/索引大小/P95、连接池/分区/LIMIT 下推）。

另：本报告未做**业务正确性**判断（M5 只裁决 PG 门与接线完成度）。

## 9. 复现命令

```bash
export CORPUS_I2_DSN="postgresql://postgres:***@127.0.0.1:543/i2_sandbox_corpus"
# ① 矩阵（默认 evidence/ 已存在时拒绝重跑；重做需另建目录并保留本目录字节）
env -u PYTHONPATH bash .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/run_matrix.sh
# ② 汇总核对（可重复执行）
.venv/bin/python .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/verify_matrix.py \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/evidence
.venv/bin/python .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/verify_matrix.py --self-test \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/evidence
# ③ 交叉核验 X1—X15：逐条命令见 cross-check.md；本轮实际输出见 cross-check-evidence.txt
# ④ F1 修复后复验
.venv/bin/python -m pytest --noconftest -c /dev/null -p no:cacheprovider -q \
  tests/test_corpus_gap_dispositions.py
```

## 10. 证据边界

- **实测**：§3 矩阵全部块（JUnit 计数为 XML 精确值）、§5 X1—X15、F1/F2 的最小复现。
- **阅读/推理**：D3/D4 的映射说明、F3 的成因（i1 校验器设计对工作区核对）、§8 未覆盖项。
- 矩阵退出码只表示「矩阵与预期一致」，不构成 M5 裁决；本报告的放行判定另有 §4/§6 的逐项推理，
  并按 §0 标注独立性偏差。
- 历史字节不改写：v1 演练记录（README §7 前段）、首次调用被拦下的产物
  （`evidence-aborted-r15-pregate/`）均原样保留。

## 11. U 签认栏

| 项 | 内容 |
|---|---|
| 技术判定 | M5 放行（见 §7.1） |
| 程序偏差 | 复核由 I0—I2 制备方会话代执行，不满足「全新会话」（§0） |
| U 签认选项 | **A. 接受偏差并签认 M5 放行**（在总台账 M5 行落签认日期与依据）／**B. 不接受，M5 维持 `not_declared`，另派全新会话复核人重做**（材料已就绪，重跑约 5 分钟） |
| 签认记录 | 见总台账 [M5 独立复核与签认](../../../../../docs/plan/claims-market-closed-loop-plan.md#m5-review-signoff)（回填处） |
