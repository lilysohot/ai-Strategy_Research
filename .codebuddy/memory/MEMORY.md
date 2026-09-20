# MEMORY（跨会话长期事实）

进度真源 = 仓库文档：`docs/plan/claims-market-closed-loop-plan.md`（总台账）+ `docs/plan/corpus-ingestion-rebuild-tasks.md`。
本文件只放跨会话稳定事实与约定。

## 用户偏好
- 用大白话 + 结合本项目实际给真实进度与下一步，不要泛泛方法论。
- 交办的复核报告/整改清单要求**真改并留证据**；只有明说"只要文档"时才不动代码。
- 结论必须可验证：给结论时一并给出实跑命令与结果，不要"应该没问题"。

## 硬约定（流程）
- 审计证据统一放 `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/<日期>-<名称>/`（回仓库根 **5 层 `..`**）：
  `review.md`（write-once）+ `remediation-checklist.md`；RM 编号分命名空间（`RM-1～13`／`RM-I28-*`／`RM-I32-*`／
  `RM-I32R2-*`／`RM-FC-*`），文档内须声明不得混引。
- 判定纪律：`complete`／M5 放行只能由独立复核 + U **具名**签认给出，实施方不得自宣；复核须全新会话，
  代执行须在报告首段登记独立性偏差并由 U 接受；签认要具名 + 记录入链。
- **校验类脚本必须支持 `--no-write`**，否则一跑就改写被绑定字节（含时间戳产物）导致链变红。
  流程固定：「复核(write) → 刷新修订哈希 → 三门验证」；签认后不得重写签认件。
- 静态门：`uv run ruff check <CI 范围>`（全仓有既有告警，不算回归）、`uv run pyright`（仅 `server/store.py` 既有缺依赖）、
  `python tools/import_smoke.py --stage 1|2`、`python tools/check_symbols.py`。
- 测试读 CLI stdout 一律**从首个 `{` 解析**：第三方库横幅（pymupdf）会污染 → "整文件绿、单跑红"的顺序依赖假红。
- 语料族回归基线：`uv run pytest tests/test_corpus_*.py -q` → **651 passed / 12 skipped**。

## 冻结链（`.scratch/.../freezes/`）
- 链 = i0c-r1…**r35** + i1-r1…r4；门 = `validate_i0c_freeze.py`（exit 0）与 `validate_i3_2_completion.py`（`i3_2_complete=true`）。
  改任何被绑字节 → 新修订重绑 + 两门复跑。
- 工具 `freezes/freeze_utils.archive_first()`／`assert_archives_faithful()`：**改动前先归档**；正不变量 =
  `i3_2_archive`/`i3_1_archive` 每条必须等于上一修订对该原路径的绑定（空组合法，假归档必失败）。
  **权威凭据只有各修订绑定哈希**，归档目录仅供参考。
- 合并「最新修订优先」必须按**修订号数值**排序（字典序会把 `i0c-r9` 排到 `i0c-r32` 之后，误判真实归档不忠实）。
- **在效绑定取值口径**：`merged_binding_from_all_but` 把 `i1-*` 排在 `i0c-*` **之后**合并 → 只在 i0c 链上绑定的路径
  （如 `tests/test_corpus_preparation_admission.py`）会取到 i1-r4 的**陈旧值**；真实在效值用
  `merged_binding_upto_revision(N)`（i0c ≤N 合并优先，缺失才回落全量合并）。诊断：`exec(compile(prefix, V, "exec"))`
  跑验证器前缀后查 `i0c_current_binding` 里该路径落在哪个组。
- 历史块的归档检查必须**时间稳定**（只合并 ≤ 该修订号）；r33 块已改 `merged_binding_upto_revision(32)`。
- i1-r4 supersession 跳过列表硬编码 `i0c-r2..r25`（与其注释不符），重绑 i1-r4 路径时须补进新修订号（已补到 r34）。
- **可重入补丁必须锚顶层**：`text.index('if "i0c-rXX" in by_id:')` 会命中历史块内缩进同名串，把该块尾部
  （含 `merge_binding(...)`）整段删除 → 一律用 `'\nif "i0c-rXX" ...'`。
- 假绿陷阱：`"exit=0" in 日志` 会被失败文案自身命中 → 判定必须 `text.rstrip().endswith("exit=0")`；
  链门绿性由验证器 **in-process** 承担，日志只作入链留证。
- 新块**先 validate 再冻结**；更稳：先干跑生成器（`--no-write`：还原/归档忠实性/补丁锚点+幂等+语法）再动真实链。
  生成器须**可重入且产物确定**（r35 已做到：复用已有 `created_at`，复跑 sha 不变）。
- 冻结链门日志的绑定要避免循环：生成器分两轮——先写 r35（暂不绑日志）→ 跑门落 `freeze-validation.txt`
  → 重绑日志再跑一次，**两次输出必须逐字节一致**（证明绑定的日志就是当前门输出）。
- `tasks.md` 里程碑表 M6 行前缀是 `"| M6  |"`（M6 后**两个空格**）：导航表新行 `| M6 判据补齐格式门 | ...` 也以
  `| M6 ` 开头，用 `"| M6 "` 取行会命中导航行 → 一律用 `"| M6  |"`。
- 验证器块的幂等比较：插入块若以 `\n` 开头，则回读区间 `text[start:end]` 须与 `R35_BLOCK[1:]` 比（差首换行）。
- 误改被绑字节要还原：查 rXX 绑定哈希 → 按编辑逆向／`git show HEAD:<path>` 逐字节还原 → 核对 sha 相等。

## 语料链（I2 现状）
- 写链 `plugins/corpus/cli.py`(plan/build/check/publish/status/rebuild-plan) → `preparation/engine.py` → `repository_pg.py`；
  读链唯一入口 `preparation/read_pg.py`（`cv2:<build_id>`／`chunk:<chunk_id>`），`service.CorpusService` 按 `CORPUS_READ_CHAIN` 路由。
- 缺口语义 `preparation/gaps.py` + 架构 §7.3：`blocking`／`acknowledged`，范围外 `out_of_scope`；
  `quality_report.gap_regions` 恒两键（`issue:<code>:<location>`）——**不要为加字段改台账形状**（牵动 5+ frozen 测试族）。
- CLI 退出码 0/2/3/4/5（同因同码）；目标 fail-closed（`--dsn`/`CORPUS_I2_DSN` 必须显式；连上后校验
  `current_database == i2_sandbox_corpus`，实例含 apodex 库即拒写）。
- 真库纪律：只写 `i2_sandbox_corpus` 的 corpus schema；生产库 I4 前零写入；PG 门不得 skip。
- 守卫 env 形态：`env -u PYTHONPATH CORPUS_GUARD_PHASE=… CORPUS_GUARD_CONFIG=… CORPUS_I2_DSN=… uv run pytest <files> -q -p plugins.corpus.preparation.guard_pytest --noconftest -c /dev/null`
  （该模式下 `/tmp` 不可写 → 临时来源放仓库内 `.scratch/.../i2/tmp/`；TRUNCATE 写成 `TRUNCATE t1, t2, …`）。
- 守卫分开：`guards/i3.json`（零模型/无网络/`read_roots: []`，自检报告 write-once）与 `guards/i3-e2e.json`
  （allowlist 仅 `127.0.0.1:543`，`allowed_source_paths` 由 audit hook 按路径强制）；配置一变须重跑自检；
  `config_version` 是**整数** `1`。
- 生成器也要入链（否则产物不可复现）；`runpy.run_path` 返回 globals **副本** → 换输出路径必须用
  `importlib.util.spec_from_file_location(...)+exec_module` + `assert_patched()`。

## I3
- **评分器**唯一落点 `plugins/corpus/scoring.py`（纯标准库、无模型/网络/PG/时钟/IO）：`score(gold, observations, policy)`／
  `gold_from_records(records)`／`format_report(report)`；门槛用 `Fraction`（10 题 95% = 10/10）。
  输入契约（改即改冻结）：`documents` 按相关性排序且来源唯一、只表示断言命中的文档；`no_match` = `outcome=NO_MATCH` + `documents=()`；
  证据只从前 k 文档计分且带来源归属；`FetchedEvidence.verified` 默认 `None`（须显式 `True`）；`answer_existence` 缺失即报错；
  有答案题默认 `evidence_required=True`；零分母/缺输入/关键题未满分 → 机读 `blockers`。
  **输入一致性校验放 `score()` 入口**（`_validate_gold`/`_index_observations`），字段级不变量才放 `__post_init__`。
- **I3-2**（r26→r31 全链）：金标 36 槽位（冻结 23 条逐字节保留 + 采纳 13 槽/49 条）、候选 82 目标、裁决件 40+24+6+1、
  门 `ready=true`／0 阻断／20 条人工同义 warning、批准投影 79 必需 + 20 补充；正式评分输入
  `i3-2/query-gold-scoring-v1.jsonl`（`1b018ceb…`）+ `scoring-input-manifest.json`（唯一读入口 `load_scoring_input`）。
  批准只能走 `evidence-targets-decisions.json` → `i3s2_apply_decisions.py` → `approved.json`；候选里的
  `adjudication.status` 门完全不读。完成门 exit 0（10/10）；签认件 `audits/20260919-i32-diagnosis/signoff-record-i3-2.*`（xyl）。
  角色口径：`required`／`supplementary`（非必需、不声明替代）／`suggested`；EvidencePass 分母 = **逐题**。
  映射规则（`evidence-mapping-6`）踩坑：数值 token 用 `(?<![\dA-Za-z.])TOKEN(?![\dA-Za-z.%])`；日期先掩码；
  同一数值每次出现都是独立要件；小数/百分数用 `Decimal.normalize()` 等价；先按 `；;。` 切子句，**仅当子句既有数值
  又有标记**才按逗号拆段；表格 item 必须带 `row/col/unit/period`，token 须来自权威侧 `read_pg.fetch_cell`。
- **I3-1**：①2026-09-19 照 U 批准集 6 份 PDF → 可发布 2/6、阻断缺口 13 处、格式覆盖仅 PDF（**i0c-r32** 入链）；
  ②2026-09-20 dev lane 8 份 → 可发布 4/8、**§12.1 格式门 = true**（pdf 2/6、docx 1/1、md 1/1）、新增检索命中
  工业富联/光模块、审计冲突 0，但 `per_class_min_2` 仍 **false**（**i0c-r34** 入链）；证据 `audits/20260920-i31-dev-lane/`；
  ③2026-09-20 **具名签署采纳 + 真实发布（i0c-r37）**：xyl 签署 4 份 → 原批准 8 份真实发布 **7/8**，company **2/3**／industry 3/3／macro 2/2
  ⇒ **`per_class_min_2=true`**；格式门 true（pdf 5/6、docx 1/1、md 1/1）；12 处人工确认缺口 → `acknowledged`（默认 disposition 仍 `blocking`，
  原 quality_report/units/chunks/claimed 范围未改）；**国信光力 `dddc7cd0` 未放行未发布**（p7 gap key 仅页级坐标、无页内区域框能力，
  须把「可复验区域框证明」接入发布门 + 反例 + 新修订；不得删必需证据 p7、不得记为已发布，但**不再阻断每类≥2计数**）；
  证据 `audits/20260920-i31-signed-release/`。**边界：仅过「数量+格式+真实 E2E」三门，不代表全部来源无阻断，不代表 M6/I4 放行**。
  裁定②（MD/DOCX 覆盖声称）已由 dev lane 关闭；裁定①的方向已由「人工具名认可 + 拒发布被阻断来源」实现（非 P0 追加路线）。
  范围唯一权威源 = `i0a2-adjudicated-20260915.json` 的 `dev_selection_approved`，**不是** `dev-manifest.dev_selection_candidates`；
  `excluded_from_active` 是人工终态（`admission.py:454` 直接判 `excluded_by_policy`），想让其入范围必须用新 ADMITTED 决定 supersedes。
- **dev lane 机制（U 2026-09-20 裁决）**：`contract.IN_SCOPE_MATERIALS_BY_POLICY_REV`（v1 仅 `research_report` 逐字不变；
  `v2-dev-20260920` 加两个内部材料类型；未知 rev 落最严默认）；dev lane = **独立政策文件**（`scope=dev` +
  `production_in_scope_unchanged=true` + 逐源 `dev_lane.sources`）；装载需 `allow_dev_lane`（CLI：`CORPUS_DEV_LANE=1`）
  否则 `AdmissionError` fail-closed，`service.py` 生产路径默认 `False`；`material_type` **如实**（`internal_committee_report`／
  `internal_unattributed`，不得伪写 research_report）；`evidence_refs` 加 `dev_lane=<lane_id>`；取代链列整条
  （生产 `excluded_from_active` → dev `admitted`）。**v1 生产判定逐字不变**（in_scope 材料恒 research_report、
  `rule_rev` 对 v1 == `RULE_REV`、evidence 无 dev 标记）。dev lane 样本**计入** §12.1 格式门但须在矩阵/证据标注 `dev_lane`。
- CLI/引擎接口约束：`review_decision_ids` 必须列**整条取代链**（否则 `conflicting_review`）；`corpus plan` 的缺口在
  `entry.precheck.{gap_summary,gaps}`，整批失败 exit 2；`domain_hint` 必须是合法 `ResearchDomain`（未知则省略）。
  阻断码 `image_region_unreadable`／`image_only_page`／`table_lines_without_extraction` **无人工认可入口**（首版不允许自动 OCR）。
- **I3 余项**：I3-3／I3-4／I3-5／I3-6／I3-7 未做（I3-5 只完成零模型审批契约门 + 89 用例清单 + 19 题锚点映射，
  真实非回归重验 **not_run**）；I3-0 复核整改 F1—F5（r21）+ r33 具名签认；M5 F3（`validate_i1_freeze.py` 对工作区
  13 项失配 = i1-r3 绑定未随 I2 合法改动更新）单列跟踪，建议随 i1-r5 重绑。
- **M6 判据口径已对齐（i0c-r35，2026-09-20，U 指令）**：`tasks.md` M6 判据行写入「声称支持的格式（PDF/DOCX/MD）
  按架构 §12.1 各有真实已用开发样本、无未处置缺格（dev lane 样本计入但须标注 `dev_lane`）」，与 §12.1、
  I3-7 行三处同源；**只改判据文字，门行为/代码零改动**，故不新增阻塞。纯文档修订：r35 只绑 tasks.md + 台账
  + 审计证据（校验脚本/一致性日志/链门日志/生成器/归档），验证器 r35 块含「越界绑定检查」禁止牵动代码。

## 语料链"反复打转"的根因（2026-09-20 复盘，U 提问）
结论：**分层没有失效，失效的是「分层 → 层内可证伪判据」未落地**。分层的价值是让失败**可归因**（i38 消融已证：
13→14(S3)→16(S2)→20(S3b)、剩 4 条逐条点名），不是让改动**免联动**（块划分变→检索变，是语义耦合，设计消不掉）。
三条真因：①**同一个上游洞在三层轮流露脸**——表格/版面结构信息缺失（i33 记 6 条 `cells=[]`/`element=null`）在
read/chunk/search 分别表现为"页文本缺"/"跨块装不下"/"排名 11–62"，i37 议题 B §6 自述与表格结构重建是同一批工作；
②**验收信号只挂链尾**端到端 EvidencePass，层内无独立判据 ⇒ 每层修复须整链重跑才能判值，观感即"打转"；
③**分母混永不可达项 + 基线本身红**：18 条 `absent_in_extraction`（金标改写/重建）永不可命中却计入分母，叠加
i36 报的 8 条未冻结漂移 ⇒ 增益读不准。
解药（优先级）：1) 把 i37 §5 的 `I-A*`/`I-B*` 不变量草案**落成常驻测试并绑修订**，端到端回测降级为**只读诊断**；
2) 回测分母分层：pipeline-reachable 与 gold-rewrite-unreachable **单列**（不动门槛）；3) 结构信息**一次性补在 reader**
（cell 网格/表头层级），禁止在 chunk/search 打补丁；4) 先修 i36 的 8 条 red 再跑分。i38 剩 4 条须下一轮定去留：
`company-007/e1`、`company-008/a-1`（clean 剔除）与 `industry-002/e2`、`industry-003/e2`（locator 不可派生候选）。
冻结成本是"回合制"放大器：i33 §3 因成本明确"不接线脆弱解析器 / 本次收口不改金标"，把问题推到下一轮。

### 层内解耦归因（2026-09-20，代码级）
**结构性硬伤：证据选择策略不在产品代码里**——`group_hits` / `per_document=8` / `observations_for`（按页聚合）
只存在于 `audits/*/calibrate.py`、`reshape.py`；`plugins/corpus/` grep 不到 `group_hits` / `max_chunks_per_top_document`。
产品 `service.py` 只有 `search_with_coverage`+`fetch_verbatim` 原语，无选择策略 ⇒ "证据选择层"=每审计目录一份的一次性
脚本副本，改它不沉淀产品行为。**解药**：抽 `preparation/selection.py`，小接口 `select(hits, policy)`，policy 注入
（现有评测 + 生产两个消费者 = 真 seam）。其余解耦点：①`chunk.py` 的 `ChunkCandidate` 用一个 interface 同时承担
`search_text`（要小纯）与 `unit_ordinals`（要覆盖引文），方向冲突 → 加连续块区间投影 `cover(quote)→(i,j)`；
②`chunk.py:169-180`/`:416` 表格只有表序+首行，`contract.py:296-303 cells` 只有 `(row,col)` 无标签 → 表格结构模型
必须做在 **reader** 层；③`search_pg.py:41-65` 单 SQL 焊死 GIN 召回+`ts_rank`+LIMIT → 拆 recall/rank seam（改信号不改阈值）；
④`search_pg.py:68-83 SearchHit` 缺 page/cells/标签 → 补字段，否则"块→页"映射只能下移到评测脚本；
⑤`clean.py:384-421` 噪声判定与投影同循环、`reasons` 无依据值。**勿动**：`pdf_reader.py:333-345 _row_text`
"只用换行 + native_pos 排序"是刻意保真（插 `" | "`/重排是历史 bug）；`clean.py:26-28` 分级归 `gaps.py`；
`verify_chunk_result`/`verify_clean_region`/`contract.__post_init__` 是现成 layer 门，接进常驻测试即可。
落地顺序：`selection.py` → `SearchHit` 补字段 → `chunk.cover()` → reader `TableModel`（要全量重摄入，压最后）→ clean 依据值。

### 解耦方案落点（2026-09-20，文档态，未动代码）
`.scratch/corpus-retrieval-decoupling/`：`spec.md` + `issues/00-freeze-realign.md`（P-1 修 i36 的 8 条 red，须先决策是否
整体采纳 reader-pdf-5 + whitespace-norm）、`01-selection-module.md`（新增 `preparation/selection.py`，默认 policy 须与
`calibrate.py:37-74` 逐字节等价、cap 锁死 8）、`02-search-hit-interface.md`、`03-chunk-cover.md`、`04-table-model.md`、
`05-clean-evidence.md`。依赖 `00→01→02→03→(04∥05)`，原则 = 先做不动被绑字节的、把全量重摄入的压到最后合并一次
（`i0c-r41`）。**新回测不可原地复跑 `calibrate.py`**（`calibration-summary.json` write-once 会 raise），必须新目录。
`spec.md` 是**自包含汇总**（12 节 + 附录 A 证据索引 / 附录 B 代码位置速查），`issues/` 仅作工单视图。
