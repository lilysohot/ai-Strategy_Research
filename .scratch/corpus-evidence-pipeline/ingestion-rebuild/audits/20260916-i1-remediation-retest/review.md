# I1 整改后独立复核：旧反例已转绿，边界与冻结链尚未闭合

日期：2026-09-16。审核对象：当前 preparation 实现、I1-1～I1-9 任务口径、`20260916-i1-remediation/verification-matrix.txt`、候选快照 i1-r2；结合前两份完整 review。

## 1. 判定

**整改有效，核心方向仍符合项目目标；但尚不满足 I1/M4 的完整放行条件。** 本轮不是上一轮的“实现未改”：原完整 review 的 11 个行为用例已全部通过，来源登记失败、明确排除、标题超长及基本质量门的改进应予保留。

本轮剩余问题分两层：

1. 实现层：scope 的非法空集合与部分重叠、实际解析未受生命周期管理、检查点未校验完整语义载荷、归档暂存路径边界遗漏。
2. 验收层：历史 r1 被原地追加修改，索引哈希失配且未登记 r2；因此“旧快照保留不改”的要求没有满足。不能把针对固定 r1 的旧审计断言变绿当作新快照已通过。

这些是既定“范围可验、完整性发布门、安全归档、可恢复执行、不可变冻结”要求的补充验证，不是新增模型需求、PG 工作或扩大到留出调参。无需取消或重做整套架构。

结论分层：**旧具体反例整改通过；I1-9 收口未完成；M4 仍阻断；I2 仍 not_ready（还独立缺 M3/I0-C）。** 不宣称全项目的数据清洗、入库、索引、CLI 和逐类非回归已达标。

## 2. 实际复测

| 检查 | 本轮结果 | 本目录证据 |
|---|---|---|
| 业务 11 文件，收集前装载 I1 守卫 | 180 passed，29.04 秒 | `business.xml` |
| 四组审计探针 | 45 passed，0.55 秒 | `previous-probes.xml` |
| 新增边界用例（最终文件） | 8 failed、1 passed，0.25 秒 | `remaining-final.xml` |
| 同一最终文件重复 | 8 failed、1 passed，0.18 秒 | `remaining-repeat.xml` |
| guard pytest，独立无预装守卫进程 | 19 passed，2.74 秒 | `guard-tests.xml` |
| I1 守卫合成自检 | 24/24 passed | `guard-selfcheck.json` |
| preparation + corpus tests Ruff | All checks passed | 本轮命令输出 |
| preparation 格式检查 | 15 files already formatted | 本轮命令输出 |
| preparation + 五个改动测试文件 Pyright | 0 errors / warnings | 本轮命令输出 |
| r2 绑定文件哈希 | 40/40 匹配，父哈希匹配当前 r1 | `integrity-comparison.json` |
| 冻结索引 | r1 哈希失配；r2 无索引项 | 同上 |

45 = 20 原初探针 + 11 二次边界 + 11 完整 review 链路 + 3 I1-9 检查。两份最早探针为当前协议适配版本，不是原字节；r2 说明其发布正例增加 register/acquire/owner/token，本轮所查正例与这一说明相符。完整 review 链路文件及 I1-9 三项检查文件保持原哈希。其中 I1-9 的一个检查变绿来自 r1 被改，不能算冻结合规通过。

新 8 个失败不是 8 个独立生产缺陷，也不是研报失败率：非法 scope 三个变体、部分重叠一个、生命周期两个、检查点一个、暂存边界一个。最终用例统一了 engine/store 的模拟时钟；探索输出 `remaining.xml` 保留，结论以 final/repeat 为准。全部新增材料为合成输入，时间推进不使用真实等待，符号链接仅在同一受控临时目录内，不接触外部用户数据。

用户留存的矩阵业务 180 项使用 normal env；本轮改在收集前装载 I1 守卫重跑，180 项依然通过。不能反推此前普通环境执行零副作用，但本轮无需按其普通环境口径重跑。守卫自身测试按设计在独立子进程中安装，单独运行。

本轮未调用业务模型、访问 PG/公网或读取留出正文；仅新增本审计目录，不改业务实现、金标、台账、历史探针或冻结文件。未重跑全库 Pyright、import smoke 或旧业务非回归；矩阵中的 import smoke 354/354 是提交方留存结果，不冒充本轮独立执行。

## 3. 已有整改的认可范围

| 原项 | 当前证据与结论 |
|---|---|
| C1 发布门 / N1 错误 PDF 正例 | 未读图片、超长块、失败阶段不能经正常 engine 发布；PDF 已改负例，MD generation 正例保留。具体用例通过；检查点损坏可消除质量信号的问题见 R4 |
| C2 scope | 完整单元内的有效 char 范围会限制 chunk，out_of_scope 有记录；非法前缀拒绝。边界不完整，见 R1/R2 |
| C3 来源登记失败 | 停止后继阶段，原反例通过 |
| C4 明确排除 | 排除快路径前移，reader 不可用也能撤销，原反例通过 |
| C5 最终归档分片链接 | 原分片越界用例已拒绝；暂存目录遗漏，见 R5 |
| C6 解析复用 / 取消 | 完整解析检查点可复用，重试 reader 只调用一次；取消会提交 CANCELLED 并阻断后继。实际计算和完整载荷仍未闭合，见 R3/R4 |
| C7 标题 + 超长内容 | 原覆盖错误修复，保留标题并登记超长复核，原反例通过 |
| N2 快照 | r2 绑定最新探针和命令输出有进步；历史不可变链不合规，见 R6 |
| N3 状态 | 最新回填明确 M4 待独立复核、I2 not_ready，方向正确；历史旧宣告已追加纠正，不再将旧文字当成当前授权 |
| N4 困难结构 | 新增有线 PDF、实录标题、条件换行三项通过；合成/人工/真实格式覆盖声明已拆分，不把未测 gold 说成通过 |

## 4. 剩余发现与建议

### R1 · P1：非空非法 scope 被解析为空约束，退回全文发布

定位：`plugins/corpus/preparation/engine.py:220`（`_parse_scope_ref`）与 `:273`（`_apply_scope_to_clean`）。

输入 scope_ref 为单个空格、逗号或空格加逗号，且 locators 非空时，准入接受该记录；解析器跳过所有空 token，返回空 tuple；后继 `if not scope` 将其解释为“没有 scope 约束”。三种输入最终均能发布完整正文。

建议：区分“没有请求 scope”和“请求 scope 但无合法范围”。仅 None 表示全篇；非空请求归一化后必须至少有一个合法区间，否则拒绝/待复核。scope_ref 与 locator 的关系由一个统一校验函数验证，不能各自只判非空。

### R2 · P1：部分重叠区被整体排除，批准范围不完整仍可发布

定位：`engine.py:250`（`_span_in_scope`）、`:273`、`:999` 附近的发布覆盖检查。

合成正文 `# Report\n\nApproved beginning.\n\nOutside 987654.\n` 批准 `char:0-18`：标题完全落入范围，但第二段的 `Approved` 也在批准范围内。当前把整个第二段记为 OUT_OF_SCOPE，最后仅发布 `# Report`，未报告批准范围处理不完整。

“不泄漏范围外内容”只是一个条件，不等于“批准范围已完整”。发布覆盖检查只在过滤后的 KEPT 集合上计算，遗漏已被过滤掉的批准内字符。

建议：选择并固定一种语义——拒绝未对齐单元的范围、留作范围待复核，或安全裁剪并保留精确字符映射。不能自动缩小批准范围后称完成。用原批准范围而非过滤后的保留集合定义分母。对照 `char:0-29` 的完整单元范围可正常发布，本轮通过。

### R3 · P1：生命周期仍包住产物写入，没有包住实际解析/清洗/切块

定位：`engine.py:605`（`_run_stage`）、`:716`（job 前完成 chunk）、`:858`（job 前调用 reader）。

两个实测：

- cancel_check 一开始就为 True，完整 reader 仍执行一次，然后才抛 EngineCancelled。
- 配置 stage_timeout=1 秒，reader 注入模拟耗时 2 秒；engine/store 使用同一模拟时钟，仍成功返回构建，无超时错误。

原因：实际工作先完成；`_run_stage` 的 produce 只是返回已计算好的 units/chunks。计时、取消与 heartbeat 发生得太晚。当前恢复免重读 reader 是真实进步，但 clean/chunk 仍先于 SUCCEEDED 短路重算。

建议：把实际计算放进受管理阶段。解析尚未形成 build 时，可使用绑定 source/规则的前置解析任务，或先完成独立受控探查再创建构建；不得用产物列表返回耗时冒充解析耗时。取消在昂贵操作前及协作检查点检查；心跳按间隔发生，超时/失去租约后禁止提交；默认 clock 应为真实时钟而非固定 now。I1 用可注入时钟测状态协议，真实 PG 并发事务留给 I2。

### R4 · P1：检查点只验证文本哈希，缺口台账损坏后可绕过质量门

定位：`engine.py:486`（检查点校验）、`:599`（仅逐单元 content_hash 比较）；`repository.py:321`（来源检查点写接口）。

实测路径：使用冻结的合成缺口 PDF，先以未决状态解析留下检查点；通过检查点存储 seam 注入损坏，仅把 issues 改为空，正文与 unit_hashes 不变；随后人工准入并 execute/publish，发布成功。被移除的 image_only_page 没有被发现，也没有触发重算。这不是正常 PDF 凭空丢失问题，而是“可验证检查点”在损坏/错误写入下的完整性保证不成立。

CandidateUnit.content_hash 仅覆盖 raw_text，不能证明坐标、状态、页数、issues 等语义载荷完整。新序列化保留 bbox/cells 是必要改进，但保留字段不等于验证字段。

建议：检查点使用版本化严格 schema，并对完整规范化载荷绑定 artifact hash，包括 units 坐标/状态/顺序、issues、格式/页数及来源/读取器规则。该 hash 由成功阶段的受所有权保护提交记录持有；不能只在同一个可任意重写对象内自报哈希。损坏或字段缺失应拒绝复用并重算，保留原因。加入仅更改 issue/坐标/status、不更改正文的负例。

### R5 · P1：归档最终路径受检查，_staging 可沿链接向外写入

定位：`plugins/corpus/preparation/source.py:146`、`:162`。

把 `archive/_staging` 指向测试临时目录的 sibling，最终 `<hash-prefix>/<hash>.md` 仍在 archive 内。当前只检查 final，因此 tempfile.mkstemp 在链接目标中创建文件、写入完整内容，再移回最终位置。受控探针记录到实际暂存路径位于 outside；没有抛 SourceIngestError。

这不是需要两个 worker 才能触发的竞态，而是单进程确定性路径遗漏。旧分片链接测试通过不能覆盖暂存路径。

建议：归档与暂存、恢复读取使用同一目录信任策略，所有实际落点均受约束；在创建文件前拒绝不允许的链接。后续再以目录 fd/no-follow/条件置入补竞态和 no-clobber，不把本轮单进程缺口推迟到 PG 阶段。

### R6 · P1（验收）：历史 r1 被更改，冻结索引与证据链不一致

定位：`freezes/i1-r1.json` 新增 full_review_chain_tests 与 notes、`freezes/freeze-manifest.json`、`freezes/i1-r2.json` parent_snapshot。

本轮哈希：

- r1 上轮原始：`d474bd6d566e8cf5d72d0531de55fe918833ec49185f0b31322f97d603f85957`。
- r1 当前：`72e5fba4b7c508b7bda3f1e863be6e8211e77408067bc5d2ab623f7db58f84a9`。
- 索引仍只有 r1，仍写原始 d474…；未追加 r2。
- r2 的 40 项绑定确实全部匹配，其父指向修改后的 72e5…，不等于保留了原冻结链。

往一个已经冻结的 JSON 内“追加字段”仍然改变字节；这不是“新增一份不可变修订”。I1-9 旧探针明确检查固定 r1 且注释说明不要求改历史，现在靠修改 r1 令其转绿，是验收对象选择错误。

建议：停止原地修补历史快照。保全当前错误链的审计记录，在有可信副本的前提下核对/恢复原 r1 的精确字节；如果不能可靠恢复，明确记录历史完整性破坏，不伪造原字节。新增修订绑定这次实际运行内容和有效父引用，追加索引。对当前版本写独立 manifest 验证器；固定 r1 的历史探针保持历史结果，不把它硬列为未来每版必须绿的当前验收。两份旧发布探针也应保存适配前版本或可审计补丁，不继续原地覆盖历史审计源。

## 5. 非阻断建议及验证限度

- clean/chunk 等语义输出已有变化，但 CLEAN_REV/CHUNK_REV 仍为 `*-2`；scope/检查点语义也应有明确行为版本进入身份计算。仅快照代码哈希变更不能替代 build 指纹的规则版本。形成下一候选前补版本影响表，避免同 build 身份对应不同产物。
- r2 notes 的契约映射含 `chain::cancel` 等概述，实际完整链路文件没有该节点；取消用例在 release_gate。改用精确 node ID + 执行结果与适用阶段，避免按说明误以为超时用例已运行。
- 人工 source-gold 独立比对、真实格式与三类检索/证据非回归仍未完成。本轮不将 I2/I3 门提前作为新增 I1 失败项，也不宣称现有合成用例已证明其他研报全不受影响。
- 有线 PDF 测试当前读取分支通过；其无法提取分支使用 pytest.skip。后续应将“明确复核且拒绝不完整发布”作为有效断言分支，而不是用 skip 代替必需行为验证。

## 6. 建议下一轮只做有限收口

1. 固定本轮九个边界用例和历史结果，修 R1/R2/R4（范围与质量闭合），不改输入规避失败。
2. 修 R3/R5（真实计算生命周期、暂存路径），补取消/超时/检查点完整载荷与必要对照。
3. 修 R6（不可变历史、当前快照选择、追加索引），核对行为版本。旧反例通过可继续保留，不退回最初设计。
4. 在收集前安装 I1 守卫，统一重跑既有业务/行为探针和本轮用例，保存原始 XML/命令/退出码/哈希。历史固定 r1 的完整性断言按历史记录处理，当前候选另测。
5. 全部适用 I1 门通过后才申请 M4；M3/I0-C 独立未完成，I2 仍不得启动。无需新增模型预算、PG 权限或留出数据。

## 7. 最小复现

WSL 仓库根目录：

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  PYTHONPATH=/home/administrator/FrontierAgent \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  CORPUS_GUARD_PHASE=i1 \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json \
  .venv/bin/python -B -m pytest --noconftest -c /dev/null \
  -p no:cacheprovider -p plugins.corpus.preparation.guard_pytest \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-i1-remediation-retest/test_remaining_contracts.py \
  -q --tb=short
```

同一最终文件两次结果均为 8 failed、1 passed。本轮依照 diagnosing-bugs 的复现/对照方法及 codebase-design 的 Interface 不变式审查开展；只执行诊断，未实施修复。
