# R2 语境保留与材料语义抽取

Status: partial
Execution: v13-final-item-failed-current-design-stopped
Requirements: PR-DATA-02, PR-DATA-09, PR-DATA-10
Depends on: R1 / 19

样板复盘：[R2 材料语义抽取：失败驱动优化样板案例](../r2-optimization-case-study.md)

当前下一步：[局部重设计与 CLI 闭环计划](../../../docs/plan/r2-local-redesign-cli-closure-plan.md) P4-A。
plan-v13：P3-I人工桥接全approve。P4冻结35 item/最多5调用/0重试预算后，首批真实调用的8行中
4行违反semantic枚举并触发fail-stop，余下4批未发送。字段回溯同时发现speaker事实不可观测、
null/unknown applicability、复合value保真和跨轴规则仍缺接口表达。P4未通过，先做scratch零模型
P4-A；P5关系、PG、入库、holdout继续冻结。
见 [PG只读核查报告](../r2-p2b-pg-readonly-report.md)；原[P2-B](../r2-p2b-report.md)及
[偏差报告](../r2-p2b-guard-incident.md)保留历史结论，不追溯放行。
最新见[P3报告](../r2-p3-report.md)、[P3-R报告](../r2-p3r-report.md)与
[P3-S报告](../r2-p3s-report.md)、[P3-H报告](../r2-p3h-report.md)与
[P4前置契约缺口报告](../r2-p4-readiness-contract-gap-report.md)。
[P4有限item试验报告](../r2-p4-item-report.md)。

## 交付与验收

- 复用 EvidenceRun 和统一入口，补齐章节/相邻段/表格解释的必要语境取回，不无限拼长输入。
- 候选入口覆盖纯定性判断、非数值预测、问答和交易记录；保留噪声负控。
- 保留原文发言归属、条件、否定和风险；问句不作承诺，交易意图不作成交，事后解释不倒填。
- 观点关联明确论据；原文关系与系统推断分开，没有依据时返回未知而非自动建联。
- 通过冻结开发金标及负控；已有数字、财务门禁和旧版本读取回归不退化。
- 不新建独立 claims 规则或自动改写旧源文件，不宣称通用 OCR/所有会议类型已覆盖。

## Comments

2026-09-13：已实现依附既有 `EvidenceRun` 的 `MaterialRun`、未入库路径入口、无数字问答召回、
发言者/行为/关系/逐字引文的失败关闭及 8 项新增测试；76 项相关回归通过。使用冻结 4 份开发材料
完成基线加两次规则修订，连同诊断共 18 次正文调用，未运行留出。最终开发 item recall 12/24、
critical recall 11/23、关系 recall 1/5；行业问答包和铜箔纪要第二包结构失败。未达到冻结门槛，
按停止条件结束调参，R2 保持 partial，R3 不启动。详见 [开发验收报告](../material-semantics-report.md)。

2026-09-13：用户授权执行 R2 结构重设计，并要求重新冻结预算、只使用开发集。新增独立预算清单
`r2-redesign-development-budget-v1.json`，不改写 R1 金标：限定 4 份 development、最多 2 个完整
轮次、每轮最多 8 次且累计最多 16 次正文调用、单文档每轮最多 4 次、holdout=0。先完成字段优先级、
结构感知分包、逐记录容错和确定性测试，再运行 `redesign-baseline`；是否使用唯一一次纠偏轮由基线
失败证据决定。

预算冻结前的确定性预检发现 `packet_chars=4000` 会产生 152 字尾包，因此在任何模型调用前将冻结值
定为 4100；铜箔纪要由 4 包变为 3 个完整话轮包，整轮计划调用由 7 降为 6。此后不再依据模型分数
修改该参数。

结构重设计两轮已执行，每轮实际 6 次、累计 12 次正文调用，holdout=0。基线 item 20/24、critical
19/23；纠偏轮 item 17/24、critical 16/23，仍有行业问答 failed packet 和铜箔 partial packet。
公司研报与个人复盘在纠偏轮全字段通过，但整体门禁未通过。按冻结停止条件结束；剩余总量护栏不是
第三轮授权，R2 保持 partial，R3 不启动。详见 [结构重设计报告](../material-semantics-redesign-report.md)。

2026-09-13：用户授权继续 R2。已冻结 `r2-jsonl-development-budget-v2.json`：只用 4 份 development，
最多 2 轮、每轮 16 次、累计 32 次、单文档每轮 8 次、holdout=0；3000 字结构包分 items/relations
两阶段，items 每包最多 30 条，failed/partial 原始响应仅本地 0600 留存。先完成协议、审计和确定性
测试，再消费 `jsonl-baseline`。

JSONL 两阶段的两个冻结轮次已消费：基线 7 次、纠偏 13 次，累计 20 次，holdout=0。基线 7 个包
均因模型枚举别名不符合严格 schema 而失败；受控审计后增加确定性归一化，最终 item 14/24、critical
13/23、关系 2/5，mapped relation precision 仅 50%。行业问答因匿名作者 display_name=null 级联失败；
个人复盘与铜箔纪要仍有归属漂移，关系阶段明显过建联。JSONL 已消除成功包截断，但没有解决关键
语义门禁。按最终轮失败停止，剩余总量余量不是新轮次授权；R2 保持 partial，holdout 未运行，R3
不启动。详见 [JSONL 两阶段报告](../material-semantics-jsonl-report.md)。

2026-09-13：按用户授权执行结构能力/槽位路线，并冻结
`r2-capability-development-budget-v3.json`：只允许一次 4 文档开发轮，计划 14、硬上限 16，
holdout=0；新增无标签光模块 DOCX 仅作零模型压力样本。先加入结构能力分级、确定性表达者兜底、
候选槽位台账、容量饱和检测和受限关系候选，再运行唯一 `capability-baseline`。

本轮实际 12 次、无重试：item 20/24、critical 19/23、semantic 18/24、attribution 8/24、
关系 1/5。mapped relation precision 为 100%，但 35 条额外关系因金标非穷举不能判为真或假；
铜箔 1 个不含金标目标的包调用超时，3 个关键遗漏来自成功包。离线回溯因此把包级槽位继续细化为
结构段内多信号义务，并将匿名 display name 合法化、来源元数据表达者与文档声音区分；版本升为
`material-semantics-9`，没有再次调用模型。R2 仍为 partial，预算关闭，holdout/R3 均未启动。
详见 [结构能力报告](../material-semantics-capability-report.md)。

2026-09-13：按建议口径补齐 6 个 development 微型穷举范围，冻结 35 个 item、17 条原文明示关系、
8 条负关系及 5 个排除片段；来源哈希和引文唯一性全部通过。零模型回放既有 capability-baseline：
item 9/35、关系 1/17；穷举范围内关系 precision 1/2，并命中 1 条明确负例（把 CEO 买入事实推成
作者加仓的 `supports`）。此前 mapped precision 100% 只是非穷举评分造成的高估。失败同时出现于
公司研报、行业问答、个人复盘与铜箔纪要，主因确定为跨类型的完整性、原子化和关系设计，而非仅是
电话纪要格式。没有新增模型调用、没有访问 holdout、没有入库；R2 继续保持 partial。

2026-09-13：按用户要求增加跨类目不退化硬门禁。`r2-non-regression-policy-v1.json` 绑定 R1 金标、
微型穷举金标、当前 material report 与 micro score 的 SHA；保护全部 4 个 development 样本和 6 个
微型范围。所有逐类指标只能持平或改善，已完成的公司/行业/个人包不得新增 failed/partial，铜箔也
不得超过当前 1 个失败包；负关系命中和关系误报不得增加。验收器对当前基线通过，并用内存构造的
公司 item recall 1.0→0.8 回退验证会失败。该门禁不把现有低分当作 R2 放行标准。

2026-09-14：按用户确认的“系统生成有限、可核验原子义务，模型逐项填写”路线完成 v10 单轮开发
验证。冻结预算 `r2-atomic-development-budget-v4.json` 只允许 4 个 development 类目、35 次 item
调用、关系调用 0、holdout 0；实际严格消费 35 次，无重试、无入库。选定联合金标 item/critical/
semantic 均为 24/24，attribution 23/24；四类 item 轴相对同评分器基线均未退化。6 个穷举微型范围
item 为 31/35（88.6%），precision 31/32（96.9%），8/8 可判负关系均未误建。

本轮仍不通过 R2：关系按预算显式延期；critical all-fields 仅 1/23；铜箔归属错 1 项；覆盖台账发现
7 个槽仍容纳多项、铜箔 39 个槽缺 coverage，说明 16 槽批次偏大。正式跨类目门禁因 partial/关系
延期而失败，未被解释成通过。预算到此关闭，未运行 holdout/R3。随后只做离线 v11 修正：强制每槽
最多保留一个 item、每槽只返回一条 item/no-supported 终态记录、问题/行为/风险信号按语义优先级
归一、被引述者不再被当前发言人覆盖、关系候选
改为逐对 present/absent 且缺项即 partial，并补充连接词边界；29 项 R2 单测及 371 项 corpus 回归
通过，但 v11 尚未消费新的模型预算。详见 [原子义务轮报告](../material-semantics-atomic-report.md)。

2026-09-14：冻结并消费 `r2-v11-atomic-items-budget-v5.json` 的唯一 item 轮：4 类 development、
6 个穷举微范围、40 槽、`max_slots_per_batch=6`，实际 9/9 次调用，无重试、关系 0、holdout 0、
无入库。结果为 29/35 item、precision 29/30，槽终态仅 30/40，item 门失败，因此没有冻结关系预算。

原始响应复核确认 6 个行业 item 已被正确抽取但统一漏 `candidate_slot_id`，旧校验器将其全丢弃；
零调用唯一引文回绑恢复 6/6。其余系统根因为完整问句在“但”前过切、future/behavior 词法信号替代
语义评分、两处“明白”寒暄误建候选。离线修正升为 `material-semantics-12`，修正后 37 个确定性槽仍
一对一覆盖 35/35 金标；34 项 R2 单测、376 项 corpus 回归、Ruff、目标 Pyright、两阶段 import smoke
及 symbol closure 均通过。该证据支持再做一次同规模 item 复验，但不支持追溯性放行 v11 或提前执行
关系。详见 [v11 item 终态验收报告](../material-semantics-v11-item-report.md)。

2026-09-14：按用户授权另行冻结并消费同规模 v12 item-only 预算
`r2-v12-atomic-items-budget-v6.json`。范围仍为 4 类 development、6 个穷举微范围，但按离线修正后的
确定性结果冻结为 37 槽；每批最多 6 槽，唯一轮次实际消费 9/9 次，无重试、关系 0、holdout 0、
无入库。37/37 槽均获得唯一合法终态，v11 的 6 个漏 ID、问句过切、信号误拒和两处寒暄槽均未复现，
因此 item 终态协议通过。

冻结微型 scorer 仍仅为 33/35 recall 与 precision：铜箔总结和听音各有一个对应 item，但模型使用的
最短唯一引文只是金标长引文子串，长度相似度低于 0.5，被评分器判成漏项+额外项。零调用 containment
审计可唯一恢复到 35/35，但执行后诊断不能追溯性放行。字段审计还显示 statement/speech role 各 60%、
perspective 85.7%，temporal/unknown 精确口径严重不一致。故 v12 总门保持失败，关系预算未冻结；下一步
必须先离线冻结 item 身份和字段验收契约，再决定是否使用最后一次优化机会。详见
[v12 item 复验报告](../material-semantics-v12-item-report.md)。

2026-09-14：完成下一步零模型任务。新增并冻结 `r2-item-acceptance-policy-v2.json`：item 身份采用
一对一唯一包含优先、相似度兜底，短引文仍须在 source packet 唯一回取；字段验收不再比较自由文本
`unknown_fields` 的精确集合，而是比较身份、时间、数值、外部核验、归属、话轮切分六类 uncertainty
axis。新 scorer `verify_material_item_contract_v2.py` 不覆盖 v12 原结果。

v12 回放确认 item recall/precision、证据唯一性均为 35/35，semantic 91.4%、condition/risk 100%；
但 speech structure 57.1%、attribution 85.7%、polarity 94.3%、behavior state+temporal 0/2、value 80%、
unknown axis 6/50，仍有 9 个契约关键错误。Ruff、Pyright 和 34 项 R2 单测通过。该结果支持最后一次
“系统接管字段”优化，不支持继续提示词调参或启动关系；最后一次仍失败即停止当前 R2 设计。详见
[item 验收契约 v2 报告](../material-semantics-item-contract-v2-report.md)。

2026-09-14：完成最后一次 v13 item 优化与验收。先将表达结构、归属、极性、行为时间、明确数值和
未知轴改为系统约束；v12 的 9 份原始响应零调用回放达到 35/35 item，所有核心字段门通过，关键错误
0。381 项 corpus 回归、目标 Pyright、Ruff、两阶段 import smoke 和 symbol closure 均通过；仓库全量
Pyright 仅被现有未安装的 Gradio/SQLAlchemy/Argon2 可选依赖阻断。

随后冻结并一次性消费 `r2-v13-final-items-budget-v7.json`：同一 4 类 development、6 个微范围、
37 槽，9/9 次调用，无重试、关系 0、holdout 0、入库 0。真实复验 item v2 为 34/35 recall、
34/34 precision；除召回外，semantic 91.18%，结构、归属、极性、行为时态、数值、证据和未知轴均
通过。唯一缺失是公司“强推”评级：模型返回了正确 item，但最短引文在 packet 内出现两次，被唯一
回取拒绝，导致 1 个槽 partial、关键错误 1。按预先冻结的 stop rule，当前 R2 设计在此停止，不修补
重跑、不冻结关系预算、不访问 holdout，R3 不启动。详见
[v13 最终 item 验收报告](../material-semantics-v13-final-item-report.md)。

2026-09-14 计划同步：用户要求先统一基线、明确公共模块禁止修改范围，重设计 R2 Interface 与验收器；
零模型反例、旧流程隔离及逐类非回归通过后才冻结新预算。Web 暂缓，后续 R3/D1/D2/A1/V1 优先
CLI 链路。已编制上述计划并同步总清单；本条不授权模型调用、不改历史分数或金标，不表示已实施。

2026-09-14 P0 执行：用户授权补齐八项条件并启动 P0。新增严格基线保护工具、18 项正反控、合成
行为快照和 write-once 审计包；2336 个代码/配置/测试文件、54 个资产已绑定，v12/v13 各 9 份 raw
完整且 hash 匹配。旧工程 605 项、新工具 18 项通过；R2 禁用重复子集 169 通过/1 跳过，三份快照
逐字一致。生产实现/旧 scorer/预算/gold 未修改，真实模型/市场/入库/生产 PG 均为 0。P0-A passed，
P0-PG 因隔离实例及扩展未验证而 not_verified，整体 P0 partial；未开始 P1—P9。

2026-09-14 P1 执行：用户授权按清单继续下一步。已冻结新 Interface、来源/义务粒度、终态、评分
契约及兼容/例外表；新增纯规划可执行规格，六组12个合成场景与来源/容量/伪造完成等负控合计
65项测试通过。保守结构候选仍标 atomicity=not_verified，复杂依赖无损保留 unresolved，不把
规划通过冒充真实研报原子化或内容忠实度通过。旧35项目标的原子分母仍需 P3 差异裁决。
执行前后 P0 保护校验通过，新的 R2 禁用快照与原冻结快照相同；未改生产、旧 scorer/gold/预算，
真实模型/市场/入库/holdout 原文访问均为0。P1设计完成，下一项P2 scorer/mutation后私有处理，
本轮未启动P2。详见 [P1报告](../r2-p1-report.md)，P0-PG继续未验证，R2整体partial。

2026-09-14 P2-A执行：用户授权继续任务，按“先scorer与反例、后私有执行”完成第一段。
新增独立item evaluator，绑定完整输出与裁决hash，显式min/max与全部预测/目标分母，十字段轴
独立评分；重复短引文合法定位、内容改写后的旧裁决失效、空输出/全拒绝、未知矛盾、代理假批准等
73项新合成测试通过。连同P0工具18项、P1规格65项共156通过；Ruff、目标Pyright、两阶段import
smoke及符号检查通过，R2禁用快照与P0完全一致。未改生产/旧scorer/gold/预算，无真实模型/市场/
入库/holdout原文访问。当前审计状态仍是规范化输入声明，尚未从raw/attempt独立核验；私有链、
fake关系、reservation崩溃与响应保存故障尚待完成，P2保持partial，不进入P3/P4。
见 [P2-A报告](../r2-p2a-report.md)，冻结清单SHA为
`72d5eb692bf44ad7f5dd61fa82e1db3e8e8cce72ee2fa461014c991e9e990cbf`。

2026-09-14 P2-B执行：新增3个R2隔离私有模块，原2336保护文件及冻结资产未改。
已实现EvidenceRun准备、fake/replay执行、raw重建核验、八关系类型协议、事务预留与崩溃/保存故障
处理；75项新测试，与P1/P2-A合计213项通过，真实模型预算仍0。未接入默认service或正式CLI。
本轮发生执行偏差：新回归入口遗漏旧main负责的外联阻断，首轮PG测试实际连接数据库，测试schema
被创建/写入/删除，现有语料被读取。已记录并作废首轮结果；修复后605项旧工程用例通过，36项PG
跳过，R2禁用169项为重复子集，旧快照不变。但没有数据库事前快照，不宣称数据库零影响。
P2仍partial，暂停P3，等待用户确认只读影响核查。见 [P2-B报告](../r2-p2b-report.md) 与
[执行偏差报告](../r2-p2b-guard-incident.md)。冻结清单SHA：
`85d587047b680b5c76ca985f63945ec243d69e7d16e8ddf35a5596144b72ab3f`。

2026-09-14 PG只读核查：用户明确授权后完成三次强制只读事务，均回滚关闭；没有DDL/DML、清理、
恢复、PG测试或模型调用。目标解析为本机pg持久卷上的postgres语料库；当前无测试schema残留，
89文档/1101块/1318claims/57EvidenceRun，孤立块/claims及失效索引均0。事发时间窗主库新增文档、
EvidenceRun及入库运行均0；9月11日备份78文档ID全部存在且存储content_hash一致。
未读取研报正文或重新计算全文哈希。没有事发前全库快照、完整语句日志或WAL归档，故历史零影响
仍未证；固定schema原内容与当时真实语料采样身份仍未知。本次授权核查已完成，不无限重复查询，
也不把当前无残留冒充事故从未发生。建议接受残余证据边界后继续PG封锁下的纯离线P3；当前未自动
启动P3、解锁PG测试或冻结模型预算。原P2-B清单及17绑定文件保持不变。
报告：[PG只读影响核查](../r2-p2b-pg-readonly-report.md)。本次独立冻结清单外部SHA：
`ec6738e40037067e1153b042054383484557c66b32332fce06f20e08da6ec1b8`。

2026-09-14 P3执行：在 PostgreSQL 强制封锁、零模型、零judge、零市场和零入库条件下，完成固定
development 的 v12/v13 历史响应盘点、六个微范围规划复核和人工差异队列。两版各9份raw均可读，
各37个终态完整、非法JSON与未知槽均为0；但旧wire缺少新协议的plan/obligation/terminal/span/
audit字段，不能在不伪造证据的前提下回放到新runtime，因此新wire接收数均为0。

更关键的是，新规划器在741字符微范围上得到0个candidate、6个unresolved，35个目标全部进入
`structurally_unresolved`人工队列且批准数为0；在四类全文17044字符上也为0个candidate、14个
unresolved。主因均为`compound_or_condition`，证明卡点是规划粒度与范围生成，不是批次容量，继续
冻结模型预算没有意义。G0与冻结的G5通过；G1/G2/G3/G4/G6因没有新协议输出而不得冒充已验收。

P1/P2-A/P2-B/P3合计224项测试通过，Ruff、两阶段import smoke、symbol closure和P2保护校验
通过；保护文件、生产接线、独立留出原文均未触碰。P3按停止条件结束，P4未授权。建议保留已验证的
runtime/audit/evaluator，仅在scratch研究有硬上限、保留定位证据的bounded clause lattice planner；
若不接受该局部重设计，则将R2降级为“证据辅助阅读+人工确认”，不再宣称自动原子关系抽取。
报告：[P3离线回放与差异裁决](../r2-p3-report.md)。冻结清单外部SHA：
`edbc14e557309adb586bc7046f4e87ac8ad5449c39449b00be2dc747204a4bef`。

2026-09-14 P3-R执行：用户在P3报告的首选建议后指示继续，已实现零模型、scratch-only的bounded
clause lattice原型。planner interface只接收五个来源字段，不接收gold item、关系或排除项；生成后
reviewer再作固定development评估。六微范围共741字符，生成360个有限节点和130条结构边，35/35
目标分别落到35个不同的唯一最小节点；17个正关系和8个负关系的端点全部可引用。whole span、条件
`qualifies`、归属`attributes`、数字千位逗号及容量失败均有反例覆盖，人工批准仍为0。

全文检查未放行：14个packet根仅个人交易1根planned，公司7个table根unsupported；公司另1根、
行业1根及铜箔4根显式unresolved_capacity。该结果证明子句格解决了微范围粒度，但scope-provider
尚不能把整packet直接交给planner，也不能把table冒充prose。未提高上限掩盖问题，P4保持未授权。

原型24项与P1/P2/P3组合248项测试通过；Ruff、目标Pyright、两阶段import smoke、symbol closure
及P2保护校验通过。生产planner、runtime/audit/evaluator、公共parser、PG、入库、模型和holdout均
未触碰。下一步需要人工复核35条分母，并另行决定是否授权零模型P3-S scope-provider；任一不通过
则R2继续阻塞或降级。报告：[P3-R有限子句格验证](../r2-p3r-report.md)。冻结清单外部SHA：
`a79ad421df11933f4360d264a60b4856aeded9273c4277af0c4f03d03b0d18b3`。

2026-09-14 P3-S执行：用户授权继续并要求明确人工参与。新增纯计算scope-provider，全文四类
development的14/14 packet和17,044/17,044字符被连续覆盖为65个candidate范围，unresolved为0；
58个prose/turn/heading范围逐一进入冻结P3-R子句格，容量/类型失败为0。公司PDF的7个table packet
保持`table_row`且0个送入clause lattice，不把表格冒充prose，也不宣称表格claim语义已通过。

35/35固定目标各有唯一生成范围，17正/8负关系端点均可引用。P3-S新增27项，组合275项测试通过；
Ruff、目标Pyright、两阶段import smoke、symbol closure及P2保护校验通过。模型、PG、入库、市场、
holdout和生产文件修改均为0。S0—S5、S7通过，S6人工原子分母批准仍为0/35，P4未授权。

已生成35条只读来源/节点签核模板、人工说明及填写完整性校验器。人工必须逐条填四项布尔检查、
`approve/reject/needs_split/needs_merge`和非空理由，并填写审阅人、时间、批准总数；agent不得代签。
全approve后也只允许另行评审P4预算，非全通过则只在development零模型修订。报告：
[P3-S全文范围验证](../r2-p3s-report.md)。冻结清单外部SHA：
`c4aa7c87e6abb706ef3d8e53acfcaed54500c82e17e44ac56091647066590512`。

2026-09-14 P3-H执行：用户提交的35条人工文件通过完整性校验，SHA为`e171ce7b...a609`，决定为
31 approve、2 needs_split、1 needs_merge、1 reject。提交文件已原样保存在
`r2-p3s-denominator-review-completed.json`，空模板恢复到P3-S冻结SHA，人工内容未改写。

按人工理由新增只读amendment overlay，不修改v1 gold：公司评级与目标价拆开；行业“关注供需”与
“价差扩张”合并；铜箔总结拆为行业阶段、泰金增长、表处理设备增量；听音测试转排除项。受合并
影响，31条旧approve中30条可安全继承；生成5条替代item待复核。有效分母仍为35 item，正关系由
17调整为16，负关系8、排除项6。零模型重放35/35唯一节点、35/35唯一范围、16/8端点全部通过。

P3-H新增18项，组合293项测试通过；Ruff、目标Pyright、两阶段import smoke、symbol closure和P2
保护校验通过。模型、PG、入库、市场、holdout、生产代码与base gold修改均为0。H0—H3/H5通过，
H4的5条替代项人工批准仍为0/5，P4未授权。报告：[P3-H人工裁决应用](../r2-p3h-report.md)。

2026-09-14：用户完成P3-H替代项复核，5/5 approve、四项检查全true；提交件只遗漏可机械推导的
`approved_records`汇总值，原始提交独立保留，规范化完成件通过严格校验。P4预算前的全量兼容性检查
发现流程遗漏：35/35有效微金标没有P1/P2 wire所需的`speaker_ref`和`unit`，同时保留了wire未单列的
`speaker_role`、`identity_status`、`unknown_fields`；8条非空value还包含复合数值/单位或非数值表达，
当前P2规则不能无损承接。该问题会使G3在模型调用后仍不可验收，因此按fail-stop保持真实模型、关系、
holdout、PG、入库均为0，不冻结P4预算。下一步先做development-only、零模型的P3-I字段契约桥接，
公共模块与旧流程继续冻结。报告：[P4预算前置契约检查](../r2-p4-readiness-contract-gap-report.md)。

2026-09-14 P3-I执行：用户允许使用模型，但本阶段需前瞻冻结评分契约，实际模型调用保持0。新增
development-only evaluation seam，将35条有效item投影到P1十轴：8个scope-local speaker引用通过
registry可逆保留role+identity；27条value保持unknown、5条来源字面绑定、3条命名白名单transform；
5条unit来源符号提案、49个unknown constraint无损保留。21项正反例测试、Ruff、Pyright通过，生产
`_r2_*`与旧流程未修改。I0—I5通过，I6待人工复核1组全局规则、8 speaker与8 value/unit；P4预算
仍未冻结。报告：[P3-I字段契约桥接](../r2-p3i-report.md)。

2026-09-14 P4执行：P3-I人工复核全部approve后，新增scratch-only有限item runner/scorer和27项
反例；组合66项、Ruff、Pyright及2336+3保护门通过。冻结单轮最多5调用、0重试预算；真实执行只
调用首批1次，8行均返回但4行使用不允许的`risk/question` semantic type，完整响应落盘后按批级
协议停机，余下4批未发送。离线字段对比进一步显示8/8将不适用behavior写为unknown、7/8缺系统
speaker identity、2/3非空value被隐式规范化，故归因为模型枚举遵从与接口不可观测/跨轴契约的
混合失败，主要修订对象仍是接口。未修改生产/旧流程，PG、入库、holdout、关系均为0；P4未验收，
P5冻结。报告：[P4有限item字段填写试验](../r2-p4-item-report.md)。
冻结清单外部SHA：`d2282d831c6bc069a1819f2fae64b2d68336c9dbbf97eb02fcc47f79747533c3`。
