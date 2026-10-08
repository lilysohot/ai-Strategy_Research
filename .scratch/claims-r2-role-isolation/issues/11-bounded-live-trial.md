# 11 · 获准后的真实模型有界试验与单文档消费

Status: needs-info
Execution: 范围已由许永立确认；r2 非表格金标及 267 条候选逐条裁定均已由 xyl 签认并正式冻结；两份来源的有界候选诊断已执行（本轮 48 次调用）；只读 query 均返回 CS_NOT_PUBLISHED，delivery/context_use 未发生；人工门已解除但质量门未通过，material_items 原子覆盖不足、relations 无候选，尚未发布或进入主线消费，任务整体未闭环
Type: task
Plan: W4/W5 真实消费；R2-S4/S5 的部分验证
Blocked by: 第 2—3 页及图像表格未覆盖；Claims 主体/期间/指标绑定和 material_items 原子覆盖未通过，relations 无候选；质量门、候选发布、M_main 消费及报告验证尚未完成；09/10/阶段证据仍需闭合
Real model calls: 116（既有 68 + 本轮 r2 48；M_main 0；自动重试 0；2026-10-04 已授权不设调用总额上限；禁止死循环）
Production database access: 0

> 2026-10-08 后续：针对本轮质量阻断的实现修复与零模型冻结已在
> [12-r3-quality-remediation](12-r3-quality-remediation.md) 完成。r2 候选、签认裁定和运行工件均未
> 覆盖；本票仍保持 `needs-info`/未发布，等待同一 24 单元的有界 r3 真实复验及重新裁定。

> 2026-10-08 复验结果：r3 在工业富联 items 协议无效后停止；针对确定性校验缺陷修复并冻结的
> r4 又遇到 Claims `outcome_unknown` 与模型错误槽位 ID，仍按停止条件结束。详见
> [13-bounded-r3-trial](13-bounded-r3-trial.md) 与
> [15-bounded-r4-trial](15-bounded-r4-trial.md)。完整 24 单元三角色候选尚未形成，因此逐条裁定、
> query/delivery/context_use 与发布均未执行。

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

在回放与质量门通过后，按批准范围验证真实 M_extract 抽取及 M_main 研究消费，明确区分协议、质量和端到端接通结论。

## 当前阻断与授权字段

2026-10-04 用户明确“允许执行，模型调用无限制，但不可死循环”。该指令覆盖此前零调用及需另批
调用总额的限制，不再要求用户填写调用次数/金额上限。实际执行采用有限任务计划、截止时间和无自动
重试控制，材料和研究问题仍待确定。以下原始清单中的预算数值要求按本次授权更新，其余证据用于
约束执行范围、记录质量与结果：

- 来源/source/build/精确包范围与实验输出目录。
- 提取 provider/model/配置指纹及用户独立配置确认；主线 M_main 的明确身份。凭据仅由运行时安全读取，不贴到票据。
- 角色、关系启用范围、候选生成/分批规则、每角色与总请求上限、token/金额/时限/并发上限。
- 真实主线消费、原文基线及修订所需的 M_main 额度，不能借已有交互会话预算推定获准。
- preflight、可能的兼容请求和所有额外 attempt 如何计入上限；首轮自动重试 0。
- 达到失败/关键错误/未知 outcome 时的停止条件、未使用额度处置、继续所需审批。
- 已冻结提示词/Schema/路由/评分与样本指纹、所需只读来源/隔离库访问范围；生产库访问不在本票授权内。

“建议最多 8 调用”不是默认授权，不能在未核算容量时套用。预算不足以覆盖计划时缩小获准范围或等待新授权，不静默少跑后宣称完整。

## 范围与预期产物

- 不以本票临时改代码来追求通过率；需要修复时停试、另记任务和版本，重新冻结再申请运行。
- 将 01/05 固定的实际 plan/check/execute 与研究入口命令、参数和退出码策略写入批准清单。
- 先做获准 B 组：独立提取模型协议/条目/必要关系；通过后才运行另有额度的主线消费。
- 如要宣称质量/成本改善，须有同控制变量的 A/C 对照及双方预算；单次 C 成功只能证明该样本真实消费，不宣称普遍收益。
- 保存逐 attempt 原始响应/用量、角色结果、覆盖/冲突、语义发布版本、消费账、报告清单、质量评分及最终报告。敏感字段脱敏。

## 验收条件

- [ ] 09/10 和主计划外部门证据齐全，获准清单明确签认；缺任一项不发请求。
- [x] preflight 经过真实提取配置/调用路径且计入预算；现有通用主线 preflight 不能替代 M_extract 验证或未经授权执行。
- [x] 正文调用命中独立提取配置，确定性任务无 attempt，SDK 无自动重试，真实执行并发 1。
- [ ] 原始响应到工件再到查询/消费/报告的版本和取证链闭合，充分证据路径无例行主线 fetch。
- [x] 真实 API/协议失败、关键语义错误或未知 outcome 按批准策略停止；不自动消耗“剩余额度”补跑。
- [x] 已知费用小计和未知调用数分开，费用不完整不能宣称节省；主线与抽取分账。
- [x] 分开报告真实接通、质量门、适用范围和不足；评分未达标也如实保留产物，不以重试筛选最好结果。
- [x] 即使单文档试验成功，也不宣告生产 PG、独立留出、全库或全部入口已验收。

## 验收命令与开启方式

开启前先复跑零模型门：

```bash
uv run pytest tests/test_corpus_structured_react_replay.py tests/test_corpus_structured_scoring.py -q
```

真实执行命令不得在未授权时试跑；待 01/05 交付且本票获准后，将精确可复制命令（不含密钥）附在 Comments，并逐条记录退出码/attempt。命令或授权字段未填写时，本票保持 needs-info，不将以上零模型命令当成真实试验已完成。

## 非目标

不采购服务、不修改用户主线配置、不进行全模型矩阵/受保护留出、不写生产 PG、不通过扩大数据范围或静默加预算取得成功。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。

### 2026-10-04 · 启动准备与用户确认栏

用户要求开始下一个任务并指出需要确认的文件。本票为下一任务；当前已开始零模型准备。
本节是本轮集中填写入口，可以直接填写，也可以在对话中按 A/B 编号回复，由执行者回填。
`待填写` 与未勾选项均不表示批准；确认 A 可先推进真实开发资产准备，B 的真实请求须等前置门齐全。

#### A · 先确认开发材料、问题与人工金标（模型调用仍为 0）

| 用户需要确认的内容 | 待确认值 |
| --- | --- |
| 允许只读的开发材料 | 已在执行任务范围内定位本地华创证券茅台中报点评，已只读核对；拟取第 1—3 页，详见文末审阅稿 |
| 研究问题 | 用户原题“茅台集团是否值得购买”；暂按贵州茅台（600519.SH）股票的买入价值、价格/估值条件与风险研究 |
| 人工金标审核与争议裁定人 | 待填写：姓名或代号；执行者可整理标注草稿，由指定人员逐项确认 |
| 候选输出接触情况 | 待填写：这些材料是否已看过候选抽取结果；若已接触，如实记录，不能声称前瞻冻结或独立留出 |
| 本地资产输出目录 | 建议 `/home/administrator/FrontierAgent/.scratch/claims-r2-role-isolation/evidence/11-live-20261004-r1/`；待确认，可指定其它目录 |
| A 确认人 / 日期 / 只读范围批准 | 待填写 |

来源批准后，执行者负责计算文件 SHA256、构造固定 source/build/snapshot、列明精确 packets、
整理逐角色金标与研究问题清单，再交人工确认并冻结。无需用户手填技术哈希。标注输出使用新资产，
本轮合成夹具中的 `adjudications.json` 和清单仍保留历史状态。

候选阈值摘自[评分定义](../../../tests/fixtures/corpus_structured_scoring/scoring-definition.json)：
Claims 精确率 ≥98%、召回 ≥95%；items 精确率 ≥95%、召回 ≥90%；
relations 精确率 ≥95%、召回 ≥85%；风险/条件召回 ≥95%；报告支持率 ≥95%；每角色金标至少 20 条。
关键语义错误一票否决；零分母或样本不足不能作为质量过门。报告支持率与样本下限是待签认的候选政策。

- [ ] 确认上述阈值，或明确写出修改意见：待填写。
- [ ] 人工金标、争议裁定与冻结时序已有证据：待完成，由执行者补文件链接后签认。

单文档材料不足三角色最低样本时会保留质量门未通过，不自动降低门槛。

#### B · 真实调用清单（调用授权已收到；实际请求数当前为 0）

| 用户需要确认的内容 | 待确认值 |
| --- | --- |
| M_extract | 已核对：`openai_compat / doubao-seed-2.0-mini`，独立 `STRUCTURED_EXTRACTION_*` 配置完整；凭据仅运行时读取 |
| M_main | 已核对 `.env`：`glm-5.3-flash`，BASE_URL/API_KEY 均存在；实际加载的主线 profile 在执行时冻结 |
| 试验范围 | 建议单文档 B 组抽取，再按单列预算执行 C 组结构化消费；是否需要 A 组原文对照：待确认 |
| 角色与关系范围 | 待确认 Claims / items / relations；关系仅限批准的包及固定合格端点 |
| 请求次数上限 | 用户不设总额上限；每批按实际有限任务数冻结容量，不使用无限循环补跑 |
| token / 金额 / 时间上限 | 用户未设累计 token/金额额度；保留传输输出上限、超时和逐请求用量记录。每次有限执行计划附截止时间 |
| 自动重试 / 并发 | 0 次自动重试、并发 1；记录所有实际请求及额外 attempt |
| 失败停止与余额 | API/协议失败、关键语义错误、未知 outcome 即停当前批次；先核查原因，禁止同参数反复重发或筛选成功样本 |
| 运行环境 | 建议本地文件 store；研究端通过只读挂载访问发布工件；生产 PG、受保护留出额度为 0 |
| B 确认人 / 日期 / 清单修订 | 用户 / 2026-10-04 / 本轮对话：“允许执行，模型调用无限制，但不可死循环” |

密钥只在本地安全配置中填写，不写入此票据或对话。本轮无需重复请求次数或金额授权；
每批有限容量是防循环执行控制，不是重新向用户申请预算。

执行者在 A 完成后补齐：来源/快照/包与金标指纹、角色 profile/提示词/Schema/路由/评分指纹、
请求容量核算、预算限制的实际实施方式、preflight 计账方案、精确 plan/check/execute 命令以及
只读研究入口命令。当前 CLI 未提供通用 `--max-tokens` 或 `--max-cost` 参数，不能虚构参数来宣称
这些上限已受控；实际方案与批准额度吻合后才可发出请求。

#### 前置验收证据与启动顺序

- [09 回放票](09-react-replay.md)：本地修复已有证据，目前仍为待复验签认。
- [10 质量门票](10-quality-gates.md)：评分代码及合成反例已通过；A 的真实范围/金标/阈值仍待完成。
- [唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)：R2-S0—S3 仍列为待执行，
  阶段证据核对与签认仍需完成；本票的启动准备没有修改阶段状态。

执行顺序：确认 A → 构造并人工冻结开发资产 → 补齐 09/10 与阶段证据 → 根据实际任务数形成 B
的精确命令和预算 → 确认 B → 计账 preflight 与 B 组抽取 → 达门后运行已批准的主线消费。
依据本票“当前阻断与授权字段”以及 spec §4.8/§5，缺来源或预算明细时保持 `needs-info`。

#### 本轮启动检查结果

2026-10-04，基线 HEAD `46a7bf9f221f8162e61b9dfabe9ff026c47f6546`，从仓库根目录执行：

```bash
uv run pytest tests/test_corpus_structured_react_replay.py tests/test_corpus_structured_scoring.py -q
# exit 0；45 passed in 43.02s
```

检查绑定的 SHA256：

- 评分实现：`172ce465492cf26cb7249599d9f53ac40d266c1883a49cea51b0b178894874f1`
- 评分测试：`1facf67a51fbd63ec63ed0c7a15e3cffa5af7ad1733b16a2a5f82ad8ff776794`
- v1 契约清单：`8cbe94827de6764feda994da4c33c9fcaf57e3ee77d3beec32da177c0cbce154`
- 合成评分资产清单：`bc6743d6e1fb5d1ed4f2c13c4ea1935b8ac545d08c4cbba150b7dee1d6f4715f`

本轮只更新本票启动记录与确认栏，使用 fake/replay 和合成资产运行启动检查。真实模型请求、
真实 preflight、生产数据库与受保护留出访问均为 0；全部真实试验验收项保持未勾选。

### 2026-10-04 · 调用授权落实与配置核对

用户授权真实模型执行，不限制调用总额，要求不可死循环。授权已记入上方 B 栏。继续执行无需
再次申请调用次数/金额额度；尚缺具体材料路径和研究问题，已向用户询问该输入。

通过 `evidence/11-live-20261004-r1/inspect_config.py` 调用现有配置加载接口进行零请求核对：
提取模型 `doubao-seed-2.0-mini` 配置有效，配置指纹
`sha256:4f0e537e2fb9bec8320c6724d8aaa16a31be70607a531745353b4988f1283164`；
主线配置模型名 `glm-5.3-flash`，endpoint/key 均存在。没有打印密钥或修改用户配置。
提取 CLI 当前仅读取进程环境，实际运行时须由明确的配置加载步骤将专用变量传入，不依赖 cwd
隐式加载 `.env`，也不把主线变量补给提取配置。

防循环执行约定：按固定来源生成有限任务列表；一次批次遍历，每任务至多一次 attempt；关系只从
固定合格 items 派生；自动重试 0、并发 1；单提取请求沿用配置的 300 秒超时和 4096 输出 token
上限；运行前按任务数设置批次截止时间，主线设有限轮数/时限；失败或未知结果即停批次核查。
预算授权不等于人工金标已存在或质量已通过，真实试验的质量结论仍按证据记录。

### 2026-10-04 · 研究问题与开发材料落实

用户给出研究问题“茅台集团是否值得购买”。结合本专项单文档研究消费目标，暂按上市公司
贵州茅台（600519.SH）股票解释，原始问题保留。已定位本地华创证券 2026 年中报点评并通过
PDF 技能渲染核对第 1—3 页；文件 7 页，SHA256 为
`6f14cc145b798b3716bad47829c05d89d8a5e5955179f11d196ed9b9b8538f11`。

人工确认集中在[研究范围与关键证据审阅稿](../evidence/11-live-20261004-r1/research-scope-review.md)。
该稿给出具体材料路径、研究子问题、12 项关键证据检查点、读取缺口及审核栏。它是执行者整理的
草稿，不是候选提取输出或完整人工金标。

视觉核对发现第 2 页季度表图像未进入普通文本提取；第 1 页价格对应 2026-08-14；
第 3 页“股利及利息支付”不可无条件充作现金分红。上述限制纳入预期，未来解析/模型不能
把缺口表述成完整覆盖。辅助提取、渲染与源文件指纹保存在同一 evidence 目录。
本轮没有真实模型请求、生产库访问或质量门放行。

### 2026-10-05 · 用户确认后的单次真实 preflight 与只读复核

本节取代上方历史记录中的“当前 0 调用/范围待确认”；历史记录不回写。
许永立已于审阅稿填写 `2026-10-05 10:30:00`，并在对话确认。确认范围为贵州茅台股票、
该研报第 1—3 页及 E01—E12 关键预期，不是完整三角色金标或质量放行。
冻结后的审阅稿不再修改；其中“真实输出尚未生成”是冻结时点的陈述。

执行限定为单次 Claims 协议 preflight，不是完整 B 组，更没有开展 C 组主线消费。
完整质量门仍缺，不能用这次调用解除此前置门或宣称完全遵循原定全量启动顺序。
未修改生产代码、用户模型配置、评分规则或原始输出；未访问生产数据库、受保护留出。

#### 范围、命令与防重发

正式仓库 reader/clean/chunk 已生成 [reader-capture.json](../evidence/11-live-20261004-r1/reader-capture.json)，
确认第 2 页图像区域读取缺口。preflight 只取第 1 页 reader units 4/5/12：发布日期、标题、
事项段；采用本地 SnapshotReader 适配器，不冒充生产 PG build。构造三个单元一个包，
Claims 预算 1、items 预算 0、relations 禁用，并发 1、自动重试 0、计划截止 1800 秒。
请求超时 300 秒、输出上限 4096 token；`started.json` 独占创建，禁止重复执行同批。

从仓库根目录执行（前缀 `PYTHONPATH=.`；uv 位于 `/home/administrator/.local/bin/uv`）：

```bash
uv run python .scratch/claims-r2-role-isolation/evidence/11-live-20261004-r1/prepare_reader.py
uv run python .scratch/claims-r2-role-isolation/evidence/11-live-20261004-r1/live_preflight.py prepare
timeout --signal=TERM 420s uv run python .scratch/claims-r2-role-isolation/evidence/11-live-20261004-r1/live_preflight.py execute
uv run ruff check .scratch/claims-r2-role-isolation/evidence/11-live-20261004-r1/audit_preflight.py
uv run python .scratch/claims-r2-role-isolation/evidence/11-live-20261004-r1/audit_preflight.py
```

以上命令均 exit 0；execute 的 exit 0 仅指 Claims 协议接通，不代表全批或质量成功。
prepare/execute/audit 写入使用独占创建，不应再次执行；重复核查仅运行
`live_preflight.py check`（零模型请求）。

冻结计划：[plan.json](../evidence/11-live-20261004-r1/preflight-claims-r1/plan.json)、
[freeze.json](../evidence/11-live-20261004-r1/preflight-claims-r1/freeze.json)。
执行账：[check.json](../evidence/11-live-20261004-r1/preflight-claims-r1/check.json)。
只读核查：[audit.json](../evidence/11-live-20261004-r1/preflight-claims-r1/audit.json)。

#### 真实执行与取证链

- batch：`batch:ab81e81187c34a8e2157db5c09359f385288fe93beec98783071a4fcb1a947ad`
- snapshot：`sha256:f6fde52d19d8d9544d751dd8cce10612a37a55f680b870091476820142652df1`
- build：`6923ac3d4fdef7bd52f39bb1bd231905da0ab0045b88661993723c5e6d1f777f`
- 独立提取配置：`openai_compat / doubao-seed-2.0-mini`；响应模型 `doubao-seed-2-0-mini-260428`。
- HTTP 200、finish_reason stop、19064 ms；实际 attempt 1，无重试。
- prompt 914、completion 3109、total 4023 token；reasoning 2105 为 completion 子项，不重复累加。
- 费用未返回：known_calls 0、unknown_calls 1。known_amount 0 不表示免费，也不支持节省结论。
- 原始响应对象：`sha256:8d0115e21687c0acb744bbde445a98c08a9306c976b7ea2d1bc69f7a33d15f8c`；
  响应内容哈希 `sha256:5a63196383a52cb24537700aabfe88e20a8c3b59c8270121c540448ec3c1d82f`。
  两者不同是封装对象与内容的区别，不是响应丢失。
- 工件：`sha256:ec51a97539947d53dab63bbcbb6ce9c074c307ad27d758f682fc9cfe2ccf1b5d`；
  负载：`sha256:ad22a9cd6d99b2e0dda773203373cf4a6af14bb4ff4530a5c27d99cc898b6c62`。
- `check_batch` plan_consistent=true；冻结文件/响应/工件哈希与 24 个 source/dependency/context
  span 均核对一致（包含重复上下文，不等于 24 条独立证据）。
- items 因计划预算 0 为 blocked，未调用；该批不是“全部角色 succeeded”。

#### 质量发现与停止原因

1. 4 条记录的业绩数字和增减方向与 E02—E04 对应文本一致，引用绑定有效；每条将金额与同比
   合并在 claim_text，不能当作 8 个已规范化指标，也不能据此计算完整精确率/召回率。
2. `26H1`、`单Q2` 未规范化为确定期间；主体原文 `贵州茅台（600519）` 未规范化为 ticker。
   原文虽在上下文中，规范化字段仍为空。不得手动填字段后冒充本轮自动输出。
3. “总收入”不在当前 metric 注册表；归母净利润另有 `qualifier_definition_unverified`。
4. 本地适配器将发布日期 unit 4 标为 period 依赖、标题 unit 5 标为 attribution 依赖；
   这不是已验证的语义依赖建模。attribution 依赖触发 qualified-context 保守降级，不能将全部
   review 原因归咎于模型。下一版本需区分发布日期与业绩期间、标题主体与言论归属，不删依赖骗过门。
5. 全部事实为 review / cite-only，角色为 review_required / unpublished。
   在 SQLite `mode=ro` 下直接调用发布候选验证器，得到
   `CS_DEPENDENCY_NOT_READY: artifact_not_publishable`；没有实际发布写入。

因此停在发布前，不发 M_main，不重复相同请求，不放宽质量门。本轮协议验证完成，
任务 11 整体仍未闭环；不输出“现在是否值得购买茅台”的投资结论。

#### 后续待处理（本轮不擅自扩大为产品修复）

- 独立修复/验证 snapshot 依赖语义和主体/期间/指标绑定；保留 r1，变更使用新版本、新冻结，
  先用已存响应做零调用回放，避免为调试反复花费真实调用。
- 补齐三角色金标及人工裁定，注明开发样本已见候选；样本不足不降低门槛、不称独立留出。
- 完成 09/10 与阶段签认，随后按有限新计划执行完整 B 组；达发布门后才开展只读研究消费、
  消费账与报告支持率检查。用户已授权调用额度，不再重复索取预算确认。

### 2026-10-07 · 完整材料语义轮（事实、预测、观点、论据、风险、条件、关系）

用户要求下一轮以七类语义为目标，并将 `material_items` 独立执行。本轮严格限定为已确认研报
第 1 页叙事 reader units 12/15/17/19/21/23；按精确源文范围拆成 8 个不可变段。范围不包括
第 2—3 页图像表格，也不冒充完整 PDF 覆盖。每段 `material_items` 最多一次请求，若存在确定性
关系候选，`material_relations` 最多一次请求；并发 1、自动重试 0。API/协议/质量失败均立即停止
所在批次，修复后创建新冻结批次，不覆盖旧结果。

最终选择清单为 [selection.json](../evidence/11-live-20261007-final/selection.json)，选择策略是复用已经
通过的不可变段、不因其它段失败而重复调用：01/02/04/05/06 来自 r7，03 来自 r11，07/08 来自
r9。选择清单哈希为
`sha256:d3efd3e774c76f72e832c2e754df4c3f487b51b4147b151f8575e8368672d167`。
失败的 r7/07、r8/03 与空关系候选的 r10/03 均保留，没有改写成成功结果。

只读聚合 [aggregate.json](../evidence/11-live-20261007-final/aggregate.json) 与
[audit.json](../evidence/11-live-20261007-final/audit.json) 已生成。审计重新计算内容寻址哈希并核对
49 个源文切片、关系端点及槽位终态，结果如下：

- 8 段、41/41 个候选槽位终态，41 个 accepted candidate items；无漏槽。
- 语义类型：fact 28、forecast 10、opinion 2、behavior 1。
- 陈述角色：claim 31、evidence 5、condition 2、risk 3。
- 显式关系 2 条，均为 `supports`：销售回款数据支持产品周转/渠道配合/经营质量判断；财务公司
  存款变化原因支持经营性现金流净额同比增长 915.8% 的解释。
- 七项目标 `fact/forecast/opinion/argument/risk/condition/explicit_relation` 均为 true。
- 最终选择包含真实 attempt 10 次、51,364 tokens；provider 未返回价格，unknown cost calls 10，
  known amount 0 不能解释为零成本。

从 r2 到 r11 的开发、拒收证据与最终选择合计 35 次真实材料模型调用、191,555 tokens；连同
2026-10-05 Claims preflight，任务累计 36 次真实提取调用、195,578 tokens，M_main 仍为 0。
所有调用 cost 均未返回。多批次来自逐项定位并修复不同的确定性问题，不是同参数自动重试；每次
失败均先停批并保留工件。最终选择只计入验收通过的 10 次调用。

为完成该轮，产品代码补强了有限槽位字段协议、市场预期与预测信号区分、显式因果拆分、中文
因果关系方向与严格候选过滤，并在证据定位时只对空白及中英文引号作展示等价映射，落盘仍保存
精确源文字符。相关回归集 `132 passed`，Ruff 检查通过。

本轮可以闭环为“第 1 页叙事材料的候选语义抽取轮”，但不能闭环任务 11：尚无人工金标，因此
不能报告精确率/召回率；候选尚未发布，未被 M_main 研究入口消费，也不能据此直接回答买入建议；
第 2—3 页及表格覆盖、Claims 规范化、完整发布链和主线报告支持率仍待后续任务处理。

### 2026-10-08 · 内容提取优化与语义复核

针对上一轮“观点过少、让步误作条件、复合财务事实、关系稀疏”的人工复核结果，继续优化
`material_items` 的原子拆分、语义类型/陈述角色归一化及关系候选。主要修复包括：

- 上半年与单 Q2 的收入、归母净利润拆为 4 个独立事实，不再各自合并成一条；
- 将“经营向上明确、底层逻辑重构/未变、改革成效、利好、增长路径清晰”等分析判断归为
  `opinion`，把 Q3、下半年、年内、明年、中长期、独立 H2 表述归为 `forecast`；
- “尽管/虽然”按让步背景处理，不再为了满足目标而伪造 `condition`；真正条件仍要求
  如果/若/只要/除非/前提/取决于等显式标记；
- “主要是/主要系/由于”等原因归为 `evidence`，并按原因 → 结果建立 `supports`；
  “表明/说明/证明”引出的结论保持 `claim`；
- 展望段将当前判断、Q3 预测、下半年预测和结构升级判断拆为独立项目；H1 历史事实不会因
  字符串含 H1 被误判为预测。

失败批次均先停止并保留：r12/03 暴露因果角色缺口，r13/05 暴露展望复合与 `other` 角色，
r14/06 暴露让步角色缺口；无自动重试。完整 r15 的 8 段均通过，随后只对人工抽查发现的
H2 预测误标执行定向替换，最终第 04 段选用 r17，其余复用 r15。选择与被替换记录见
[selection.json](../evidence/11-live-20261008-optimized/selection.json)。

最终 [aggregate.json](../evidence/11-live-20261008-optimized/aggregate.json) 和
[audit.json](../evidence/11-live-20261008-optimized/audit.json) 的只读复核结果：

- 8 段、48/48 候选槽位终态，48 个 accepted candidate items；
- semantic type：fact 23、forecast 13、opinion 12；
- statement role：claim 37、evidence 8、risk 3；
- 5 条显式 `supports` 关系；62 个项目/关系源文切片逐字符核对；
- 条件状态为 `absent_in_source_scope`，不是抽取失败；本范围没有显式真条件；
- 未来内容误标为事实/观点、判断误标为事实、无条件词的条件项均为 0；
- 最终选择含 11 次 attempt、58,809 tokens；价格未返回，不能把 known amount 0 解释为免费。

回归测试 `135 passed`，相关 Ruff 检查和格式检查通过。本节闭环“第 1 页叙事内容提取优化”子任务；
仍不等于任务 11 全部验收：候选未发布，缺人工金标及精确率/召回率，第 2—3 页图像表格与主线
研究消费仍不在本次范围内。

#### 状态总账

截至 2026-10-08，任务 11 累计 116 次真实提取 attempt（本轮 r2 新增 48 次；本段历史统计保留），
自动重试 0，M_main 调用 0，生产数据库访问 0。最新最终选择
复用 7 个 `material-semantics-17` 已验收段，并以 `material-semantics-19` 定向替换 H2 预测所在段；
两个版本及逐段 provenance 已在 aggregate/audit 中显式记录。正式发布前须由质量门决定接受兼容
选择还是统一版本重跑，不能把当前候选直接视为已发布语义代。

### 2026-10-08 · PDF 表格消费边界收敛

依据本轮上游核查与人工取舍，不继续增加 OCR 或 reader 特例：后续真实运行对 `reader-pdf-*`
快照中的 table unit 默认 fail closed。表格原文、定位和缺口仍保留供审计，但 Claims、
`material_items`、relations 及 M_main 均不得消费；统一原因码为
`table_untrusted_or_incomplete`。只有另行完成完整性核验并显式标记 `verified_complete` 后才可进入
确定性表格分支。依赖未放行表格的正文不得把表文作为 context 间接送入模型，并同步降级为 partial。

该策略适用于未来运行，不追溯改写既有冻结金标、质量报告或本任务历史实际得分。第 2—3 页表格
继续记为明确范围缺口，而不是“无内容”；第 1 页已验收叙事抽取结果不受影响。

### 2026-10-08 · r2 签认后的有界候选诊断

两份 r2 审阅文档已签认，签认人/争议裁定人记录为 `xyl`；正式冻结产物见
[frozen-gold.json](../evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json)。冻结目标为
Claims/items/relations=20/48/24，金标未暴露给模型。按新增 r2 运行计划，工业富联 Markdown 使用
21/32 次调用，光模块 DOCX 使用 27/47 次调用，合计 48/79 次，单并发、自动重试 0；生产数据库和
holdout 访问为 0。

两份 Claims 均执行成功且协议有效，但为 `review_required`（分别产生 91、41 条候选事实）。两份
`material_items` 均执行成功但协议无效：Markdown 53 条 item（46 extracted、9 partial、1
no_supported），DOCX 82 条 item（71 extracted、20 partial、1 no_supported）。原子槽的否定/论据等
必需信号未完整覆盖及部分 item 校验失败，触发 `CS_DEPENDENCY_NOT_READY`；因此关系角色没有发起调用。
完整账本和诊断摘要见 [candidate-evaluation-summary.md](../evidence/11-live-20261008-non-table-gold-r2/candidate-evaluation-summary.md)。

本轮只闭合了“签认—冻结—有界候选执行”链路，未通过真实质量门。候选逐条裁定、额外候选 precision
判定、query/delivery/context_use 观察和发布/M_main 消费仍未完成，不能据此放行下游。

### 2026-10-08 · 候选逐条预裁定与发布前阶段观察

在不新增模型调用、不修改执行 store、不发布候选的前提下，已对两份来源持久化的全部 267 条候选
建立逐条代理预裁定草案：Claims 132 条，material_items 135 条，relations 0 条；每条保留原始候选、
证据、建议终态、建议匹配金标、规范化观测字段和理由，草案内部 unresolved 为 0。该草案明确记录为
`agent_pre_adjudicated_pending_named_human_signoff`，审核人字段没有冒充 xyl；只有具名人工逐条签认或
修订并追加冻结后，才可满足 scoring contract 的人工门。

当前代理建议的严格口径结果为：Claims matched/correct-extra/incorrect/duplicate = 15/22/94/1，
候选 precision 37/132（28.03%）、目标 recall 15/20（75%）；items = 4/65/65/1，候选 precision
69/135（51.11%）、目标 recall 4/48（8.33%）；relations 无候选，precision 为 N/A、目标 recall
0/24。以上是待人工签认的诊断建议，不是正式质量分数；即使全部照签，也明显不满足既定门槛。

对两个精确 source/build/store 分别实际执行一次只读 `purpose=cite`、`query_text=风险` 查询，均返回
`page_status=not_published`、`CS_NOT_PUBLISHED`、0 records。故本轮 query 记 missed；没有完整语义
证据单元可送达，delivery 记 not_delivered；没有语义证据进入成功的 M_main 请求且 M_main 调用仍为
0，context_use 记 not_used。该负向观察闭合了“发布前为何不能送达/消费”的实际证据，不可当作发布
后交付验收。

证据文件：

- [逐条代理预裁定](../evidence/11-live-20261008-non-table-gold-r2/candidate-adjudications.agent-draft.json)
- [query/delivery/context_use 观察](../evidence/11-live-20261008-non-table-gold-r2/coverage-observations.agent-draft.json)
- [摘要](../evidence/11-live-20261008-non-table-gold-r2/candidate-adjudication-summary.agent-draft.md)
- [输入输出指纹](../evidence/11-live-20261008-non-table-gold-r2/adjudication-manifest.agent-draft.json)

本步新增真实提取调用 0、M_main 调用 0、生产数据库访问 0、holdout 访问 0。任务继续保持
`needs-info`，下一门是具名人工逐条签认/争议修改；在此之前不得把草案改称人工裁定完成，也不得
发布或为观察 delivery/context_use 而绕过质量门。

### 2026-10-08 · 候选逐条裁定签认与正式冻结

用户随后明确确认 `candidate-adjudications.agent-draft.json` 已签认；签认人/审核人/争议裁定人记为
`xyl`。签认文件中的 267 条终态决定未发生改动，现已生成不可覆盖的正式冻结后继文件，并保留
代理理由与人工接受记录：

- [正式逐条裁定](../evidence/11-live-20261008-non-table-gold-r2/candidate-adjudications.signed.json)
- [冻结状态](../evidence/11-live-20261008-non-table-gold-r2/candidate-adjudication-freeze-state.json)
- [签认摘要](../evidence/11-live-20261008-non-table-gold-r2/candidate-adjudication-summary.signed.md)
- [冻结清单与指纹](../evidence/11-live-20261008-non-table-gold-r2/candidate-adjudication-freeze-manifest.json)

正式结果与草案建议一致：Claims precision 28.03%、目标 recall 75.00%；material_items precision
51.11%、目标 recall 8.33%；relations 无候选、目标 recall 0%。因此 `human_gate_satisfied=true`，但
`quality_gate_passed=false`、`publication_authorized=false`。此前两个精确 source/build/store 的
只读查询结果继续有效：均为 `CS_NOT_PUBLISHED`、0 records，delivery=`not_delivered`、
context_use=`not_used`、M_main 调用 0。

本次冻结新增真实模型调用 0、生产数据库访问 0，也没有执行发布。任务仍保持 `needs-info`：人工签认
不再是阻断项，后续须另行修复抽取质量并重新冻结/验证，不能用本次签认绕过质量门。

### 2026-10-08 · r5 校验/派生修复与零模型真实响应重放

复用 r4 工业富联的 17 份已保存 items 响应完成离线重放，不增加模型调用、不修改 r3/r4 历史账、
不重做金标。r5 结果为 92 items、78/78 extracted、10/10 packets completed，items 工件
`succeeded/valid/accepted`；92 个合格端点确定性生成 4 个 relation 候选。此前错误槽位 ID、三个
否定信号缺口和“整批不完美即阻断所有 relations”均已通过真实响应验证修复。

同时，真实 HTTP adapter 增加稳定 `Idempotency-Key=attempt_id`，但 provider 没有统一结果查询
接口，历史 Claims `outcome_unknown` 仍未被伪造为成功，也没有自动重发。光模块和 relations 模型
仍为 0 次调用；完整三角色候选名册、发布、query/delivery/context_use 与最终人工裁定仍待后续有界
任务。详见 [16 · r5 零模型重放与局部依赖修复](16-r5-offline-replay-remediation.md)及
`evidence/17-r5-remediation-freeze-20261008/freeze-manifest.json`。
