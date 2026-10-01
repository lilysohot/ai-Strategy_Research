# 19：存储与迁移故障缺少就绪门禁

Status: ready-for-human
Priority: P1
Type: task
Requirements: PR-GOV-01

## 问题与验收

完整代码证据、复现边界、修复要求和验收见[报告 F19](../../../docs/plan/web-runtime-trace-repair-report.md#f19存储与迁移故障缺少就绪门禁)。
执行记录和覆盖矩阵见[存储链路复核](../../../docs/plan/web-storage-chain-audit.md)。

- 以隔离合成数据复现，不以真实账户/轨迹作为测试输入。
- 执行报告列明的正常、失败、恢复及兼容性验收。
- 已实现（2026-10-01）；验收与未完成项见下方 Comments，未完成项不得视为已验收。

## Comments

- 2026-09-29：全面存储复核新增，详见报告证据等级；运行代码尚未修改。
- 2026-09-29 证据补正：替身检查不等于真实 DB 断连；healthz 200 仅证明存活，不证明就绪。正常链路先复用原环境，故障按[环境方案](../../../docs/plan/web-storage-validation-environment.md)隔离，T8 验收仍待执行。
- 2026-10-01：**F19 后半（schema 门禁 + 迁移显式步骤）已实现**。
  ① **拆开两个探针**：`/healthz` 只回答"数据库是否应答"（`store.check_db` 由 `SELECT count(*) FROM users`
  改为 `SELECT 1`——表读会让"空库"被报成"不可达"，两者的处置办法不同）；新增 `server/readiness.py`，
  `/readyz` 在应答之上再要求 **schema 版本匹配** 与 **运行数据根可写**，未就绪返回 503
  `{"status":"not_ready","reasons":[...]}`。
  ② **状态判定**（`server/readiness.py`，只读、从不迁移/修复）：head 由迁移脚本的 `revision`/`down_revision`
  链推出（不 import，避免执行迁移代码）；已打戳则必须等于 head（落后=`schema_behind`、超前或未知
  revision=`schema_ahead`、多 head=`schema_ambiguous`）；未打戳（`create_all` 路径）则要求
  **所有 ORM 表都在**（缺表=`schema_missing`）；数据根用**真实写探针**（`os.access` 在 Windows/只读挂载上会骗人），
  探针文件随即删除。
  ③ **启动失败阻断**：`lifespan` 跑同一门禁，未就绪且非 `SERVER_DEBUG` 时抛
  `StorageNotReadyError` 拒绝服务（此前 `init_db`/reconcile 的异常被 `contextlib.suppress` 吞掉后照常接单）；
  debug 下仅告警，且此时**跳过** 孤儿 reconcile（库里状态不可信时不改写 run 行）。
  ④ **迁移是独立步骤**：新增 `deploy/entrypoint.web.sh`（`alembic upgrade head` → `exec uvicorn`，`set -e` 失败阻断），
  `Dockerfile.web` 的 `CMD` 改指它；`deploy/README.md` 新增「数据库迁移与就绪门禁」一节，写明两探针分工、
  `reasons` 取值、启动拒绝语义与**绝不 downgrade** 的回退规则。
  **证据**：`tests/test_web_f19_schema_gate.py` **15/15**（空库/落后/到 head/未打戳但有表/未知 revision 报超前/
  双 head/不可写根/探针不留残留/启动在 prod 抛错且 dev 降级为告警/断连时不给"去迁移"的错误建议/两个探针确实不同/
  迁移后 200），负向对照（去掉 schema 分支、去掉可写检查、去掉 raise）**6 条失败**，确认判据非空。
  **真实容器实测**（`frontier-agent-web:f19`，1.64 GB，`docker build` exit 0）：空 SQLite 库启动 →
  日志显示 `0001→0002→0003→0004` 依次迁移、`alembic current` 在容器内为 `0004_control_records (head)`、
  `/healthz` 与 `/readyz` 均 **200**；**负向对照**：数据库不可达 → 入口脚本在 alembic 处失败、容器 `exit 1`、
  uvicorn 从未启动；schema 停在 `0003` 且绕过入口直接起 uvicorn → `StorageNotReadyError: ... schema_behind
  ({'expected_head': '0004_control_records', 'current_revision': '0003_turn_seq_unique'})`、`exit 3`；
  debug 逃生舱（`SERVER_DEBUG=1`）→ 告警后启动成功，而 `/readyz` 仍 **503 `schema_behind`**、`/healthz` **200**；
  数据库断连（不可达 DSN）→ `/healthz` **503 `storage_unavailable`**、`/readyz` **503 `database_unavailable`**
  （即 T8 的完成标准"停库后 503、恢复后 200"在容器内成立）。容器与临时数据已清理，业务库全程未触碰。
  **只读核对**：业务库 `apodex` 现为 `0002_run_usage`，head 为 `0004_control_records` → 门禁判定
  `schema_behind`；即**正式部署前必须先迁移（0003/0004 均未应用）**，本机 debug 模式不受影响。
  隔离审计契约（F19 首半）**24/24** 仍通过；`ruff`/`pyright` 在 `server/` 仅剩 1 处既有类型错误。
  **未完成**：磁盘满注入、真实只读挂载（本轮用"父路径是文件"等价复现）、compose 未接 `service_healthy`
  healthcheck、旧版镜像回退演练只写在文档而未实测。
- 2026-10-01：**剩余三项注入在 WSL/容器完成，并发现且修复一处探针缺陷**（批次
  [e1-wsl-batch-registry.json](../audit/e1-wsl-batch-registry.json)）：
  ① **真实只读挂载**（`frontier-agent-web:f19` + `-v vol:/data/runs:ro`）：非 debug 启动 →
  `StorageNotReadyError: data_root_unwritable`、exit 3、uvicorn 未起；debug 下 `/healthz` 200 而
  `/readyz` 503 `data_root_unwritable`。② **磁盘满注入**（tmpfs size=64k 填满）：**发现真缺陷**——
  `probe_data_root` 写 **0 字节**探针文件，满 tmpfs 上 0 字节创建仍成功（数据页耗尽而非 inode），
  `/readyz` 误报 200 ready；修复为写真实字节 `b"readyz-probe"`（`server/readiness.py`），复测翻转
  为 503 `data_root_unwritable`、`/healthz` 仍 200；新增回归
  `test_data_root_probe_writes_real_bytes`（文件 16/16）。③ **compose `/readyz` healthcheck + 消费方接线**（2026-10-01 用户确认后）：
  `deploy/docker-compose.yml` api 增加 `/readyz` healthcheck（为何不用 /healthz 已注释），并让 `caddy`
  增加 `depends_on: api: {condition: service_healthy}`——存储未就绪时不接流量；`docker compose config`
  解析确认该依赖，同款 healthcheck 命令在镜像内实测 `health=healthy`。另：真部署门禁
  （业务库 0002 → `/readyz` 503 `schema_behind`）已在 WSL 原样复现。**仍未完成**：旧版镜像
  回退演练实测（文档规则已就绪）；修复后镜像未重建（复测用 bind-mount 补丁文件，发布前需
  按常规构建一次）。
- 2026-10-01（下午）：**上条「仍未完成」三项全部闭环**。
  ① **镜像重建**：按常规构建 `frontier-agent-web:head`（`036bbd787437`，含 `84258f3` 探针修复与 `38d73bc`
  展示投影 `external_id`）；镜像内断言 `probe writes real bytes: True`、`control_to_dict has external_id: True`。
  ② **旧版镜像回退演练实测**（隔离库 `apodex_f19_drill`）：新镜像 entrypoint 迁移空库→`0004`、`/healthz` 200、
  `/readyz {"status":"ok"}`；上一镜像 `frontier-agent-web:f19` 对同库启动迁移**幂等**（版本不变）；
  将 `alembic_version` 置 `zz_future`（schema 超前）后——上一镜像 entrypoint **exit 255**（`Can't locate
  revision identified by 'zz_future'`）、新镜像跳过 entrypoint 直起 uvicorn **exit 3**
  `StorageNotReadyError: schema_ahead ({expected_head: 0004_control_records, current_revision: zz_future})`。
  见 `audit/f19-rollback-drill.json`。
  ③ **整栈 compose 就绪门禁实测**（隔离项目 `e1wsl`，端口 8125/8199/8444 避让）：**反例**——
  `SERVER_DATABASE_URL_DOCKER` 指向不存在的库 → entrypoint 在 alembic 处失败、compose 报
  `dependency failed to start: container e1wsl-api is unhealthy`、`caddy` 容器 `State=created` **未启动**、
  站点不可达；**正例**——空库 `apodex_f19_stack` → entrypoint 迁移到 `0004`、api `healthy`、caddy
  `Starting→Started`、`https://localhost:8444/`（--resolve）**200** 且返回 `<title>投研 Agent 平台</title>`。
  业务库 `apodex` 全程 `0002_run_usage`（每轮前后核对），隔离资源已 `compose down` 清理。见
  `audit/f19-stack-gating.json`。
  **仍未完成（非 F19 范围）**：业务库正式迁移——**已于 2026-10-01 晚完成**（`apodex` → `0004_control_records`，
  0003 upgrade + 0004 stamp 因 create_all 已建表，备份 `~/backups/apodex-20261001-161402.sql`；live API `/readyz` 翻绿 200）。
