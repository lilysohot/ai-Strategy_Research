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
- **冻结链**：`.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/`（i0c-r1…r15 + i1-r1…r4）。
  改动任何被绑定的实现/测试/文档字节后，必须①新建修订（生成器脚本 + manifest 追加 + 扩展
  `validate_i0c_freeze.py`）②`validate_i0c_freeze.py` exit 0。**write-once：冻结后不得再改被绑文件**，
  否则只能再建一版（先跑完 ruff/pyright/测试再冻结）。`validate_i1_freeze.py` 自 I0-C/I2 起对工作区已失配（既有状态）。
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
