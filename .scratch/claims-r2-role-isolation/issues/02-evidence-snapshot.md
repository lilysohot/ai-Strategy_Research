# 02 · 同源证据快照、必要语境与取证映射

Status: ready-for-human
Execution: 已验收
Type: task
Plan: W1；R2-S1
Blocked by: 01
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；本票所列 snapshot 实现、合成夹具与测试现已交付，真实 PG 集成仍不在本票范围。

## 目标

让 Claims 和 R2 从同一不可变证据快照取输入，保留可验证表格及必要限定，并能映射到当前原文 resolver 接受的坐标。

## 前置与外部门

01 已验收；确认 R2-S1 的 S0/I1 前置，不把合成快照通过冒充真实来源准入。数据库读取用内存/录制 Adapter；真实 PG 集成验证另经环境门，不在本票连接生产库。

## 范围与预期文件

- plugins/corpus/service.py、evidence_pipeline.py、material_semantics.py 的输入接缝；优先复用 preparation/read_pg.py、现有表格/cell 结构，不重写解析器。
- 快照实现固定落在 `plugins/corpus/structured/snapshot.py::build_snapshot`，输出遵守
  `contracts/v1/evidence-snapshot.schema.json`；tests/test_corpus_structured_snapshot.py 与合成 fixtures。
- 精确绑定 source/build/publication、units/cells/坐标、解析缺口、包清单及规则版本，先封存后调度。
- 在包/条目中记录必要标题、指代、条件、否定、表头和脚注依赖；未知依赖不猜补。

## 验收条件

- [x] 活动 build/publication 切换期间，只产生一致快照或调用前失败；同文字但位置/类型变化会改变指纹。
- [x] 两路可取不同候选子集但共用快照；R2 启动不要求 Claims facts 成功，旧文件独立解析不被当作新默认输入。
- [x] 仅经独立核验并显式标记 `table_consumption_status=verified_complete` 的完整表格进入 Claims
  table 分支；PDF reader 表格默认仅审计留存、禁止下游消费，R2 所需脚注/说明仍不因 table 类型
  被静默跳过。
- [x] 包外“仅在并购完成情况下”能关联原文依赖；歧义、缺失、超预算时给出明确降级与定位，不能发布为无条件可计算预测。
- [x] 每段发布候选可映射为 cv2:<build_id>、chunk:<chunk_id> 和准确 unit/cell/quote 区间；拒绝将 source_id 当 build_id。
- [x] 重复引文、复合证据和续表不靠首次字符串命中/最近文本猜测；不同片段保留各自句柄。
- [x] 现有业务字段/历史读取契约回归通过，未改变基础入库成功条件。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_snapshot.py tests/test_corpus_evidence_pipeline.py tests/test_corpus_material_semantics.py -q
uv run ruff check plugins/corpus tests/test_corpus_structured_snapshot.py
```

新增快照测试须通过注入只读 Adapter 覆盖版本切换，不依赖真实 DB。

## 非目标

不新增 OCR、视觉/解析供应商，不无差别重建来源，不保证确定性规则发现所有隐含语义遗漏。

## 验收记录与后续

以下各轮交付和修订记录保留为历史；当前有效验收结论以文末“最终收口核查”为准。
本票已完成约定的本地验收；不代表全仓或真实环境全部门禁通过。

2026-10-02 本轮交付：

- `plugins/corpus/structured/snapshot.py`：只读 `SnapshotReader` seam、活动 publication 双读一致性门、
  source/build/generation/parser 绑定、不可变 unit/cell/dependency/gap 封装、content identity 校验及
  Claims/material 独立候选选择。SHA-256：
  `334df26d6892a199325ff4e14d88984e3489592cfd5392036a8e09037746a0b2`。
- `evidence_pipeline.py`：`evidence_document_from_snapshot` / `build_evidence_run_from_snapshot`；
  `cv2:<build_id>` + `chunk:<chunk_id>` 句柄，table/cell 确定性投影与 unit code-point spans。
- `material_semantics.py`、`service.py`：同一 snapshot 的 R2/Claims 调用接缝；R2 的 heading/table note
  转为独立 prose packet，不以 Claims facts 为输入，不走文件二次解析。
- `tests/fixtures/corpus_structured_snapshot/asset-manifest.json` 与 `source.json`，均为纯合成、真实
  source 清单为空。清单 SHA-256：
  `a98d7b4d984f6b73f5ae87526905e9ed510fd2a0f0694a348f873e09f499cd1d`；source SHA-256：
  `cfadeececa49d855e194165e8b10d98a77a849ba70ffc22fe1d31b6f36398e78`。
- `tests/test_corpus_structured_snapshot.py`：publication 切换、同文异位/异类、双角色同源、table
  + footnote、跨包条件、missing/ambiguous/budget 降级、续表、重复引文、坏 cell 区间及 service
  零 DB 接缝。SHA-256：
  `7b81ba0d24c0a622f2b45aa215fce43d50ad73f67cf8a2f172c95fa2c8f0215b`。

实际验收命令及结果：

```text
uv run pytest tests/test_corpus_structured_snapshot.py \
  tests/test_corpus_evidence_pipeline.py tests/test_corpus_material_semantics.py -q
70 passed in 0.78s                                      exit 0

uv run ruff check plugins/corpus tests/test_corpus_structured_snapshot.py
All checks passed!                                      exit 0

uv run pyright plugins/corpus/structured/snapshot.py \
  plugins/corpus/evidence_pipeline.py plugins/corpus/material_semantics.py plugins/corpus/service.py
0 errors, 0 warnings, 0 informations                   exit 0

uv run pytest tests/test_corpus_structured_contracts.py \
  tests/test_corpus_structured_snapshot.py tests/test_corpus_evidence_pipeline.py \
  tests/test_corpus_material_semantics.py -q
81 passed                                               exit 0

uv run python tools/import_smoke.py --stage 1
[framework] 372/372 modules imported                    exit 0

uv run python tools/check_symbols.py
OK: 0 missing-symbol import(s) across 471 file(s)       exit 0

git diff --check -- <02 changed paths>
(no output)                                             exit 0
```

边界：I1/M4 的公开前置已核验，01 已验收；本轮只用注入只读 Adapter 和合成 fixture，未连接 PG、
未读取真实/受保护来源。真实 PG read adapter、真实 source/build/scope 准入和 R2-S1 阶段签认仍需其
独立环境/范围门；本票进入人工验收前不解除 04 的依赖。真实 preflight 按 spec 留给 11，本轮未运行。

本轮真实模型调用 0，业务网络调用 0，生产数据库访问 0。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
- 2026-10-02：01 已验收且用户要求开始下一个任务；进入同源快照、必要语境与取证映射实现，
  继续保持真实模型调用、业务网络和生产数据库访问为 0。
- 2026-10-02：snapshot facade、Claims/R2 输入接缝、合成 fixture 与回归已交付；70 项目标/回归测试、
  Ruff、Pyright、import smoke、symbol check 均通过，转 `ready-for-human / 待验收`。
- 2026-10-08：按最新人工决策增加 PDF 表格 fail-closed 消费门。`reader-pdf-*` 快照中的 table unit
  默认保留原文和定位，但 packet 标为 `partial / table_untrusted_or_incomplete`，Claims 与
  `material_items` 均不提取；依赖该表的正文不得把表文混入 context，并显式降级。只有单独核验完整
  后写入 `table_consumption_status=verified_complete` 才可放行。非 PDF 的既有结构化表格默认兼容，
  也可用 `untrusted|incomplete|blocked` 显式阻断。本修订不增加 OCR/reader 复杂度，不改写历史评分。
- 2026-10-08：本修订验证：任务卡 pytest **127 passed**；跨角色任务卡 pytest **279 passed**；
  改动文件 Ruff/format 与 Pyright 均通过；stage-1 import smoke **386/386**，symbol check
  **484 files / 0 missing**。扩展 `test_corpus_structured_*.py` 为 **351 passed / 1 failed**；唯一失败
  是 publication 的 condition 跨角色映射期望 conflict、实际 confirmed，使用非 PDF 合成输入，
  不经过本次 PDF table 消费门，作为范围外问题保留，未通过改断言掩盖。
- 2026-10-08：后续独立诊断确认上述唯一失败不是 publication 丢失 condition，而是测试仍按模型
  原始 `statement_role=condition` 断言；`material-semantics-19` 会对没有显式条件词的来源将该伪条件
  正确规范化为 `claim`，发布层比较的是已校验后的 accepted record，因此 `confirmed` 才是正确终态。
  集成期望已按最终工件修正；显式条件词继续由材料语义专项测试保留为 `condition`。
  修复后跨角色映射 **13 passed**、publication 专项 **28 passed**、全部 structured 回归
  **352 passed**；相关 Ruff 与 format check 通过。

## 根因核查与通用修复（revision 2）

2026-10-02，用户要求先核查根源，再进行普遍性修复。基线 HEAD：
`d05df2251e6a505aa96405b2981d430a19a61abc`，保留此前未提交的 02 实现。

### 根因与复现

使用 diagnosing-bugs 流程，先运行内存最小复现，再添加调用面回归：

- 一个 unit + 一个 gap，删除 gap 后 snapshot_id 不变；连续两次复现。
- `uv run pytest tests/test_corpus_structured_snapshot.py -q`：首次新增反例得到
  **14 failed, 14 passed，exit 1**；覆盖 gaps/dependencies 身份、显式错误 chunk、传递依赖、
  四种清洗处置状态、R2→Claims 耦合、模型配置回退及 Unicode 续表坐标。
- 后续三条限定语反例证明：已关联的 condition/negation/attribution 仍会得到 calculate 权限；
  邻包反例证明：out_of_scope 包仍能进入 R2 previous_excerpt。均先失败、后修复。
- 对照 `preparation/clean.py::verify_clean_region`、真实清洗器合成调用和
  `preparation/read_pg.py` 的原文/拼接映射，未发现上述问题来自清洗文本算法；根因在清洗结果的
  消费边界丢失状态、依赖和坐标语义，以及复用旧执行入口。**不改清洗规则、解析器或基础入库条件。**

### 通用修复及兼容边界

- 构建规则升为 `structured-snapshot-2`；通过 v1 允许扩展的 metadata 绑定完整 gaps 摘要，
  校验 dependencies 与已哈希 dependency_details 一致、目标存在、身份唯一和合法 generation。
  输入 metadata 深拷贝；入口校验拦截序列化/内存篡改。旧 builder-1 快照必须重建，不能假装升级。
  原冻结 Schema、manifest 和合成资产均未覆盖；新增测试验证 runtime 输出仍符合冻结 v1 形状。
- 显式 chunk 错误即 missing；按完整依赖图传播 missing/ambiguous/budget/清洗不可用状态，
  循环降为 ambiguous，强失败继续传播；非递归实现验证 1,100 单元链。候选选择和必要语境使用闭包。
- 表格 value 和标签使用 exact unit 区间；表头/单位必须提供显式来源引用，没有证明则降级。
  原旧夹具的裸标签不再作为完整表格通过，新增完整来源证明正例保留确定性抽取与可计算能力。
  公共 `structured/mapping.py` 明确区分内部 packet 拼接偏移与对外 unit 坐标，返回
  build/chunk/unit/locator/hash/quote/区间；重复引文、重复 unit 名、续表、跨 chunk 表头及 Unicode
  均不用首次字符串命中或最近位置猜测。
- Claims payload 继续使用原业务 Schema，evidence_alignment 保留原文与依赖片段；条件、否定、
  归属尚未完成语义核验时撤去 compare/calculate，不能作为无条件数字发布。R2 邻包语境不再包含
  unavailable 包；原文顺序保留。R2 使用无 facts 的 EvidenceRun 输入封装，不再执行 Claims。
- 新 snapshot service 正预算入口只接受显式注入的提取 Adapter，缺失即拒绝，不回退 OPENAI_*。
  03 的专用配置和 04 的角色协议执行仍归后续任务，本票不抢先实现真实模型接线。
- 新测试显式阻断 socket 连接、CorpusService._connect 和默认模型构造；数据均为合成。

### 修订验证记录

```text
uv run pytest tests/test_corpus_structured_contracts.py tests/test_corpus_structured_snapshot.py \
  tests/test_corpus_evidence_pipeline.py tests/test_corpus_material_semantics.py \
  tests/test_corpus_preparation_clean.py tests/test_corpus_preparation_chunk.py -q
156 passed in 14.87s                                   exit 0
其中 snapshot 专项 43 项；含历史业务、清洗和分块回归。

uv run ruff check plugins/corpus tests/test_corpus_structured_snapshot.py
All checks passed!                                    exit 0

uv run pyright plugins/corpus/structured plugins/corpus/evidence_pipeline.py \
  plugins/corpus/material_semantics.py plugins/corpus/service.py
0 errors, 0 warnings, 0 informations                  exit 0

uv run python tools/import_smoke.py --stage 1
[framework] 373/373 modules imported                  exit 0

uv run python tools/import_smoke.py --stage 2
[eval] 420/421 modules imported                       exit 1
ModuleNotFoundError: harbor（当前环境缺少可选 eval 依赖）

uv run python tools/check_symbols.py
OK: 0 missing-symbol import(s) across 472 file(s)      exit 0

git diff --check
(no output)                                          exit 0
```

修订工件 SHA-256（不覆盖首次交付指纹）：

| 文件 | SHA-256 |
|---|---|
| `plugins/corpus/structured/snapshot.py` | `3489df9bdd4925d6bc13c707e700eb9c179aa1cb316c4672d3f7dddf6e132f18` |
| `plugins/corpus/structured/mapping.py` | `b9a5808732ee18b7ce363db343878f31e57b8b65e1a81fe69abd86c723d9ab30` |
| `plugins/corpus/evidence_pipeline.py` | `af805aa92c24eae4221d05441a90053da9a960a5be6ab5b6e534031b972e7402` |
| `plugins/corpus/material_semantics.py` | `eca1034c4f9169c5c35a1ff6be4aa32a18a8de83f0da18a62b4687f8663193b1` |
| `plugins/corpus/service.py` | `e73502a924120c98dab65184e934d8832d38a2ae68a0894d12d7b6a5ca249835` |
| `tests/test_corpus_structured_snapshot.py` | `85ad8a5cbf096d9f24fef7510a93a2ccb538ffcfc4754c3c930ddd443a2ad04a` |

结论：已复现缺陷的本地通用修复及目标回归通过；仍为 `ready-for-human / 待验收`。
eval 环境门尚未通过，未安装依赖、未宣称所有提交门通过。真实 preflight 未运行；真实模型、
业务网络、生产数据库调用仍为 0。真实 PG Adapter、来源准入、阶段签认及后续角色执行不在本次
证明范围；不解除 04 依赖，不修改主计划阶段状态。

### 收口核查修复（revision 3）

2026-10-02 的双轴收口核查发现：快照此前只验证身份哈希自洽，没有完整验证冻结输出契约；
`_chunk_locator` 又会把空输入规范化为 `chunk:`。因此空 `chunk_id`、空 `locator`、缺失或空
parse/clean/chunk 版本仍可能构成自洽快照。修复采用同一 `verify_identity()` 契约门覆盖构造与
反序列化消费，并在构造版本映射时拒绝非空字符串契约不成立的输入；同时验证 gap 必需字段。

修复前新增的最小红灯集为 13 failed / 1 passed；修复后边界集 16 passed。最终门禁：

```text
02/03 专项及历史回归：212 passed                         exit 0
ruff check + ruff format --check：通过                    exit 0
pyright plugins/corpus/structured：0 errors, 0 warnings   exit 0
import smoke stage 1：375/375                              exit 0
import smoke stage 2：424/424                              exit 0
check_symbols：474 files，0 missing                        exit 0
git diff --check：无输出                                   exit 0
```

Stage 2 先前的 `harbor` 失败已通过仓库锁文件规定的 `eval` extra 解除，属于环境补齐而非代码绕过。
收口核查中发现的公共 API docstring 遗漏也已修复。最新 SHA-256：

```text
plugins/corpus/structured/snapshot.py:
  d85103a7194c7e4014455f605ddc8de26d39c2d39bedc82175016756ee6e61a6
tests/test_corpus_structured_snapshot.py:
  f399f58e42c4f76003d74bb632fa1c16d3a2bac2b46b32a0def9a3a72cefcdd6
```

02 的已知本地规格阻塞已修复，保持 `ready-for-human / 待验收`。全仓测试在核查时另有与 02/03
调用链无关的黄金语料、reader 版本、工具注册及 Web fixture 失败，未在本票内改动或宣称全仓全绿。
本轮未读取真实 `.env`，真实模型、业务网络和生产数据库调用均为 0；04 仍等待用户验收 02/03。

### 最终收口核查（2026-10-02）

用户授权“如果达到验收标准闭环当前任务”。重新核对本票七项验收条件、03 的配置边界和
此前 P2/P3 修复后，发现并补齐两个遗漏：

- 空 `metadata.source_unit_id` 以前可通过构造，直到解析原文引用才失败；现在构造完成前和
  反序列化消费时均经过 `verify_identity()` 中同一原文 unit 身份检查。
- 显式空 `target_chunk_id` 以前被 `or` 当成缺省值并匹配本 chunk；现在仅 `None` 表示缺省，
  显式空串保留为缺失依赖，使必要条件不能被静默认定完整。

三个针对性测试修复前失败、修复后通过。公共 API 说明核查扩展到类内公开方法，补充了
SnapshotReader 方法和配置对象属性的 docstring。验收覆盖核对如下：

| 验收项 | 实现与验证依据 |
|---|---|
| 一致版本及身份 | publication 双读、内容/位置/metadata/gaps 哈希与必需版本检查 |
| 同源、角色独立 | 共享 snapshot；material_items 分支不执行 Claims；service 显式 Adapter |
| 表格和脚注保留 | cell 原文区间、显式标签来源、R2 table_note/heading 候选 |
| 必要语境降级 | 依赖闭包、循环与缺失传播、显式 chunk 不回退、限定事实用途 |
| 原文可定位 | mapping 的 unit/cell/packet 区间校验；空 unit/chunk/locator 拒绝 |
| 重复与续表 | 多 unit 片段映射、重复值及 Unicode 原文局部坐标测试 |
| 兼容性 | EvidenceRun/MaterialRun、clean/chunk 历史回归与冻结 v1 契约测试 |

本轮最终命令（均通过 `uv run --no-sync` 使用已安装环境）：

```text
pytest tests/test_corpus_structured_snapshot.py tests/test_corpus_structured_config.py
  tests/test_corpus_structured_contracts.py tests/test_corpus_evidence_pipeline.py
  tests/test_corpus_material_semantics.py tests/test_corpus_preparation_clean.py
  tests/test_corpus_preparation_chunk.py -q --tb=short
  exit 0；215 passed
ruff check plugins/corpus tests/test_corpus_structured_snapshot.py tests/test_corpus_structured_config.py
  exit 0
ruff format --check plugins/corpus/structured tests/test_corpus_structured_snapshot.py tests/test_corpus_structured_config.py
  exit 0；7 files already formatted
pyright plugins/corpus/structured plugins/corpus/evidence_pipeline.py plugins/corpus/material_semantics.py plugins/corpus/service.py
  exit 0；0 errors, 0 warnings
python tools/import_smoke.py --stage 1：exit 0；375/375
python tools/import_smoke.py --stage 2：exit 0；424/424
python tools/check_symbols.py：exit 0；474 files，0 missing
```

最终 SHA-256：

```text
snapshot.py: a578a1c3972ad9a97efe4e0727e1e54fbca9d5433d72cf0787de2a9e934ed69b
tests/test_corpus_structured_snapshot.py:
  468989aaf4f82342bc6c0f2a3021e90186da41eea4d3480b1f7886d4230f01f8
```

结论：02 本地验收通过并闭环，Execution 更新为已验收。真实 PG Adapter/来源准入、真实模型
连通性与阶段签认仍归后续任务。全仓上次结果为 3365 passed、20 skipped、3 failed、6 errors，
失败涉及 golden recall、reader 版本断言、finance 工具注册及 Web fixture 外键；本轮未重跑全仓，
也未通过干净基线对照证明这些失败的归因，不宣称全仓全绿。哈希实现重复属于非阻断维护建议，
保留现有冻结算法。真实模型和生产库访问仍为 0。
