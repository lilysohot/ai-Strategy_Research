# M4 独立复核报告（I1 内存链 → M4 放行裁决）

| 项 | 内容 |
|---|---|
| 日期 | 2026-09-16（运行时刻 19:31 +08:00）|
| 复核人 | 独立复核会话（全新会话，未参与 r1/r2/r3 制备；模型 DeepSeek-V4.1-Flash）|
| 复核对象 | [freezes/i1-r3.json](../../freezes/i1-r3.json) @ `f22525c3957f8d09890600eb1df7e3cab3a6fce61f79b196c6067cbd9f39dd59`；直接父 = 已恢复原始字节的 i1-r1 @ `d474bd6d…` |
| 执行方式 | `bash .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-m4-review/run_matrix.sh` 逐块实跑（默认 evidence/、write-once）＋ 复核人独立交叉核验（见 §2）|
| 环境 | WSL2 Linux 6.6.114.1；git HEAD `8d4772ca8fb2e368d4a256554784c7384c8f24ea`；Python 3.12.14；pymupdf 1.28.2；python-docx 1.2.0；pyright 1.1.411 |
| 矩阵结果 | 16 块全部命中预期；脚本退出码 0（按本包 §4 语义，该退出码**只是**「矩阵与预期一致」，不作为放行依据）|
| **裁决** | **M4 放行**（依据见 §1 逐项证据与 §2 独立核验；范围边界见 §4）|
| 复核后补充 | 2026-09-17 U 独立核查提出三点建议，经核对均**不推翻结论**；处置与新增留痕见 §6 |

证据目录：[evidence/](evidence/)（write-once；`index.txt` `b7c581c7…`、`matrix-summary.json` `77747e63…`、`environment.txt` `83c8293e…`、`guard-selfcheck.json` `03d5d355…`、`postflight-hashes.txt` `e4ba9076…`）。

## 0. 执行纪律声明

- 未修改 `freezes/`、`plugins/corpus/preparation/`、`tests/`、历史审计目录、总台账：`git status` 在复核前后一致；运行后 freezes 五个文件哈希复算不变（r1 `d474…`、r2 `3d27…`、r3 `f225…`、manifest `4e81c886…`、trusted 副本 `d474…`）。
- 未运行 PG 依赖套件、未访问留出正文（对抗探针中对留出路径的 `open` 被守卫拒绝，未读取任何内容）、未调用业务模型（守卫 env 结构性保证 + 复核人自律）。
- 矩阵逐块退出码（`evidence/index.txt`）：

| 块 | exit | 块 | exit |
|---|---|---|---|
| freeze-validator | 0 | guard-tests-normal-env | 0 |
| freeze-hashes | 0 | pyright-i1-scope | 0 |
| freeze-r1-trusted-cmp | 0 | ruff-check | 0 |
| guard-selfcheck | 0 | ruff-format-check | 0 |
| chain-contracts-full-review | 0 | import-smoke-stage1 | 0 |
| i19-acceptance-historical | 1（设计内：恰失败固定历史节点 1 次，见 §2.4）| postflight-freeze-revalidate | 0 |
| legacy-probes | 0 | postflight-lib-versions | 0 |
| boundary-contracts-r1-r5 | 0 | verify_matrix.py（汇总）| 0（16 块 ok）|
| business-11-files-guard-env | 0 | | |

## 1. 复核清单逐项证据（本包 §3）

### A 前置与冻结链

- **A1 通过**。`evidence/freeze-validator.log`：`freeze chain verified: index ids unique, r3 bindings ok, lineage r3->r1->i0a5(M1) ok`（exit 0）；运行后 `evidence/postflight-freeze-revalidate.log` 同样通过（绑定零漂移门）。验证器实现已读（[validate_i1_freeze.py](../../freezes/validate_i1_freeze.py)）：显式检查、非 assert、校验索引↔文件哈希、r3 全部绑定、r1→i0a5 血缘。
- **A2 通过**。复核人独立复算：r1 `d474bd6d…`、r2 `3d27a690…`、r3 `f22525c3…` 与索引/本包声明逐一一致；`cmp i1-r1.json i1-r1-original.json` 逐字节相等（exit 0，`evidence/freeze-r1-trusted-cmp.log` = `byte-identical`）。r2 字节与 manifest 登记值一致，其 parent `72e5fba4…`（曾被原地补丁的 r1）属已登记历史，不作当前血缘——与 [freeze-manifest.json](../../freezes/freeze-manifest.json) 说明及 [i1-r3.json](../../freezes/i1-r3.json) notes 一致。
- **A3 通过**。[guards/i1.json](../../guards/i1.json)：`phase=i1`、`network.mode=deny_all`、`allowed_targets=[]`；`forbidden_roots` 3 份留出（贝特利 / 中银高频 / 华泰宏观海外周报）、`allowed_source_paths` 6 份开发材料（茅台、光力科技、长江十问十答、华福新材料、华创宏观、光大非农），复核人逐条 `os.path.exists` 命中，`read_roots=data/corpus`、`protected_roots=data`；`poisoned_env=[OPENAI_*]`、`poisoned_dsn=[CORPUS_DSN]`。该文件哈希 `45330fad…` 与 r3 绑定及自检报告 `config_sha256` 一致。

### B 守卫先行（I1-8 绑定 + 零模型契约）

- **B1 通过**。`evidence/guard-selfcheck.json`：`passed=true`、24/24 case 全过（拒绝类 22：模型导入 ×5、网络 audit 重放 ×2、留出/相对路径/受保护写入/删除/重命名/允许清单外/空 read_roots ×7、非 Python 子进程、exec/system/posix_spawn ×3、pytest 部分声明、先污染后装载、非法配置；正例 2：允许清单只读哈希、CLI 包装传播）。config_sha256 与守卫绑定一致。
- **B2 通过**。5 个行为块在守卫 env（`env -i` + `guard_pytest` 先于收集装载）实跑：chain 11、i19 3、legacy 31、boundary 9、business 186，计数与预期逐一命中（`evidence/*.xml`）。`guard_pytest.py` 两种声明必须同时给出、阶段不一致即失败（fail-closed），插件在未声明时惰性。
- **B3 通过**。`evidence/guard-tests-normal-env.log`：19 passed（受控普通 env，与守卫 env 不混跑）。
- **B4 通过**。守卫 env 零继承、`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`、`--noconftest`；复核人另做**对抗性探针**（见 §3.3）验证拒绝行为真实生效；全程未触真实 PG/公网/模型。

### C M4 必需测试族

计数全部来自 `evidence/*.xml` 的 JUnit 精确值，并由复核人 `--collect-only` 逐文件独立复核（§3.2）：

- **C1 admission** 52/0/0/0（`test_corpus_preparation_admission.py`）。
- **C2 fidelity** readers 14 + remediation 15 + counterexamples 3 + fixtures 15，全绿；空页/纯图页/大图缺口/嵌套表/cell 图/有线表格/实录标题冲突/条件句跨行/char_span 保真均在列。
- **C3 mapping** clean 13 + chunk 14，全绿（映射 roundtrip、verify_clean_region、context_refs 引用式、覆盖不变式、超长复核）。
- **C4 接收/编排恢复** contract 17 + source 18 + engine 13 + release_gate 12，全绿（幂等/Failed 恢复/取消生命周期/发布所有权门/检查点完整载荷/暂存与归档路径边界/scope 非法与部分重叠拒绝）。
- **C5 行为探针**：完整链路 11/0（`evidence/chain-contracts-full-review.xml`，11 个节点名逐一核对）；I1-9 验收 3 例——2 passed + 恰 1 个固定历史节点失败（§3.4）；旧探针 20 + 边界 11 = 31/0；R1—R5 边界 9/0。
- **C6 业务套件** `evidence/business-11-files-guard-env.xml`：tests=186、failures=0、errors=0、skipped=0（守卫 env）。

### D 已知未覆盖（如实声明，不阻断 M4，本报告不宣称其通过）

fidelity 人工 source-gold 独立比对（unverified）、格式真实样本（I3 格式门）、authority / publication_pg / cli_isolation（I2 门）、coverage / retrieval_pg / legacy_regression（I2/I3 门）、`INDEX_REV_V1=index-1` 为 I1 无索引阶段占位。复核人对以上逐条确认**未在本轮运行**，也未据本报告主张其通过。

## 2. 复核人独立交叉核验（超出命令矩阵的部分）

### 2.1 冻结链与绑定

- 独立复算 5 个哈希（§A2）与 `cmp`；`i1-r1.json` 绑定总数 35（configs 3 + evidence_and_probes 4 + fixtures 3 + implementation 15 + tests 10），`i1-r3.json` 绑定总数 37（configs 3 + current_audit_probes 4 + fixtures 3 + implementation 15 + tests 12），与索引及验证器口径一致。
- r1→M1 血缘独立核验：`i1-r1.parent_snapshot = i0a5 @ 71aa61af…`，文件 `i0a5-logic-contract-frozen-v1-20260915.json` 存在且哈希相符。
- r3 的 **4 份现行审计探针**哈希与 `postflight-hashes.txt` 留痕一致（均为 r3 `current_audit_probes` 绑定组）：chain `e883133e…`、probes `4a7bc08d…`、boundaries `bbfde1bd…`、remediation-retest `5dc50b3f…`。另有一份**历史 I1-9 探针** `06325401…`——不在 r3 绑定面，仅因 run_matrix.sh 对其哈希留痕而出现在 postflight-hashes.txt（2026-09-17 修正：初稿曾把两者混列为五项，纯文案问题，实际哈希匹配无误）。

### 2.2 用例数独立核对（collect-only，守卫 env）

`admission 52 / readers 14 / remediation 15 / counterexamples 3 / fixtures 15 / clean 13 / chunk 14 / contract 17 / source 18 / engine 13 / release_gate 12`（合计 186）；旧探针 20 + 边界 11 = 31。与本包 §3.C 括号内数字**逐文件一致**，无虚报。业务 186 与早期台账 180 之差（release_gate 7→12、source 17→18）与当前计数算术自洽（+5+1=+6）。

### 2.3 对抗性守卫探针（复核人自建，守卫 env）

| # | 操作 | 预期 | 实际 |
|---|---|---|---|
| 1 | `open(留出路径)` | 拒绝 | REFUSED（未读取内容）|
| 2 | `open(data/corpus 内未列入允许清单的路径)` | 拒绝 | REFUSED |
| 3 | 允许清单文件只读哈希 | 放行 | ALLOWED |
| 4 | 写 `data/` 受保护路径 | 拒绝 | REFUSED |
| 5 | `import openai` | 拒绝 | REFUSED |
| 6 | `socket.connect`（audit 重放，无真实连接）| 拒绝 | REFUSED |
| 7 | 派生非 Python 子进程 `/bin/true` | 拒绝 | REFUSED |
| 8 | 派生 Python 子进程并在其内读留出 | 子进程继承守卫 | `CHILD_REFUSED`（rc=0）|
| 9 | 投毒检查 | 生效 | `OPENAI_API_KEY=CORPUS_GUARD_DISABLED`、`CORPUS_DSN` 已投毒 |

结论：拒绝是**执行期强制**而非仅日志；子进程传播真实生效。守卫的固有边界（不覆盖 C 扩展原生 syscall、OS 级隔离交沙箱后端）已在 [guard.py](../../../../plugins/corpus/preparation/guard.py) 如实声明，复核人认可该声明边界。

留痕（2026-09-17 补充）：探针已固化为 [evidence/reviewer-probes/adversarial_guard_probe.py](evidence/reviewer-probes/adversarial_guard_probe.py)（sha256 `58458c54…`），并在同守卫实现/配置下复跑留痕 [adversarial_guard_probe-output.txt](evidence/reviewer-probes/adversarial_guard_probe-output.txt)（sha256 `11ff5000…`，`all_expected=true`、exit 0，9/9 与上表一致）。首次执行在本复核会话内完成、stdout 未落盘，上表即其结果；复跑仅作可追溯补强。

### 2.4 历史探针失败的独立评估

- 独立复现：守卫 env 重跑 i1-9 验收，稳定 `1 failed, 2 passed`，失败节点恒为 `test_acceptance_freeze_does_not_omit_latest_known_chain_tests`（`test_i1_9_acceptance.py:77`：断言 chain 测试在 r1 绑定内）。
- 独立评估：r1 为 I1-9 时点冻结件（补丁前锚点 `d474…` 由 manifest 在补丁前登记），而 11 项链路测试产生于其后的 full-review 轮；忠实恢复的 r1 **不可能**含该绑定——使其转绿只能再次原地改 r1，恰是上轮 R6 定性的缺陷。r1 的字节完整性已由精确哈希 + 可信副本逐字节比较独立证明；当前候选完整性由 r3 的 37 项绑定承担（含 4 份现行探针）。此处置与上轮 remediation-retest review §6 建议 4「历史固定 r1 的完整性断言按历史记录处理，当前候选另测」一致。**判定：设计内失败，非缺陷。**

### 2.5 版本纪律核对与 INGEST_REV 裁定

- 常量实测与 §5 表一致：`reader-pdf-2/docx-2/md-2`、`clean-3`、`chunk-2`、`engine-1`、`parse-2`（checkpoint schema `parse-checkpoint-2`，engine.py:471/529 实测）、`ingest-1`、`index-1`、`POLICY_REV_V1=v1-20260915`（`_SUPPORTED_POLICY_REVS` 仅含 v1）。
- 身份构成实测（[engine.py](../../../../plugins/corpus/preparation/engine.py) L765-778）：`parse_rev=f(PARSE_RULE_REV, source_id, extractor_rev)`、`clean_rev=f(CLEAN_REV)`、`chunk_rev=f(CHUNK_REV)`、外加 `index_rev/scope_ref/decision_id`。语义变化且进入身份的版本均已升版：范围语义入 clean-3、检查点入 parse-2、reader 经 `extractor_rev` 入 parse_rev。
- **INGEST_REV 裁定（本包 §5 转交项）：不升版，非阻断。** 理由：①`INGEST_REV` 不进入 build 身份（身份构成无该量；仅作为 `IngestOutcome` 字段，source.py:97）；②source.py 本轮变更（C5/R5 的归档与暂存落点边界、恢复读入口复用同一信任边界，source.py:131-144/146-187/283-285/329-331）均为**拒绝式**加固——改变接受/拒绝与错误语义，不改变被接受来源的归档字节（内容寻址由原始字节决定），不可能出现「同 build 身份→不同产物」。上轮 review §5 首条所要求的身份卫生目标已由 clean-3/parse-2/chunk-2/readers-2 满足。若 I2 使接收行为影响产物，须复评此裁定。

### 2.6 其他独立动作

- **write-once 拒绝路径**：本包实跑后再次触发 `run_matrix.sh`，稳定输出 `拒绝：evidence 目录已存在（write-once）`，exit 2，未产生新写入。
- **静态检查原文**：pyright `0 errors, 0 warnings`（仅提示新版本 1.1.411→1.1.414 可升级）；ruff `All checks passed!`；format `15 files already formatted`；import smoke `354/354`。
- **证据反篡改抽查**：JUnit suite 时间戳与本轮运行时刻一致（2026-09-16T19:31:17+08:00），`index.txt` 与 `matrix-summary.json` 内容互洽，16 块预期/实际逐块记录。

## 3. 发现记录（模板 §8）

| ID | 严重度 | 定位 file:line | 复现命令+最小输入 | 预期 | 实际 | 对 M4 的影响 |
|---|---|---|---|---|---|---|
| N-1 | P3（观察，不阻断）| [engine.py](../../../../plugins/corpus/preparation/engine.py) L81 | `grep -rn ENGINE_REV plugins/corpus/preparation/*.py` | — | 常量已声明但无消费点（身份构成不含 ENGINE_REV）| 无。本轮裁定 engine-1 无需升版即以此为据之一；建议 I2 接线检查点/编排身份时纳入或移除 |
| N-2 | P3（观察，不阻断）| [source.py](../../../../plugins/corpus/preparation/source.py) L43 | 见 §2.5 | INGEST_REV 是否升版 | 不升版（拒绝式加固，不入身份）| 无。裁定理由已留痕 §2.5；I2 若改变接收-产物耦合须复评 |
| N-3 | P3（观察，不阻断）| [run_matrix.sh](run_matrix.sh) L56-74 | 各 pytest 块 `-c /dev/null --noconftest` | 仓库 pytest 配置（asyncio_mode 等）被绕过 | 本轮 186+19+各项无需 async，全绿 | 无。I2 若引入 async 用例，命令矩阵须复评插件/配置装载方式 |
| N-4 | P3（改进项，不阻断；2026-09-17 U 反馈）| [verify_matrix.py](verify_matrix.py) L39-49 | 构造「日志内容命中但进程异常退出」的块（如工具打印通过信息后崩溃，exit≠0）| index.txt 各块退出码纳入自动判定 | 退出码仅由 `run()`/`gate()` 留痕进 index.txt，verify_matrix 不读取、不比对 | 本轮无影响（16 块退出码由复核人与 U 分别人工核对一致）。**已闭合（2026-09-17）**：[verify_matrix_v2.py](verify_matrix_v2.py)（sha256 `a34b97c9…`）实现退出码自动判定并回放本轮证据全绿（[matrix-summary-v2.json](evidence/matrix-summary-v2.json) `ad29851c…`，含 i19=1 共 16 块逐块比对 + 增删块检出）；反例自证通过（篡改副本退出码→MISS、exit 1）。下轮复核矩阵直接采用 v2 |

无 P1/P2 发现；未发现与预期不符的块或计数。

## 4. 未覆盖范围与放行边界（不宣称通过）

- 本裁决仅覆盖 **M4**（M1+I1 完成；admission/fidelity/mapping 及接收/编排恢复测试 + 先行零模型守卫；未触真实 PG、未访问留出）。
- **不覆盖**：M3/I0-C（未启动）、I2 全部（真实 PG DDL/repository/FTS/CLI 消费者/publication_pg）、I3 格式门与指标、人工 source-gold 独立比对、R2 语义任务；D 节所列 read/authority/coverage 等门均为后续阶段事项。
- 放行后由 U 在总台账签认 M4 回填；I2 启动仍另需 M3 完成，本报告不构成 I2 启动授权。

## 5. 裁决

**M4 放行。**

依据：①冻结链与血缘（r3→r1(已恢复)→i0a5/M1）经验证器与复核人独立复算双重确认，绑定零漂移；②守卫先行契约（自检 24/24、对抗探针 9/9、守卫 env 行为矩阵）成立；③M4 必需测试族（C1—C6）计数与内容逐项命中且经独立 collect-only 复核；④历史探针失败经独立评估为设计内、且有可信副本锚定的完整性证明替代；⑤版本纪律经身份构成实测核对，INGEST_REV/ENGINE_REV 裁定不升版、非阻断；⑥裁决时点三项 P3 观察（N-1—N-3）均无 M4 影响，留档备 I2（N-4 为 2026-09-17 复核后新增改进项，见 §6，不改变本裁决）。

复核人：独立复核会话（2026-09-16）

## 6. 复核后补充核对与改进项（2026-09-17，U 反馈处置）

U 对本轮复核做了一次独立检查，提出三点建议；经复核人逐条核对，均**不推翻 M4 放行结论**，处置如下。

| # | U 建议 | 核对结论 | 处置 |
|---|---|---|---|
| 1 | verify_matrix.py 未把 index.txt 的退出码纳入自动判定；本轮人工核对一致，以后应自动验证 | 属实。本轮 16 块退出码由复核人与 U 分别人工核对一致 | 登记 **N-4（P3，见 §3）** 并**已闭合（2026-09-17）**：新增 [verify_matrix_v2.py](verify_matrix_v2.py)（sha256 `a34b97c9…`，append-only 补充实现，不改写被复核的 v1 `3915aa87…`）——解析 index.txt 的 `块 exit=N` 与各块预期退出码（含 i19=1）逐块精确比对，并检出期望块的缺失/未预期块的新增。回放本轮 evidence：33 项记录全 ok、exit 0（[matrix-summary-v2.json](evidence/matrix-summary-v2.json) `ad29851c…`）；反例自证通过（副本篡改退出码→MISS、exit 1）。下轮复核矩阵直接采用 v2 |
| 2 | 九项对抗探针无独立脚本与原始输出，可追溯性不足 | 属实。首跑于复核会话、stdout 未落盘 | 已固化并复跑留痕：[evidence/reviewer-probes/adversarial_guard_probe.py](evidence/reviewer-probes/adversarial_guard_probe.py)（sha256 `58458c54…`）+ [adversarial_guard_probe-output.txt](evidence/reviewer-probes/adversarial_guard_probe-output.txt)（sha256 `11ff5000…`；同守卫实现/配置复跑，`all_expected=true`、exit 0，9/9 与 §2.3 一致）；§2.3 已补证据位置 |
| 3 | 报告把「4 份现行探针」与历史 I1-9 探针混列为五项 | 属实，纯文案问题；实际哈希匹配无误（i1-9 探针不在 r3 `current_audit_probes` 绑定面，仅因 run_matrix.sh 留痕出现在 postflight-hashes.txt）| §2.1 文案已修正为「4 份现行 + 1 份历史（仅留痕）」分列 |

本轮运行证据未被触动：`index.txt` `b7c581c7…`、`matrix-summary.json` `77747e63…`、`environment.txt` `83c8293e…`、`postflight-hashes.txt` `e4ba9076…` 复算不变（2026-09-17 复核）；`reviewer-probes/`（对抗探针脚本+复跑输出）与 `matrix-summary-v2.json`（v2 回放汇总）、包根 `verify_matrix_v2.py`（N-4 闭合实现）均为复核人追加的补充留痕，不属于 run_matrix.sh 的 write-once 运行输出，也未改动任何 v1 产物。**裁决维持：M4 放行。**