# MEMORY（跨会话长期事实）

来源：`.codebuddy/memory/YYYY-MM-DD.md` 的沉淀。只放稳定事实与约定；进度真源永远是仓库文档
（`docs/plan/claims-market-closed-loop-plan.md` 总台账 + `docs/plan/corpus-ingestion-rebuild-tasks.md`）。

## 用户偏好

- 用**大白话 + 结合本项目实际**回答；给真实进度与下一步，不要泛泛方法论。
- 用户交办的材料（复核报告 / 整改清单）通常要求**按清单把问题真正改掉并留证据**，而不是只出文档；
  只有用户明说"只要文档"时才不动代码。

## 项目硬约定（违反会被复核打回）

- **审计与复核证据**统一放 `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/<日期>-<名称>/`；
  复核报告 `review.md`（write-once，不改）+ 整改清单 `remediation-checklist.md`（编号 `RM-*`）。
  **RM 编号分命名空间**：`RM-1～13`（I2-5 轮）/ `RM-I28-*`（I2-8·I2-4 轮）/ `RM-FC-*`（全链路轮），
  文档内必须声明不得混引。从我该目录回仓库根需 **5 层 `..`**。
- **冻结链**：`.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/`（i0c-r1…r20 + i1-r1…r4）。
  改动任何被绑定的实现/测试/文档字节后，必须①新建修订（生成器脚本 + manifest 追加 +
  **扩展 `validate_i0c_freeze.py` 并先跑一遍 validate 再冻结**）②`validate_i0c_freeze.py` exit 0。
  **write-once：冻结后不得再改被绑文件**，否则只能再建一版（先跑完 ruff/pyright/测试再冻结）。
  验证器新块写完后**必须先本地跑 validate 再生成快照**——否则会白多出一版修订（先例：i0c-r19→r20，
  路径拼装写成 `guards/guards/i3.json`）。`validate_i1_freeze.py` 自 I0-C/I2 起对工作区已失配（既有 P3，建议随 I3 前置理顺）。
- **真库纪律**：只写 `i2_sandbox_corpus` 的 corpus schema；生产库（含 `apodex` 库的实例）I4 前零写入；
  PG 门不得 skip。守卫 env 跑测试统一 `env -u PYTHONPATH`（宿主 IDE 的 sitecustomize 会派生 node 子进程被守卫拒）。
- **守卫 env 限制**：`/tmp` 不可读写（Python `tmp_path` 会失败）——测试的临时来源/归档放仓库内
  （`.scratch/corpus-evidence-pipeline/ingestion-rebuild/i2/tmp/`）；`read_roots: []` 的守卫阶段拒绝一切来源读取。
- 守卫 env 运行形态：
  `env -u PYTHONPATH CORPUS_GUARD_PHASE=i2-verify CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json CORPUS_I2_DSN="postgresql://postgres:postgres@127.0.0.1:543/i2_sandbox_corpus" uv run pytest <files> -q -p plugins.corpus.preparation.guard_pytest --noconftest -c /dev/null`
  （`--noconftest -c /dev/null` 下 TRUNCATE 必须写成 `TRUNCATE t1, t2, ...`，不能多个 TRUNCATE 前缀）。
- **判定纪律**：`complete`/`M5 放行` 只能由独立复核 + U 签认给出；实现方不得自我宣告。
  复核报告里的"裁定项"若阻塞实施，可由实施方**作出裁定并写入规格文档**（架构 §7.2/§7.3/§9 + tasks.md），
  但必须在整改记录中显式登记裁定和理由（既有先例：RM-I28-0、RM-FC-0）。
  复核必须由**全新会话**执行（M5 包 §9）；若 U 指令由制备方代执行，须在报告首段显著登记独立性偏差
  并由 U 在签认时明确接受（先例：2026-09-18 M5）。
- **M5 复核包**（`audits/20260918-m5-review/`）：`run_matrix.sh` 三段式（前置门→行为/静态→运行后零漂移门），
  evidence write-once；实现字节一变，包必须重发 + **新建冻结修订重绑包字节**，否则前置门按设计拦住。
  判据里「模块计数」类量应写**闭合性正则**（`(\d+)/\1 modules imported`），不要写死数字。
- 测试读 CLI 的 stdout 一律**从首个 `{` 解析**，不要 `json.loads(stdout)`：第三方库（pymupdf 等）
  会打一次性提示行，造成「整文件跑绿、单独跑红」的顺序依赖假红。
- 静态门：`uv run ruff check <CI 范围>`（全仓 `ruff check .` 与 `ruff format --check` 有大量既有告警，不算回归）、
  `uv run pyright`（`server/store.py` 的 sqlalchemy 缺依赖为既有）、
  `python tools/import_smoke.py --stage 1|2`、`python tools/check_symbols.py`。

## 语料链关键事实（I2 现状）

- 写链：`plugins/corpus/cli.py`（plan/build/check/publish/status/rebuild-plan）→
  `preparation/engine.py`（plan→execute→publish，缺口裁决）→ `repository_pg.py`；
  读链唯一入口 `preparation/read_pg.py`（句柄 `cv2:<build_id>` + `chunk:<chunk_id>`），
  `service.CorpusService` 按 `CORPUS_READ_CHAIN` 路由（新库上 legacy 不可达）。
- 缺口（读取缺口）语义见 `preparation/gaps.py` + 架构 §7.3 裁定：默认分级 `blocking`/`acknowledged`，
  scope 可证范围外 → `out_of_scope`；缺口恒可见（`quality_report.gap_regions` = `issue:<code>:<location>`，
  形状固定两键，**不要为加字段而改台账形状**——那会牵动 5+ 个 frozen 测试族）。
  活动 build 有缺口 ⇒ `coverage.processing=scoped` + `reason_codes=gap_regions_present`。
- CLI 退出码：0 成功 / 2 输入非法 / 3 目标或守卫拒绝 / 4 门未过 / 5 目标不存在（同因同码）。

## I3 阶段约定（2026-09-18 起）

- **评分器**唯一落点 `plugins/corpus/scoring.py`（架构 §12.3 三类指标；纯标准库、无模型/网络/PG/时钟/I-O）：
  接口 `score(gold, observations, policy)` / `gold_from_records(records)` / `format_report(report)`。
  门槛用 `Fraction` 精确比较（19/20 ⇒ 10 题 95% 即 10/10，float 会被咬掉边界）。
- **评分器输入契约**（调用方必须遵守，改接口即改冻结）：
  `documents` 按相关性排序、**同一来源只出现一次**（重复即入口拒绝；chunk 须先聚合为文档 Top-k），
  只表示"运行断言命中的文档"，`no_match` 的正确表达是 `outcome=NO_MATCH` + `documents=()`；
  证据只从前 k 名文档计分且**带来源归属**（默认允许集=相关文档集，或 `EvidenceTarget.source_id` 显式绑定），
  越界记账 `evidence_outside_top_k`、来源不符记账 `evidence_source_mismatch`；
  `FetchedEvidence.verified` 默认 `None`=未提交核验（漏接 verify 不自动成功），必须显式 `True`；
  `RetrievedDocument.build_id` 是身份留痕位（本版不参与计分，I3-1 接线扩展跨 build 判定）。
  `answer_existence` 缺失即报错（不得默认负例 = 静默退出分母）；有答案题默认 `evidence_required=True`，
  不做证据评分的题必须显式 `evidence_required=False`，否则 `evidence_targets_absent` 阻断。
  零分母/未定义指标/缺必需输入/关键题未满分一律落机读 `blockers`，`passed` 只在这些都干净时为真。
- **校验分层纪律（复核教训）**：字段级不变量放 frozen dataclass 的 `__post_init__`；
  **输入一致性**校验（重复来源、NO_MATCH 带 payload、多文档未声明 any/all、sources/target 重复）
  必须放 `score()` 入口（`_validate_gold` / `_index_observations`），否则 `dataclasses.replace`
  在 try 外拼出的矛盾输入会让红例关不掉（复核探针正是这么写的）。
- **I3 守卫阶段**：`guards/i3.json`（deny_all 网络 + 零模型 + `read_roots: []` + protected `data`），
  自检报告 `i3-guard-report.json`（write-once，脚本 `i3_guard_selfcheck.py`）。I3-1 起需要开发来源 + 隔离 PG 时
  **另建 `i3-e2e.json`**，不改 i3.json（守卫配置一变就要重跑自检并绑定新哈希）。
- **I3-2 补料（阻塞 M6 判据，当前 i0c-r24）**：冻结 `query-gold-frozen.jsonl` 30 题只有散文
  `evidence_requirement`，缺机器可读 `evidence_targets`，I3-2 必须补。
  当前候选规则 **`evidence-mapping-5`**：30 题 ⇒ machine_ready 2／pending_human 20／blocked 2
  （`macro-003`「强就业降低加息顾虑」、`macro-004`「本文聚焦前四者」无承载 item）／负例 6；
  目标 54 = 必需 35／补充 4／待批准锚点 15（partial 9）。产物：`i3-2/evidence-targets-candidates.json`、
  `evidence-targets-review.md`（核对单）、`evidence-targets-adjudication.md`（**人工裁决单**：
  要件 40 + 整题 24 + 负例 6 + 状态澄清 1）、`evidence-targets-verification.json`（三段自检）、
  `approval-report.json`（门）；工具：`i3s2_textutil.py`（共享切分/词元规则）、
  `i3s2_evidence_targets.py`、`i3s2_verify_candidates.py`、`i3s2_apply_decisions.py`、
  冻结脚本 `i3s2_remediation_freeze.py`(r23)／`i3s2_remediation_r24_freeze.py`(r24)。
  **审批硬规矩（二轮复核 A1/A2 的核心）**：批准只能走
  `evidence-targets-decisions.json` → `i3s2_apply_decisions.py` → `approved.json` + `approval-report.json`；
  **候选里的 `adjudication.status` 是信息字段，门完全不读它**（v4 曾"改状态即开门"）。
  门的必查项：要件逐 `item_id` 裁决（chosen 须在该题候选来源范围内、item 存在）／有答案题**整题验收**
  （`reviewed_against_requirement=true`，`machine_ready` 题也要）／负例 `full_text_coverage_confirmed`／
  来源状态澄清（`实质未决` 阻断）／锚点覆盖度／审批件三重输入哈希未过期／审阅人非空。
  `驳回` 不删除原题要求；`补标注` 必须是**冻结标注中尚不存在**的 item 且声明新
  `source_gold_revision`，否则保持未决。
  **EvidencePass 分母 = 逐题**（架构 §12.3）；"逐 item vs 槽位聚合"二选一**已作废**，item/槽位计数只作诊断。
  **覆盖账与角色**：`required`／`supplementary`（补充，非必需，**不声明替代关系**）／`suggested`
  （待批准锚点，批准前不计入必需）；机器锚点给 `adequacy` + `uncovered_terms`，面级
  `union_uncovered_terms` 取**各锚点未覆盖集合的交集**（取并集会误判；降噪：df ≤ max(2,20%×item 数)，
  二元组按字序包含即视为覆盖）；`partial` 锚点须改选/补标/`residual_accepted` 才可批准；
  备选标 `search_hint` 不进可批准集合。`machine_ready` 只表示"数值要件都有承载 item"。
  表格 item 必须把 `row/col` 写进 `locator`、`row/col/cell/unit/period` 写进 `constraints`，
  **I3-1 的 token 必须来自权威侧**（`read_pg.fetch_cell`），不得从金标回填。
  **映射规则要点（踩过的坑）**：数值 token 用**字母边界** `(?<![\dA-Za-z.])TOKEN(?![\dA-Za-z.%])`
  （修 v1 `20` 命中 `2026`、v3 `8230` 命中 `8230CF`）；日期先掩码；**同一数值的每次出现都是独立要件**
  （`0.0%` ×2 ⇒ 两个不同单元格）；小数/百分数用 `Decimal.normalize()` 做数值等价（`13.40`↔`13.4`，
  quote 不改写）；`item_text` 必须**逐字段归一化后分隔连接**（直接拼接会造假边界，令精确匹配失效）；
  4 位数字紧跟元/点/倍等单位要升为强 token；不要用"连续汉字串"当关键词。
  **分段纪律**：先按 `；;。` 切子句，**仅当子句既有数值又有标记时**才按逗号拆段——无差别逗号切分会把
  "约四个月""均下降""括号须解为负数"切成无锚点假缺口（`blocked` 2→6）。含数值子句里的限定必须并行登记
  （否则 `macro-003`「区分附条件判断/市场预期/正式决定」这类要求漏账）。
  自检三段：`self_consistency` / `regression_probes`（16/16，含审批门反例）/ `completeness_gate`
  （候选阶段 `no_decisions`/`ready=false` 是**正确状态**）；冻结脚本强制 `ready is False` +
  审批件与批准投影不存在 + 输入哈希与 gold 一致才出包。
  冻结件被同名覆盖前**先归档旧字节**（r24 已把 r23 的候选/核对单/裁决单/验证报告归档为
  -v4/-v4/-v1/-v2 并绑定）；误删恢复：`.scratch` 已被 git 跟踪，
  `git show HEAD:<path> > <归档名>`，还原后核对哈希等于旧修订绑定值。
  **`runpy.run_path` 返回 globals 副本**：给"换输出路径/换输入件"打补丁必须用
  `importlib.util.spec_from_file_location(...)+exec_module` 拿真模块对象，并加
  `assert_patched()` 断言（否则补丁静默失效、脚本会在正式路径上跑——本会话真实踩过，
  靠生成器自动归档 + r25 绑定哈希恢复）。
  **采纳干跑（2026-09-18，i0c-r25 之后）**：`audits/20260918-i32-adoption-dryrun/`（U 全量采纳
  AI 补证包后的干跑，未落正式路径）。结论：新 source-gold 版本候选 = 冻结节逐字节保留 + 采纳
  13 槽/49 条（只收支持证据）+ 负例近似命中 7 条隔离成库；重映射 54→82、blocked 2→1（剩 macro-004）；
  裁决件 40+24+6+1 全可机械生成；门机器口径 17 项未决 → 逐项同义确认口径 1 项未决
  （纯日期 span 无内容词元会被拒）→ 两项假设叠加才 ready=true 但 approved_required=96（需 U 定
  "必需/补充"口径）。
  **署名口径（U 于 2026-09-18 晚确认）**：具名审核人 = **xyl**（本人已全文审核并确认署名），
  `reviewer` 写 `xyl`，同时必须保留 `ai_assisted: true` + `ai_reviewer_label`（AI 辅助核验、
  不是人类签名）——"AI 辅助"要注明，但署名是实际审核人；历史"待真人复核"字样按残留描述处理，
  不改写/不删除历史字段。
  **落地（i0c-r26，2026-09-18）**：I3-2 采纳稿已落正式路径——新金标 36 槽位（23 条冻结字节逐字保留 +
  采纳 13 槽/49 条）、候选 v7（82 目标）、裁决件 40+24+6+1、**门 ready=true／0 阻断／20 条人工同义 warning**、
  批准投影 79 必需 + 20 补充、验证 30/30 + 16/16；`validate_i0c_freeze.py` exit 0。
  两条新约定：①**最小覆盖收窄**——批准 `chosen` 只留满足"未覆盖词元集合不变 + 每来源至少一条"的最小集，
  移出者记 `supporting_anchors` 且不计入 EvidencePass；②**source-gold 首次被冻结修订直接绑定**
  （新增 `i3_2_source_gold` 组），不再只靠候选内 `inputs.sha256` 传递。
  落地脚本 `audits/20260918-i32-adoption-dryrun/promote_i3s2.py` + `freeze_r26.py`（含验证器 r26 规则 +
  台账回填），落地记录 `landing-record.md`。仍未做：20 条同义映射审计、`macro-004` 机器 blocked 未消、
  I3-2 其余冻结项、I3-1（E2E）、I3-5。
  写中文引号别用 ASCII `"`（在双引号字符串里直接语法错误，本轮踩 4 次，统一 `「」`）。
