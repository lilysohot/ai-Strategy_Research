# MEMORY（跨会话长期事实）

真源 = `docs/plan/claims-market-closed-loop-plan.md` + `docs/plan/corpus-ingestion-rebuild-tasks.md`。
本文件 = **稳定约定 + 状态索引**；实测数字与流程细节见 `.codebuddy/memory/2026-09-*.md` 与各 audit 目录。压缩整理：2026-09-29。

## 0. 判定纪律（U 偏好）
- 大白话 + 真实进度与下一步；**结论必须附实跑命令与结果**。
- 交办的复核/整改要**真改并留证据**；只有明说「只要文档」才不动代码。
- **交付物口径**：纯文本报告/清单/方案**不算**；只有入冻结链的改动（代码/金标/层内门禁/常驻测试/冻结修订）才算。
- `complete`/里程碑放行只能由**独立复核 + U 具名签认**，实施方不得自宣。
- 校验类脚本须支持 `--no-write` 且幂等可重跑；阈值/粒度变更须具名签认。
- 报分须区分「回测/诊断口径」与「生产默认口径」；负例数字须带路径口径。
- 同一信息反复复述 ⇒ 缺共同口径：停止复述，请 U 裁决。

## 1. 环境坑位（硬约定）
- 审计证据放 `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/<日期>-<名称>/`：`review.md`（write-once）+ `remediation-checklist.md`；RM 编号分命名空间。流程 = 复核 → 刷新修订哈希 → 三门验证；签认后不得重写。
- **write-once 产物不放墙钟时间戳**（重跑字节必不同 ⇒ 假冲突）：比较剔 `generated_at`，语义全同则保留原字节；脚本不可原地复跑，须新目录。
- 读 CLI stdout **从首个 `{` 解析**（pymupdf 横幅 ⇒ 假红）。
- `tests/test_corpus_cli_isolation.py::test_subprocess_model_client_import_refused` 普通 pytest 必 fail，须 `env -i … CORPUS_GUARD_PHASE=i2-verify` 守卫 env。
- **`.scratch` 未被 gitignore 且已入库**（2026-09-28：5622 tracked / 1.2G）；`search_content` 搜不到是隐藏目录 ripgrep 默认跳过 ⇒ 用 shell grep / read_file。
- **U 裁决（2026-09-28）：`.scratch` 瘦身推迟到上线前**（并行会话在写、27 文件未提交、freeze 绑 13 个 pdf 路径）；当时只给 `.gitignore` 加增量防护；上线前才 `git rm --cached` / filter-repo。
- psycopg 里 SQL **别写裸 `%`**（`LIKE '%unit%'` 报 `got '%u'`）⇒ 参数传。
- 查库走 `uv run python` + psycopg（**本机无 psql**）。旧库 `postgresql://postgres:postgres@127.0.0.1:5432/postgres`；沙箱库 `…@127.0.0.1:543/i2_sandbox_corpus`（corpus schema）。
- 有并行会话/自动提交流程在写 ⇒ 改 memory/spec 前先 `git status`。
- `git` 报 `index.lock: File exists`：先 `ps` 确认无活 git 进程，再 `rm -f .git/index.lock`（2026-09-29 处理过一次 23:45 遗留的 0 字节空锁，无进程持有）。
- **投影（projection）** = 一处权威源按固定口径派生只读视图。三铁律：①不复制权威（`corpus_units.raw_text`/冻结裁定件）②口径带版本指纹 `UNITS_PROJECTION_VERSION="evidence-units-projection-1"` ③不回流（只供 evaluator，禁进 prompt）。落点：`clean.py::clean_view`、`corpus_chunks`、`build_evidence_run_from_units:629`、`project_claims:205`+`claims_of:1672`、`i3s2_apply_decisions.py`→`evidence-targets-approved.json`、P3-I 35 条字段契约。对账 `verify_evidence_against_authority`（`service.py:1490`）：`parse_rev` 不符即 `IntegrityError`。

## 2. 冻结链（`.scratch/.../ingestion-rebuild/freezes/`）
白话：freezes = 项目拍照存档（代码/语料/尺子/分数，编号连父快照链，校验器 `validate_*_freeze.py`；红 = 照片与实物不符）。git 答「代码长什么样」，freezes 答「结论是哪版跑出来的」。
- i0c 链 …r43 → r4n…r4z → r5/r5a–r5d → r5g/**r5h**（最新）；i1 链 r1…**r6**。门 = `validate_i0c_freeze.py`/`validate_i1_freeze.py`/`validate_i3_2_completion.py`；2026-09-23 三门实跑 **exit 0**（i0c 日志 r29 NOTE 为既有非失败项）。
- 修订语义：r41 scoped、r42 S1 清账、r43 R3 闭环(生产接 perdoc)、r4n F2 band+cell、r4p F3 clean 句粒度、r4q F4 跨边界取证、r4r r39 漂移豁免、r4s M5 两处 MISS 重绑、r4t B2 abstain 拒检(默认 off)、r4u B3/F3 句尾续接、r4v prune_fn_punct 排序、r4w M5 具名签认、r4x 金标 col 口径、r4y D2 脚注挂靠、r4z I3-5 台账回填、r5d 三项 P1、r5g 目标授权闸、r5h 收尾。
- 跨链联动：路径只在 i1 链绑定时，i0c 侧重绑须同步补 i1 修订（r4s→i1-r6）。改前 `archive_first()`；权威凭据只有各修订绑定哈希；改前字节取 `git show HEAD~1:`。
- 合并按修订号数值；在效绑定用 `merged_binding_upto_revision(N)`（`from_all_but` 会取 i1 陈旧值）。
- 其它坑：可重入补丁锚 `text.index('\nif "i0c-rXX" in by_id:')`；假绿判定须 `text.rstrip().endswith("exit=0")`；i1 校验器 in-process 须 `exec(compile(...), {"__name__":"__main__","__file__":path})`；门日志绑定两轮逐字节一致；`tasks.md` M6 行前缀 `"| M6  |"`；误改被绑字节按 rXX 哈希 / `git show HEAD:<path>` 还原核 sha。

## 3. 语料链（I2）
- 写链 `plugins/corpus/cli.py`(plan/build/check/publish/status/rebuild-plan) → `preparation/engine.py` → `repository_pg.py`；读链唯一入口 `preparation/read_pg.py`（`cv2:<build_id>`／`chunk:<chunk_id>`）；`service.CorpusService` 按 `CORPUS_READ_CHAIN` 路由。
- **生产默认检索形态 = band**（r4n）：`search_with_coverage_bands` → `_apply_selection`（`select_structural` 定来源序、`select_band` 定文档内带，G=1/K=1/带数=8/`POOL_CAP=24`）→ `cross_boundary.aggregate_band_chunks`（r4q/r4u/r4y 默认开）。
- 库形态 `corpus.corpus_{builds,sources,publications,units,chunks,admissions,review_decisions,jobs,source_checkpoints}`；块只收 kept 单元（`unit_refs` 形如 `unit:0717`）。缺口语义 `preparation/gaps.py`：`blocking`/`acknowledged`/`out_of_scope`；`quality_report.gap_regions` 恒两键。
- CLI 退出码 0/2/3/4/5；fail-closed（`--dsn`/`CORPUS_I2_DSN` 必需，校验 `current_database == i2_sandbox_corpus`）。只写沙箱 corpus schema；生产库 I4 前零写入；PG 门不得 skip。
- 约束：`review_decision_ids` 须列整条取代链；`corpus plan` 缺口在 `entry.precheck.{gap_summary,gaps}`（整批失败 exit 2）；`domain_hint` 须合法 `ResearchDomain`；阻断码 `image_region_unreadable`/`image_only_page`/`table_lines_without_extraction` 无人工入口；`put_admission` 唯一性 = `decision_id` 全局唯一（RM-7）。
- 守卫 env：`env -u PYTHONPATH CORPUS_GUARD_PHASE=… CORPUS_GUARD_CONFIG=… CORPUS_I2_DSN=… uv run pytest <files> -q -p plugins.corpus.preparation.guard_pytest --noconftest -c /dev/null`。guards：`i3.json`、`i3-e2e.json`（allowlist 仅 `127.0.0.1:543`）、`i1.json`；`config_version` 整数 1。
- **I2-8 四条（RM-I28-0）**：①文档级与块级**同句柄版本语义**（`cv2:<build_id>` 返回该 build 原文）②来源撤销/排除 ⇒ 文档级 `None`、块级 `WithdrawnError` ③**迁移目标无 legacy fallback**（`auto` 仅未迁移过渡）④`doc_id→source_id` manifest 属 I4 停写窗口交付件，之前只给 `archive_required` 拒绝路径。落点：`read_pg.fetch_document:289`、`service.read_chain:838`、`preparation/pg_target.py`、`service.fetch/fetch_verbatim:1272/1414`。
- **检索 scope ≠ 取证 scope**：检索只搜已发布 active build（`search_pg.py:68` INNER JOIN）；取证锁句柄版本，旧 build 可取且 `active=False`，只有来源撤销/排除才拒。发布是显式动作（`engine.py:1434` + `repository_pg.py:920`，`generation`+1）。
- **RM-FC-5 拼接语义**：`Evidence.text` = 所引单元 `raw_text` 的确定性 `"\n"` 拼接，**不是源文件字节还原** ⇒ 跨单元引文须按单元取证，不得把 text 当原文切片。

## 4. dev lane（U 2026-09-20 裁决）
`contract.IN_SCOPE_MATERIALS_BY_POLICY_REV`（v1 仅 `research_report`；`v2-dev-20260920` 加两个内部材料类型；未知 rev 落最严）。dev lane = 独立政策文件（`scope=dev` + `production_in_scope_unchanged=true`）；装载需 `CORPUS_DEV_LANE=1` 否则 fail-closed；`evidence_refs` 加 `dev_lane=<lane_id>`；样本计入 §12.1 格式门但须标注。范围唯一权威源 = `i0a2-adjudicated-20260915.json::dev_selection_approved`；`excluded_from_active` 是人工终态（`admission.py:454`）。测试 `tests/test_corpus_dev_lane.py`（9 条，仅 `i3-e2e` 守卫）。

## 5. I3 评分器与子项
- **唯一落点** `plugins/corpus/scoring.py`（纯标准库、无模型/网络/PG/时钟/IO）：`score`/`gold_from_records`/`format_report`；门槛用 `Fraction`。当前字节 `f61573d7`（r41 绑定；旧严格 `bf9c8b80`）。**No tuning after scores**（r39）。
- 输入契约（改即改冻结）：`documents` 按相关性排序且来源唯一、只表示命中断言的文档；`no_match` = `outcome=NO_MATCH` + `documents=()`；只从前 k 计分；`verified` 默认 `None`；`answer_existence` 缺失即报错；零分母/缺输入/关键题未满分 → `blockers`。
- **`EvidenceTarget.matches`**：`verified is True` + 整条 `quote` 逐字包含（去空白 code point）+ `locator` token 全在证据 locator 里；`basis.matched_tokens` 不参与。
- **负例（M6 硬判据）**：`NO_ANSWER` 走 `_score_negative`，三指标记 `None`；`documents` 非空即 `false_positive=True`，引文条数累加 `fabricated_citations`；默认 `max_=0` ⇒ 超限落 `blockers`；6 题 `critical=true`。**24/24 也绕不过 1 条负例误报。**
- **I3-1**：格式门达标（pdf 5/6、docx 1/1、md 1/1）、`per_class_min_2=true`（i0c-r37，xyl 签署 + 真实发布 7/8）；国信光力 `dddc7cd0` 未放行。
- **I3-2**：36 槽位/候选 82/批准 79 必需 + 20 补充；评分输入 `i3-2/query-gold-scoring-v1.jsonl` + `scoring-input-manifest.json`（唯一读入口 `load_scoring_input`）；完成门 10/10 exit 0；签认件 `audits/20260919-i32-diagnosis/signoff-record-i3-2.*`（xyl）。
- **I3-5（2026-09-23，零模型/原库零写/留出零读）**：审计 `audits/20260923-i35-legacy-nonregress/`。实测 财务 47/47 + 公式 7/7 + 高盛负控 PASS、客户表 12/12、正文 2/2、宏观 0/3 单列、旧检索 golden 19/19、审批契约门 32 passed；**not_run 4 项；不是最终版本放行**。偏差：冻结契约 `verify_claims_entry.py` 默认连旧库且 `extract_claims(persist=True)` 会写 `corpus_evidence_runs`，I2-7 后原样不可执行 ⇒ 走 `build_evidence_run` 库级等价路径（零写）。pilot 三源中仅高盛 `excluded`。
- **里程碑序（`tasks.md:350-357`）**：M1=I0-A → M2=I0-B → M3=I0-C 冻结 → M4=I1 → M5=I2 → **M6=I3 最终 E2E + 非回归（切换前最后业务门）** → M7=I4 切换 → M8=I5 退役。**M6 判据（`tasks.md:271`）**：I3-7 对 I3-6 重验通过 + 逐类三指标达标 + 关键引用题 100% + 旧检索/财务不退化 + **伪引用负例为 0**；宏观 0/3 单列。

## 6. 检索/取证修复簇（i33→i42 + band + F1–F4 + D2）
- 方案 `.scratch/corpus-retrieval-decoupling/spec.md`（§0–§14.11；工单 `issues/00`–`11`：00–05 closed、03 作废、08(F3)/11(D2) 收口）。核心病理：分层可归因，失效的是「分层 → 层内可证伪判据」没落地。
- **六个解耦点**：①选择策略落产品 ②`SearchHit` 补 `page`/`cells`/`label_path` ③拆 recall/rank（`chunk.cover` 作废→band）④连续块区间→band ⑤表格结构模型在 reader（`TableModel.label_path`）⑥clean 判定机读（`NoiseVerdict`，只记账）。**勿动**：`pdf_reader.py:333-345 _row_text`；`clean.py:26-28`；`verify_chunk_result`/`verify_clean_region`/`contract.__post_init__` 是现成层内门。
- **漏斗（79 目标，i42 perdoc）**：S0 77→S1 66→S2 60→S3 51→S4 44；band 后 **S3=59、S4=50**（`funnel.S4_matched` 权威；`target_buckets.matched`=60 是 doc 级补充口径，**不得相减**）。
- **标签注入（S2）**：`search_tsv` 是 GENERATED 列 + GIN，查询侧剔不掉，注入词元抬高 `ts_rank`。实测 无注入+perdoc 2/24 / 有注入+perdoc 12/24 / 有注入+band 19/24（互补，都要）；判定价值须看端到端 `S2_doc_topk`/`S4_matched`。归因修正见 `issues/10`。
- **落点**：F1 `negative_query.py`（`content_lexemes` 收紧 + `is_relevant_candidate`；B2 追加 `abstain_*`）；F2 = r4n band 生产默认；F3 = r4p `clean.py` 数字事实句谓词；F4 = r4q `cross_boundary.py::aggregate_band_chunks`。**B2 三者互斥**（疑问词不在 `_FUNCTION_WORDS`）⇒ 产品改走**判定层拒检**（r4t，默认 off）。**D2（r4y）** 脚注挂靠：块内表格行 + 同页 + 版面在表格下方（bbox y0 ≥ y1，Δ<12pt）+ 段形「来源注+说明性分句」；全库 4 条/2 份；旧报告「78 段/139 配对」是裸谓词高估。

## 7. 状态与开放项（2026-09-24）
- **M6 评测口径**：EvidencePass 24/24、逐类 8/8、doc_recall 三类 1、blockers 空（r4x+r4y）⇒ 评测口径已达成，但**产品口径未过**。
- **M6 独立审核（`m6-current-review-20260923/review.md`）**：成绩可复现，但**不能认定产品路径达标**；3 项 P1：①**S1** 跨边界补证丢弃 `content_hash` 不验哈希（`cross_boundary.py:236/261/292/313-321`）②**F1** 联合证据只接 `search_bands()`，正式 `corpus_fetch→fetch_verbatim()` 未接 ③**F2** 评分观测人工构造，与正式 `corpus_search`（默认 10/上限 20）口径不同。
- **三项 P1 修复（`m6-repair-20260923/report.md`，i0c-r5d）**：缺陷已修 + 回归通过，但 `business_accepted=false`。**真实产品成绩**：默认（题干/limit=10/abstain=off）**QP 0/24、EP 0/24**；OR 诊断（limit=20）QP 22/24、EP 13/24、**负例 6/6 误报**。**机制**：产品 `websearch_to_tsquery('zhcfg',…)`（`search_pg.py:65`）空格默认 **AND** ⇒ 整句中文问句必零命中；旧「24/24」靠评测侧 OR 改写 + `search_bands(limit=2000)`。工具 limit 是 chunk 数，**不得与文档 top_k=5 混用**。**待 U 裁决**：① 是否接受「题干 AND 语义」为产品默认；② OR 诊断负例 6/6 误报如何处置。
- **M7/I4 停写窗口已执行（`audits/20260923-i4-window/report.md`，U 签认）**：九表两阶段 reset；停写点 LSN `0/4FB2BD00`（门禁 8/8）；备份 `backups/i4-final-20260923T1544Z` + 台账 `ledgers/corpus_evidence_runs.jsonl`；I4-7 九表迁生产（19 索引）；reset 阶段 1（七表）归零；I4-4 重建 8/8、chunks 834/units 3887；I4-5 往返 4 命中/18 单元、旧句柄 `archive_required`、零模型。**reset 阶段 2（blocks/documents）U 裁决「暂缓」**；报告明确不构成 M7 放行。
- **实测库现状**：生产 `5432/postgres` = public 七派生表全 0 + blocks 1101/documents 89 + **corpus 九表已装满**（sources 8/builds 8/publications 8/admissions 8/review_decisions 10/chunks 834/units 3887/jobs 24/checkpoints 12）。冻结 run 复验三项**无法对在线旧库原地复现**（属批准 TRUNCATE），须走 `ledgers/*.jsonl` 或备份恢复库并注明口径。
- **门与回归**：三门 exit 0（r4z 入链）；`tests/test_corpus_selection.py` 38 passed；语料族 772 passed/17 skipped（skip 全因 `CORPUS_I2_DSN` 未设）；ruff CI 范围通过；pyright 基线 19 errors/7 文件（缺 `sqlalchemy`/`argon2`，与 corpus 无关）；`import_smoke` 365/365 + 414/414；`check_symbols` 0 missing。
- **已闭环**：B2(r4t)、B3(r4u)、B8、I3-5(r4z)、M7/I4 窗口主体。**开放项**：B6 = M5 待独立复核 + U 签认；B7 = 工作树未收口；**M6 未放行**（余 I3-6/I3-7/格式门独立复核/U 具名签认）；I4 reset 阶段 2；I5-1/2/3。`r42/r43` 的 `i31_complete`/`i33_complete`/`m6_released` 回退 `None`。

## 8. 常用实跑命令
- 回归 `uv run pytest tests/test_corpus_*.py -q`；lint `uv run ruff check <CI 范围>`。
- 三门 `uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_{i0c_freeze,i1_freeze,i3_2_completion}.py`（判绿须 exit 0）。
- 零模型审批门 `uv run python -m pytest -q .scratch/.../audits/20260918-i32-remediation/test_approval_contract.py`（32 passed）。
- audit 目录自带回放：`i35_replay.py`、`f3_replay.py`、`b2_replay_abstain.py`、`c3_attribution.py [--no-write]`、`d2_replay.py`。

## 9. Web 平台（server/ + web/）
- 后端 `server/app.py`（FastAPI/uvicorn，端口 **8000**），依赖组 **`web`**（`uv sync --group web`）；`/api` 需登录，`/healthz` 公开。前端 `web/`（Vue3+Vite，端口 **5173**），`/api` 代理到 8000。**服务非常驻**，每会话重拉。
- 启动密钥门 `security.check_startup_secrets`：正式需 `SERVER_MASTER_KEY` + `SERVER_JWT_SECRET`（`SERVER_DEBUG=true` 降级 warning）。
- **`/healthz` 会假绿**：`init_db()` 被 `contextlib.suppress(Exception)` 包住 ⇒ DB 挂仍 200，业务全 500。**判活看 `/tmp/fa-backend.log` 的 asyncpg `ConnectionRefusedError`**。
- **两套库别混**：① corpus 语料九表 = I4 迁移目标，在 `5432/postgres` 的 `corpus` schema；② web 业务表（users/sessions/runs/turns/artifacts/user_llm_configs/audit_log）在 **`5432/apodex`**（users 25/runs 1257/sessions 134，alembic `0002_run_usage`）。
- **WSL2 里 PG 由宿主机提供**（本机未装 postgres、无 docker）⇒ 先确认 PG 监听再起后端，不要退回 SQLite。应急才用 `SERVER_DATABASE_URL="sqlite+aiosqlite:///./server/dev.db"`（数据陈旧）；权威数据在 PG apodex。
