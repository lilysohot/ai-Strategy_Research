# M4 独立复核包（I1 内存链 → M4 放行裁决）

| 项 | 内容 |
|---|---|
| 日期 | 2026-09-16 |
| 性质 | **申请方备料，非复核结论**。本包只定义复核对象、放行条件、命令矩阵与预期结果；复核执行与 M4 裁决由独立复核人完成，最终放行由 U 在总台账签认 |
| 复核对象 | I1 内存链当前候选快照 [freezes/i1-r3.json](../../freezes/i1-r3.json)（直接父快照 = 已恢复原始字节的 i1-r1；i1-r2 仅作历史审计记录，不作为当前候选血缘）|
| 申请方自证留痕 | [verification-matrix.txt](../20260916-i1-remediation/verification-matrix.txt)、i1-r3.verification_matrix、总台账 2026-09-16 各回填条目——均为申请方留存结果，**不冒充本轮独立执行** |
| 复核人 | 待定（应使用全新会话）|

## 1. 本次复核裁决什么

唯一裁决项：**M4 是否放行**。通过条件（任务清单 §2 M4 行原文）：

> M1 与 I1 全部完成；admission/fidelity/mapping 及接收/编排恢复测试 + 先行零模型守卫；不触真实 PG、不访问留出。

不在本轮裁决范围（复核人不得要求补做，也不得宣称已通过）：M3/I0-C（未启动）、I2 全部（真实 PG DDL/repository/FTS/CLI/消费者接线/publication_pg）、I3 格式门与指标、人工 source-gold 独立比对、R2 语义任务。

## 2. 复核对象与版本锚点

| 锚点 | 值 | 核验方式 |
|---|---|---|
| i1-r3 快照 | `f22525c3957f8d09890600eb1df7e3cab3a6fce61f79b196c6067cbd9f39dd59` | sha256sum + validate_i1_freeze.py |
| i1-r1（已恢复原始字节）| `d474bd6d566e8cf5d72d0531de55fe918833ec49185f0b31322f97d603f85957` | 同上；且须与可信副本 [i1-r1-original.json](../20260916-i1-remediation/i1-r1-original.json) 逐字节一致（cmp exit 0）|
| i1-r2（历史审计记录，字节不改）| `3d27a690519cb006b319da6fbc59dac2e81199b77b2b650983f700ea2f1f71e2` | sha256sum；其 parent 指向曾被补丁的 r1（72e5fba4…）属已登记历史，不作为当前候选血缘 |
| freeze-manifest.json | `4e81c886…`（追加式索引，哈希随追加变化，仅 informational）| validate_i1_freeze.py 校验条目↔文件 |
| 守卫 guards/i1.json | `45330fad…`（绑定于 r3.binding.configs）| validate_i1_freeze.py |
| r3 绑定面 | **37 项绑定**（实现 15 文件 + 测试 12 文件 + 夹具 3 件 + 配置 3 件 + 现行审计探针 4 文件，全 SHA-256）| validate_i1_freeze.py 全量核验 |

血缘语义：r3.parent_snapshot = i1-r1 @ `d474…`（恢复后字节）；r1 本身父快照 i0a5（M1 快照 71aa61af…，见总台账）。

## 3. M4 放行条件核对清单（复核人逐项记录证据）

**A 前置与冻结链**
- A1 `validate_i1_freeze.py` 通过（索引、父哈希、r3 全部绑定）
- A2 r1 == 可信副本（cmp exit 0）；r2 字节未改；r3 哈希与索引一致
- A3 i1.json：phase=i1、network.mode=deny_all、allowed_targets=[]、3 份留出在 forbidden_roots、6 份开发材料在 allowed_source_paths

**B 守卫先行（I1-8 绑定 + 零模型契约）**
- B1 guard selfcheck 通过（合成反例，write-once 落 evidence/guard-selfcheck.json）
- B2 守卫 env（env -i + guard_pytest，守卫先于测试收集装载）下 §4 全部行为矩阵通过
- B3 guard 测试 19 项在普通环境独立通过（守卫自装子进程语义，不与守卫 env 混跑）
- B4 复核全程未触真实 PG/公网/模型（守卫 env 结构性保证 + 复核人自律）

**C M4 必需测试族（架构 §12.2 九族中 M4 范围；括号内为当前每文件用例数，总计 186）**
- C1 admission：表驱动 52（未决不发布/冲突/取代链/异源哈希不继承/十问十答 mixed 不阻断）
- C2 fidelity（合成不变量）：readers 14 + remediation 15 + counterexamples 3 + fixtures 15（空页/纯图页/大图缺口/嵌套表/cell 图/有线表格零丢失/实录标题冲突/条件句跨行/char_span 保真）
- C3 mapping：clean 13（映射 roundtrip/verify_clean_region）+ chunk 14（context_refs 引用式/覆盖不变式/超长复核）
- C4 接收/编排恢复：contract 17 + source 18 + engine 13 + release_gate 12（幂等/FAILED 恢复/取消生命周期/发布所有权门/检查点完整载荷/暂存与归档路径边界/scope 非法与部分重叠拒绝）
- C5 行为探针（独立于业务套件）：完整链路 11（guard env）；I1-9 验收 3 项为历史口径——2 项通过 + 1 项不适用于当前候选的历史断言（预期恰失败 1 个固定节点，见 §6）；旧探针 20 + 边界 11 = 31；R1—R5 边界收口 9
- C6 业务套件 11 文件在守卫 env 全绿：186 passed

**D 已知未覆盖（如实声明；不阻断 M4，但复核报告不得宣称已通过）**
- fidelity 人工 source-gold 独立比对（unverified）、格式真实样本（I3 格式门）
- authority / publication_pg / cli_isolation（CLI 全链真 Interface）→ I2 门
- coverage / retrieval_pg / legacy_regression → I2/I3 门
- INDEX_REV_V1=index-1 为 I1 无索引阶段占位

## 4. 命令矩阵与预期结果

执行方式（仓库根目录）：

```bash
bash .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-m4-review/run_matrix.sh
```

**执行模型（三段式）**：

1. **前置门（失败即停，exit 2）**：冻结验证器 → 快照哈希 + r1 可信副本逐字节比较 → 守卫自检。任一失败不进入行为矩阵。
2. **行为矩阵 + 静态检查（失败继续收集证据）**：pytest 块全部产出 JUnit XML（守卫 env 块在 env -i 下先装载守卫再收集；受控普通环境同样最小化 env -i、禁用插件自动加载与 conftest——普通环境 ≠ 允许连接 PG 或模型）；随后运行后门重跑冻结验证器（**绑定零漂移检查**，失败 exit 2）并留痕验证器/脚本/探针/uv.lock 哈希与 pymupdf、python-docx 版本。
3. **汇总核对（verify_matrix.py）**：按 JUnit XML 精确核对每块 tests/failures/errors/skipped 计数（历史探针块额外核对失败节点白名单精确匹配），日志块核对内容命中，自检按 JSON 结构核对（passed=true 且 24/24）；产出机器可读 `evidence/matrix-summary.json`。

**退出码语义**：0 = 矩阵与预期一致；1 = 存在 MISS（发现候选）；2 = 前置门或运行后门失败。**退出码只表示「矩阵与预期一致」，不构成 M4 裁决**；预期不符按 §8 记录，不得修改预期凑结果。

| 阶段 | 块 | 环境 | 预期 |
|---|---|---|---|
| 前置门 | freeze-validator | 普通 | exit 0：`freeze chain verified`（索引 ID 唯一、r3 37 项绑定、血缘 r3→r1→i0a5(M1)）|
| 前置门 | freeze-hashes + freeze-r1-trusted-cmp | 普通 | §2 三个快照哈希命中；r1==可信副本 exit 0 |
| 前置门 | guard-selfcheck | 受控最小 | exit 0；`passed=true` 且 24 项 case 全过 |
| 行为矩阵 | chain-contracts-full-review | 守卫 env | JUnit：tests=11 failures=0 errors=0 skipped=0 |
| 行为矩阵 | i19-acceptance-historical | 守卫 env | JUnit：tests=3 failures=1（失败节点固定为 `test_acceptance_freeze_does_not_omit_latest_known_chain_tests`）errors=0 skipped=0 |
| 行为矩阵 | legacy-probes | 守卫 env | JUnit：31/0/0/0 |
| 行为矩阵 | boundary-contracts-r1-r5 | 守卫 env | JUnit：9/0/0/0 |
| 行为矩阵 | business-11-files-guard-env | 守卫 env | JUnit：186/0/0/0 |
| 行为矩阵 | guard-tests-normal-env | 受控最小 | JUnit：19/0/0/0 |
| 静态 | pyright-i1-scope | 受控最小 | exit 0 + `0 errors` |
| 静态 | ruff-check + ruff-format-check | 受控最小 | `All checks passed` / `already formatted` |
| 静态 | import-smoke-stage1 | 受控最小 | exit 0 + `354/354` |
| 运行后 | postflight-freeze-revalidate（+ 哈希/版本留痕）| 普通 | exit 0：绑定零漂移；postflight-hashes.txt / postflight-lib-versions.txt 生成 |
| 汇总 | verify_matrix.py | — | 16 块全部 ok → exit 0 |

## 5. 版本/REV 清单（版本纪律核对点）

| 模块 | 当前值 | 备注 |
|---|---|---|
| READER_PDF/DOCX/MD_REV | reader-pdf-2 / reader-docx-2 / reader-md-2 | 二次复核轮升版 |
| CLEAN_REV | clean-3 | R1/R2 范围语义升版 |
| CHUNK_REV | chunk-2 | R4 context_refs 升版 |
| ENGINE_REV / PARSE_RULE_REV | engine-1 / parse-2（checkpoint schema parse-checkpoint-2）| R3/R4 生命周期与检查点 |
| INGEST_REV | ingest-1 | C3/C5/R5 改 source.py 行为；是否应升版由复核人裁定（上轮 review §5 首条的版本影响表要求）|
| INDEX_REV_V1 | index-1 | I1 占位，I2 换真索引 |
| admission POLICY_REV | v1-20260915（_SUPPORTED_POLICY_REVS 绑定）| R5 未支持版本拒绝 |

## 6. 已知口径差异（复核人注意，非缺陷）

- 业务套件 186 与早期台账 180 之差 = 整改复测轮新增 6 用例（release_gate 7→12、source 17→18）；r3.verification_matrix 的 205 = 186 业务 + 19 guard。
- 守卫 env 与普通 env 不可互换：guard 测试须普通环境单独跑；业务/探针须守卫 env 跑（守卫 env 口径下的 186 为本轮新组合，申请方演练已命中，见 §7）。
- r2 的 required_case_coverage_map 在 r3 未重复该节，继续有效；本包 §3.C/D 即其 M4 相关子集。
- **I1-9 验收探针 `test_acceptance_freeze_does_not_omit_latest_known_chain_tests` 的指定历史断言（「r1 含最新 11 项链路测试」）不适用于当前候选**。i1-r1 的历史字节完整性由精确哈希与逐字节比较证明（前置门 freeze-hashes + freeze-r1-trusted-cmp），**该探针失败本身不证明完整性**；矩阵对其预期仅为「恰失败该固定节点一次」——若它通过，反而说明 r1 字节又被动过。当前候选的冻结完整性由 validate_i1_freeze.py 承担（r3 的 37 项绑定含 4 份现行探针）。此处置对应上轮 review §6.4「历史固定 r1 的完整性断言按历史记录处理，当前候选另测」。
- r2 仅作历史审计记录（parent 指向曾被补丁的 r1）；当前候选血缘只有 i0a5 → r1（恢复后）→ r3。

## 7. 备料自检（申请方演练记录）

修订后的矩阵（含五项执行控制：前置门 fail-fast、JUnit XML 精确核对、验证器去 assert 并加强血缘校验、运行后绑定零漂移门、受控最小环境含 noconftest/禁插件自动加载）由申请方以 `M4_REVIEW_EVIDENCE_DIR=<临时目录>` 完整演练一次：前置门 4 项全过；行为/静态块 16 块中 15 块 exit=0（唯一 exit=1 为 i19-acceptance-historical 的设计内历史探针失败，JUnit 精确核对失败节点白名单命中）；运行后零漂移门通过；verify_matrix 16 块全部 ok、脚本总退出码 0；write-once 拒绝路径实测 exit 2。演练证据在临时目录、已删除，**不构成证据也不替代独立复核**；正式复核一律使用默认 evidence/ 落盘。

## 8. 发现记录模板（reviewer 填写）

| ID | 严重度(P1/P2/P3) | 定位 file:line | 复现命令+最小输入 | 预期 | 实际 | 对 M4 的影响 |
|---|---|---|---|---|---|---|

## 9. 复核纪律与判定输出

复核人必须：
- 全新会话执行；run_matrix.sh 逐块实跑并保留 evidence/ 原始输出、退出码、环境记录；预期不符→最小复现→发现记录。
- 报告落本目录 `review.md`（若另建目录须回告路径）；按 §3 清单逐项给出证据引用。

复核人不得：
- 修改 freezes/、plugins/corpus/preparation/、tests/、历史审计目录、总台账（M4 裁决由 U 签认后回填）。
- 运行全库 PG 依赖套件、访问留出正文、调用业务模型。

判定结论只有两种：**M4 放行** / **M4 阻断（列最小收口项）**；部分通过不是结论。
复核人不得以「脚本退出码 0」单独作为 M4 放行依据——退出码只表示矩阵与预期一致；放行须基于 §3 清单逐项证据与复核人独立判断。
放行后由 U 在总台账签认 M4；I2 启动仍另需 M3（I0-C 未启动，与本复核相互独立）。
