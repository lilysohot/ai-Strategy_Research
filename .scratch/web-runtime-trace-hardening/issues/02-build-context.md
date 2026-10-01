# 02：排除 Web 运行数据进入构建上下文和镜像

Status: ready-for-human
Priority: P1
Type: task
Requirements: PR-GOV-01, PR-GOV-06

## 问题与范围

见[报告 F02](../../../docs/plan/web-runtime-trace-repair-report.md#f02运行数据进入构建上下文及镜像的风险)。
核验根/专属 Docker ignore、Web 构建路径及必须保留的源码。Git ignore 不能代替 Docker ignore。

## 修复前提与验收

- 临时构建目录用无敏感 sentinel 复现，不复制真实用户数据作为样例。
- build/runtime 镜像及相关层均不含 sentinel，源码和必要 fixture 正常打包。
- 新增构建回归保护；若发现历史受影响镜像，另行记录范围并制定处置，不擅自删发布镜像。

## Comments

- 2026-09-29：复制链和 ignore 缺口确认，尚未构建测试镜像；没有已泄露证据。
- 2026-09-30：**修复前复现（合成 sentinel，无真实数据）**。临时构建目录（非真实仓库）放置
  唯一 sentinel 模拟 `server/runs/<test-id>/run/agent/trajectories/react_agent.jsonl` 与
  `uploads/sentinel-upload.csv`，用与 `deploy/Dockerfile.web` 相同的 stage 结构
  （`COPY server ./server` → 下一 stage 复制 `/build`）构建：导出内容命中 sentinel 1 处；
  整 context 探针（`COPY . /ctx`）命中 6 处（server/runs、uploads、data、web/dist、
  web/node_modules、.scratch）。**缺口确认为真实可触发，非理论风险。**
- 2026-09-30：**修复内容**（根 [.dockerignore](../../../.dockerignore)，唯一生效的 ignore 入口）：
  排除 `server/runs/`、`uploads/`、`data/`、`server/*.db(+wal/shm)`；排除前端
  `web/node_modules|dist|dist-ssr|coverage|*.local|.env|.env.*|npm-debug.log*|.vscode|.idea`
  （附 `!web/.env.example`）；排除本地大目录 `.kilo/ .scratch/ .e5runs*/ .playwright-cli/
  .codebuddy/ .trae/ .pytest_cache/ .ruff_cache/`。
- 2026-09-30：**修复后证据（真实仓库 context）**。`COPY . /ctx` 探针：context
  **33.18 MB / 1110 文件**；`server\runs`、`uploads`、`data`、`.kilo`、`.scratch`、
  `web\node_modules`、`web\dist`、`.e5runs`、`.venv`、`.git`、`server\dev.db` **全部 absent**；
  `server/app.py`、`pyproject.toml`、`uv.lock`、`web/package.json`、`config/providers.yaml`、
  `frontier_agent/core/runtime/loop/agent_loop.py`、`docker/entrypoint.sh` **全部 present**。
  `COPY server ./server` 探针：导出 30 个 `.py`（含 `alembic/`、`routes/`），**`server/runs`
  与 `uploads` 均不存在，`.pyc` 0 个** → 排除生效且构建输入未被误伤。
- 2026-09-30：**回归保护** `tests/test_build_context_ignore.py`，**40 通过**；负向对照：
  临时注释 `server/runs/` 后 4 条断言失败（非总通过的空测试）。合成 sentinel 与临时目录已清理。
- 2026-09-30：**附带发现并一并修复**（均非用户数据，单独记录以免混入 F02 的敏感数据结论）：
  ① `__pycache__` / `*.pyc` 在 `.dockerignore` 中只匹配 context 根级，嵌套字节码仍被复制，
  已加 `**/__pycache__/`、`**/*.pyc`；② `web/.dockerignore` **惰性**——
  `deploy/Dockerfile.frontend` 以仓库根为 context，Docker 只读 `<context-root>/.dockerignore`，
  该文件从不生效，其规则已镜像到根 ignore 并由测试守卫。
- 2026-09-30：**仍未验收（故维持 ready-for-human）**：本机 registry 不可达
  （`auth.docker.io` 连接超时，无法拉取 `python:3.12-slim`），**真实 `deploy/Dockerfile.web`
  的完整镜像构建未执行**；上述证据用 `FROM scratch` 探针测量「哪些文件进入镜像文件系统」，
  未覆盖 `uv sync` 及 runtime stage 的真实层。须在可访问 registry 的环境补跑真实构建并核对
  镜像层。历史已发布镜像是否含数据仍未调查（本轮不擅自处置镜像）。
- 2026-10-01：**真实构建已补跑，镜像层核对通过（上条的验收前提闭合）**。
  此前记录的 registry 阻断为瞬时故障；`docker build -f deploy/Dockerfile.web -t frontier-agent-web:verify .`
  **exit 0**（1.64 GB / 18 层，runtime stage = `python:3.12-slim`，`uv sync --frozen --extra sandbox
  --extra document-readers --extra eval --extra dev --group web` 全部完成）。
  在**真实构建产物**内核对：`server/runs`、`uploads`、`data`、`.git`、`.venv`、`.scratch`、
  `web/node_modules`、`web/dist` **全部 absent**；`*.pyc` **0**；`server/*.db` 不存在；
  `server/app.py`、`pyproject.toml`、`uv.lock`、`config/providers.yaml`、
  `frontier_agent/core/runtime/loop/agent_loop.py` **全部 present**。
  即此前用 `FROM scratch` 探针测得的结论在真实镜像上复现一致，根 `.dockerignore` 在完整构建链路中同样生效。
  历史已发布镜像是否含数据仍未调查（本轮不擅自处置镜像）。
- 2026-10-01（晚）：**历史已发布镜像数据调查完成（上条遗留项闭合）**，证据
  [audit/f02-historical-image-data.json](../audit/f02-historical-image-data.json)。
  **结论：历史受影响镜像集合为空，无需处置。** ① 修复（2026-09-30 `.dockerignore`）之前从未成功构建过
  web 镜像（Windows 侧 registry 阻断，本工单 2026-09-30 注释记录「完整镜像构建未执行」），本机现存 3 个
  web 镜像（verify/f19/head）全部构建于 2026-10-01 即修复后，无 dangling 镜像；② 对 3 个现存镜像逐层核对
  （docker history COPY/ADD 层 + Config.Env + 容器内逐路径存在性）：COPY 层仅源码 13.4–13.6MB + venv
  1.11GB，`server/runs`/`uploads`/`data`/`.git`/`.env`/`.scratch`/`web/node_modules`/`web/dist`/`*.db`/
  `/data` 全部 absent，`*.pyc`=0，`providers.yaml` 唯一 api_key 命中为 `${OPENAI_API_KEY}` 占位符，
  config env 无密钥。范围外记录：`docker-corpus-db`（语料库 PG 镜像，数据在卷属设计使然）、
  `more-*`（其它项目）、其余为上游官方镜像。处置建议：无需删除；`:verify`/`:f19` 验证 tag 如需释放
  磁盘可另行确认后清理。
