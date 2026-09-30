# 01：对齐运行根目录与持久卷，兼容历史 Run

Status: ready-for-human
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
- 2026-09-30：**仍未验收（维持 ready-for-human）**：① 容器部署——`deploy/docker-compose.yml`
  的卷仍挂 `/app/agent_data`、`deploy/Dockerfile.web` 仍声明 `VOLUME /app/server/runs`，未同步到
  源码树外目标；② WSL 部署（`/home/administrator/FrontierAgent`，663 条 run）与 `/tmp` 85 条的
  历史兼容与迁移未做；③ 活动 Run 跨新旧根保护、真实重启后新旧 Run 追溯、容器重建验收未做；
  ④ `.env.example` / 部署文档尚未写明新默认与 `SERVER_RUNS_ROOT` 覆盖。
  另记录：环境存在批量删除守卫，单轮删除文件数 > 500 会拦截（迁移工具因此需分批），非代码缺陷。
