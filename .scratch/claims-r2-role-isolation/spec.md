# Claims／R2 独立结构化提取：实施规格与任务索引

- 日期：2026-10-02；状态复核：2026-10-08
- 状态：01—08 已完成本地功能验收；09 的 react/tui 零模型回放及两项 P2 修复已通过，待复验签认；10 已签认阈值、冻结 E01—E12 部分关键检查点并运行 seen-development 诊断，质量门未通过；非表格真实开发金标已修订为 r2 有限目标待审包（20/48/24），已修正条件、归属、重复与关系问题，尚未人工签核或正式冻结；11 已完成第 1 页叙事材料的真实 R2 候选抽取与语义优化（48 items / 5 relations），尚未发布或进入 M_main，任务整体未闭环。
- 设计依据：[report.md](report.md)；阶段放行真源：[R2 主计划](../../docs/plan/claims-market-closed-loop-plan.md)。
- 本文件保存实施范围、依赖和任务索引；逐任务状态与验收证据保存在各 issue，主计划保留阶段状态。不得在三处各维护一份独立完成率。

## 1. 首轮目标与边界

首轮打通 `react → stateful-react-agent/tui` 的单文档路径：固定来源快照 → Claims 与 R2 items 独立执行 → 按需 R2 relations → 校验/文件发布 → 新研究运行查询 → 完整证据进入实际模型消息 → ConsumptionLedger → corpus_submit_manifest → A4 报告检查。

先在合成夹具与 fake/replay 下零模型验证，再经独立授权试验真实提取模型和主线模型。文件工件试点不是恢复旧数据库写链，也不是完成 R2-S5 的生产 PG 验收。

非目标：第三条模型复判链、前置通用 LLM 抽取、自动模型级联、全库重跑、新解析/OCR 系统、Agent Team 全入口改造、默认生产启用、生产 PG 迁移和留出集试验。多模型组合和并发正确性用 fake/replay 验证；首轮真实执行并发上限 1。

## 2. 不得改变的契约

1. M_extract 在 `.env` 中独立配置 `STRUCTURED_EXTRACTION_PROVIDER/MODEL/BASE_URL/API_KEY`，不读 `OPENAI_*` 补缺值，不复用主线客户端；真实密钥由用户配置，不写入工件或测试。缺提取配置不阻断确定性处理、已发布结果查询或原文研究。
2. Claims、items、relations 是独立角色；首轮共用提取配置不包含 M_main。同源快照先于角色任务生成，R2 不以 Claims facts 为必需输入。
3. 复用 EvidenceRun/EvidenceFact、MaterialRun/MaterialUnderstanding；新增版本/执行/发布封装，不发明第三套断言 Schema。items-only 不隐式调用 relations，关系只使用固定且合格的 R2 端点。
4. 必要条件、否定、表头和脚注属于证据依赖；缺失/歧义必须降级，不把引文存在和执行成功当成语义完整。原文金标不能从路由输出或成功任务反推。
5. 外部取证绑定 `cv2:<build_id>`、`chunk:<chunk_id>` 及准确 unit/cell/区间；不直接转交现有 `cv2:<source_id>`，不由模型猜定位。
6. 每次实际模型请求单独登记 attempt 并预留角色/批次预算；兼容请求也计账，首轮自动重试为 0。未知 outcome 不自动重发、不记零费用。核查只读、零模型。
7. 不可变工件与版本化语义发布清单分离；跨运行回读走受控文件 Adapter，不调用旧表 load_evidence_run 加载新 JSON，不恢复 save_evidence_run。
8. 查询只读，不隐式抽取。完整证据单元须经所有后处理进入真实请求消息，才可确认送达；充分证据不要求 Agent 例行 fetch，后台确定性引文核验仍保留。
9. 抽取执行账、语义发布清单、研究消费账、报告证据清单各有职责。A4 的 skip/observe/异常不等于验收成功，不把 semantic manifest 直接提交为报告清单。
10. 原文研究始终可独立运行；真实模型、生产库、受保护样本和主计划阶段放行均不能由本规格自动授权。
11. `reader-pdf-*` 表格默认不可信任其完整性：原文与定位留在快照供审计，但 packet 必须以
    `partial / table_untrusted_or_incomplete` 阻断 Claims、R2、发布、语义查询和 M_main 消费；依赖该
    表格的 prose 不得通过 context 旁路。只有经过独立完整性核验，并在新快照中显式标记
    `table_consumption_status=verified_complete` 才可放行。评分范围内的表格目标继续计缺口/FN，
    不得从分母删除；本规则不追溯改写冻结金标或历史质量报告。

## 3. 任务索引与依赖

编号是依赖 ID，不是要求把所有任务顺序执行。表中不复制状态；状态以 issue 为准。01 完成后，02/03/10 的无外部副作用部分可协调推进；共享文件由任务负责人协调，不并发覆盖。跨 R2 阶段的开发夹具前置不等于绕过该阶段放行门。

| ID | 独立任务 | Blocked by | 工作包 / 主计划 |
|---|---|---|---|
| 01 | [冻结范围、契约与开工资产](issues/01-scope-contracts.md) | 无本地任务依赖 | W0；R2-S0，接口决议供 S2 使用 |
| 02 | [同源快照、证据依赖与取证映射](issues/02-evidence-snapshot.md) | 01 | W1；R2-S1 |
| 03 | [独立 env 与模型 Adapter](issues/03-extraction-config.md) | 01 | W2；R2-S2 |
| 04 | [角色入口、路由与关系拆分](issues/04-role-execution.md) | 02、03 | W2；R2-S2 |
| 05 | [调度、执行账、预算及只读核查](issues/05-execution-ledger.md) | 04 | W2/W3；R2-S2/S3 |
| 06 | [工件保存、发布与跨运行回读](issues/06-artifact-publication.md) | 05 | W3；R2-S2/S3，非生产 S5 |
| 07 | [语义查询、分页与完整证据交付](issues/07-semantic-query.md) | 06 | W5 前置接线；R2-S2/S3 |
| 08 | [消费账与报告清单/A4 适配](issues/08-consumption-report.md) | 07 | W5 前置接线；R2-S2/S3 |
| 09 | [react/tui 接线及零模型端到端门](issues/09-react-replay.md) | 08 | W5 回放；R2-S3 |
| 10 | [评分、标注范围与质量门冻结](issues/10-quality-gates.md) | 01 | W0/W6 准备；R2-S0/S3 |
| 11 | [获准后的真实模型有界试验](issues/11-bounded-live-trial.md) | 09、10、独立授权 | W4/W5 真实消费；R2-S4/S5 部分 |

01—08 已交付并完成本地功能验收；09 已完成零模型产品回放及遗漏修复，但仍待复验签认；10 的
评分实现与阈值签认已验收；非表格真实开发金标已形成满足最低数量的待审草案，但逐条人工签核、
争议裁定与追加式正式冻结仍缺。11 的来源范围和真实模型调用已获用户授权并实际
执行，当前只形成未发布候选：Claims 仅完成 preflight，R2 仅覆盖第 1 页叙事，M_main 调用为 0。
W6 的独立留出/多模型比较、W7 的生产化仍须另行立项，不能通过候选抽取成功自动宣布完成。

## 4. 01 已冻结的实现决议

本节是后续票据的接口真源。`contracts/contract-manifest.json` 及其绑定的 v1 Schema/样例是
机读版本；本文解释落点、事务和恢复语义。名称是后续实现目标，不表示生产入口已经存在。

### 4.1 模块、公开 Interface 与命令

- 新封装统一放在 `plugins/corpus/structured/`：`contracts.py`、`config.py`、`snapshot.py`、
  `roles.py`、`ledger.py`、`store.py`、`query.py`、`cli.py`。它们分别组合既有能力，不移动或
  复制 `EvidenceRun/EvidenceFact`、`MaterialRun/MaterialUnderstanding`。配置加载不得进入通用
  ReAct 内核。
- Python 调用面固定为 `build_snapshot`、`plan_batch`、`execute_batch`、`replay_batch`、
  `check_batch`、`publish_semantic`、`query_semantic`；研究 Agent 只暴露只读工具
  `corpus_semantic_query`，不暴露抽取执行工具。
- CLI 模块固定为 `plugins.corpus.structured.cli`，精确命令为：

```bash
uv run python -m plugins.corpus.structured.cli plan --snapshot SNAPSHOT.json --out PLAN.json
uv run python -m plugins.corpus.structured.cli execute --plan PLAN.json --store-root ROOT --allow-model
uv run python -m plugins.corpus.structured.cli replay --plan PLAN.json --responses RESPONSES --store-root ROOT
uv run python -m plugins.corpus.structured.cli check --batch-id BATCH_ID --store-root ROOT
uv run python -m plugins.corpus.structured.cli query --source-id SOURCE --build-id BUILD \
  --purpose cite --limit 20 [--cursor CURSOR] --store-root ROOT
```

  `plan` 只读快照并写调用方指定的计划文件；`check`、`query` 以 SQLite URI `mode=ro` 打开索引，
  不改账、不发布、不触发模型；`replay` 只消费显式响应目录并可写测试账；只有 `execute
  --allow-model` 可进入实际请求 Adapter。缺 `--allow-model`、专用配置或有效预算均在请求前拒绝。
  恢复继续使用已有 batch/task/attempt；`outcome_unknown` 不自动重发，另发请求必须显式建立新 attempt。
- 退出码固定为：`0` 成功；`2` 输入/Schema/协议非法；`3` 配置、根目录或安全边界拒绝；`4`
  预算、依赖、上下文或发布门未过；`5` 对象/版本/游标不可用或工件损坏；`6` 调用 outcome
  未知、需人工核查。细分错误码及 retryable 语义以 `contracts/v1/state-codes.json` 为准。

### 4.2 配置、文件布局与事务

- 文件根目录唯一配置键为 `CORPUS_STRUCTURED_ROOT`；CLI 的 `--store-root` 可显式覆盖。两者都缺失
  返回 `CS_STORE_ROOT_REQUIRED`，绝不回退 cwd、仓库扫描或旧 evidence 表。解析后的所有路径必须
  位于该根目录，越界返回 `CS_PATH_OUTSIDE_ROOT`。
- M_extract 仍只读 `STRUCTURED_EXTRACTION_PROVIDER/MODEL/BASE_URL/API_KEY`。四项按 provider
  契约整体校验，缺失返回 `CS_CONFIG_MISSING`；不逐字段回退 `OPENAI_*`。确定性任务、回放、
  check、query 在这些变量缺失时仍可运行。
- 根目录格式冻结为：`objects/sha256/<前两位>/<hash>.json|jsonl` 保存不可变快照、响应和角色工件；
  `manifests/<publication_id>.json` 保存不可变语义发布清单；`index/structured.sqlite3` 保存 batch、
  task、attempt、预算预留、派生任务、发布 generation/head；`cache/heads/` 仅保存可重建的发布指针缓存；
  `scratch/` 保存临时文件。manifest/ledger 绝不保存 API key 或含凭据 URL。
- 写端使用 SQLite（WAL、`foreign_keys=ON`、`synchronous=FULL`、`BEGIN IMMEDIATE`）完成“批次与角色
  额度检查 + attempt 预留”单事务；框架 no-op EventStore 不参与。不可变对象先写同目录临时文件、
  fsync 后 `os.replace`，但该原子替换不承担预算事务。
- 发布由同一 SQLite 的 source/build 行串行化，事务中比较父 generation、登记不可变 manifest hash
  并更新权威 head；`cache/heads` 在提交后刷新，仅是缓存。进程在 DB 提交后、缓存刷新前崩溃时，读端
  以 DB head 为准并可重建缓存；对象写成但未被事务引用时视为孤儿，不自动发布。研究读端使用只读
  连接和只读对象权限，不获得后台写权限。

### 4.3 Schema、哈希与坐标

- v1 分别冻结 snapshot、batch/task/attempt、角色工件、semantic publication、query/page、report
  semantic reference 六类封装。所有封装必有 `schema_version`；合法/非法样例与字节指纹由
  `contracts/contract-manifest.json` 绑定。
- 角色工件只记录业务 payload 的媒体类型和 SHA-256：Claims payload 必须验证为现有
  `EvidenceRun/EvidenceFact`，R2 payload 必须验证为现有 `MaterialRun/MaterialUnderstanding`；不创建
  第三套 Claim/Item Schema。
- 身份哈希为小写 SHA-256；输入使用 UTF-8、键排序、紧凑 JSON，数组保序。snapshot 身份必须含
  schema/parser/clean/chunk 版本、source/build/publication generation、unit/chunk、证据类型、locator、
  坐标系与起止、text hash、metadata hash；task/artifact/publication 身份再绑定其 profile、输入、上游
  artifact 和规则版本。时间戳、绝对路径、密钥及可变状态不进入身份。
- 原文区间固定为 exact unit `text` 上的零起点、半开 `[start,end)` Unicode code-point 区间；不是
  UTF-8 byte、UTF-16、PDF glyph、页内或拼接全文坐标。对外句柄为
  `cv2:<build_id>#chunk:<chunk_id>`，另带 unit、locator、text hash 和区间。重复引文必须靠句柄与
  区间区分，不按首次字符串命中。

02 的追加实现修订 `structured-snapshot-2` 不修改已冻结 v1 Schema：完整 gaps 摘要通过
已参与身份的 metadata 绑定，dependencies 必须与已哈希的明细一致。旧 builder-1 快照缺少这些
保证，消费端拒绝并要求重建。packet 内部拼接坐标必须经 `structured/mapping.py` 转换为上述
原文句柄；cell 标签缺少显式原文区间时降级，不推测表头。修订证据与限制以 02 文末记录为准。

### 4.4 状态、转换与跨角色映射

- 六个状态域严格分开：execution、protocol、publication、context、mapping、quality。唯一枚举和
  合法转换在 `state-codes.json`；执行成功不推出协议有效、发布、语境完整、跨角色一致或质量通过。
- `unlinked` 表示尚无可证对应，不能解释为 `confirmed`；`suspected` 需保留原因；只有相同 snapshot、
  可定位命题跨度/cell 及主体/指标或对象/期间绑定可确认时才为 `confirmed`。可比字段在 value、unit、
  factuality、polarity、condition 或 attribution 上不同则为 `conflict`，受影响 compare/calculate
  许可撤去，但不静默改写任一业务 payload。
- Claims/items 可独立合格和发布；relations 只依赖固定且合格的 material item IDs。关系失败不撤销
  items；端点撤回后旧关系不能自动挂接新 item。未执行、无候选、未就绪、预算不足必须使用不同状态/
  原因，不能都写成“无关系”。

### 4.5 首轮协议与关系候选范围

| 角色/方法 | 首轮唯一支持协议 | 约束 |
|---|---|---|
| Claims table | `claims-deterministic-v1` | 仅显式 `verified_complete` 的结构完整 cell 可确定性投影；PDF reader 表格默认审计留存且拒绝消费，零模型 |
| Claims prose | `claims-json-v2` | 复用 ClaimRecord/EvidenceFact 规范化与校验 |
| R2 items | `material-atomic-jsonl-v4` | speakers/items only，禁止隐式 relations |
| R2 relations | `material-relations-jsonl-v1` | 只接收固定 items validation 版本和端点集合 |

历史联合 JSON、旧 `material-jsonl-v1`、slot 模式中的隐式关系和其他 provider 特有格式不在首轮支持
矩阵，真实请求前返回 `CS_PROTOCOL_UNSUPPORTED`，不静默降级。关系候选只从同一 snapshot、同一或
显式复合证据包中已合格 items 的原文明示连接词、问答配对、归属结构及已版本化确定性规则生成；不以
共现生成因果，不跨文档，不使用 Claims fact_id 作端点。每父 items task 最多一个派生候选清单；批次
计划分别冻结候选规则版本、最大关系 tasks 和最大 attempts，超出须新计划。

### 4.6 查询、分页与报告引用

- `corpus_semantic_query` 输入固定 source/build、purpose、词法/字段过滤、limit/cursor；首轮排序为
  `semantic-lexical-sort-v1`，不做 LLM query rewrite/rerank。游标绑定 query hash、排序版本、
  publication ID/generation 和页位置；撤回、用途收紧或发布变更返回 `CS_CURSOR_STALE`，不得跨版续页。
- 返回的 evidence unit 必须把 value/period/unit/header/footnote/condition/negation/attribution 依赖
  与原文范围成组交付；依赖状态与 `usable_for = cite|compare|calculate` 分开。预算放不下完整单元时少返
  一条并标 `budget_limited`，不截断 JSON，不只发裸数值。
- 报告引用固定携带 report anchor/quote、publication ID、record ID、purpose、一个或多个精确原文
  ranges、逐依赖 required_for/status、delivery/publication/quality/verification 状态。只有原文确实进入
  实际模型消息后 delivery 才能从 pending 变为 delivered；后台 resolver 核对或工具返回成功不算送达。
  semantic publication manifest、执行账、消费账和 report evidence manifest 互不替代。

### 4.7 合成资产与指纹

- Schema 清单：`contracts/contract-manifest.json`，SHA-256
  `8cbe94827de6764feda994da4c33c9fcaf57e3ee77d3beec32da177c0cbce154`。
- 合成资产清单：`tests/fixtures/corpus_structured_synthetic/asset-manifest.json`，SHA-256
  `6f9cc51597601b05e220ce3b74696269311ff50d246cf8272aced833a491d073`；cases SHA-256
  `df2f1c9e4005a13702df798df0141b397c99a90e68ff9a8f1b4179692a23b179`。覆盖普通数字、纯观点、
  混合条件、否定、预测/实际、表头/脚注、跨包限定、重复引文、解析缺口；全部虚构，不含真实业务原文。

### 4.8 主计划前置核对与边界

- 已从唯一主计划公开台账核验：I0 A/B/C 已完成；I1 已完成并经 M4 独立复核与 U 签认；这些证据允许
  本票继续规格与合成资产工作。未读取其受保护来源或留出内容。
- I3/S3 的阶段放行不能由本专项替代。09 的零模型回放已通过但待复验签认；10 已将候选输出前
  人工确认的 E01—E12 冻结为部分关键检查点，阈值与裁定人也已签认，但诊断评分未通过，且该集合
  不是每角色至少 20 条的完整三角色金标。后续已从两份获准、尚未执行本专项候选的真实开发材料
  起草并修订非表格 Claims/items/relations=20/48/24 的 r2 有限目标审阅包。在逐条人工签核和正式
  冻结前不能计为人工金标；该包不宣称整篇穷尽标注，额外正确输出须独立裁定、不自动计 FP，
  全部候选未裁定前不能报告完整 precision，因此真实质量门仍未过。
- 用户已于 2026-10-04—05 明确批准贵州茅台研报范围并授权有界真实提取调用；11 已执行 Claims
  preflight 和第 1 页 R2 语义抽取。该授权只覆盖开发试验，不转授生产 PG、受保护留出、正式发布或
  M_main 消费，也不能补足 10 的金标与质量分母。
- 本票未修改主计划、report 或既有 freeze/guard/gold 文件，只新增 v1 契约和合成资产并更新本专项的
  spec/issues。未来若改既有冻结资产，必须按其 manifest 的追加式 parent/revision 流程另立修订，禁止
  原地覆盖历史。

## 5. 全局执行约束与验收纪律

- 01—10 仍保持真实模型请求与生产数据库访问为 0，只用 fake/replay、合成夹具和显式批准的本地开发
  资产。11 已在独立授权下产生 68 次真实提取 attempt，自动重试 0，生产数据库和 M_main 调用仍为 0。
  不得使用工具查询隐式触发模型；SDK 自动重试和隐藏兼容请求也必须计账。
- 文件测试写 pytest 临时目录或明确的专项输出目录。不得读取真实 `.env` 密钥作为测试数据；环境隔离测试使用假值。读端/主线不获得后台写权限。
- 01 已创建本专项的 v1 Schema、正反例和合成 fixtures；02—08 已实现第 4 节主要 Interface，并由
  09 的文件工件产品回放接通。这里的“已实现”不等于生产 PG、真实质量门或默认产品启用；未采集的
  环境/真实消费证据和被跳过的必要用例仍不能算通过。
- 每票使用调用方相同 Interface 测试。保存测试命令、退出码、结果、适用范围、基线/工件指纹及已知限制；仅把 fixture 手工填成预期状态不能证明接通。
- Python 环境按仓库使用 uv；命令从仓库根目录执行，不通过 pip 安装。新增开发测试须明确阻断真实网络/模型/生产数据库，尤其防止 uv 环境准备之外的测试业务路径触外部资源。
- 代码任务按影响执行 Ruff、类型检查、符号闭包及 import smoke；真实模型 preflight 只能在 11 获准预算内运行。零模型阶段明确记录其未执行，不宣称所有提交前门已通过。
- 未落定决议在对应 issue 中保持 needs-info/needs-triage，不由实现者选择会扩大数据、预算或产品范围的默认值。不得以“本地票已完成”代替主计划阶段签认。

## 6. 第一阶段完成条件

09 的回放闭环能从固定快照生成、发布并跨运行读取两路结果，经实际 react/tui 工具链送达证据、提交报告清单，正例最终 verified；仅新查询不 skip，充分证据不例行 Agent fetch。缺脚注、错误句柄、裁剪、撤回、未知调用和损坏工件均产生预期缺口/降级，零真实模型调用可核验。

10 单独交付质量评分与标注冻结；不得把接线通过当作模型准确率过门。11 已在具体模型/来源/预算获得
独立授权后开展有界开发试验，但 09/10 和阶段门未闭合，因此其结果只能作为候选与缺口发现，不能
倒推阶段验收。当前历史消费账/清单测试只作为回归基线，不是上述真实闭环的验收证据。

## 7. 任务状态维护

每个 issue 的 `Status` 使用仓库分诊标签；`Execution` 记录未开始/进行中/待验收/已验收，只有交付与验收证据齐备才可标已验收。`Blocked by` 指向必须先验收的票据，外部门另列。不得把 ready-for-agent 当作已完成；依赖解除后须复核任务契约，再改变分诊状态。每次执行结论追加到该票据 `Comments`，阶段证据回填唯一主计划，本索引不复制执行进度。
