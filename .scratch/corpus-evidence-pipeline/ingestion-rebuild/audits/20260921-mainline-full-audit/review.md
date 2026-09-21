# 解耦主线全量审核测试（review，write-once）

- 时点：2026-09-21
- HEAD：`fc39905`（`chore(audits): 新增 F1 负例金标无关探针与只读重放脚本`），工作树仅 `MEMORY.md` 脏
- 范围：`.scratch/corpus-retrieval-decoupling/spec.md` 主线（票 00–05 + F1–F4 + 冻结链 r42/r43/r4n/r4p/r4q/r4r/r4s + i1-r5/i1-r6）
- 性质：**只读复核**。未改任何代码 / 冻结链 / 金标 / 语料；未写 PG（仅读 `i2_sandbox_corpus` 计数与跑自建自清测例）。
- 结论速览：**代码与行为面全绿；冻结链 3 门中 i0c 转红（2 errors）；测量语料仍为空。**

---

## 一、门矩阵

| # | 门 | 命令 | 实测 | 判定 |
|---|---|---|---|---|
| 1 | 语料族回归（无 DSN） | `uv run pytest tests/test_corpus_*.py -q` | **757 passed / 12 skipped**（44.01s） | ✅ 绿 |
| 2 | Ruff（CI 范围） | `uv run ruff check frontier_agent/ apodex/ benchmarks/ workflows/ plugins/ deploy/ tools/ scripts/` | `All checks passed!`，exit 0 | ✅ 绿 |
| 3 | Pyright | `uv run pyright` | `19 errors, 0 warnings` | ✅ 与基线一致（缺 `sqlalchemy`/`argon2`） |
| 4 | 导入冒烟 stage 1 | `uv run python tools/import_smoke.py --stage 1` | `[framework] 365/365` | ✅ 绿（基线 363，+2 模块） |
| 5 | 导入冒烟 stage 2 | `uv run python tools/import_smoke.py --stage 2` | `[eval] 414/414` | ✅ 绿（基线 412，+2 模块） |
| 6 | 符号闭包 | `uv run python tools/check_symbols.py` | `OK: 0 missing-symbol import(s) across 464 file(s)` | ✅ 绿（基线 462，+2 文件） |
| 7 | i0c 冻结门 | `uv run python …/freezes/validate_i0c_freeze.py` | `I0C FREEZE CHECK FAILED: 2 error(s)`，**exit 1** | ❌ **红** |
| 8 | i1 冻结门 | `uv run python …/freezes/validate_i1_freeze.py` | `freeze chain verified … i1-r5 supersession -> i1-r6`，exit 0 | ✅ 绿 |
| 9 | I3-2 完成门 | `uv run python …/freezes/validate_i3_2_completion.py` | `"i3_2_complete": true`, `failed_items: []`，exit 0 | ✅ 绿 |

- 判定纪律：退码用「重定向到日志再取 `$?`」，不用 `cmd | tail` 取码。
- 12 条 skip 全部为 `CORPUS_I2_DSN 未设置（非 I2 演练环境）`（PG 门在无 DSN 下按设计跳过，非失败）。
- 增量口径：`import_smoke` +2 / `check_symbols` +2 文件 = 本轮主线新增 `plugins/corpus/preparation/cross_boundary.py`（F4，r4q 入链）与
  `plugins/corpus/preparation/negative_query.py`（F1，**未入链**）。

### i0c 红的确切内容

```
I0C FREEZE CHECK FAILED: i0c-current.binding[chain_rebind_implementation]: plugins/corpus/service.py 哈希失配或缺失
I0C FREEZE CHECK FAILED: i0c-current.binding[implementation]: plugins/tools/corpus_search.py 哈希失配或缺失
i0c freeze verification FAILED: 2 error(s)
```

（另有 3 条 `NOTE（非失败）: r29 归档不是真实 pre-r29 字节`，为既有说明，非本轮引入。）

---

## 二、PG 行为矩阵（守卫 env，`CORPUS_I2_DSN=…@127.0.0.1:543/i2_sandbox_corpus`）

| 块 | 集合 | 结果 |
|---|---|---|
| publication-pg | `tests/test_corpus_preparation_publication_pg.py` | 17 passed |
| repository-pg | `tests/test_corpus_preparation_repository_pg.py` | 18 passed |
| authority-pg | `tests/test_corpus_authority_pg.py` | 8 passed |
| consumers-pg | `tests/test_corpus_consumers_pg.py` | **20 passed**（M5 MISS① 已由 r4s 修复） |
| cli-pg | `tests/test_corpus_cli_pg.py` | 4 passed |
| cli-isolation | `tests/test_corpus_cli_isolation.py`（i2-verify 守卫） | 5 passed |
| i28-i24-probes | `audits/20260918-i2-8-i2-4-review/test_review_probes.py` | 6 passed |
| i2-fullchain-probes | `audits/20260918-i2-fullchain-review/test_fullchain_probes.py` | 12 passed |
| i2-gap-dispositions | `tests/test_corpus_gap_dispositions.py`（i2-verify 守卫） | 13 passed |
| i1-business-guard-env | `BUSINESS_I1` 11 文件（i1 守卫） | **202 passed**（M5 MISS② 已由 r4s 拆 dev-lane 修复） |
| guard-tests-normal-env | `tests/test_corpus_preparation_guard.py` | 19 passed |
| dev_lane（i3-e2e 守卫） | `tests/test_corpus_dev_lane.py` | 9 passed |

⇒ 行为矩阵**全绿**，计数与 M5 复核（`audits/20260922-m5-rereview`）逐块一致（consumers-pg 19→20 即 MISS① 修复后口径）。

### 口径陷阱（新记录，避免假红）

`tests/test_corpus_cli_isolation.py::test_subprocess_model_client_import_refused` 在**普通 `uv run pytest`** 下会 **fail**
（继承环境允许子进程 `import openai`）。该测例**必须**在 `env -i … CORPUS_GUARD_PHASE=i2-verify` 的守卫环境里跑，方为 5 passed。
⇒ `test_corpus_cli_isolation.py` 不得用普通 pytest 结论判红。此结论与 r4s 记录一致。

---

## 三、关键发现

### F-A1（阻断级）i0c 冻结门转红：B2「暂停态」abstain 代码已提交但未冻结

**根因（机读）**：HEAD 提交 `fc39905` 除审计产物外，**顺带提交了 B2 的产品侧 abstain 代码**：

```
plugins/corpus/service.py          | 71 +      ← _abstain_decision / search_with_coverage 拒检分支
plugins/tools/corpus_search.py     | 26 +      ← ABSTAIN_HINT + coverage["abstain"] 分支
tests/test_corpus_negative_query.py| 119 +     ← 6 条 B2 测例（回归 751→757 即此 6 条）
.trae/documents/b2-abstain-reject-channel.md | 60 +
```

而 B2 按 U 2026-09-21 裁决**不建冻结修订**（"暂停，保留开关默认关"）⇒ 字节入工作树未入链：

| 文件 | 链上绑定 | `fc39905^`（改前）实测 | HEAD（改后）实测 |
|---|---|---|---|
| `plugins/corpus/service.py` | r4q = `0227529c…` | `0227529c…`（一致） | `76536426…`（漂移） |
| `plugins/tools/corpus_search.py` | r11 = `8ff78c11…` | `8ff78c11…`（一致） | `c70e5b9c…`（漂移） |

即：**漂移 100% 由 `fc39905` 引入，与 `fc39905^` 逐字节一致**。

**影响**：
1. `validate_i0c_freeze.py` exit 1 ⇒ 「三门全绿」状态自 `fc39905` 起不再成立（B1 收口时记录的三门全绿是提交前的时点）。
2. M5 复核矩阵 `audits/20260918-m5-review/run_matrix.sh` 的**第一道前置门**即 `validate_i0c_freeze.py` ⇒ 现在整矩阵会 `exit 2` 直接中止，
   **无法产出完整 M5 证据**。
3. 功能面**无回归**：开关 `CORPUS_ABSTAIN_NO_ANSWER` 默认 `off`（且 `read_chain() != "new"` 时亦恒 False），
   非法值 fail-closed；回归 757/12 与行为矩阵全绿，生产路径零扰动。

**处置选项（须 U 裁决，本轮不擅自执行）**：

| 选项 | 动作 | 代价 |
|---|---|---|
| **A（推荐）** | 新建冻结修订（如 `i0c-r4t`）重绑 `service.py` / `corpus_search.py` / `test_corpus_negative_query.py`，不改行为（开关仍默认 off），archive-first + 三门复跑 | 一次冻结成本；把"暂停态代码"如实登记入链 |
| B | 把两文件字节回退到 `fc39905^`（`git show fc39905^:<path>`），B2 代码移出工作树另存 | 需同时回退 `test_corpus_negative_query.py`（回归 757→751）；丢弃已写的 B2 实现 |
| C | 不动，接受 i0c 红 | **不可行**：冻结门红 = 后续任何校准读数不可信，矩阵不可跑 |

### F-A2（阻断级，与上轮同）测量语料仍为空，B8 未解

`i2_sandbox_corpus` @ `127.0.0.1:543` 实测：

```
builds = 1   (build_id ccededc2… / source cbf58d57… / decision_id=d1 / parse_rev=parse-test …)
units  = 1
chunks = 1
```

即 r4s/consumers-pg 测例残留，**不是** index-4-zhcfg-2 的 8 份 active builds。5432 实例无 `i2_sandbox_corpus` 库。
⇒ F2「band+cell 18/24」、F4「company-008 a-1 转绿」、funnel「S0 77 / S1 66 / S2 60 / S3 59 / S4 50」、F1/F2「负例 0」
**全部不可复现**。任何回归 I3-3 的校准在此之前**无法产出可信同口径数字**，须 U 授权全量重建（重建顺带让 F3 clean 语义生效，可一并解 B3）。

### F-A3 F1 仍未入链（与上轮一致）

`negative_query.py` 已在 `plugins/` 有产品调用点（`service._abstain_decision`，见 F-A1），但：
- 调用点被**默认关闭的开关**挡住 ⇒ 产品侧负例仍 6；
- 模块与 F1 测试**未入冻结链**（F-A1 同因）；
- F1 的 6→0 证据（`audits/20260921-f1-negative/`）来自按金标 `answer_existence == NO_ANSWER` 分支收紧查询的回测脚本，
  与 spec §11「评测量尺不得来自金标」冲突（上轮 B2 已记录，未变）。

---

## 四、与上一轮的差异

| 项 | `20260921-spec-closure-audit`（提交前时点） | 本次（HEAD `fc39905`） |
|---|---|---|
| i0c 冻结门 | exit 0 | **exit 1（2 errors）** ← 因 `fc39905` 提交 B2 字节 |
| i1 冻结门 | exit 1 | exit 0（i1-r6 已收口） |
| 语料族回归 | 751 passed / 12 skipped | 757 passed / 12 skipped（+6 = B2 测例） |
| 导入冒烟 | 363 / 412 | 365 / 414 |
| 符号闭包 | 462 文件 | 464 文件 |
| 工作树 | spec/MEMORY/f1_replay 未收口 | `f1_replay_readonly.py` 仍未跟踪；MEMORY 本轮已整理 |

即：**B1 已闭环，但 B2 的"暂停态落地"把 i0c 门重新打红**（新增 B9，与 B2 同源）。

---

## 五、判定：能否回归 I3-3

**形式前置已满足**：I3-3 的依赖 I3-1（r38，8/8 发布）与 I3-2（本门 `i3_2_complete=true`）均已绿；解耦主线票 00–05 已闭环。

**但当前不具备"回归 I3-3 并产出可信结果"的条件**，三条硬阻塞：

1. **冻结基线是红的**（F-A1）：I3-3 的产物是"每轮配置哈希 + 三类指标"的**可比读数**。基线红 ⇒ 读数不可比，
   且 M5 矩阵前置门直接中止。**必须先处置 B2 字节（选项 A/B）使 i0c 转绿。**
2. **没有可测语料**（F-A2）：I3-3 要求"执行 retrieval_pg + 报告三类指标"，当前 `i2_sandbox_corpus` 只有 1 个测例 build。
   **须 U 授权全量重建 8 份 active builds**（或明确改用哪一批语料）。
3. **达标判据差距未缩小到可过**：M6/逐类三指标门槛 ≥95%（24 题口径 ≈ ≥23/24）与负例 0：

| M6 判据 | 当前最好（历史记录） | 生产默认（已接线） | 门槛 |
|---|---|---|---|
| 逐类三指标（EvidencePass） | 19/24（band+cell，i41，**诊断脚本**）｜18/24（band+cell，当前语料，F2） | **band**（r4n：`search`/`search_with_coverage` → `search_with_coverage_bands` → `_selected_chunk_hits`） | ≥23/24 |
| 伪引用负例 | 0（仅 F1 回测脚本，按金标分支） | **6**（开关默认 off） | 0 |
| 关键引用题 100% | 未达 | 未达 | 100% |
| 旧检索/财务基线不退化 | 未验 | 未验 | 不退化 |

⇒ **即便做完 1、2 两项收口，按现数据回归 I3-3 仍会以「未达标、按边界停止」收口**——解耦主线只把 EvidencePass 侧
抬升（+6 层、产品默认已接 band），**负例（唯一零进展的 M6 硬阻断）在产品侧没有任何变化**。

**建议顺序**：
1. 处置 F-A1（推荐选项 A：`i0c-r4t` 重绑，行为零改动）→ 三门复跑 + 矩阵可跑；
2. U 授权全量重建测量语料（顺带解 B3/F3 重摄入）；
3. 先在重建语料上跑一次**同一次运行内 `off/on` 对照**（探针已就绪：`audits/20260921-f1-goldfree-probe/probe.py`），
   把"产品默认（band+cell）"的真实三指标与负例数钉住；
4. **再做「回归 I3-3」的决定**：若目标是"再跑一轮留失败"，现可做（但读数须等 1+2）；
   若目标是"过 I3-3 → 推进 M6"，则必须先在产品侧解决负例 6→0（B2 重新设计免金标判别器）+ company-003 文档级召回独立议题 + 关键题 100%。

**一句话**：可以回到 I3-3 的**流程**，但现在回去只会得到"又一次未达标"；先补 F-A1（冻结门）＋F-A2（语料）＋负例产品化三项，才值得付 I3-3 的校准成本。

---

## 六、本轮未做 / 边界

- 未运行 M5 全量矩阵 `run_matrix.sh`：其第一道前置门即 i0c（红）⇒ 会 `exit 2` 中止且创建 write-once `evidence/`。
  改以**逐块等价复跑**替代（第二节，计数与 M5 记录逐块一致）。
- 未改动任何代码 / 冻结链 / 金标 / 守卫 / 语料；未 commit。
- 未做 I3-3/I3-4/I3-5/I3-7 的真实校准或非回归（无可用语料，且判据未冻结）。
- 未对 M6/M5 做放行判定（放行只能由独立复核 + U 具名签认给出）。
