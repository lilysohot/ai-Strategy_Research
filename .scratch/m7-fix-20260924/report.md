# M7 复核修复最终总结报告

- **日期**：2026-09-24
- **依据**：外部复核报告 `.scratch/m7-review-20260924/report.md`（六项问题全部核查属实），U 裁决「全部修复，P1 优先」
- **结论**：六项（G1/G2/S1/S2/G3/G4）全部整改闭环；冻结链头推进 **i0c-r5i → i0c-r5j**（验证器 exit 0）；冻结 PG 电池复放全绿；全仓 pytest 与复核基线同构
- **零模型调用**：全程未触发任何 LLM 调用（复核哨兵 env 下执行）

---

## 1. 六项问题整改对照

| 项 | 级别 | 复核问题 | 整改 | 状态 |
|---|---|---|---|---|
| G1 | P1 | 默认服务未恢复（.env 缺 `CORPUS_TARGET_DB`） | [.env](file:///home/administrator/FrontierAgent/.env) L85 交付 `CORPUS_TARGET_DB=postgres`；[.env.example](file:///home/administrator/FrontierAgent/.env.example) L84 同步键位（空占位，模板约定）；default 模式验收 **30 题 24/24** | 完成 |
| G2 | P1 | 旧 ingest 写入口未关 | `service.run_ingest` 恒定拒绝（`RetiredIngestError`，任何 DB 连接/DDL/advisory lock/台账写入之前）；`corpus-service ingest` CLI 结构化 JSON 拒绝 exit 2（实现在 service `_main`）；新增 `tests/test_corpus_ingest_retired.py` **零连接回归**（monkeypatch `psycopg.connect` 即炸，含失败路径） | 完成 |
| S1 | P2 | 目标库 import 时缓存 | service / read_pg / search_pg / cross_boundary / cli 全部改为构造/调用时动态 `resolve_target_db()`（显式 `CORPUS_TARGET_DB` 优先，空回落 `i2_sandbox_corpus`） | 完成 |
| S2 | P2 | 检索选择逻辑分叉（冻结测试稳定失败） | `search()` 统一委托 `search_with_coverage`（r5e 产品门 24/24 口径：top_k 来源 × 每源 1 锚点），删除 `_selected_chunk_hits` 双入口；[tests/test_corpus_consumers_pg.py](file:///home/administrator/FrontierAgent/tests/test_corpus_consumers_pg.py) 断言口径 10→5 | 完成 |
| G3 | P2 | I4-6 恢复验证记录缺权限对账 / 旧引用回环 / 实测耗时 | 隔离恢复补验（见 §4），报告 write-once | 完成 |
| G4 | P2 | 冻结链未绑定窗口关键证据 | r5j 冻结修订：9 件窗口证据首次入链 + 修复后代码/测试/台账/验证器重绑（见 §3） | 完成 |

## 2. 测试重验

### 2.1 fullchain 12/12 回绿（根因定位）

- **根因**：`.env` 注入链——`import plugins.tools.corpus_fetch` → run_python_code → `frontier_agent/infra/config.py:35` 模块级 `_load_env_file()` → `load_dotenv(override=False)` 把 .env 值灌进 lane 子进程，守卫误判目标为 `postgres`。
- **修复**：守卫 lane env 固定 `CORPUS_TARGET_DB=i2_sandbox_corpus`（dotenv 不覆盖已存在键）。
- **契约记录**：lane 子进程 env 为白名单构造，`.env` 新增键必须显式预置（空串中和或守卫值固定）。

### 2.2 违规单跑排查（零污染）

7 个 `-k corpus` 失败逐一定性为 **lane 契约伪失败**（沙箱被 fullchain TRUNCATE、claims/metadata/audit/evidence 需专用 lane、cli_isolation 需哨兵凭证）。期间四个误触生产 DSN 的测试经实地核验（scratch schema + finally DROP CASCADE；生产 schema 清单/计数与阶段 2 收尾态精确一致）：**生产库零污染**。

### 2.3 冻结 PG 电池复放（[replay_battery.py](file:///home/administrator/FrontierAgent/.scratch/m7-fix-20260924/replay_battery.py)）

| lane | 结果 |
|---|---|
| m4-plain / m4-i1 | 各 320 passed + 7 skipped |
| dev-lane | 9 passed |
| search-live（PG lane 首跑，8 源完好） | 11 passed |
| fullchain | 12/12 回绿 |
| m5-hermetic | 78 零跳 |
| m5-dsn-d2d6（第三库无 corpus schema） | 73 零跳 |
| `--restore` 独立子进程恢复 | build_id 确定性复现 + active 指针严格 8 源 |
| **总门** | **passed=true** |

### 2.4 全仓 pytest（复核哨兵 env）

**2931 passed / 2 failed（既有同一对，与复核基线一致）/ 49 skipped**。

## 3. G4：r5j 冻结修订（链头 i0c-r5j）

三阶段（archive-first 先例：r4z/r5g/r5h/r5i）：

- **Phase A**（[r5j_prepare.py](file:///home/administrator/FrontierAgent/.scratch/m7-fix-20260924/r5j_prepare.py)）：`audits/20260923-i4-window/before-r5j/` 归档（5 代码 = git HEAD 字节 = r5g 绑定；test_consumers = HEAD = r4s `24c65f47`；validator = 扩展前 = r5i 绑定 `c9e46bf9`）+ `previous-effective-bindings-r5j.json` 平铺 8 条（全取自链文件，断言归档==声明）。
- **Phase B**：[validate_i0c_freeze.py](file:///home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py) 新增 r5j 节（binding 六组 scope + archive-first + G1/G2/S1/S2/.env/tasks.md 语义门 + validator supersession 台账）；tasks.md §0 回填置顶条目。
- **Phase C**（[r5j_finalize.py](file:///home/administrator/FrontierAgent/.scratch/m7-fix-20260924/r5j_finalize.py)）：写 [i0c-r5j.json](file:///home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/i0c-r5j.json)（sha256 `327890c1d1d8e9db1bff19d7ae94bcb1f36df7e3ea5af1ce7e3f80cef165305f`，parent=r5i 实测哈希，supersedes=`c9e46bf9`）+ freeze-manifest 追加 + 验证器 **exit 0**（打印 `CURRENT r5j`）。

### r5j 首轮验证 4 失配与修复（均按既有先例，未改写历史）

| 失配 | 根因 | 修复 |
|---|---|---|
| r5j cli.py 门 | G2 的 CLI 结构化拒绝实际在 service `_main`（`retired_ingest_entry`），cli.py 仅承 S1 | 门移至 service.py `_main`；cli.py 门改为 S1 动态解析语义 |
| r4n service 门 | 要求 `_selected_chunk_hits`（S2 已删） | r5e/r4v 先例：r5j 条件分支（band/cell 保留 + 统一委托断言） |
| r39 search_pg | 权威哈希 supersession 链停在 r5g | 推进至 r5j `m7_fix_code` 绑定值 |
| r42 search_pg | 同上（消费 r39 映射） | 随 r39 修复自动解决 |

### r5j binding（六组）

- `m7_fix_code`：service.py / read_pg.py / search_pg.py / cross_boundary.py / cli.py（修复后字节）
- `m7_fix_tests`：test_corpus_consumers_pg.py（口径更新）+ test_corpus_ingest_retired.py（首次入链）
- `m7_window_evidence`（G4，9 件首次入链）：窗口 report.md、i4-reset-manifest.json、i4-cutover-manifest.json、i47-reset-phase1-report.json、i44-rebuild-report.json、i45_tool_roundtrip.py、i45-tool-roundtrip.json、i4c_reset_phase2.py、i4c-reset-phase2-report.json
- `m7_fix_state`：tasks.md（§0 回填后重绑，archive-first）
- `previous_effective_bindings` + `freeze_validator`

## 4. G3：隔离恢复补验（[g3-isolated-restore-verification.json](file:///home/administrator/FrontierAgent/.scratch/m7-fix-20260924/g3-isolated-restore-verification.json)，write-once）

- **方式**：corpus-db 隔离实例（127.0.0.1:543，PG 18.6 与源匹配）一次性库 `i4_g3_restore_20260924`；`pg_restore -U postgres --no-owner --exit-on-error < postgres.dump`；验证后 `DROP ... WITH (FORCE)` 销毁并核验。生产 pg 容器仅只读目录查询（`PGOPTIONS default_transaction_read_only=on`），**零写路径**。
- **七门全过（gate.passed=true）**：
  1. 备份 manifest 25/25（sha256sum -c）
  2. pg_restore exit 0，**实测 1.433s**（宿主机 perf_counter 墙钟）
  3. 计数 11/11（vs 备份时刻精确基准 `ledgers/_counts.json`）
  4. 扩展 4/4（pg_trgm 1.6 / plpgsql 1.0 / vector 0.8.6 / zhparser 2.4）+ `zhparser.zhprs_custom_word` 0 行
  5. **权限对账五轴 parity**（pg_roles / pg_database.datacl / pg_namespace.nspacl / pg_tables.tableowner / pg_class.relacl）：两侧均为 postgres 单角色默认权限态（dump TOC 0 条 ACL，`--no-owner` 语义下所有权一致），无 verify-only 角色
  6. **引用回环**：回环 A——备份 claims.jsonl → 恢复库 blocks(doc_id, locator) **1318/1318 全解析**；回环 B——七表 CSV 台账 \copy 入临时表与恢复库**双向 EXCEPT 逐行 0/0 diff**（claims 1318 / claim_block_runs 290 / corpus_evidence_runs 57 / ingest_runs 11 / ingest_failures 1 / docs 3 / chinese_docs 3）
  7. 一次性库销毁核验
- **脚本侧转换修复**（非被测物缺陷）：数组列 Python repr→PG 字面量（`ast.literal_eval`，单引号 repr 非 JSON）、jsonb payload 大字段（field_size_limit）、ordinal 1 基→CSV 0 基索引错位、tsvector 空串导出混淆（导出把 `''` 写成空串、`NULL ''` 导入为 NULL——以 `coalesce(col::text,'')` 投影中和，恢复库实测为空 tsvector 非 NULL、无生成列/触发器，属导出伪差）。
- **信息性记录（不入门）**：cbr `claims_n` 与恢复库分组一致 247/290（43 个 run 为失败/重试批次语义）；cer `source_rev` 非 md5(text) 前缀（口径假设不成立，仅记录）。两者均不构成恢复缺陷，恢复保真度以回环 B 逐行 EXCEPT 为权威证据。

## 5. 产物清单（`.scratch/m7-fix-20260924/`）

| 文件 | 说明 |
|---|---|
| `report.md` | 本报告 |
| `replay_battery.py` + `lane-*.txt` / `i37-tests-results.json` / `pytest-full.log` | 冻结电池复放 + 全仓 pytest 产物 |
| `live_default_product.py` + `live-default.json` / `product-trace-default.json` | G1 default 模式 30 题验收 |
| `r5j_prepare.py` / `r5j_finalize.py` / `r5j-finalize.json` | r5j 三阶段执行与落章记录 |
| `g3_isolated_restore_verify.py` / `g3-isolated-restore-verification.json` | G3 隔离恢复补验脚本与 write-once 报告 |

冻结链产物：`freezes/i0c-r5j.json`（`327890c1…`）、`freeze-manifest.json` 追加条目、`audits/20260923-i4-window/before-r5j/`（9 件归档）、`previous-effective-bindings-r5j.json`。

## 6. 遗留与注意事项

1. **既有失败对**：全仓 pytest 的 2 failed 为复核前既有同一对（非本轮引入），与复核基线一致。
2. **lane env 契约**：后续向 `.env` 新增键时，守卫 lane 需显式预置（空串或固定值），否则模块级 `_load_env_file()` 会注入 lane 子进程——已记录于 tasks.md §0。
3. **r5j 后 tasks.md 已冻结**：tasks.md 绑定于 r5j，任何后续编辑需新修订重绑（archive-first）。
4. **G3 不绑链**：补验报告按 tasks.md r5j 条目注明「另行执行」，未触发 r5k；如需入链另行核定。
5. **复核遗留观察**：`i45-tool-roundtrip.json` 未绑定执行代码快照——其执行脚本 `i45_tool_roundtrip.py` 已随 r5j 入链（G4 覆盖），工具往返产物本身作为窗口证据绑定。

---

**签署**：M7 复核六项整改完成，链头 i0c-r5j，验证器 exit 0，冻结电池复放全绿，全仓 2931/2 既有/49。M7 放行以总台账为准。
