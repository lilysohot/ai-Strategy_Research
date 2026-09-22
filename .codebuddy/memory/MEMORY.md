# MEMORY（跨会话长期事实）

进度真源 = `docs/plan/claims-market-closed-loop-plan.md` + `docs/plan/corpus-ingestion-rebuild-tasks.md`（M6 判据在 `tasks.md:260`）+ `.scratch/corpus-retrieval-decoupling/spec.md`。本文件只放稳定事实与约定；细节见 `.codebuddy/memory/2026-09-*.md` 与各 audit 目录。最近整理：2026-09-22。

## 0. 判定纪律（U 偏好）
- 大白话 + 真实进度与下一步；**结论必须附实跑命令与结果**。
- 交办复核/整改要**真改并留证据**；只有明说「只要文档」才不动代码。未裁决不动产品字节。
- **交付物口径**：纯文本报告/清单/方案**不算交付物**；只有入冻结链的改动（代码/金标/层内门禁/常驻测试/冻结修订）才算。
- `complete`/里程碑放行只能由**独立复核 + U 具名签认**给出，实施方不得自宣。
- **校验类脚本必须支持 `--no-write`** 且**幂等可重跑**；阈值/粒度类变更须**具名签认**。
- 报分须区分「回测/诊断口径」与「生产默认口径」；引用负例数字必须带路径口径。
- 同一信息被反复复述 ⇒ 缺的是共同口径而非产出量：停止复述，请 U 裁决。

## 1. 环境硬约定
- 审计证据放 `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/<日期>-<名称>/`（回仓库根 **5 层 `..`**）：`review.md`（write-once）+ `remediation-checklist.md`；RM 编号分命名空间。流程 = 复核(write) → 刷新修订哈希 → 三门验证；签认后不得重写签认件。
- **write-once 产物别放墙钟时间戳**（重跑字节必不同 ⇒ 假冲突）：比较用**语义逐字段**（剔 `generated_at`），语义全同则保留原产物字节，不同才报冲突 + 列差异字段。模板 = `c3_attribution.py`（已修）；**`f3_replay.py`/`f3b_replay.py` 仍是整文件字节比较、无 `--no-write` ⇒ 重跑必假红，待修**（2026-09-22 实跑撞到）。
- 读 CLI stdout 一律**从首个 `{` 解析**（pymupdf 横幅 ⇒ 假红）。
- `.scratch` 被 gitignore ⇒ `search_content` 搜不到，须 shell grep / read_file。
- `tests/test_corpus_cli_isolation.py::test_subprocess_model_client_import_refused` 普通 pytest 下必 fail，须 `env -i … CORPUS_GUARD_PHASE=i2-verify` 守卫 env。
- 查库走 `uv run python` + `psycopg`（**本机无 psql**）；DSN = `postgresql://postgres:postgres@127.0.0.1:543/i2_sandbox_corpus`（表在 `corpus` schema）或 `audits/20260920-i31-region-review/release.py::connect()`。**psycopg 里 SQL 别写裸 `%`**（`LIKE '%x%'` ⇒ `got '%u'`），用参数传。
- 守卫 env：`env -u PYTHONPATH CORPUS_GUARD_PHASE=… CORPUS_GUARD_CONFIG=… CORPUS_I2_DSN=… uv run pytest <files> -q -p plugins.corpus.preparation.guard_pytest --noconftest -c /dev/null`（该模式 `/tmp` 不可写 ⇒ 临时来源放 `.scratch/.../i2/tmp/`）。guards：`i3.json`(0 条)、`i3-e2e.json`(allowlist `127.0.0.1:543`，8 条)、`i1.json`(6 条)；`config_version`=1。

## 2. 冻结链（`.scratch/.../freezes/`）
**白话**：freezes = 项目拍照存档（代码/语料/尺子/分数，编号成父快照链；`validate_*_freeze.py` 校验；**红 = 照片与实物不符**）。git 答「代码长什么样」，freezes 答「结论是哪一版跑出来的」。
- 链：i0c-r1…r43、**r4n→r4p→r4q→r4r→r4s→r4t→r4u（最新）**；i1-r1…**r6**。门 = `validate_i0c_freeze.py` / `validate_i1_freeze.py` / `validate_i3_2_completion.py`（2026-09-22 均 exit 0）。
- 修订语义：r41 scoped / r42 S1 清账 / r43 R3 闭环(生产接 perdoc) / r4n F2 band 接生产+cell / r4p F3 clean 句粒度 / r4q F4 跨边界取证 / r4r r39 漂移豁免 / r4s M5 两处 MISS 重绑 / r4t B2 abstain 拒检(默认 off) / **r4u F3-B 续接片段聚合**（路径 B，免重摄入）。
- **跨链联动坑**：路径只在 i1 链绑定时，i0c 侧重绑后须同步补 i1 修订。**改动前先归档** `archive_first()`／`assert_archives_faithful()`；权威凭据只有各修订绑定哈希。
- 合并按**修订号数值**；**在效绑定**用 `merged_binding_upto_revision(N)`（`from_all_but` 会取 i1 陈旧值）；历史块归档检查须时间稳定（只合并 ≤ 该修订号）。
- 其它坑：**可重入补丁锚顶层** `text.index('\nif "i0c-rXX" in by_id:')`；假绿判定须 `text.rstrip().endswith("exit=0")`（`"exit=0" in 日志` 不行；`cmd | tail; echo $?` 是 tail 的码）；i1 校验器 in-process 须 `exec(compile(...), {"__name__":"__main__","__file__": path})`；门日志绑定分两轮（两次输出逐字节一致）；`tasks.md` M6 行前缀 `"| M6  |"`（两空格）；误改被绑字节按 rXX 哈希 / `git show HEAD:<path>` 还原核 sha；"是否待批"只读 `freezes/` 最新修订。

## 3. 语料链（I2）
- 写链 `plugins/corpus/cli.py`（`plan`/`build`/`check`/`publish`/`status`/`gap-review`/`rebuild-plan`）→ `preparation/engine.py` → `repository_pg.py`；读链唯一入口 `preparation/read_pg.py`（`cv2:<build_id>`／`chunk:<chunk_id>`），`service.CorpusService` 按 `CORPUS_READ_CHAIN` 路由。
- **生产默认检索形态 = band**（r4n）：`service.search`/`search_with_coverage` → `read_pg.search_with_coverage_bands` → `_apply_selection`（`select_structural` 定来源序）→ `_selected_chunk_hits`（`select_band` 定文档内带）；cell 由 `_emit_cells`；`search_bands` 接 `cross_boundary.aggregate_band_chunks`（r4q 表头/脚注聚合 + r4u `stitch_continuation` 续接片段）。`selection.py`：`select(top_k=5)`／`select_structural(perdoc)`／`select_band`（G=1/K=1/带数=8/`POOL_CAP=24`，可证带宽上界 49，实测 max 33）。
- 库形态 `corpus.corpus_{builds,sources,publications,units,chunks,admissions,review_decisions,jobs,source_checkpoints}`；块只收 kept 单元（`unit_refs` 形如 `unit:0717`）。**`corpus_builds` 无 `active` 列**（active 在 `corpus_publications.active_build_id`）。
- 缺口语义 `preparation/gaps.py` + §7.3：`blocking`/`acknowledged`、范围外 `out_of_scope`；`quality_report.gap_regions` 恒两键。
- CLI 退出码 0/2/3/4/5（同因同码）；fail-closed（`--dsn`/`CORPUS_I2_DSN` 显式必需，校验 `current_database == i2_sandbox_corpus`）。真库纪律：只写 `i2_sandbox_corpus` 的 corpus schema；生产库 I4 前零写入；PG 门不得 skip；**重摄入属生产数据写，须 U 授权**。
- 约束：`review_decision_ids` 须列整条取代链；`corpus plan` 缺口在 `entry.precheck.{gap_summary,gaps}`（整批失败 exit 2）；`domain_hint` 须合法 `ResearchDomain`；`image_region_unreadable`/`image_only_page`/`table_lines_without_extraction` 无人工入口；`put_admission` 唯一性 = `decision_id` 全局唯一（RM-7，同内容幂等重放才允许）。

## 4. dev lane（U 2026-09-20 裁决）
`contract.IN_SCOPE_MATERIALS_BY_POLICY_REV`（v1 仅 `research_report`；`v2-dev-20260920` 加两个内部类型；未知 rev 落最严）；dev lane = 独立政策文件（`scope=dev` + `production_in_scope_unchanged=true` + 逐源 `dev_lane.sources`），装载需 `allow_dev_lane`（`CORPUS_DEV_LANE=1`）否则 fail-closed；`evidence_refs` 加 `dev_lane=<lane_id>`。样本计入 §12.1 格式门但须标注。范围权威源 = `i0a2-adjudicated-20260915.json::dev_selection_approved`；`excluded_from_active` 是人工终态（`admission.py:454`）。测试 `tests/test_corpus_dev_lane.py`（9 条，仅 `i3-e2e` 守卫）。

## 5. 评分器与子项
- **唯一落点** `plugins/corpus/scoring.py`（纯标准库、无模型/网络/PG/时钟/IO）：`score`/`gold_from_records`/`format_report`，门槛用 `Fraction`。当前字节 `f61573d7`（空白规约，r41 绑定；旧严格 `bf9c8b80`）。**No tuning after scores**（r39）。
- 输入契约（改即改冻结）：`documents` 按相关性排序且来源唯一；`no_match` = `outcome=NO_MATCH` + `documents=()`；只从前 k 文档计分；`verified` 默认 `None`；`answer_existence` 缺失即报错；零分母/缺输入/关键题未满分 → `blockers`。
- **`EvidenceTarget.matches`（易错）**：`verified is True` + **整条 `quote` 逐字包含（去空白后 code point）** + `locator` token 全在证据 locator 里；`basis.matched_tokens` 不参与。
- **负例**：`NO_ANSWER` 走 `_score_negative`，三指标记 `None`；`documents` 非空即 `false_positive`，引文条数累加 `fabricated_citations`；默认 `max_false_positives=0`/`max_fabricated_citations=0` ⇒ 超限落 `blockers`；6 题 critical（company/industry/macro-009/010）。**24/24 也绕不过 1 条负例误报。**
- **I3-2**：36 槽位 / 候选 82 / 批准投影 79+20；评分输入 `i3-2/query-gold-scoring-v1.jsonl` + `scoring-input-manifest.json`（唯一读入口 `load_scoring_input`）；批准只走 `evidence-targets-decisions.json` → `i3s2_apply_decisions.py` → `approved.json`；完成门 10/10 exit 0；签认件 `audits/20260919-i32-diagnosis/signoff-record-i3-2.*`（xyl）。映射坑：数值 token `(?<![\dA-Za-z.])TOKEN(?![\dA-Za-z.%])`、日期先掩码、`Decimal.normalize()`、先按 `；;。` 切句且仅当子句含数值+标记才按逗号拆段、表格 token 须来自 `read_pg.fetch_cell`。
- **I3-1**：格式门达标（pdf 5/6、docx 1/1、md 1/1）、`per_class_min_2=true`（i0c-r37）；国信光力 `dddc7cd0` 未放行未发布。
- **M6 判据**：I3-7 对 I3-6 冻结版重验通过；逐类三指标达冻结目标 + 关键引用题 100% + 旧检索/财务基线不退化 + **伪引用负例 0**；宏观 0/3 单列。**余项**：I3-3/4/5/6/7 均未完。

## 6. 检索/取证修复簇（F1–F4 + r4u）
- **打转的根因**：分层能可归因，失效的是「分层 → 层内可证伪判据」没落地。六解耦点：①选择策略落产品 ②`SearchHit` 补 `page`/`cells`/`label_path` ③拆 recall/rank（`rank_hits`；`chunk.cover` 作废→band）④连续块区间→band ⑤表格结构在 reader 层（`TableModel.label_path`）⑥clean 判定机读（`NoiseVerdict`，只记账不提升分数）。**勿动**：`pdf_reader.py:333-345 _row_text`；`clean.py:26-28` 分级归 `gaps.py`；`verify_chunk_result`/`verify_clean_region`/`contract.__post_init__` 是现成层内门。
- **漏斗（79 目标，i42/band 口径，同口径可减）**：S0 77 → S1 66 → S2 60 → S3 51(perdoc)/59(band) → S4 44(perdoc)/**50(band)**。桶 = matched 50 / match_fail 9 / no_band 1 / candidates_no_doc 6 / kept_not_candidate 11 / not_in_doc 2。**`funnel.S4_matched`（50）权威；`target_buckets.matched`（60，doc 级"可达"）是补充口径，不得与 S4 相减**。对比纪律见 spec §13.4（同口径 + 单变量 + 每层报 Δ + 数据落盘 + 负例同步报）。
- **标签注入（S2 判定）**：`search_tsv` 是 GENERATED 列 + GIN，查询侧剔不掉；注入词元抬高 `ts_rank`（`norm=0`）。实测：无注入+perdoc 2/24、有注入+perdoc 12/24、有注入+band 19/24 ⇒ 注入与 band 互补、都要。判定价值**必须看 `S2_doc_topk`/`S4_matched` 端到端**，不得用单层指标（S1 是集合语义）。
- **F1–F4 + B2/B3 落点**：F1 `negative_query.py`（负例归零；B2 追加 abstain 拒检，默认 off）；F2 r4n band 接生产 + `_emit_cells`；F3 r4p `clean.py` 数字事实句谓词；F4 r4q `cross_boundary.aggregate_band_chunks`（表头/脚注聚合）；**r4u `stitch_continuation`（续接片段聚合，路径 B）**。工单 `.scratch/corpus-retrieval-decoupling/issues/00`–`10`（00–05 closed、03 作废、08/10 open）。**回测不可原地复跑 `calibrate.py`**（write-once 会 raise），须新目录。
- **B2 三者互斥**：`negative_query.content_lexemes` 的 `_FUNCTION_WORDS` 不含疑问词 ⇒ 「负例归零 + S1=66 + 0 model calls」互斥；产品落地走判定层拒检（开关默认 off，生产零扰动）。
- **中文检索口径**：裸 `websearch_to_tsquery('zhcfg', 题面)` 因无空格解析成相邻短语 ⇒ 命中 0；`plainto_tsquery`（全 AND）同样 0；实际生效的是 `service.py` 的 AND→OR 兜底（`& `→` | `，1033 块/15 build），与脚本显式 OR 词元集一致 ⇒ 回测口径可信。

## 7. 当前状态与开放项（2026-09-22）
- **门与回归（HEAD `8dc3ba2`）**：三门 exit 0（r4u 入链）；`pytest tests/test_corpus_*.py -q` **762 passed / 12 skipped**（skip 全为 `CORPUS_I2_DSN` 未设）；ruff CI 范围全通过；`pyright` 19 errors/7 文件（缺 `sqlalchemy`/`argon2`，与 corpus 无关）；`import_smoke` 365/365、414/414；`check_symbols` 0 missing。
- **B8 已解除**：`i2_sandbox_corpus`@543 = 16 builds / 7686 units / 1649 chunks / 9 publications；**8 份 active builds 于 2026-09-22 02:16 UTC（本地 10:16）全量重建，`clean_rev=f1775328…`（含 F3）**（实证：company-007 ord717 = `kept`，F3 已在语料内）；`7e0e068edaee` active=None。
- **B2 已闭环**（r4t + 真库复验）：开关 on 下 6 负例 `product_hits=0` + `query_status=abstain`，S1=66/S2=60 不回退。
- **B3/F3 已闭环（路径 B，i0c-r4u，U 具名裁决）**：重摄入后 ord717 kept 但 ord718（「份。」，NOISE）不在块内 ⇒ 引文逐字不可承载；`cross_boundary.stitch_continuation`（默认开，免重摄入）保序聚合尾片段。2026-09-22 不落盘重跑 `f3b_replay.py` 复现：e1 off=false→on=true、82 目标零回退、新增恰 {company-007/e1}、EvidencePass **19/24**、负例 6×0、选择不变（带宽 33≤49）、产品 `svc.search_bands` 逐字段一致。全库精化谓词仅 ord717/718 一处（裸放宽 132 处会混入页眉/页脚）。
  **残留**：路径 B **只在 band 读取链生效，perdoc 路径 e1 会回退**；且**召回侧吃不到「股份」词元**（索引向量未变，切开后 717→「股」/718→「份」「。」）。U 提出「单元级根治」= 路径 A（把尾片段并入单元），**待裁决，未动字节**；A 与 B 覆盖同一批样本 ⇒ 分数零增量，A 的真实收益 = chunk 文本完整 + 全读取路径受益，代价 = 重摄入 8 builds + 新冻结修订 + 粒度具名签认。
- **company-003（issues/10，产物 `audits/20260922-company003-doc-recall/`）**：P1 金标 doc `dddc7cd0` 词法 rank 6、band top-5 不含它；**2026-09-22 归因修正**：top-6 best chunk 全为 body 块、`matched_label_only_lexemes` 全空 ⇒ rank-6 是**全池排序环境效应**（Δ vs rank5 ≈0.35%），非"竞品靠标签词元"；body-only 反事实金标回 rank5，但 8/24 题 top-5 变 ⇒ 全局去注入仍否。P2 叠加：e1–e6 locator 含 `row:/col:`，band 证据只带 `page:`、光力 `cells=[]` ⇒ P1 单独修不产生新 matched。候选 a(doc_topk 5→N)/b(公司名×标题先验，非单调)/c(P2 修复+重摄入，唯一能 19→20)/d(登记不修)。红线：不动注入、不降 `max_false_positives=0`、不改 `matches` 口径、`max_chunks_per_document=8`、负例不回升。
- **排序机制根因（2026-09-22 细化，只读）**：文档名次由**最高分块**决定；金标最高分块 `body:0023`=0.0328272（只命中 光/力/科技/现金流/经营/预测 + 4 虚词），而**真正答题的 `table:0018`（含 2026e/2027e/2028e/每股/收益/现金流）=0.03207323 更低**；top-5 门槛 0.03294254 ⇒ 用最高分块差 0.35%，换答题块差 2.6%，**都进不去**。机制：`ts_rank`（norm=0）主要计"命中词元个数"，题面 24 词元中 8 个虚词/标点 ⇒ 无关正文块（命中 10 个含虚词）压过表块（命中 6 个全实词）；rank1 `793b3967` 命中 11 个全是通用词同理。去标签反事实"有效"是因 `cc03f55b` full 0.0344→body 0.03159 掉到金标下，非金标被压制。⇒ 新增路径 **c′ 排序信号侧（去虚词/实词加权）**，属排序改动，须端到端 EvidencePass + 负例复验。
- **当前基线**：EvidencePass **19/24**、6 负例归零、S1=66/S2=60/S4=50；**M6 门槛 23/24（未达）**；关键题 100%、旧检索/财务非回归未验、I3-7 未开始。
- **其它开放项**：B6 = M5 待独立复核 + U 签认；B7 = 工作树未收口（`spec.md`、`MEMORY.md` 未提交；`f1_replay_readonly.py` 未归档；`issues/08` status 仍 `in-progress` 未随 r4u 收口）。`r42/r43` 的 `i31_complete`/`i33_complete`/`m6_released` 回退为 `None`。

## 8. 常用实跑命令
`uv run pytest tests/test_corpus_*.py -q`（762/12）；`uv run ruff check <CI 范围>`；三门在 `.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/`（判绿须 `endswith("exit=0")`）。各 audit 目录自带回放脚本：`f3_replay.py`、`f3b_replay.py`（**write-once 假红，重跑须打补丁或改用语义比较**）、`b2_replay_abstain.py`、`c3_attribution.py [--no-write]`（模板）。
