# R2 P0：执行条件与基线保护报告

日期：2026-09-14。执行授权：补齐条件并启动 P0；未启动 P1—P9。

## 结论

**八项执行条件已补入 plan-v2；P0-A 离线基线通过，P0-PG 尚未验证，因此 P0 总状态为 partial。**
当前可以为后续 P1 设计提供固定基线，不构成新模型调用、生产代码改造、R2/R3 放行或 CLI 全链路
已验收。Web 继续暂缓。

本轮没有修改生产实现、旧 scorer、历史预算、gold 或真实来源；没有真实模型/市场请求、入库或
生产 PG 连接。操作范围是计划/任务文档、scratch 基线工具、合成夹具及审计产物。

## 1. 补齐的执行条件

详见 [计划 §11](../../docs/plan/r2-local-redesign-cli-closure-plan.md)：

| 条件 | 本轮落实的定义 | 实现责任阶段 |
|---|---|---|
| 运行时与开发验收分离 | ValidationReport 不读取 gold，EvaluationReport 才评开发语义；证据合法不等于语义已验证 | P1—P2 |
| 消除验证依赖循环 | P3 验已有响应经新链路的稳定性；P4 验新协议实际生成；fake 不替代实测 | P0—P4 |
| 有限义务可行性 | 六类结构正反例、深度/容量/未解决项，禁止用 gold 决定 planner | P1 |
| 旧检索衔接新证据 | 明确 doc/locator→source_rev/指定 EvidenceRun；缺失/歧义阻塞，不默认最新版本 | P6 |
| 人工裁决边界 | 代理提供差异建议；用户/指定审核者裁决争议，记录 hash/理由/身份；限首批范围，不无限加任务 | P1—P3 |
| 中断预算一致性 | 调用前预占额度；unknown_outcome 占额度且不自动重试，恢复先对账 | P2—P4 |
| 成功响应留存 | 新授权轮保留全部响应正文和安全诊断，写入失败停止；不记录隐藏推理/密钥 | P2—P4 |
| PG 与规模前置 | 提前盘点独立 PG/扩展；长开发范围先离线算容量，再单独申请实测 | P0/P3/P6/P9 |

这些是执行条件，不是已完成的重设计能力。按 codebase-design 的 Interface/Seam 分工避免把金标
验收放入正式运行路径；没有为本轮建立第二套业务框架或存储。

## 2. 已冻结的基线

目录：[baseline-4e2c45ce216a9421](p0-baselines/baseline-4e2c45ce216a9421/baseline-manifest.json)。

- [baseline-manifest.json](p0-baselines/baseline-4e2c45ce216a9421/baseline-manifest.json)：HEAD、环境、开发资产绑定、独立实例盘点。
- [protected-paths.json](p0-baselines/baseline-4e2c45ce216a9421/protected-paths.json)：2336 个代码、配置和测试文件 hash，当前例外列表为空。
- [baseline-results.json](p0-baselines/baseline-4e2c45ce216a9421/baseline-results.json)：实际门禁结果、行为快照和结果文件 hash。
- workspace-code.patch：仅代码的 HEAD→工作树差异；不包含 `.env`、配置明文或原始材料。11 个未跟踪受保护源码路径单独登记，不误认为 HEAD 已覆盖它们。
- 四份批准的开发来源只做字节哈希绑定；旧金标仅作为不透明文件哈希读取，不读取留出原文。
- 54 个绑定资产包含旧预算/评分代码、四份开发来源、两份 gold、v12/v13 产物、18 份原始响应及本轮基线工具/夹具。

基线 manifest 的外部固定 SHA-256：

```text
4e2c45ce216a942137f60b863e236ae46f3a8870317ebdbe9ead6342b4698076
```

HEAD 是 `2c0c76582ae611e5b518b331673bd917212bc342`。实际基线是其上的当前脏工作树，不是回退到
HEAD；历史 R2 失败代码也在基线中如实保存。

基线工具 [p0_baseline.py](p0_baseline.py) 的 verify 检查文件增加/删除/内容漂移、历史资产、HEAD、
环境及保存的 patch。manifest 本身必须匹配外部固定 SHA，不能只靠“重算自己的 hash”通过。
结果文件另由 baseline-results 中的 hash 绑定；verify 不冒充语义评分或候选结果比较器。

当前为 **P0 严格保护**，包括整个 material_semantics 和 service，不自动开启未来 R2 白名单。
进入 P1/P2 后如需允许局部改造，必须另立前瞻保护策略、保留本基线及其快照，不能覆盖本清单解除
报错。service 公共 AST 指纹已记录，但本轮并未以 AST 相同替代整文件保护。

## 3. 实际执行结果

| 检查 | 结果 |
|---|---|
| 核心离线数据链，34 文件 | 495 passed、36 skipped、1 deselected |
| workflow/registry/CLI profiles，5 文件 | 110 passed |
| 基线工具正反控 | 18 passed |
| R2 禁用故障注入，重复子集 | 169 passed、1 skipped |
| import smoke stage 1 / 2 | 336/336、385/385 |
| symbol closure | 435 文件，0 missing |
| scratch 新工具与测试 Ruff | 通过 |
| v12/v13 原始响应库存 | 各 9/9，hash 错误 0；MaterialRun 身份验证通过 |
| 两次独立进程快照 + R2 禁用快照 | 三者逐字一致 |

不重复计算的测试共 **623 项通过**，其中 605 项为既有工程用例、18 项为本轮基线工具用例。
169 项隔离结果是重复子集。没有将这些数量解释成相同数量的真实材料或业务场景已通过。

反控实际覆盖：源码修改/删除、新增文件、资产修改/缺失、保护清单篡改、manifest 篡改及重新序列化、
HEAD/环境变化、patch 修改、越界路径/符号链接、重复写入；修改 service 公共方法或新增 import
会改变公共 AST 指纹。所有变异都在临时夹具中，不修改真实公共代码。

工具初次自测发现 20 与 20.0 的字符串比较不适合作为 Decimal 数值控制，已在冻结前修为数值比较，
随后真实结果仍完整保存原精度。该问题属于新诊断工具，不是旧财务计算错误。

## 4. 行为快照的覆盖与限制

使用一份固定合成公司材料，调用现有正式 Interface，保存：

- EvidenceRun、source/parse/packet/fact/run 身份与原文坐标、Claim 用途许可和投影。
- 100→120 的营收增速复算结果 20%、反向期间与错 revision 的拒绝。
- 零预算 deferred 状态，正式 `claims --run-id ... --purpose calculate` 的 JSON 与退出码。
- 临时 SQLite 的重复入库 `[true,false]`、检索句柄/排序/snippet 和逐字 fetch。
- 既有固定 HTTP 夹具经真实市场 transport、render、trace resolver 得到的行情/历史/财务输出与回取文本。

三份快照 SHA-256 均为：

```text
847f3381a5c2f86a86b0efcde6ae79efceba7e9662e964962e69071a06b0133b
```

仅去除行情的相对显示字段 age；没有去掉 as_of、published_at、known_at、期间、版本或金额精度。
SDK 日志中的 example.test 是 httpx.MockTransport 固定响应，不是外部请求；jieba 的“加载模型”
也不是 LLM 调用。证据保存用内存替身，市场用固定 HTTP 夹具，SQLite 不是 PG 中文检索验收。

旧市场 resolver 未按 request_id 严格过滤的问题仍存在，不借基线冻结掩盖。该修正属于 D1 的独立
变更评审，当前快照用于保护既有行为而非证明其精确调用语义已达标。

## 5. 离线安全与 P0-PG 未完成项

执行器在测试前设置不可用诊断 DSN，并直接阻断 psycopg.connect，避免 libpq 绕过 Python socket。
Python socket.connect 同时禁止外连。原 PG 测试因此显式 skip，不会创建/删除生产 schema。
真实 PDF 抽样测试文件及真实铜箔分类测试被排除；没有运行真实模型 preflight、线上 THS 或独立留出。

环境：Python 3.12.14，pytest 9.1.1，pydantic 2.13.4，PyMuPDF 1.28.2，python-docx 1.2.0，
psycopg 3.3.5，httpx 0.28.1，jieba 0.42.1；uv.lock 已绑定。

只读盘点确认本机无 initdb，存在 Docker 命令。**未连接 Docker daemon、未创建容器、未拉镜像，
因此没有证实独立 PostgreSQL 可用，更不能声称整个数据库能力不存在。**
现有初始化要求 zhparser、vector、pg_trgm 与 zhcfg；独立实例必须确认扩展及权限，不能用普通
PG 或 SQLite 冒充。P0-PG 保持 not_verified；P6/V1 前需在用户确认的隔离环境补齐存储、恢复、
版本引用与实际检索基线。当前无需提供生产密钥。

## 6. 复核命令

执行结果清单 `p0-baselines/baseline-4e2c45ce216a9421/baseline-results.json` 的外部固定 SHA-256：

```text
be0a071986d01bf2f179fa8318edb6eb161afdce621c4178961031c549e5dc86
```

该清单绑定各测试结果与三份快照；源代码基线验证和执行结果完整性检查须分别进行。

在 WSL 仓库根目录运行（当前环境可使用 `/home/administrator/miniconda3/bin/uv`）：

```bash
uv run python .scratch/corpus-evidence-pipeline/p0_baseline.py verify \
  --manifest .scratch/corpus-evidence-pipeline/p0-baselines/baseline-4e2c45ce216a9421/baseline-manifest.json \
  --sha256 4e2c45ce216a942137f60b863e236ae46f3a8870317ebdbe9ead6342b4698076
```

重放时先验证基线，输出必须是同一基线目录下尚不存在的新文件，工具拒绝覆盖已冻结结果：

```bash
uv run python .scratch/corpus-evidence-pipeline/p0_baseline.py snapshot \
  --manifest .scratch/corpus-evidence-pipeline/p0-baselines/baseline-4e2c45ce216a9421/baseline-manifest.json \
  --sha256 4e2c45ce216a942137f60b863e236ae46f3a8870317ebdbe9ead6342b4698076 \
  --block-r2 \
  --out .scratch/corpus-evidence-pipeline/p0-baselines/baseline-4e2c45ce216a9421/snapshot-recheck.json
```

比较新快照的 SHA 是否等于上面固定值；不能只看进程退出码 0。测试重跑使用 action `suite`，
`--suite core|platform|isolation|guard`，同样指定 manifest/SHA 和新的 `--out` 文件。
本报告不是要求重复消费任何模型预算。

## 7. 下一步

本轮到此停在 P0：离线部分完成，数据库部分明确保留。后续 P1 可基于此做零模型 Interface/planner/
评分分工设计，但需用户继续授权，不自动启动实现。后续 P3 的逐类语义非回归、P4 模型实测、关系、
R3/CLI 和独立留出全部仍未完成；本轮资产 hash 通过不替代其中任何业务门。
