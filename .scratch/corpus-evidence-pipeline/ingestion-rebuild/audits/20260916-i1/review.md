# I1-1～I1-5 独立验收复核

日期：2026-09-16。性质：当前工作区验收审查，不是修复提交或阶段放行。

## 1. 结论

方向没有脱离三类研报、确定性基础处理、原文权威、CLI 优先、零模型的项目目标；无需据此推倒整体架构、引入 LLM 清洗或扩大材料范围。但不能维持 I1-1～I1-5「验收全部通过」的强结论，应区分「实现已交付」和「存在验收阻断、需修正复验」。

主要问题不是模型能力或电话纪要，而是：**规范中的约束尚未全部成为接口不变式；结构和缺口在读取端丢失；原测试覆盖了正常路径，但未覆盖足以推翻完整性声明的边界。**

清单没有 I1-0；先行守卫任务是 I1-8，本次一并核查。M4 仍依赖 I1-6/I1-7/I1-9，不能将这些后续未实现事项算作本轮违规，也不能以当前模块测试替代完整 I1 或 PG/CLI 验收。

## 2. 实测范围与证据

| 检查 | 本次结果 | 解释 |
|---|---|---|
| 现有 contract/readers/clean/chunk/admission 测试 | 110 passed，19.74 秒 | 包含守卫允许的 6 份开发 PDF；不包含 19 项 guard pytest，故不是历史总数 129 的同一分母 |
| 新增合成反例，第一轮 | 15 failed，0.47 秒 | 通过当前公开模块接口构造边界；失败断言表达应满足的规范 |
| 同一反例 + 正向对照，第二轮 | 15 failed、5 passed，0.29 秒 | 确认复现稳定；不是随机抽样，不能解释为总体失败率 75% |
| 当前 I1 守卫合成自检 | 24/24 passed | 合成文件、模拟 socket 审计事件、导入拒绝和子进程继承；无真实 PG/DNS/公网连接 |
| 限定实现文件 Ruff | All checks passed | contract/repository/readers/clean/chunk/admission；不自动格式化 |

产物均在本目录：`existing-tests.xml`、`acceptance-probes.xml`、`guard-selfcheck.json`、`test_acceptance_probes.py`。

所有业务测试在 pytest 收集前装载 I1 守卫，使用清空后的进程环境、禁用 pytest 插件自动发现和项目 conftest。未读取真实留出集，未调用模型，未连接或清理数据库，未修改正式源材料、生产实现和任务状态。合成文件位于 pytest 临时目录。本轮仅新增审计文件；诊断用失败测试有意不放进常规 tests/。

未重跑全库 Pyright、全库测试、import smoke、历史财务/检索非回归、真实 PG 和 CLI E2E，不能把本报告当作那些门的通过凭证。

旧 I1-8 自检绑定的 6 个文件中，5 个哈希一致，`preparation/__init__.py` 哈希变化；当前该文件仅包说明，无可执行导入。新自检已绑定当前哈希并通过；历史报告不覆盖或改写。

## 3. 任务判定

| 任务 | 实现情况 | 本次验收建议 |
|---|---|---|
| I1-8 守卫 | 已交付，本轮受限执行和合成自检成功 | 在本次范围内通过；保留环境隔离边界，不扩大为操作系统级沙箱保证 |
| I1-1 契约/内存存储 | 已交付，17 项现有测试通过 | 需重新打开验收：发布、当前决定、所有权和重试上限有反例 |
| I1-2 读取 | 已交付，14 项现有测试通过 | 需重新打开验收：阅读顺序及未读取区域记账不完整 |
| I1-3 清洗 | 已交付，13 项现有测试通过 | 需补保真校验反例；本次证明校验器可漏报，不是证明正常清洗器必然改写数字 |
| I1-4 切块 | 已交付，14 项现有测试通过 | 需重新打开验收：表边界、尾部标题和上下文长度失败 |
| I1-5 准入 | 已交付，52 项现有测试通过 | 需重新打开验收：非法审核值和不完整取代链可被纳入 |

以上是审查建议，不是已修改统一状态。历史通过记录应保留，新增本轮反例和 remediation_required 状态，不抹掉旧结果。

## 4. 已复现缺陷与归因

### F1 — P1：旧决定可覆盖撤销和缩小后的 scope

位置：`plugins/corpus/preparation/repository.py:179`、`:223`。

三个独立反例：

1. 写入 d0=准入、d1=撤销后，重放相同 d0，将 latest_admission 从 d1 倒退成 d0。
2. d1 撤销且 retire 后，调用 publish(d0, old_build) 仍成功。
3. d1 仅允许 page:1，却可用 d1 发布绑定 d0 的全篇 build。

原因：put_admission 将「不可变历史追加」和「无条件更新当前指针」混在一起；publish 只检查所传决定为 in_scope，没有核对当前决定、build 所绑定决定及 scope。接口没有 expected_generation 参数。

影响：今后重试、撤销或部分准入可能重新暴露被排除内容，不符合架构 §8 第 3/5 条及 M1 publish 约束。

建议：将历史登记与当前决定推进分开；发布在存储边界检查 current decision、build/scope、verified 条件与 generation。重复提交必须按已提交操作身份返回原结果。应在 I1 修好内存协议，I2 再验证真实 PG 条件写入，不等到 I2 才定义语义。

### F2 — P1：租约只保护作业状态，没有覆盖权威输出；过期接管绕过次数上限

位置：`repository.py:198`、`:211`、`:272`。

反例：worker A 过期、B 接管后，仍能通过无 owner/token 的 put_units 接口写入 A 的新产物。另将 max_attempts=2，连续两次过期接管后仍能取得 attempt=3。

原因：put_units/put_chunks/publish 不携带或验证所有权；acquire_job 仅对 failed 检查 max_attempts，未对过期 running 检查。stage_timeout_seconds 虽在配置中存在，当前存储路径尚未体现截止逻辑。

影响：当前心跳/finish 的 fencing 并不能证明「旧 worker 停写」，可能产生陈旧产物、确定性冲突或无限接管。M1 明确要求 I1 内存实现保留同一次序与幂等语义，因此不是单纯延后的 PG 实现细节。

建议：权威写入使用同一受保护提交接口，绑定 job/attempt/token；次数上限覆盖所有重试/接管路径。engine 与 repository 明确超时和提交责任，避免由调用者先检查后无条件写入。

### F3 — P1：PDF 同页标题和正文失去交错顺序

位置：`readers/pdf_reader.py:295`～`:343`。

合成页面原序：Section A → A body 1 → A body 2 → Section B → B body 1 → B body 2。

实际输出：Section A → Section B → A body 1 → A body 2 → B body 1 → B body 2。

原因：遍历行时先发射所有 heading，正文累积到循环后统一发射；表格又在更后面的独立循环追加。单标题对照通过，多标题交错失败。

影响：字符即便全部存在，章节归属也已错误。下游 chunk 按 ordinal 建立标题关联，可能把 A 正文归到 B；这是原始结构错误，不是模型问题。

建议：先形成含位置和类型的有序区域流，在遇到标题/表格/列边界时 flush 已累积正文；保留原提取顺序与重建顺序的区别。增加两标题、多表格、跨栏的关系断言，而不只验证标题存在和正文数量。

### F4 — P1：混合 PDF 图片和 DOCX 嵌套表格可无记录消失

位置：`readers/pdf_reader.py:246`、`readers/docx_reader.py:106`～`:119`。

反例一：同页有少量可读标题及大幅图片，结果只有 kept 的标题，issues 为空。因为仅在整页完全无文字时才检查图片。

反例二：DOCX 外表格单元格内含嵌套表格「Revenue 1234」，读取只保留外层文字，issues 仍为空。cell.text 没有覆盖嵌套表格；表内元素也未经过段落级 unreadable 检查。

影响：后续 clean 台账只覆盖已经被 reader 发现的单元，无法恢复未被发现的区域，不能据此声称全文无缺口。

建议：页/正文/单元格都有元素枚举及分类台账；未读取区域至少记录坐标、类型与原因。图片不必统一升级为整篇 OCR，也不能因为标题可读就忽略主体；可明确标注为装饰噪声、待复核或 needs_ocr。嵌套表格可以递归支持，也可以先显式复核，但不能静默丢失。

### F5 — P1：未决审核值和不完整取代链被当成有效批准

位置：`contract.py:362`～`:381`、`admission.py:252`～`:267`、`:367`。

反例一：ReviewedDecision(decision="pending") 未在构造时拒绝，decide_admission 返回 in_scope。因为仅判断 excluded 两种状态，其余全部进入 admitted 分支。

反例二：A supersedes B、B supersedes A，另有无关 C。程序发现唯一 tip=C 就放行，未识别另一连通分量中的环。

影响：JSON/人工输入边界一旦接入，静态类型提示不能防止未决材料上线；不符合「未决不能发布」和「成环冲突」的明确声明。

建议：边界严格解码/校验枚举，只有显式 ADMITTED 才可进入批准分支；取代链检查 ID 唯一性、环、断链、分支及全部记录是否得到唯一有效历史解释。简单唯一 tip 不等于历史有效。

### F6 — P2：保真校验器能接受清空和重排

位置：`clean.py:118`～`:156`。

两个最小反例均未报错：verify_clean_region("12", "", ())；verify_clean_region("12", "21", ((0,1),(1,0)))。

原因：空 clean_view 直接返回，未检查非空白原文；字符覆盖使用集合，逐字符虽然都能回原文，却不验证原文映射顺序和重复覆盖。

边界说明：本次没有证明正常 _clean_pieces 会产出 "21"；证明的是验收器不能独立守住其声明的空白投影不变式。None 作为噪声/复核状态没有 clean_view 可以合理，但应与 kept 非空原文被清空区分。

建议：对于保留区要求非空白序列相等、原文偏移有序且非重复，并明确允许的空白转换。增加空串、反向、重复、漏首尾等变异测试。验收器不能仅校验自产映射的自洽性。

### F7 — P1/P2：切块丢失表格边界，另有末尾标题和 context 长度失败

位置：`readers/md_reader.py:103`～`:108`、`chunk.py:147`、`:288`、`:306`。

三个反例：

1. 两张以空行分开的 Markdown 表（2025 revenue、2026 margin）被合成一个 table chunk，未保留 table identity/关系边界。原因：reader 无 table_id，chunk 分组键均为空。这是 P1 结构混淆风险，不等于已经证明某个真实单元格被改写。
2. 文档仅一个标题，最终 pending_title 没有 flush，抛「保留区未进入任何检索块」。这是 P2 可用性缺陷；当前 verifier 有效阻断，不能描述为静默发布丢字。
3. 表头和数据行各约 994 字、分别低于 1800，续块加回表头超过 1800，抛「超上限却无复核标记」。原因：空 current 分支不计 context 长度；缩短表头的对照通过。这也是 P2 受控失败，尚非错误发布。

建议：reader 输出稳定 table_id、header/body 角色与列关系；chunk 保留核心区与引用上下文的区别。所有 append 分支统一计算「上下文＋正文」实际长度；无法安全容纳时引用式关联或显式复核，不截断。循环结束及 oversized 分支都应处理 pending title。

## 5. 为什么旧测试全部通过

不是测试造假，而是覆盖不足，且部分验收使用了实现自身定义的分母。

- 发布测试只验证用「新的 excluded 决定」发布会拒绝，没有验证「撤销后重放旧 admitted」。
- max_attempts 测试只覆盖 failed 重试，没有覆盖 expired running 接管。
- PDF 测试使用单标题，没有同页多个标题与正文交错；只检查纯图片页，未检查文本与图片同页。
- DOCX 图片测试位于正文段落，没有嵌套表格/表内对象。
- 现有「无后文标题」用例其实是连续两个标题后接正文，没有触达文件末尾 pending title。
- 6 份开发材料的 clean/chunk smoke 使用 reader 已提取单元与实现自己的 verifier。它们能检查输出一致性，但 reader 根本没提取的内容不在这个分母里。

建议把三层门分开：合成协议/性质测试、独立人工源锚点比对、真实 CLI/PG 非回归。不能为 I1 提前声称 I3 金标或留出已过；但 I1 已承诺的结构和缺口反例必须补齐。扩充合成边界不会污染真实留出集。

## 6. 工程提升与责任边界

1. **存储接口自身拒绝非法状态。** 本轮采用 codebase-design 的接口不变式视角；不要把关键校验全推给未来 engine。MemoryStore 和 PG Store 共用行为契约，PG 额外测试真实事务竞争。
2. **中间数据不要提前丢结构。** CandidateUnit 应足以表达表归属、标题层级、阅读次序和未读区域；ChunkCandidate 应能区分核心范围/context。引擎事后不能可靠猜回这些信息。
3. **将 gold 与运行参数隔离。** 运行时不读答案；验收独立引用冻结开发 gold，禁止因当前输出而修改预期。现有冒烟和表驱动夹具不自动等于完整人工金标消费。
4. **政策版本必须真实绑定规则。** 静态检查发现 load_admission_policy 接受任意以 v 开头的版本，却总返回硬编码 v1 domains，探查表达式也仍为 v1。当前 v1 不因此判错，但未来升级会错误标注实际执行版本；应白名单支持版本并校验策略内容/哈希，或编译受限确定性规则。
5. **补齐元数据边界。** ReportPublication 的 known 状态目前不强制 evidence_refs 非空；人工材料类型/领域尚未在 ReviewedDecision 中显式承载，domain_hint 仍来自登记元数据。应在接入输入解码前明确批准凭证与建议字段的责任，不能仅靠名称和类型注释。
6. **状态与证据同版本。** 本次相关实现多为未跟踪文件，旧运行日志未全面绑定当前 I1 实现哈希；后续阶段冻结应绑定代码、测试、政策、配置、结果，不用通过计数单独充当验收证据。

本轮未发现新 preparation 路径已接入旧 service/search/fetch 的运行消费者；因此缺陷目前主要位于未切换的候选实现。搜索引用结果不等于完整非回归证明，仍需后续按 baseline-bindings 重验旧财务、检索与三类研报。不能声称「其他原流程已证明完全不受影响」。

## 7. 推荐下一步

1. 保留既有测试和历史记录，把本轮 15 个反例转成正式回归测试；给 I1-1～5 增补本轮验收未通过的状态，不删除原分数。
2. 先修 F1/F2/F5（决定、发布、所有权），再修 F3/F4（读取顺序和完整分母），最后修 F6/F7（保真与切块）。限定零模型、合成样本＋6 开发材料，不用保留集调试。
3. 复验：110 项现有测试＋本轮 20 项诊断/对照，守卫 24 项；补 lint/types、阶段 import smoke 与独立 source-gold 开发锚点验证。固定代码/规则/测试哈希并记录结果。
4. 上述局部验收闭合后再将其作为 I1-7 engine 的可信依赖。I1-6 可在明确独立边界内开发，但不能据此越过验收阻断。I1-9/M4、I0-C/M3 仍按原任务依赖收口，真实 PG/CLI 留在 I2，不清库、不恢复 R2 模型实验。

这些修复目前都能通过工程反例推进，无需用户新增材料、数据库权限或模型预算。若要改变冻结准入政策或 gold，则另行解释并取得确认。

## 8. 复现命令（WSL，仓库根目录）

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  PYTHONPATH=/home/administrator/FrontierAgent \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  CORPUS_GUARD_PHASE=i1 \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json \
  .venv/bin/python -B -m pytest --noconftest -c /dev/null \
  -p no:cacheprovider -p plugins.corpus.preparation.guard_pytest \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-i1/test_acceptance_probes.py \
  -q --tb=short
```

本次预期诊断输出：15 failed, 5 passed。修复后应全部通过，不应调整断言去适配已知错误。现有测试命令使用相同环境和 pytest 参数，将目标替换为五个 `tests/test_corpus_preparation_{contract,readers,clean,chunk,admission}.py` 文件。

守卫：`.venv/bin/python -B -m plugins.corpus.preparation.guard --config .scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json --selfcheck`，同样在清空后的环境运行。历史报告是 write-once，新运行不得覆盖本目录已存在的 JSON/XML。

## 9. 被审查实现 SHA-256

| 相对路径 | SHA-256 |
|---|---|
| plugins/corpus/preparation/contract.py | 6dc26767319649a63c121418286d98e2099b14690d711ae51df47fc7640bf10b |
| plugins/corpus/preparation/repository.py | bbd725a0898c770251de0d3966ebc2c519e94d1d87288f7d165407695329f793 |
| plugins/corpus/preparation/admission.py | c24797efa0d7feede59c655b9d2ad3a0438f3c05eb1dc23539388dbe9df34b72 |
| plugins/corpus/preparation/clean.py | f37ef6d06f5057d9ecbaf8f63216324f1319361c671d17aa41406c554a8edd85 |
| plugins/corpus/preparation/chunk.py | 3c8fb928497f95b554d24bbac97dbf6b5685926421bdc9acb1a895df89c1716b |
| plugins/corpus/preparation/readers/pdf_reader.py | 813fd8892bfd3cb6bd417879904e21a1f07dc9bd843ca88d9ca41cbf723fc43e |
| plugins/corpus/preparation/readers/docx_reader.py | 31dcbbfd96204af3391d4c5029235ac0917d929f5d8e125a487f2e62df934484 |
| plugins/corpus/preparation/readers/md_reader.py | 2856a5531931a72ca41812596626e00dfe8baab1d9513b3e705be44773acc404 |

守卫代码/配置哈希见本目录 `guard-selfcheck.json`；本报告只对上述当前实现负责。
