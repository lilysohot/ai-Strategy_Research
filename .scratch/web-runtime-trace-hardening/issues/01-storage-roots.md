# 01：对齐运行根目录与持久卷，兼容历史 Run

Status: closed
Priority: P1
Type: task
Requirements: PR-GOV-01, PR-GOV-05, PR-BIZ-06

## 问题与范围

见[报告 F01](../../../docs/plan/web-runtime-trace-repair-report.md#f01持久卷数据根目录及历史路径迁移)。
范围为 server 配置/受控路径解析、Web Docker 部署和历史 Run 兼容；不是直接移动或删除生产目录。

用户已明确要求：当前位置不合理时，本次修复必须一并整改。目录调整不再是可选建议。
目标布局：Compose 使用 `/var/lib/frontier-agent/web/runs`，显式持久卷；本地交互式 Linux/WSL 使用
实际用户 XDG 数据目录下的 `frontier-agent/web/runs`；系统服务显式指定稳定服务目录。
保留源码树外绝对路径覆盖能力，不要求将当前本机服务改成容器。
完整路径、上传配置处理和迁移契约以报告 F01 v1.4 为准；不改变 CLI 的运行目录。

## 修复前提与验收

- 核验实际环境覆盖、卷、Run 数据量；依赖 07 提供迁移前备份和回退。
- 明确生产目录，卷挂到准确落点；旧/新 Run 读取使用一致、受控的定位。
- 按实际部署验证重启/重新部署、根目录切换、历史读取、越界拒绝、缺失状态与回退；容器交付另验容器重建。
- 活动 Run 不跨新旧根目录读写；不得仅修改配置就宣称迁移完成。
- dry-run、可重入迁移、文件冲突处理、文件清单校验与数据库存储引用同步均有验证。
- 默认新写入离开源码树；轨迹、输入、产物、摘要、历史和 spill 一并处理，旧 Run 可查可读。
- Compose、Dockerfile、配置样例、部署说明同步；回退包含切换后新写入的保护。

## Comments

- 2026-09-29：配置/读取路径已检查，实际部署及迁移验收未执行。
- 2026-09-29：用户要求位置不合理时随本次修复改正，已明确为必交付范围；本轮更新计划，未迁移运行文件。
- 2026-09-29 全面复核：UUID 变体定位差异已隔离复现；卷挂载和迁移仍待部署验收。 执行结果见 `audit/` 及全面复核记录，未修复。
- 2026-09-29 环境补正：先复用现有服务核实实际身份与落点；测试分层及迁移门槛见[环境方案](../../../docs/plan/web-storage-validation-environment.md)，不统一要求另建 PG 或换端口。
- 2026-09-30：**本机 Windows 目录迁移已完成**（用户确认范围：仅本机，WSL 663 条不动）。
  ① `server/config.py`：`runs_root` 默认从 `<repo>/server/runs` 改为源码树外
  （Windows `%LOCALAPPDATA%\frontier-agent\web\runs`，POSIX `$XDG_DATA_HOME`），保留
  `SERVER_RUNS_ROOT` 覆盖；移除无消费者的 `uploads_root` 字段与其 `ensure_dirs` 创建
  （已确认上传实际写 `<runs_root>/<run_id>/inputs`，`uploads_root` 是纯遗留）。删除空 `uploads/` 目录。
  ② 迁移工具 `scripts/run_retention.py migrate-runs-root`（dry-run 优先，单 `asyncio.run`）：
  本机 6 条 run 中 4 个目录**移入新根**（`0be1fc12…/bebb833e…/d85d6b6d…/f696e9d2…`），
  2 条本就缺文件（`6109bf60…/d40a6d74…`，E1 重启 reconcile 置 failed）；DB `run_dir` 6 条同步更新。
  ③ 清理 **99 个孤儿磁盘目录**（测试残留，无 DB 引用；清单见 `audit/f01-orphan-dirs.json`）。
  ④ 验证：`server/runs` 目录数 103 → **0**；迁移后 `inspect_trajectory('0be1fc12…')` 返回
  `state: complete, valid_lines: 5`（`run_dir_for` 按新默认路径可读）；DB `run_dir` 前缀为
  `/home` 663、`/tmp` 85、本机新路径 6。回归 80/80 通过。
- 2026-09-30：**容器侧配置与文档已同步**。① `deploy/Dockerfile.web` 移除
  `VOLUME ["/app/server/runs", "/app/uploads"]` —— 在源码树内声明 `VOLUME` 会静默创建匿名卷、
  反而破坏可识别备份；② `deploy/docker-compose.yml`：`api.environment` 增加
  `SERVER_RUNS_ROOT=/var/lib/frontier-agent/web/runs`，`agent_data` 卷挂载点由 `/app/agent_data`
  改为 `/var/lib/frontier-agent/web`（保留卷名以维持卷身份）；③ `deploy/README.md` 数据持久化
  一节与 `docs/tech-stack.md` §7.1 缺口描述更新为已对齐；④ `.env.example` 新增 `SERVER_RUNS_ROOT`
  说明（并实测空值不会覆盖默认路径）。
  **验证**：`docker compose config --quiet` 退出码 0；`--profile full config` 解析出
  `SERVER_RUNS_ROOT: /var/lib/frontier-agent/web/runs` 与 `agent_data → /var/lib/frontier-agent/web`。
  另注：**容器从未部署过**——`agent_data` 命名卷不存在、无 Web 容器，因此本次是纯配置改动，
  无历史容器数据需要迁移或保留。
- 2026-09-30：**仍未验收（维持 ready-for-human）**：① 容器**实测**未做——镜像无法构建
  （registry 不可达，见工单 02），`docker compose up` 后卷落点、容器重建后历史 Run 可读性均未验证；
  ② WSL 部署（`/home/administrator/FrontierAgent`，663 条 run）与 `/tmp` 85 条的历史兼容与迁移未做；
  ③ 活动 Run 跨新旧根保护、真实重启后新旧 Run 追溯未做。
  另记录：环境存在批量删除守卫，单轮删除文件数 > 500 会拦截（迁移工具因此需分批），非代码缺陷。
- 2026-09-30：**WSL 侧迁移已完成（口径经用户确认）**，上条②的"663 条 run"前提被纠正为 DB `run_dir` 行数。
  ① **核查**：`/home/administrator/FrontierAgent/server/runs` 实有 837 个目录，其中仅 **244 个被 DB 引用且存在**、
  **419 个已缺失**（全盘 find 无果）、**593 个不被 DB 引用**（09-23 后占 386 个）；`/tmp` 的 85 条 `run_dir`
  均为字面量 `/tmp/x`（非真实目录），另有 6 条 Windows `C:\…` 路径。
  ② **口径（用户定）**：孤儿**一律不删**；419 条缺失行**保持指向旧根、不改写**。
  ③ **工具改动**：`scripts/run_retention.py migrate-runs-root` 增 `--keep-orphans` 与 `--only-moved`，
  默认行为不变；验证 `ruff check` 通过、`tests/test_web_f07_retention.py` **22/22**、一次性库 `apodex_f01_sim`
  端到端对照两种口径（新口径 removed 0 且缺失行未改写；默认口径 removed 2 且缺失行改写）。
  ④ **备份**：`~/.local/share/frontier-agent/backups/f01-wsl-20260930/`（仓库外、非容器 /tmp）——
  `apodex-pre-f01.dump` 183,697 B（可 `pg_restore --list`，含 runs TABLE DATA）、`server-runs-pre-f01.tar.gz`
  7,451,755 B、`SHA256SUMS`。
  ⑤ **执行**：moved **244** / already missing **419** / removed **0**；目录 593+244=837、文件 3459+1688=5147
  （守恒，零丢失）；DB 新根 244、旧根 419、`/tmp` 85、`C:\` 6。`SERVER_RUNS_ROOT` 已写入 `.env`
  （= `/home/administrator/.local/share/frontier-agent/web/runs`），API 已重启（64560 → 49379，`/healthz` 200）。
  ⑥ **历史兼容无需改代码**：`inspect_trajectory` 对 `/tmp/x` 与 419 缺失均返回 `unavailable`、
  已迁移 run 返回 `complete`，F06 三态已覆盖，不渲染为空轨迹。
  ⑦ **孤儿已归档**（用户确认口径）：593 个孤儿（19.4 MB / 3459 文件）整体移到仓库外
  `~/.local/share/frontier-agent/archive/f01-orphans-20260930/runs/`，附 `MANIFEST-orphans.json`；
  守恒 593 目录 / 3459 文件，`server/runs` 现为 **0**（源码树不再残留运行数据）。
  剩余未完成：容器实测、活动 Run 跨新旧根保护（回退演练已于同日完成，见下条）。
- 2026-09-30：**回退演练完成（隔离复演，生产全程未触碰，已清理）**。"回退包含切换后新写入的保护"一项由此闭合，工单 07
  "保留切换后新数据的回退路径，不能只改回根目录变量"的要求得到实证。
  ① **重建迁移前状态**：独立库 `apodex_f01_rollback` + 临时根。`pg_restore` 零错误，7 张表行数逐一吻合
  （users 29 / sessions 141 / runs 754 / turns 1093 / artifacts 296 / llm_configs 164 / audit_log 1978）、外键 9/9；
  tar 解包 837 run 目录 / 6758 嵌套目录 / 5147 文件，与清单一致。
  ② **模拟切换后新写入**：3 条（2 completed + 1 running）落在隔离新根（含 inputs/summary/history/ws/outputs/spill/轨迹），
  并写入对应 runs/turns/artifacts 行（757/1094/298），留存 post 快照。
  ③ **负向对照（复现失败）**：仅把 `SERVER_RUNS_ROOT` 切回旧根 → 切换后 3/3 run 解析为 `dir_exists=False`、`unavailable`；
  仅恢复 pre 业务库 → 切换后 3 行剩余 **0**。证实"只改根目录变量"不可接受。
  ④ **正向流程四步**：恢复 pre 业务库 → 文件从新根移回旧根 → COPY 合并切换后 runs/turns/artifacts → **重定位** `run_dir`。
  ⑤ **终验全过**：文件守恒 840 目录 / 5168 文件（837+3 / 5147+21）；切换后文件 sha256+size **21/21**；
  引用完整性 **247 可解析 / 510 缺失**（247 = 244 pre + 3 post；510 = 419 缺失 + 85 `/tmp` + 6 `C:\`）；
  轨迹三态 post `complete`/`partial`/`complete`、pre 抽样 `complete`；行数 757/1094/298、外键 9/9。
  ⑥ **代码级机理**：读取侧一律 `run_dir_for(id) = runs_root / canonical_run_id(id)`（inspect_trajectory、relay、artifacts、revert、worker），
  **不读**表中存储的绝对 `run_dir`——故只改根变量必然打散新写入；但 `orchestrator._read_run_summary(row.run_dir)`
  与 `routes/runs.py` 响应使用存储值，故合并后若不重定位，这两条路径会指向已清空的新根。
  ⑦ 证据：[audit/f01-rollback-drill.json](../audit/f01-rollback-drill.json)。
  剩余未完成：容器实测、活动 Run 跨新旧根保护。
- 2026-09-30：**活动 Run 跨新旧根保护已实现（拒绝式，用户选定口径）**。
  ① **根因**：`_plan_root_migration` 不区分状态，`_apply_root_migration` 会把 queued/running 的 run 目录
  一并搬走并改写 `run_dir`；而 worker 的绝对路径（`FRONTIER_AGENT_*_DIR` / `_trial_dir` / `CODING_WORKSPACE_ROOT`）
  是 spawn 时从**旧根**烘焙进环境与 metadata 的，读取侧却一律走 `run_dir_for`（当前根）——同一条 run
  一半写旧根、一半读新根，正是 F01 禁止的"活动 Run 跨新旧根读写"。
  ② **口径**：不采用"跳过/延后"。延后会把文件留在旧根而 `run_dir_for` 读新根，是同一分裂反过来的形态；
  只有终态才证明该 run 可以搬。故命中活动 run 时**整体拒绝**，不做部分迁移。
  ③ **实现**（`scripts/run_retention.py`）：`RunMigration` 增 `status`；`_plan_root_migration` 读取
  `Run.status`（仍不按状态过滤，计划保持自描述）；新增纯函数 `active_migrations()` 与
  `_refuse_active_migrations()`；`_apply_root_migration` 在**任何文件移动之前**调用守卫，命中即
  `SystemExit`（退出码 1），不移动目录、不改写 `run_dir`；dry-run 逐行标 `ACTIVE-REFUSED` 并打印
  `REFUSES TO APPLY` + run id 清单，提示"先结束，或重启 API 让启动 reconcile 收口，再重跑"；
  模块"不可协商设计规则"第 3 条补记该严格语义。
  ④ **测试**：`tests/test_web_f07_retention.py` 由 22 → **27/27 通过**（新增 5 项：活动状态判定 ×2、
  DB 级拒绝且"拒绝不是部分迁移"——目录不动 / `run_dir` 不变 / 新根不创建、无活动时照常移动并改写
  `run_dir`、dry-run 报告）。**负向对照**：临时注释守卫后
  `test_apply_refuses_while_a_run_is_active` 以 `DID NOT RAISE SystemExit` 失败，确认用例非空。
  ⑤ **真实 PG 端到端**（一次性库 `apodex_f01_active`，已 DROP、临时目录已删，业务库全程未触碰）：
  seed 1 completed + 1 running 于临时旧根 → `--apply --yes` **拒绝**、退出 1、只列出活动 run id、
  两目录仍在旧根、新根未创建；把该行改为终态后重跑 → `moved 2 / missing 0`、旧根空、
  `run_dir` 全部改写为新根路径。
  ⑥ **无回归**：对真库（当前无 queued/running）干跑 `migrate-runs-root` 仍计划 419 条、0 孤儿、无拒绝。
  当时记下的"**未修**项：新/旧同 ID 目录冲突时停止并报告"已于同日修复，见下条。
- 2026-10-01：**迁移冲突处理已实现（报告 F01「发现新旧同 ID 文件冲突时停止该项并报告，不覆盖未知内容」，上条列为未修）**。
  ① **根因**：`_apply_root_migration` 对已存在的目标无检查，`shutil.move(str(src), str(dst))` 在 `dst`
  已是目录时会把 `src` **移进 `dst` 之内**（错位，且随后仍把 `run_dir` 改写成 `dst`，指向未经核验的内容）；
  若 `dst` 是文件则直接覆盖。
  ② **实现**：`RunMigration` 增 `target_exists`（plan 期按 `new_root/<id>` 探测，供 dry-run 预告）；
  `_apply_root_migration` 在移动前**按活文件系统复核** `dst.exists()`——命中即计入 `conflicted`、`continue`，
  **不移动、不改写 `run_dir`**，其余条目照常迁移；返回值扩为
  `(moved, missing, removed, conflicted)`；dry-run 逐行标 `TARGET-EXISTS` 并打印 `WILL SKIP`；
  apply 打印 `CONFLICT` 段并提示"人工确认哪份为准后重跑"。
  ③ **测试**：`tests/test_web_f07_retention.py` 由 27 → **30/30 通过**（新增：冲突即停且**不嵌套不覆盖**
  / `run_dir` 不动、冲突不阻塞其余条目、dry-run 预告）。**负向对照**：把 `if dst.exists()` 短路为
  `if False` 后两个冲突用例均失败（`moved` 多出冲突 id、`conflicted` 为空），确认用例非空。
  ④ **真实 PG 端到端**（一次性库 `apodex_f01_conflict`，已 DROP、临时目录已删）：seed 2 completed +
  在新根预置其中 1 个同 ID 目录（内含 `unrelated.txt`）→ `--apply --yes --keep-orphans` 输出
  `moved 1 / CONFLICT: 1`；冲突目录仍留旧根、目标目录**仅含 `unrelated.txt`**（无 `clash/` 嵌套）、
  其 `run_dir` 仍指向旧根；同状态 dry-run 显示 `TARGET-EXISTS` + `WILL SKIP`。
  剩余未完成：**仅容器实测**（镜像无法构建，见工单 02）。
- 2026-10-01：**容器实测已完成（首次真实镜像 + 卷落点 + 重建后历史 Run 可读）**，并暴露一个致命部署缺口。
  ① **镜像可构建**：此前记录的 registry 阻断（`auth.docker.io` 连接超时）为**瞬时故障**——本轮
  `docker pull python:3.12-slim` 成功、容器内 `apt-get` 直连 `deb.debian.org` 正常。
  `docker build -f deploy/Dockerfile.web -t frontier-agent-web:verify .` **exit 0**，1.64 GB / 18 层，
  runtime stage = `python:3.12-slim`（日志 `/tmp/f01-web-build.log`）。工单 02 的"真实构建未执行"随之闭合。
  ② **卷落点（F01 核心）**：compose 等价的 `docker run`（`-v <vol>:/var/lib/frontier-agent/web` +
  `SERVER_RUNS_ROOT=/var/lib/frontier-agent/web/runs`）容器内
  `runs_root = /var/lib/frontier-agent/web/runs`、`run_dir_for()` 落该根、`ensure_dirs()` 在卷内建出 `runs/`；
  **连字符与紧凑两种 id 写法解析到同一目录**（`canonical_run_id` 生效）。
  负向对照：不设 `SERVER_RUNS_ROOT` 时容器读到挂载 `.env` 的**宿主 WSL 路径**
  `/home/administrator/.local/share/frontier-agent/web/runs` —— 证明 compose 那行 env 是必需的，不是可选。
  ③ **重建后历史 Run 可读**：卷内 seed 1 条 completed run（`ws/outputs`、`inputs`、`spill`、
  `run/agent/trajectories/react_agent.jsonl`、`summary.json`）→ `docker rm -f` + 同卷重启 →
  轨迹与 `summary.json` **sha256 前后逐字节一致**（`d438abb1…` / `1816881b…`），
  `inspect_trajectory` 仍返回 `partial / valid_lines=3 / corrupt_lines=0`（partial 为用例未写终结标记所致，非缺陷），
  DB 行 `status=completed / run_dir=/var/lib/frontier-agent/web/runs/e0744a42…` 完好，`/healthz` **200**。
  ④ **新发现的致命缺口：compose 未覆盖 `SERVER_DATABASE_URL`**。
  `deploy/docker-compose.yml` 覆盖了 `CORPUS_DSN`，但 `SERVER_DATABASE_URL` 未设；而
  `server/config.py` 的 `env_file=/app/.env`（compose 已挂载 `../.env`），故容器内解析出
  `postgresql+asyncpg://postgres:***@localhost:5432/apodex` —— 容器内 localhost 是容器自身。
  **实测**：按现 compose 环境启动容器 → `ConnectionRefusedError: [Errno 111]` →
  `GET /healthz` = **503 `storage_unavailable`**。即按现配置部署，API 容器**起不到可用状态**。
  两点加重：它默认指向**生产库名 `apodex`**（只是因不可达而未误连）；且这是 fail-closed 暴露，
  若宿主 PG 恰好在容器 localhost 可达，反而会静默连到生产库。
  ⑤ **隔离与清理**：一次性库 `apodex_f01_container`（已 DROP，`pg_database` 仅剩 `apodex`）、
  临时卷 `f01-verify-agent-data`（已删）、两个测试容器（已删）；**业务库全程未触碰**。
- 2026-10-01：**已修 `SERVER_DATABASE_URL` 的容器覆盖（口径经用户确认：比照 `CORPUS_DSN`）**。
  ① **改动**：`deploy/docker-compose.yml` 的 `api.environment` 新增
  `SERVER_DATABASE_URL: ${SERVER_DATABASE_URL_DOCKER:-postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/apodex}`
  （紧邻既有的 `CORPUS_DSN`）；仓库根 `.env` 与 `.env.example` 各增 `SERVER_DATABASE_URL_DOCKER`
  （说明容器内必须用宿主地址、scheme 必须 `+asyncpg`、业务库 `apodex` ≠ 语料库 `postgres`）；
  `deploy/README.md` 新增「数据库连接（业务库 / 语料库）」一节，列出两处 `_DOCKER` 覆盖来源。
  ② **解析验证**：`docker compose --env-file ../.env --profile full config` 现输出
  `SERVER_DATABASE_URL: postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/apodex`
  （修复前该项缺失）；`SERVER_RUNS_ROOT` / `CORPUS_DSN` 不变。
  ③ **端到端（隔离库 `apodex_f01_dbfix`，生产 `apodex` 全程未触碰）**：
  容器内 `-e SERVER_DATABASE_URL=…host.docker.internal:5432/apodex_f01_dbfix` →
  `GET /healthz` **200 `{"status":"ok"}`**，容器内 `get_config().database_url` 与 `runs_root`
  解析正确。**负向对照**：同一镜像改为 `…localhost:5432/…` → `GET /healthz` **503 `storage_unavailable`**，
  确认用例非空（200 不是平凡返回），并复现修复前机理。
  ④ **清理**：容器 `f01-dbfix-api` / `f01-dbfix-neg`、临时卷 `f01-dbfix-data`、一次性库
  `apodex_f01_dbfix` 均已删；`pg_database` 仅剩 `apodex`。
  剩余未完成：无（容器实测三项 + 本缺口修复均已闭环）。
  附观察（未在本轮修，属既有配置、需按实际宿主判定）：`host.docker.internal` 在原生
  Linux Docker 引擎上需 `extra_hosts: host-gateway` 才可解析，现 compose 未声明；Docker Desktop
  （WSL2 / Windows）自带该名，故本机 WSL 不受影响，`CORPUS_DSN` 亦同此前提。
- 2026-10-01：**关闭（用户指示）**。F01 验收项全部闭环：本机迁移 / WSL 迁移 / 孤儿归档 /
  回退演练 / 活动 Run 跨新旧根拒绝 / 冲突非覆盖 / 容器实测（可构建 · 卷落点 · 重建后可读）/
  容器业务库覆盖修复；迁移工具回归 `tests/test_web_f07_retention.py` 30/30。
  上条附观察（`host.docker.internal` 在原生 Linux 引擎需 `extra_hosts`）为既有配置前提
  （`CORPUS_DSN` 同此），不属本工单引入的缺口，另记、不阻塞关闭。`Status → closed`。
