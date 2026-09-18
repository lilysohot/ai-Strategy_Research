# I1-9 联合复核：夹具与冻结已交付，I1 验收仍被阻断

日期：2026-09-16。范围：结合 `audits/20260916-i1-full-review/review.md` 复验 C1—C7，检查 I1-9 新测试、快照及统一台账。性质为审查，不是修复提交或阶段放行。

## 1. 结论

**可以认可 I1-9 新增三格式合成夹具、15 个测试及候选冻结快照的交付；不能认定 I1-9 整项验收完成，也不能放行 M4/I2。**

- 当前九业务测试文件 170 项通过（原 155 + 新夹具 15）；前两轮旧探针 31 项通过，合并运行 201 passed。
- 上次完整 review 的链路用例原样复跑仍为 **9 failed、2 passed**，C1—C7 均未关闭。
- 上次审查绑定的 15 个实现文件、9 个原测试文件、守卫配置及链路探针均未变。29 项比较中仅两份进度文档改变，架构文件未变。不能把本次新增测试资产视为这些缺陷已被修复。
- `i1-r1.json` 的 35 项绑定、父快照和索引哈希均匹配；这是完整性通过，不是正确性通过。快照没有纳入最新完整 review 的 11 项链路测试。
- 新增 PDF 发布正例与已有质量门冲突，实际把“存在未读取缺口仍可发布”的旧缺陷固定为成功预期。
- 任务台账仍写“I1 全部完成、I2 可启动”，同时又写“M4 待复核、I0-C 未启动”，不满足 I2 的 M3+M4 前置。

方向判断：三类研报、确定性准备、单一原文权威、CLI 优先、零模型、内存与 PG 分阶段的方向保持；偏差发生在**测试预期、验收分母和放行状态**。不建议重做整个架构或换模型。

## 2. 实测与证据

| 核验 | 本轮结果 | 本目录证据 |
|---|---|---|
| 九业务文件 + 两轮旧探针 | 201 passed，35.17 秒 | `business-and-old-probes.xml` |
| 完整 review 原链路探针 | 9 failed、2 passed，0.39 秒 | `prior-chain.xml` |
| 新增 I1-9 接受性检查与对照 | 2 failed、1 passed，0.23 秒 | `i1-9-acceptance.xml` |
| 原链路 + 新 I1-9 检查合并重复 | 11 failed、3 passed，0.23 秒 | `chain-and-i1-9-repeat.xml` |
| 守卫合成自检 | 24/24 passed | `guard-selfcheck.json` |
| preparation 包及新夹具测试 Ruff | All checks passed | 本轮命令输出 |
| 冻结绑定、索引、父快照 | 35/35 一致；索引及父快照一致 | `integrity-comparison.json` |

201 = 170 + 20 + 11；170 内含新增夹具 15。未重跑普通环境 guard pytest 19 项，不将其加进本轮总数。重复运行不是新增覆盖。新增两项失败分别是旧 C1 在冻结 PDF 上的重现、验收证据完整性检查，不是又发现两项独立生产缺陷；不以这些定向用例计算研报失败率。

业务测试均在收集前装载 I1 守卫，使用 env -i、禁用项目 conftest 与自动插件。来源限原配置允许的六份开发 PDF 和合成材料；本轮无模型调用、PG/公网连接、留出内容读取或数据库修改。只新增本目录审计文件，不改实现、任务台账、既有探针、gold 或旧冻结快照。

本轮未重新运行全库 Pyright/import smoke、旧业务非回归、PG/真实 CLI E2E，不把原台账中的历史成功转述为本轮实测。六份开发 smoke 也不能替代人工 source-gold 的独立比对或后续真实格式门。

## 3. 与引用 review 逐项对照

| 原编号 | 问题 | 本轮状态 / 具体信号 |
|---|---|---|
| C1 / P1 | 发布未执行质量、阶段完整性和完整所有权门 | 未修复。未读图片、超长待复核内容及 CHUNKED 失败的三个拒绝断言均失败；新冻结 PDF 再次复现 |
| C2 / P1 | scope 只有标签，未限制发布内容 | 未修复。仅批准 char:0-34，已发布 chunk 仍包含范围外 987654 |
| C3 / P1 | 来源登记失败被引擎忽略 | 未修复。put_source 失败后仍返回 build，来源记录不存在 |
| C4 / P1 | 明确撤销依赖成功解析 | 未修复。有效 EXCLUDED 取代链遇到 reader 异常时旧 active_build_id 保留 |
| C5 / P1 | 归档分片父目录符号链接越界 | 未修复。受控临时目录中实际置入越出 archive_root，未拒绝 |
| C6 / P2 | 恢复只跳写入、不跳已完成计算 | 未修复。PARSED 成功后 CHUNKED 失败，再跑 reader 次数变为 2 |
| C7 / P2 | 标题 + 超长不可分段落覆盖错误 | 未修复。抛出“保留区未进入任何检索块: [1]” |

这些行为及实现行号与原 review 对应。不得用新增 15 个夹具测试通过替代上述未通过关系。I1-7 的取消、心跳、真实阶段时钟等静态缺口仍在；本轮没有另行声称已动态复现每种竞态。恢复测试 `tests/test_corpus_preparation_engine.py:331` 的自比较恒真断言也未调整。

## 4. I1-9 新交付的具体审查

### N1 · P1：PDF 正例固化了错误发布预期

位置：`tests/test_corpus_preparation_fixtures.py:240`（发布断言 253—256）；同文件页面缺口与 NEEDS_OCR 测试明确承认该 PDF 有未处理图片区。

同一个四页 PDF 被人工整源 admitted 后，直接调用 publish_build 并要求 generation=1，再要求第二次激活 generation=2。它没有批准的章节 scope，也没有解决这些质量缺口。材料准入不等于处理完整，架构 §8 第 2—3 条明确要求缺口阻断常规发布。

本轮 `test_frozen_pdf_with_unresolved_gaps_cannot_publish` 先确认 quality_report 确有 image_only_page 缺口，再断言发布拒绝，得到 DID NOT RAISE。与此相对，`test_control_clean_md_can_exercise_generation_independently` 用同批无缺口 MD 完成 generation 1→2 和幂等重试，通过。

建议：将 generation 正例改用无缺口材料；保留原 PDF 作为“候选可留存、常规发布必须拒绝”的负例。以后若做 scoped 发布，须另有真实范围批准、裁剪与完整性检查，不能让 fixture 标记自动豁免质量。修 C1 后更新这一条错误预期不属于降低验收标准；以架构为依据修正测试，并保留旧报告。

### N2 · P1：冻结覆盖集合遗漏最新阻断，不能作为通过证据

位置：`freezes/i1-r1.json:8`、`:50`、`:76`。

快照绑定两轮较早探针（20+11），未绑定完整 review 的 `test_chain_contracts.py`，verification_matrix 也没有该组失败结果。`m4_declaration` 虽声明待复核，却同时写“全部必需用例本轮通过”。现有完整 review 的 9 项失败直接否定这一描述。

区分：**r1 作为开发候选快照有价值，可以保留；它作为完整验收证据不充分。** 本轮完整性检查确认 35 项哈希一致，不是快照遭篡改。新增快照接受性测试的失败表达的是验收范围不完整，不要求反写历史 r1。

建议：后续 r2 追加最新 review/探针及其结果，保留失败，不覆盖 r1；每项必需契约映射到具体 node ID、结果文件与 SHA-256。命令保存完整参数而非“env -i guard_pytest 9 business files”摘要。至少包含登记失败、scope、质量/阶段发布门、撤销、归档越界、真实阶段恢复、取消、超时及标题超长组合。

### N3 · P1：任务完成/里程碑/授权三个状态混在一起

位置：`docs/plan/claims-market-closed-loop-plan.md:433` 及 `docs/plan/corpus-ingestion-rebuild-tasks.md` 状态摘要。

同一行既写 M4 待复核，又写“I1 全部任务完成，I2 可启动”。I1-9 本身包含全部必需用例通过；不能把“夹具与快照文件齐”代替整项完成。即使将来 M4 通过，I0-C/M3 未通过仍单独阻断 I2。

建议统一记录：`I1-9 partial：夹具及候选快照已交付，C1—C7 与验收修正未关闭；M4 blocked；I2 not_ready（M3+M4）`。如果保留旧 complete 日志，追加纠正记录，不删除历史。这里只核查到放行文字错误，没有发现本轮实际启动 I2 或操作 PG 的证据。

### N4 · P2：夹具避开困难结构，应限缩覆盖声明并保留反例

位置：统一台账 435—440 行、夹具生成器说明及 freeze coverage map。

台账明确记录：PDF 去掉有线表格；问答标题避开“实录”；条件句保持单行。为单个机制设计聚焦夹具是合理的，但不能用这些夹具证明被避开的结构已经支持，也不能让 MD/DOCX 表格替代 PDF 表格路径的验收。

建议：保持当前三件套，同时追加有线 PDF 表格、正文引用访谈/带“实录”标题、条件句换行变体的独立小反例，冻结期望为正确读取或明确复核，不强求全部自动准入。不要通过改样本使特征冲突消失。fidelity 的“covered”应拆成合成不变量、人工 source-gold 比对、格式真实样本三个维度；没有执行独立人工预期比对的部分标未验。

这是覆盖与泛化风险判断，本轮未对这三个变体另做实测，不将它们计入新增失败数，也不直接断言所有“实录”材料都应自动准入。人工金标才是相关业务预期的依据。

## 5. 建议执行顺序与放行口径

1. **先修验收台账和测试预期。** 将 I1-9 标部分完成；把完整 review 11 项纳入固定必测集合；拆开 PDF 缺口拒绝与无缺口 generation 正例。保留历史快照。
2. **修 C1—C4 的端到端约束。** 来源登记失败必须终止；scope 真正限定 units/chunks；质量及阶段完整性控制发布；明确撤销不依赖全文解析成功。普通 metadata unknown 不应被过度阻断。
3. **修 C5—C7 和执行生命周期。** 安全归档读写共用边界策略；真实计算进入受租约/时钟/取消控制的阶段；重试验证并复用检查点；覆盖标题+超长分支。
4. **验收后追加冻结。** 170 现有业务测试、31 旧探针、11 完整 review 探针及新增契约测试使用同一候选快照重验；修正 N1 后的结果按新版本记录。哈希、原始测试结果、守卫报告、静态/导入门和适用 gold 证据一致后再形成新快照，r1 保留为历史候选。
5. **分别裁决阶段门。** I1/M4 只覆盖内存链；M3 的物理方案与运行参数仍走 I0-C。两者均通过后才进入隔离 PG/真实 CLI；不把 PG 实测提前搬进本轮，也不把内存逻辑门推迟到 I2。

目前修复与补测不需要新模型额度、数据库权限或留出材料。若要改变准入政策、scope 定义或人工金标，需要另行明确批准；不通过降低这些规则换取全绿。

## 6. 最小复现命令

WSL 仓库根目录运行；不覆盖既有 XML：

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  PYTHONPATH=/home/administrator/FrontierAgent \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  CORPUS_GUARD_PHASE=i1 \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json \
  .venv/bin/python -B -m pytest --noconftest -c /dev/null \
  -p no:cacheprovider -p plugins.corpus.preparation.guard_pytest \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-i1-full-review/test_chain_contracts.py \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-i1-9-retest/test_i1_9_acceptance.py \
  -q --tb=short
```

本轮合并重验：11 failed、3 passed。快照完整性检查见本目录 `integrity-comparison.json`；它只读取列出的实现/测试/配置/快照，不读取原始材料内容。

本次按 diagnosing-bugs 的可复现信号与对照方法、codebase-design 的 Interface 约束审查方法开展：通过正式 execute/publish 路径核验行为，而不是只检查对象能否生成。没有进入修复阶段。
