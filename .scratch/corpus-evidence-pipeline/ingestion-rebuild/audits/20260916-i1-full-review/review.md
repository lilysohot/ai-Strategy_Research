# I1 全模块复核：旧缺陷复验、source/engine 集成及阶段门

日期：2026-09-16。性质：审查与受限测试，不是修复提交、阶段冻结或执行授权。

## 1. 结论

**前两轮具体缺陷已修复，本轮原探针 31/31 通过；I1 整体仍未达到验收放行条件。** 新增的 I1-7 已把模块接成可运行链路，但尚未把登记状态、批准范围、质量结果和阶段完成度变成端到端强制约束。

大方向仍正确：三类研报、确定性准备、原文可追溯、零模型、CLI 优先、内存与 PG 分阶段；未发现本轮擅自引入模型/OCR 服务、向量库或 Web 开发。局部执行顺序和发布协议偏离已定契约，另有提前放行的状态文字。需要修正控制流与阶段门，不必推倒 parser/clean/chunk 全部实现。

用户所称 I1-0 在当前清单中不存在，先行守卫任务是 I1-8。完整 I1 还包括 I1-9，不能只以 I1-1～I1-8 实现存在判定 M4。更广义 I0—I5 尚未整体完成；本次不代替 I0-C、I2/I3 真实 PG/CLI 或 I4 切换验收。

## 2. 本轮实际运行

| 检查 | 结果 | 本目录证据 |
|---|---|---|
| 前两轮原文件合并复跑 | 31 passed，0.47 秒 | previous-probes.xml |
| 当前八组正式测试 | 155 passed，34.60 秒 | current-suite.xml |
| 最终新增链路反例及对照 | 9 failed、2 passed，0.29 秒 | chain-contracts-final.xml |
| 同一最终文件重复复跑 | 9 failed、2 passed，0.20 秒 | chain-contracts-repeat.xml |
| 当前 I1 守卫合成自检 | 24/24 passed | guard-selfcheck.json |
| 整个 preparation 包 Ruff | All checks passed | 本轮命令输出 |

155 = 前轮七组 142 + engine 13；不含 guard pytest 的 19 项，故与台账 174 分母不同。31 项旧探针与正式整改测试有重复，不能累加为独立覆盖总分。9 项是定向链路断言失败，不代表真实研报的统计失败率。

最初 chain-contracts.xml 中，超长质量用例先遇到另一个标题覆盖错误；随后将它拆为「无标题超长发布门」和独立「标题+超长块」用例。另将 scope 断言精确到已发布 chunk 的范围，允许全原文继续归档。最终 11 项语义以 test_chain_contracts.py、final/repeat 两份 XML 为准，探索结果保留未覆盖。

业务测试均在收集前装载 I1 守卫，env -i、禁用 pytest 自动插件与项目 conftest。真实材料只读守卫允许的 6 份开发 PDF；新增材料全部合成。归档越界测试只在同一 pytest 临时目录里建立受控符号链接，无真实用户数据被触碰。无业务模型调用、PG/公网连接、留出读取、清库或业务代码修改。

本轮未重跑全库 Pyright、import smoke、历史财务/检索非回归或 PG/CLI E2E。代码、配置、测试和计划的 29 个文件哈希记录在 review-manifest.json；这是审查快照，**不是 M4 冻结件**。

## 3. 分任务完成度

| 任务 | 本轮判定 |
|---|---|
| I1-1 contract/repository | 已交付；旧身份/幂等/令牌反例通过。发布仍允许未登记 PUBLISHED job 的直发路径，也未强制完整性/verified 门，尚未收口 |
| I1-2 readers | 已交付；原有次序/图片/嵌套表反例通过，REV 已升到 *-2。不能扩大为所有版式和视觉区域均已正确理解 |
| I1-3 clean | 已交付；原保真反例通过。需要将台账完整传给后续 check/publish，不仅留在临时 CleanResult |
| I1-4 chunk | 已交付；旧表边界、尾标题、context 引用反例通过。另确认标题后紧接超长不可分段落仍触发覆盖错误 |
| I1-5 admission | 已交付；非法审核链/枚举及不支持政策版本反例通过。但引擎未落实部分 scope，也把明确撤销置于解析成功之后 |
| I1-6 source | 基本接收、哈希、失败返回及现有 17 测试通过；归档分片目录符号链接可使实际写入越出 archive_root，需补边界 |
| I1-7 engine | 已交付正常链路和 13 个现有测试；多项端到端门失败，不能认定完整验收通过 |
| I1-8 guard | 本轮收集前装载与 24 项合成拒绝/对照通过；不扩大宣称为完整操作系统沙箱 |
| I1-9 收口/阶段冻结 | 未找到有效完成记录及当前 I1 冻结件，且本轮必需用例失败；M4 不通过 |

I1-2/3/5 原整改用例通过不意味着独立批准整个 I1，亦不撤销它们已经完成的有效工作。

## 4. 已确认阻断与定位

### C1 · P1：发布只看批准关系，没有执行质量和阶段完成门

位置：engine.py:242、:451；repository.py:293、:501。对应架构 §8 第 1～3 条、§8.1 和 I1-1/I1-7。

三个反例均可调用正式 publish_build 成功切换活动指针：

- 必需图区被 reader 标为未读取，质量报告有缺口；
- 2000 字不可安全切分的段落带 oversized 复核记录；
- CHUNKED 写入注入失败，只留下 build 和部分阶段产物。

publish_build 仅查 build 存在后转发 store.publish。后者查当前 admission、绑定决定及 scope 标签，但不查 quality_report、单位/块完整性或 verified。PUBLISHED job 未登记时 _require_publication_ownership 直接放行；engine 自身不登记该 job，因而正常公开调用走的正是直发旁路。

建议：在内存实现就建立 check/verified 与带所有权的发布协议；I1 不伪造 FTS 已建，可明确内存适用检查，I2 再验证 PG/索引事务。任何失败或未满足范围完整性的候选均不能转 active。不能等接 PG 后才实现已有的逻辑门。

### C2 · P1：scope 只写入身份，没有约束已发布内容

位置：engine.py:179、:209、:319、:383。对应架构 §5.2、§8 第 2 条、I1-5/I1-7。

对合成 MD 仅批准 char:0-34、给出非空 locator，结果 build.scope_ref 虽保留局部标记，正文 chunk 仍含批准范围外「Outside approved scope: 987654」，且能发布。

这里不要求删除全原文归档；要求活动检索/证据处理范围受批准范围限制。当前拼接所有 reader units 和 clean/chunk 结果，没有 scope 解析、坐标核验或过滤。

建议：将审核 locator 解析成可验证的范围，再给 units 标 out_of_scope 并限制 chunk/上下文投影；无法解释的 scope 应拒绝而不是全篇降级。检查范围必须绑定 build 和 publication。增加跨范围标题/表头引用的明确规则。

### C3 · P1：来源登记失败被引擎当成成功继续处理

位置：source.py:220 附近；engine.py:353～364。对应 I1-6/I1-7。

注入 put_source 失败：source 模块正确返回 registered=False 和 error（对照通过）；engine 忽略该结果，继续准入、写 build/units/chunks，返回有 build 的正常 ExecuteOutcome，而 store.get_source 仍为空。

建议：registered=False 必须停止后续阶段，返回明确可恢复状态和归档引用；恢复登记成功后才进入内容准备。由统一结果契约约束，而不是调用者事后猜测 source 是否存在。这个问题归因于 I1-7 对 I1-6 返回值的消费，不是 I1-6 没有报告失败。

### C4 · P1：明确排除来源，却要解析成功后才能撤下活动版本

位置：engine.py:362～381、:396。对应架构准入/撤销规则。

先将合成来源正常发布，再登记完整取代链的 EXCLUDED 决定，调用同一执行入口并让 reader 抛错；旧 active_build_id 保持不变。排除动作尚未发生就被前面的解析异常打断。

内容级探查有时需要解析，但已经绑定同源哈希、历史有效的明确排除不能依赖清洗/切块成功。建议在来源身份核验后优先处理有效撤销；普通未知材料继续做受控探查。不能因撤销对象解析困难而继续保留旧活动资格。

### C5 · P1：归档实际落点没有检查父目录符号链接

位置：source.py:131～154、:196；恢复入口同样要核查 resolve 边界。对应 I1-6 的受批准归档目标。

把 archive_root/<哈希前缀> 指向同一测试临时目录下的 outside-archive，再 ingest_source，调用成功并沿链接置入内容，而非拒绝。路径字符串位于 archive_root 下不代表实际落点仍在该目录。

建议：明确归档目录信任策略，核验实际父路径、拒绝越界链接，置入采用不能被父目录竞态绕过的方式；恢复读入口也复用该策略。现有 final.exists 检查与后续 os.replace 分离，不能把原子重命名等同于并发 no-clobber 保证；竞态为待补测试，不计入本轮 9 个失败。

### C6 · P2：恢复只跳过最终写入，没有跳过已成功的解析处理

位置：engine.py:255～291、:362～364。对应 I1-7 与架构 §8 第 4 条。

首次仅 CHUNKED 写入失败、PARSED 已成功。重试时 reader 计数从 1 变成 2，然后才到 _run_stage 的 SUCCEEDED 短路。也就是说 parse/clean/chunk 都在真正 job 检查之前执行。

建议：实际计算在对应阶段内执行，检查点持有输入/产物哈希与可复用产物；先读有效检查点再决定重算。无效检查点才重算并留原因。现有恢复测试 `assert recovered.unit_count == recovered.unit_count` 是恒真断言，无法证明阶段复用。

静态缺口：engine 无取消参数/检查点消费、无心跳调度、未使用 stage_timeout_seconds；实际解析不在受管理阶段内；全过程复用同一个传入 now。repository 能拒绝 cancelled job 不能替代 engine 取消协议。上述须按 I1-7「取消/恢复可测」补齐，不能把数据库条件写入在 I2 实测解释成 I1 不需要状态语义。本轮不声称已复现每一种超时/取消竞态。

### C7 · P2：标题后跟超长段落仍会丢失标题引用

位置：chunk.py:305～310 与 :445 附近。对应 I1-4。

输入一个标题加 2000 字不可分段落，抛 ChunkError「保留区未进入任何检索块: [1]」。oversized 分支没有携带已消费的 title_ordinal，尾部 flush 也无法找回已清空的 pending title。

这是受控失败，不是静默错误发布；应保留标题引用并让超长内容进入显式复核。旧「只有一个末尾标题」已经修复，不代表这个组合场景也修复。

## 5. 状态门问题：I2 不能由本轮宣布启动

任务清单第 40 行写「I2 可启动」，下一行又写「I0-C 未启动，M3—M8 未通过」；统一台账 I1-7 回填亦有类似表述。清单自己的 §3.5/I2-1 明确要求 **M3 + M4**。

本次只发现 I0A 的冻结材料与旧守卫报告，未找到有效 I1-9/M4 收口证据；且已复现的链路失败本身阻断 M4。因此「I1 核心模块文件齐」不等于「I1 全部通过」，更不等于 I2 获得执行前置。

建议追加本轮状态回填，明确 I1-7/I1-9 待整改验收、M4 未过、I0-C/M3 未过；旧日志保留。不修改本次之外的预算、物理方案或数据库授权。本轮没有实际启动 I2，也没有证据表明已越权操作数据库；问题是放行文字错误。

## 6. 工程结构与验收提升

### 保留的正确方向

- 单一 preparation 入口、source 字节身份、归档副本解析、原始文本与派生视图区分；
- 旧反例已进入正式回归，前两轮文件未由本轮修改，规则行为版本已升级 *-2；
- 存储写入开始落实令牌/时钟约束，有限重试与明确异常保持；
- reader、存储及时钟可注入，能用合成材料独立复现故障而不用模型调用。

### 当前关键偏差

把「模块能返回对象」当成「阶段已完成」；把「状态字段存在」当成「状态已经参与控制」。表现为 registered=False 被忽略、scope 只是标签、quality_report 只是字符串、SUCCEEDED 只跳写库、publish 只转发。

因此下一步应按**端到端不变式**闭合，不建议继续按文件逐个加 if 后就宣布完成：

1. 每个阶段输出明确成功/失败/待复核/可恢复状态，后继消费状态而非仅消费 payload；
2. 当前审核与范围是构建约束；完整性检查是发布前置；撤销资格不依赖全文解析成功；
3. 执行协议管理实际工作、可验证检查点、取消和时钟；内存与 PG 共享同一行为契约；
4. 发布不允许任何无 job/no-check 的备用路径，generation/token/当前审核各司其职；
5. I1-9 用独立测试验证上述关系，再冻结实现/测试/配置/结果。

### 尚需明确但未加入本轮失败计数的事项

- engine 的质量 JSON 目前主要保存 gap key 和 oversized chunk ID；合成缺口不成为 Unit，详细 bbox/状态/原因不能都依靠一个 key 留存。应定义完整质量账本的持久表示。
- context_refs 在候选块中有独立身份，但 engine 合并到普通 unit_refs 后丢掉 core/context 区别；source_ranges 未装配。后续取证要保留角色和范围，不能由 consumers 猜回。
- 小图虽然不再无记录消失，但 `<25%` 一律映射 NOISE 未证明就是装饰。需开发 gold/明确图类依据验证，不应仅凭面积判断业务重要性。
- 政策加载已拒绝未知版本；人工材料类型/领域凭证、日期 known 必有依据等前轮静态建议仍应纳入输入契约收口。

本次对既有运行消费者的引用搜索未发现 service/tools/CLI/kernel/workflows 已接入新 preparation 运行链。故目前是候选实现验收问题，不等于旧线上数据已被污染；但也没有重跑旧财务/检索基线，不能宣称其他研报已被全面证明不受影响。

## 7. 建议执行顺序及需要人工参与的部分

1. 先更正放行状态，再修 C1/C2/C3/C4：登记、范围、质量、撤销、发布强制闭合。
2. 修 C5 与 C6：安全归档、真实阶段恢复、取消/心跳/截止时间协议；修 C7 标题超长组合。
3. 保留 31 个旧探针与 155 项现有测试，纳入本轮 11 项链路测试及缺失的取消/故障恢复用例；不改预期适配已知错误。
4. I1-9 按冻结清单验证开发 source-gold 的独立锚点、接口不变式与版本，运行静态/导入门，产出阶段快照。现有 6 份 PDF 的 engine smoke 都没有人工准入，build=None，不能充当真实开发材料从批准到发布的完整验证。
5. M4 真正通过后，仍须先完成 I0-C/M3，才能进入 I2 的隔离 PG/真实 CLI 实测。

修这些工程问题目前不需要新材料、模型预算或数据库权限。若要改变 scope 语法、准入政策、金标口径或原定 gate，应另行说明并确认，不通过降低验收标准换取全绿。

## 8. 复现入口

在 WSL 仓库根目录执行：

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  PYTHONPATH=/home/administrator/FrontierAgent \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  CORPUS_GUARD_PHASE=i1 \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json \
  .venv/bin/python -B -m pytest --noconftest -c /dev/null \
  -p no:cacheprovider -p plugins.corpus.preparation.guard_pytest \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-i1-full-review/test_chain_contracts.py \
  -q --tb=short
```

当前 9 failed、2 passed。将目标替换为前两轮探针为 31 passed；替换为 contract/readers/clean/chunk/admission/remediation/source/engine 八个 tests 文件为 155 passed。同一报告不混用分母；新运行另存结果，不覆盖旧 XML/报告。
