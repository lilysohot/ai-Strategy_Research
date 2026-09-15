# R2 材料语义抽取：失败驱动优化样板案例

| 项 | 内容 |
|---|---|
| 案例版本 | v1 |
| 日期 | 2026-09-13 |
| 当前结论 | **R2 未通过，保持 partial；holdout 未运行，R3 未启动** |
| 案例用途 | 作为复杂材料抽取、有限模型预算、逐轮验收和防退化改造的标准复盘样板 |
| 样本范围 | 4 份 development 材料；新增无标签光模块 DOCX 只做确定性压力测试 |
| 模型范围 | 历史授权轮次使用 `glm-5.3-flash`；本报告不新增模型调用 |

## 1. 案例摘要

R2 的目标不是生成一段“看起来合理”的摘要，而是在既有不可变 `EvidenceRun` 上形成可回链的
`MaterialRun`：保留事实、预测、观点、行为、条件、风险、问答、表达者、视角、否定、时间框架、
显式关系和逐字证据。

本案例经历四类主要优化：整体 JSON 抽取、结构分包与逐记录容错、JSONL 两阶段、结构能力与候选
槽位。工程稳定性逐步改善，最好一次选定目标 item recall 达到 20/24，但始终没有通过冻结业务
门槛。后续微型穷举正负例又证明，早期的 mapped relation precision 高估了真实表现：6 个短范围内
item 只召回 9/35，关系只命中 1/17，两条输出关系中有一条为明确误报。

最终诊断是：来源读取和“未入库”不是主要问题；核心瓶颈是完整性单位、原子化、表达者约束、
未知字段定义、关系证据门禁和评分版本管理。当前离线 v9 槽位方案还存在静态容量矛盾，不能直接
进入下一轮模型测试。

## 2. 业务问题与验收边界

### 2.1 要解决的问题

- 研究材料格式不统一，可能是券商研报、问答研报、电话交流纪要或个人交易复盘。
- 电话纪要可能有明确角色、匿名问答、混合话轮，或完全没有“专家”标签。
- 同一段可能同时包含事实、预测、否定、条件、行为和被引述论据。
- 系统必须忠实记录来源表达，不得把模型归纳、邻近共现或事后推断写成原文明示关系。

### 2.2 不属于本案例的问题

- 不验证来源观点后来是否正确。
- 不接入同花顺或政府数据，不做跨层事实验证。
- 不要求材料先入库；路径输入默认不写数据库。
- 不通过增加 prompt、token 或无限模型调用来换取偶然高分。

### 2.3 冻结门槛

| 指标 | R2 门槛 |
|---|---:|
| item recall | 每集合至少 90% |
| 关键 item recall | 100% |
| 语义 precision / recall | 至少 90% |
| 表达者、视角、问答归属 | 100% |
| 否定、条件、风险、行为状态 | 100% |
| `source_explicit` 关系 | precision 100%，recall 至少 90% |
| locator 与引文唯一回取 | 100% |

门槛来自[材料理解最小契约](../../docs/corpus-material-understanding-contract.md)，不能在看到模型结果后
降低。开发失败时不运行 holdout。

## 3. 样本设计

### 3.1 联合开发样本

| 样本 | 类型 | 主要压力点 |
|---|---|---|
| 公司研报 | research report / company | 作者、公告转述、EPS、目标价、评级、风险 |
| 行业问答研报 | research report / industry | 编号问句、连续回答、否定、条件预测 |
| 个人交易复盘 | post-trade review | 多动作原子化、声称成交、事后信息、行为动机 |
| 铜箔电话纪要 | conference minutes / industry | 匿名角色、长回答、混合话轮、转述论据、问答关系 |

R1 联合金标含 37 个 item、7 条关系、44 条唯一引文，其中 development 实际评分目标为 24 个 item、
5 条关系。它适合测目标召回和关键字段，但不是全文穷举金标，不能衡量所有额外 item/关系的真实
precision。

### 3.2 微型穷举正负例

为修复上述评分盲区，另冻结 6 个 development 短范围：

- 35 个穷举 item；
- 17 条原文明示正关系；
- 8 条刻意负关系；
- 5 个排除片段；
- 全部 source SHA、locator 和引文唯一性通过确定性校验。

金标见
[r2_material_micro_gold_v1_20260913.json](../../data/corpus/.audit/r2_material_micro_gold_v1_20260913.json)，
验收器见 [verify_material_micro_gold.py](./verify_material_micro_gold.py)。

## 4. 优化历程

### 4.1 阶段 A：整体 JSON 基线

**假设**：只要提示词完整描述材料语义，模型可以一次返回 speakers、items 和 relations。

**实现**：

- 建立依附 `EvidenceRun` 的 `MaterialRun`；
- 支持未入库文件路径；
- 对 item、关系和引文做严格 schema 与唯一回取校验；
- 每文档最多 2 次正文调用。

**结果**：

| 指标 | 最终结果 |
|---|---:|
| item recall | 12/24（50.0%） |
| critical recall | 11/23（47.8%） |
| semantic accuracy | 11/24（45.8%） |
| attribution accuracy | 11/24（45.8%） |
| relation recall | 1/5（20.0%） |

**有效发现**：未入库不是失败原因；公司研报和个人复盘可以产生有效结果。

**失败原因**：行业研报出现非法枚举，铜箔第二包为不完整 JSON；一个坏字段或截断会拖垮整包。

**决策**：停止继续堆叠提示词，转向结构分包和逐记录容错。

详见[初版开发报告](./material-semantics-report.md)。

### 4.2 阶段 B：结构分包与逐记录容错

**假设**：主要失败来自包边界和大对象截断；若保持完整话轮、逐记录校验，可显著恢复召回。

**实现**：

- 分包优先在新问题、编号问题和说话人边界断开；
- speaker/item/relation 逐条验证；
- 截断时抢救完整记录，但包必须标为 partial；
- 增加角色类别兼容和行为/目标价等确定性归一化。

**结果**：

| 指标 | redesign baseline | correction-1 |
|---|---:|---:|
| item recall | 20/24（83.3%） | 17/24（70.8%） |
| critical recall | 19/23（82.6%） | 16/23（69.6%） |
| semantic accuracy | 18/24（75.0%） | 16/24（66.7%） |
| attribution accuracy | 19/24（79.2%） | 17/24（70.8%） |
| critical all-fields | 12/23（52.2%） | 14/23（60.9%） |
| relation recall | 2/5（40.0%） | 1/5（20.0%） |

**正向效果**：包边界和逐记录容错确实有用，基线召回从 50% 提升至 83.3%。

**反向证据**：第二轮并未继续改善，item recall 反而下降；铜箔第三包输出54条可抢救记录后仍触发
8192-token partial。说明“更长提示、更大输出、再纠偏一次”不是稳定路线。

**决策**：把 item 与 relation 拆成两阶段，并改用逐行 JSONL。

详见[结构重设计报告](./material-semantics-redesign-report.md)。

### 4.3 阶段 C：JSONL 两阶段

**假设**：逐行 JSONL 可以消除大 JSON 对象截断；items 和 relations 分开后可降低单次复杂度。

**实现**：

- speaker/item 与 relation 分阶段调用；
- 每行独立解析，已完成行不因后一行失败而丢失；
- failed/partial 原始响应只在本地 0600 审计目录保存；
- item 上限每包30条；枚举别名做确定性归一化。

**结果**：

| 指标 | JSONL baseline | correction-1 |
|---|---:|---:|
| item recall | 0/24 | 14/24（58.3%） |
| critical recall | 0/23 | 13/23（56.5%） |
| semantic accuracy | 0/24 | 13/24（54.2%） |
| attribution accuracy | 0/24 | 9/24（37.5%） |
| relation recall | 0/5 | 2/5（40.0%） |
| mapped relation precision | 无可判预测 | 2/4（50.0%） |

**正向效果**：纠偏后所有成功包都不再因大对象截断失败，证明 JSONL 是正确的传输协议改造。

**失败原因**：

- baseline 中模型使用自然业务词而不是严格枚举，导致记录被拒绝；
- 行业研报 `display_name=null` 使匿名 speaker 及其16个 item 级联淘汰；
- 铜箔输出104个 item 仍漏掉6个关键目标，证明增加输出数量不等于完整；
- relation 阶段产出71条关系，候选空间没有受到有效控制。

**决策**：保留 JSONL，但把结构能力、speaker 和候选槽位前移为确定性系统职责。

详见[JSONL 两阶段报告](./material-semantics-jsonl-report.md)。

### 4.4 阶段 D：结构能力、speaker registry 与候选槽位

**假设**：系统先判断对话结构、建立安全 speaker，并枚举抽取义务，可避免匿名 speaker 级联和模型
自由选择遗漏。

**实现**：

- 增加 `dialogue_structure`、`attribution_capability`、`processing_mode`；
- 缺少专家标签时使用 `document_voice + document_only + degraded`，不源头拒绝；
- 建立确定性 speaker registry；
- 增加候选槽位和覆盖台账；
- 限制 relation candidate pair；
- 无标签光模块 DOCX 只做零模型结构压力测试。

**单轮结果**：

| 指标 | capability baseline |
|---|---:|
| item recall | 20/24（83.3%） |
| critical recall | 19/23（82.6%） |
| semantic accuracy | 18/24（75.0%） |
| attribution accuracy | 8/24（33.3%） |
| relation recall | 1/5（20.0%） |
| mapped relation precision | 1/1（100%，仅目标端点） |

**正向效果**：匿名 speaker 不再清空整包；前三类包级台账完整；无标签文档可以安全降级处理。

**失败原因**：执行版本 v8 仍是一包一个槽位。后续微型回放发现，26个遗漏 item 全部位于
`completed` 包，证明包完成不等于内容完整。铜箔一次超时不含冻结目标，关键遗漏均来自成功包。

**决策**：预算关闭后只做离线 v9 设计，不追加模型调用。

详见[结构能力报告](./material-semantics-capability-report.md)。

### 4.5 阶段 E：v9 离线槽位细化与静态否证

v9 将槽位细化到结构段，并用 question、forecast、condition、risk、negation、behavior、evidence 等
信号检查覆盖。24/24 原联合金标引文均能落入至少一个候选槽位，说明候选入口方向有效。

但静态容量检查发现：

| 铜箔包 | 槽位数 | 信号义务数 | item 上限 |
|---|---:|---:|---:|
| 1 | 25 | 42 | 30 |
| 2 | 33 | 50 | 30 |
| 3 | 23 | 41 | 30 |
| 4 | 40 | 55 | 30 |

第2和第4包连“每槽位一个 item”都无法容纳；一个槽位还可能包含多个原子命题。因此 v9 当前形态
在模型调用前已经被静态否证，不能直接冻结下一轮预算。

## 5. 微型穷举回放：纠正评分盲区

既有24个 development 目标是选定金标，不是全文穷举。它只能回答“目标有没有命中”，不能回答
额外82个 item、35条关系是真是假。早期 `mapped precision=100%` 因此被错误地理解得过于乐观。

用6个穷举微型范围零模型回放 capability 产物：

| 指标 | 结果 |
|---|---:|
| item recall | 9/35（25.7%） |
| 范围内 item detection precision | 9/9（100%） |
| relation recall | 1/17（5.9%） |
| relation precision | 1/2（50.0%） |
| 可判负关系规避 | 2/3（66.7%） |
| 尚不可判负关系 | 5/8（端点未召回） |

明确误报是：系统把“CEO 买入”事实与作者的加仓动作建立 `supports`，但原文没有因果连接。当前
v9 的确定性候选算法仍会允许这一已知负例，并可从铜箔既有 items 生成55个候选对，说明“限制候选
数量”尚未升级为“限制到有显式证据的候选”。

回放产物见
[micro-score-2686b3be2bccb3fa67f70edeab0f997abe6cc59a7a01c5e43876b28b6256679b.json](./material-semantics-runs/micro-score-2686b3be2bccb3fa67f70edeab0f997abe6cc59a7a01c5e43876b28b6256679b.json)。

## 6. 六个原子化反例

模型能够看到原文，但把多个独立命题合成一条：

1. 目标价与评级合并；二者语义类型不同。
2. 三项风险合并；无法逐项判断遗漏和 unknown 字段。
3. “改善长期赔率”与“不一定等同拐点”合并；肯定作用和否定边界不能独立评分。
4. 加仓与卖出 call 合并；两个行为、数量和价格无法分别保存。
5. “设备精度领先”与“良率大概率取决于工艺”合并；结论对象不同。
6. 被转述的“64开、工艺占大头、设备只是配套、没设备也不行”合并；支持、限制和反向补充关系
   无法可靠建立。

这些例子说明 prompt 中写“每条只保留一个原子命题”并不足以形成执行约束。原子候选边界必须由
系统先提供，模型只能逐候选填充或拒绝。

## 7. 评分版本回溯

最新评分器将 `value` 和 `unknown_fields` 纳入关键全字段检查。同一份 capability 抽取产物用统一
新口径重放后：

| 样本 | 旧报告 critical all-fields | 新评分重放 |
|---|---:|---:|
| 公司研报 | 1/4（25.0%） | 0/4 |
| 铜箔纪要 | 3/11（27.3%） | 0/11 |
| 总体 | 4/23（17.4%） | 0/23 |

抽取产物没有变化，变化来自评分定义。因此当前
[r2-non-regression-policy-v1.json](./r2-non-regression-policy-v1.json) 绑定旧报告指标，会把同一产物
的新口径重放误判为退化。该策略尚不能用于下一轮准入，必须先完成评分版本化和同口径重基线。

字段失败分布也显示问题是系统性的：20个已匹配目标中，`unknown_fields` 失败15项、speaker 12项、
identity status 8项、value 7项、polarity 6项。

## 8. 根因树

```text
R2 未通过
├── 评测基座
│   ├── 联合金标非穷举，早期 precision 被高估
│   └── 评分字段增加后未版本化，防退化基线口径错位
├── 完整性
│   ├── completed 表示“响应可解析”，不是“义务已覆盖”
│   ├── 槽位粒度仍可能包含多个命题
│   └── v9 单包槽位数超过 item 容量
├── 归属与字段
│   ├── 确定性 speaker 仍可被模型 speaker 覆盖
│   ├── 混合话轮会被最近角色标签强制归属
│   ├── unknown_fields 是自由字符串
│   └── 定性预测可能被错误追加 numeric_value unknown
├── 关系
│   ├── nearest question/claim 启发式代替显式关系证据
│   ├── 已知负例仍进入候选集合
│   └── 缺少可判负例时 mapped precision 失真
└── 次要执行因素
    ├── 大 JSON 截断已由 JSONL 基本解决
    ├── 仍有一次超时，但不解释关键目标遗漏
    └── 单一模型能力尚未独立比较，但协议缺陷必须先修
```

## 9. 哪些方向被证明有效

- 直接路径读取、source hash、locator 和唯一引文链路有效。
- 不要求先入库是正确边界。
- 缺少专家标签时降级而非拒绝是正确策略。
- 按话轮和编号问题分包优于固定字符硬切。
- JSONL、逐记录解析和 partial 状态保留是正确的传输与容错设计。
- 确定性 speaker registry、候选槽位和覆盖台账方向正确，但执行边界仍需重做。
- 小型穷举正负例比 selected-target mapped precision 更能发现真实关系误报。
- 冻结预算、开发失败不碰 holdout，避免了留出污染。

## 10. 哪些方向不应继续

- 不继续向同一 prompt 追加更多自然语言规则。
- 不通过提高 token 上限掩盖原子化和容量问题。
- 不只针对铜箔文档写专用规则。
- 不把更多输出条数当作更完整。
- 不以最近 item、同段共现或“看起来合理”建立 source-explicit 关系。
- 不切换模型后直接比较旧分数；评分器和基线必须同版本。
- 不用总体平均上涨抵消某一已验证类目退化。
- 不在 development 未通过前运行 holdout 或启动 R3。

## 11. 下一版正确实施顺序

### P0：先修评测基座

1. 给 R1 scorer 和 micro scorer 增加明确版本。
2. 同一评分器现场重算 baseline 与 candidate，不直接信任旧报告中保存的指标。
3. 重新冻结跨类目不退化基线及其 SHA。
4. 分开报告 detection、字段正确率、关系正例、可判负例和不可判负例。

### P1：重做候选义务与批次

1. 保留 source segment，但在段内按问句、并列动作、转折、风险枚举、引述边界生成 proposition
   obligation。
2. 每个模型批次冻结最大 obligation 数和最大预期 item 数；任何情况下都不得超过输出容量。
3. 模型逐 obligation 返回 `extracted` 或 `no_supported_item`，系统根据实际记录生成 ledger。
4. 所有 obligation 有终态且信号满足后，packet 才可 complete。

### P2：系统接管确定性归属

1. 无标签研报和个人复盘的 source voice 由系统绑定，模型不能覆盖。
2. 明确角色按 segment 绑定；混合话轮无法安全拆分时保持 unknown。
3. 被引述者使用独立 quoted source，不归给当前发言者或材料作者。
4. `unknown_fields` 使用受控枚举或系统推导；定性预测不因 `value=null` 自动报缺数字。

### P3：重做关系层

1. `answers` 从确定性问答结构生成或验证。
2. `supports/motivates/challenges` 必须存在覆盖两个端点的显式连接证据。
3. 已知负例在进入模型前即被候选器排除。
4. relation evidence 不仅唯一回取，还必须包含可验证的连接表达。

### P4：离线红灯测试

- 六个原子化反例必须先失败、改造后通过。
- v9 槽位/容量不变量必须有确定性测试。
- CEO→加仓负关系不得进入候选对。
- completed packet 中故意删除一个义务时，完整性必须变为 partial。
- 当前4个开发类目和6个微型范围使用同一评分版本做差分。

### P5：有限模型验收

只有 P0—P4 全部通过后，才冻结一个新的 development 单轮预算：

- 必须同时包含4个开发类目，不能只测铜箔；
- holdout calls 固定为0；
- 任一类目退化立即失败，总体均分不能抵消；
- 先检查正式门槛和微型穷举门槛，再决定是否需要一次受控纠偏；
- development 未通过则再次停止，不运行 holdout。

## 12. 样板决策记录

| 决策 | 依据 | 状态 |
|---|---|---|
| 未入库材料允许直接理解 | source hash、locator、引文均可验证 | 保留 |
| 无专家标签不源头过滤 | 光模块文档可形成 document voice 结构 | 保留 |
| JSONL 两阶段 | 消除了成功包大对象截断 | 保留 |
| 逐记录容错 | 单条坏记录不再清空整包 | 保留 |
| 包级完成 | 26/26 微型遗漏位于 completed 包 | 废止 |
| 最近 claim/answer 关系候选 | 已知 CEO→加仓负例仍被允许 | 废止 |
| 当前 v9 直接进模型轮 | 单包40槽位超过30 item 上限 | 阻止 |
| 当前不退化策略直接用于下一轮 | 新旧评分口径下同一产物被判退化 | 阻止并重基线 |
| 继续访问 holdout | development 尚未通过 | 禁止 |
| v13 最终 item 轮后继续修补重跑 | 34/35，冻结 stop rule 已触发 | 禁止，当前设计停止 |

## 13. 可复用验收清单

### 改造前

- [ ] 业务门槛、开发样本、holdout 身份和 source SHA 已冻结。
- [ ] 反馈环可离线重放并准确返回失败。
- [ ] scorer 版本固定，baseline 与 candidate 使用同一实现。
- [ ] 目标问题有最小正例、负例和排除例。
- [ ] 预算包含所有受保护类目，而非只包含目标失败样本。

### 模型调用前

- [ ] 候选义务数不超过协议容量。
- [ ] 原子边界不依赖模型自由决定。
- [ ] speaker、日期、来源等可确定字段由系统提供。
- [ ] 已知关系负例不会进入候选集合。
- [ ] 缺少角色标签触发降级，不触发补造或拒绝。
- [ ] 所有确定性测试和跨类目不退化门禁通过。

### 模型调用后

- [ ] 报告每类分子/分母，不能只报总体均分。
- [ ] completed 表示全部义务有终态，而非仅响应可解析。
- [ ] 额外 item/关系有穷举范围或明确标记为不可判。
- [ ] 负例仅在端点可判时计分，端点未召回单列。
- [ ] 任一类目退化、关键错误、超时或预算耗尽即停止。
- [ ] development 未通过时不访问 holdout。

## 14. 证据索引

- [R1 材料理解契约](../../docs/corpus-material-understanding-contract.md)
- [R2 任务记录](./issues/20-material-semantics.md)
- [初版开发报告](./material-semantics-report.md)
- [结构重设计报告](./material-semantics-redesign-report.md)
- [JSONL 两阶段报告](./material-semantics-jsonl-report.md)
- [结构能力与槽位报告](./material-semantics-capability-report.md)
- [微型穷举金标](../../data/corpus/.audit/r2_material_micro_gold_v1_20260913.json)
- [微型验收器](./verify_material_micro_gold.py)
- [跨类目不退化策略](./r2-non-regression-policy-v1.json)
- [R2 当前实现](../../plugins/corpus/material_semantics.py)

## 15. 案例结论

本案例最重要的经验不是某一次 prompt 调整，而是：

> 结构化抽取的完整性不能由“模型返回了内容”证明；必须先把来源拆成有限、原子、可核验且容量可行
> 的义务，再让模型逐项完成。关系必须由显式证据证明，评分和防退化基线必须同版本。

R2 下一步的第一个任务因此不是模型调用，而是修复评分版本与非退化基线；随后重做 proposition
obligation、系统归属和显式关系门禁。完成离线红灯测试前，不冻结新模型轮。

## 16. 原子义务单轮验证（2026-09-14）

P0—P4 的首轮实现完成后，冻结 `r2-atomic-development-budget-v4.json`。预算只包含四个开发类目，
`max_slots_per_batch=16`，item 调用上限 35，关系阶段显式延期，holdout 固定为 0；无标签光模块文档
仍仅作零调用结构压力测试。实际消费 35 次，无重试、无入库。

| 指标 | capability 同口径基线 | atomic item 轮 | 结论 |
|---|---:|---:|---|
| 选定 item recall | 20/24 | 24/24 | 提升 |
| critical item recall | 19/23 | 23/23 | 提升 |
| semantic accuracy | 18/24 | 24/24 | 提升 |
| attribution accuracy | 8/24 | 23/24 | 提升，仍错 1 项 |
| critical all-fields | 0/23 | 1/23 | 仍不合格 |
| 微型穷举 item recall | 9/35 | 31/35 | 提升 |
| 微型穷举 item precision | 9/9 | 31/32 | 仍有 1 项边界不一致 |
| 可判负关系规避 | 2/3 | 8/8 | 关系延期下无误建 |

四个开发类目的 item recall、critical recall、semantic 和 attribution 均逐类持平或改善；正式
非回归门禁仍失败，因为关系被延期且所有处理包按约定标为 partial，不能用 item 改善掩盖完整性
下降。

本轮覆盖台账提供了此前没有的直接证据：7 个候选槽被模型填入多项，铜箔 39 个槽缺少 coverage，
26/28 个铜箔批次出现 coverage protocol incomplete，而 API finish reason 均为 stop，不是 token
截断。这说明剩余问题不是“模型看不到原文”，而是 16 槽批次仍过大、若干长复句仍未原子化。
公司漏掉评级和两条风险；铜箔长摘要只抽了首个子命题，和长引文金标不一致。

因此本轮后的决策是：

1. v10 预算关闭，不追加纠偏调用。
2. v11 离线强制一槽最多一个 item，并将 item+coverage 两行合并为每槽唯一终态记录；同时补充
   复句/英文句号边界并归一信号优先级。
3. 被引述观点由独立 quoted source 承载，不能被当前专家或作者覆盖。
4. 关系候选改成每对必填 present/absent；缺失、重复或越界决定均使 packet partial。
5. 下一次模型预算必须缩小 item 批次，并先冻结独立的 item-phase 门禁；在 v11 重新验证前，
   holdout 和 R3 继续禁止。

正式开发报告为
[report-41375baa…](./material-semantics-runs/report-41375baa853ecfec08fcb8b0ffa10ca2da4960387c73cda07607308448c0ea94.json)，
SHA-256 为 `0f894fe9942fc7f0bd4d5d4f41f50401433e50fe3d380d8e09279d8770fa959f`；微型报告为
[micro-score-bcde356c…](./material-semantics-runs/micro-score-bcde356c19bc4df28926ff16939782d4796e67019100467cdc8cee6523b302f9.json)，
SHA-256 为 `6df7a84abe6a3f6618b5f0ea77b978ce42193c120960bfabeda72d6b83928c03`。

## 17. v13 最终 item 轮与停止结论（2026-09-14）

在 item acceptance v2 冻结后，系统接管了编号问答结构、确定性归属、极性别名、行为时间、明确数值
和六类未知轴。复用 v12 原始响应的零调用回放为 35/35 item、关键错误 0，且 381 项 corpus 回归通过。
据此冻结 `r2-v13-final-items-budget-v7.json`，只允许同一 37 槽的 9 次真实调用，关系与 holdout 仍为
0。

最终真实复验为 34/35 recall、34/34 precision；34 个已匹配 item 的结构、归属、极性、行为时态、
数值、证据和未知轴全部通过。唯一缺失的“强推”评级实际已由模型输出，但模型选取的短证据引文在
packet 内出现两次，严格唯一回取在利用 candidate slot 消歧前将记录拒绝。

这次失败把当前设计的最后一个未系统化边界暴露出来：系统拥有原子槽位，却没有完全拥有 evidence
span。未来若重启 R2，应让系统同时冻结 obligation 与唯一证据锚点，模型只填写受限字段；这属于新
设计版本，不能作为 v13 的追加修补。按照最终预算的 stop rule，当前 R2 设计停止，关系阶段、holdout
和 R3 均不启动。完整结论见
[v13 最终 item 验收报告](./material-semantics-v13-final-item-report.md)。
