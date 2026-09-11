# 投研 Agent 平台 — 部署手册

本目录是平台的上线配置：Caddy 作为唯一入口，同时承担**前端静态托管**与
**API 反向代理**，后者以关闭缓冲的方式转发 SSE 事件流。

## 架构

```text
浏览器 ──HTTPS──▶ Caddy (80/443)
                    ├─ /api/*  ──▶ api:8000   (FastAPI + Agent，内部端口，不对外暴露)
                    └─ /*      ──▶ /srv/web   (Vite 构建产物，SPA fallback)
```

三个服务由 `docker-compose.yml` 编排：

| 服务 | 作用 | 是否长驻 |
| --- | --- | --- |
| `frontend` | 构建 `web/dist` 并发布到 `web_dist` 卷 | 否，构建完即退出 |
| `caddy` | 静态托管 + 流式反代 + 自动 HTTPS | 是 |
| `api` | FastAPI 与 Agent 运行时 | 是 |

`caddy` 通过 `depends_on.condition: service_completed_successfully` 等待
`frontend` 完成，因此站点不会在空目录状态下启动。

## 快速开始

```bash
# 1. 准备环境变量（仓库根目录）
cp .env.example .env          # 至少配置 OPENAI_API_KEY / 模型相关变量

# 2. 全栈拉起（--build 会构建前端产物与 API 镜像）
cd deploy
docker compose --env-file ../.env --profile full up -d --build

# 3. 查看状态与日志
docker compose --profile full ps
docker compose --profile full logs -f caddy
docker compose --profile full logs -f api
```

默认访问地址：

- **HTTPS**：`https://localhost:8443`（自签证书，浏览器需信任一次）
- **HTTP**：`http://localhost:8080`（Caddy 默认会将 HTTP 重定向到 HTTPS，仅用于健康检查）

> 所有服务都在 `full` profile 下，日常 `docker compose up` 不会误拉起整套栈。

## 端口与域名

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SITE_ADDRESS` | `localhost` | Caddy 站点地址。设为真实域名即自动申请并续期公开证书 |
| `CADDY_HTTP_PORT` | `8080` | 宿主机 HTTP 映射端口 |
| `CADDY_HTTPS_PORT` | `8443` | 宿主机 HTTPS 映射端口 |
| `API_DEBUG_PORT` | `8000` | API 调试端口；生产环境建议不映射 |
| `CONTAINER_PREFIX` | `frontier-research` | 容器名前缀 |

**生产部署**（有域名、80/443 可用）：

```bash
export SITE_ADDRESS=agent.example.com
export CADDY_HTTP_PORT=80
export CADDY_HTTPS_PORT=443
docker compose --env-file ../.env --profile full up -d
```

Caddy 会自动完成 ACME 挑战与证书续期，无需额外配置。

## SSE 流式传输

Agent 的每一轮输出都以 SSE 推送到浏览器，因此**代理层必须关闭响应缓冲**，
否则界面会一直转圈，直到整轮结束才一次性显示。相关配置位于 `Caddyfile`：

```caddyfile
handle /api/* {
    reverse_proxy api:8000 {
        flush_interval -1                 # 不缓冲，边产出边下发
        transport http {
            read_timeout 7200s            # 长 run 在 token 间隙合法空闲
            write_timeout 7200s
        }
    }
    header X-Accel-Buffering "no"         # 兼容仍按 nginx 语义处理的中间层
}
```

排查 SSE 问题时先确认这几行仍在——它们是本文件中最关键的配置。

## 静态资源缓存

- `/assets/*`（Vite 带 hash 的产物）：`public, max-age=31536000, immutable`
- 其余路径：`no-cache`，保证新版本发布后能立即生效
- SPA 路由：`try_files {path} /index.html`，使客户端路由与刷新都不会 404

## 数据持久化

| 卷 | 内容 |
| --- | --- |
| `web_dist` | 前端构建产物（由 `frontend` 写入，Caddy 只读挂载） |
| `agent_data` | Agent 运行时数据 |
| `caddy_data` | TLS 证书与 ACME 状态（**不要删除**，否则会重复申请证书） |
| `caddy_config` | Caddy 运行时配置 |

宿主目录挂载：`../config`（只读）、`../.env`（只读）、`../data`。

## 安全说明

### 密钥（`SERVER_MASTER_KEY` / `SERVER_JWT_SECRET`）

两者**必须分别设置**，且都不能是仓库里的占位值。启动时会校验，不合规直接拒绝启动：

- `SERVER_MASTER_KEY`：用于 Fernet 加密用户保存的 LLM `api_key`。
- `SERVER_JWT_SECRET`：用于签发登录 JWT。

分开的理由：共用一个值时，一次泄露会同时交出「加密的 LLM 凭证」和「伪造登录态的能力」。

```bash
# 生成（两条命令各生成一次，不要复用同一个值）
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

| 操作 | 后果 |
| --- | --- |
| 轮换 `SERVER_JWT_SECRET` | 所有人被强制重新登录（旧 token 立即失效） |
| 轮换 `SERVER_MASTER_KEY` | 已保存的 LLM `api_key` **全部无法解密**，用户必须重新录入 |

本地开发可用 `SERVER_DEBUG=true` 把该校验降级为警告（允许使用默认 `SERVER_MASTER_KEY`）。
**部署时务必删除 `SERVER_DEBUG`**，否则服务会以仓库里的公开占位密钥运行。

- 平台会处理用户的 API Key，**不应以明文 HTTP 暴露在公网**。`SITE_ADDRESS`
  默认为 `localhost`（自签证书）；部署到公网请使用真实域名走自动 HTTPS。
- API 容器启用了 `SYS_PTRACE` 与宽松的 seccomp/apparmor，这是 bubblewrap
  沙箱创建用户命名空间所必需的，属于有意配置，详见 `Dockerfile.web`。
- 数据库与 trace 文件落在宿主的 `../data`，备份时一并纳入。

## 离线/无 Docker 环境

本目录的镜像构建与编排需要 Docker。若环境没有 Docker daemon，可直接在宿主
运行 API（功能等价，但**不具备 OS 级沙箱隔离**）：

```bash
uv run uvicorn server.app:app --host 0.0.0.0 --port 8000
```

前端开发态：

```bash
cd web && npm install && npm run dev     # http://localhost:5173，/api 已配置代理
```

生产产物本地预览：`npm run build` 后由 Caddy 托管（即本目录的编排）。
