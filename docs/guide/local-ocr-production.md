# 本地 OCR 生产接入

2026-10-31 已在当前 WSL 业务环境正式启用。模型和方向判定沿用旁路冻结版本，
生产服务为 `rapidocr-prod-dd340f6c8a6592ff`。本次没有批量重建或重新发布历史研报。

## 业务入口

1. **研报构建**：`plugins.corpus.preparation.readers.read_document` 在原生 PDF
   解析后处理图片页、图片区域和乱码缺口。保留原生单元，新增 OCR 文字、原页坐标、
   模型版本、结果 artifact ID；结构节点 `text_origin=ocr`，单元 element 为
   `local_ocr:line:<序号>`。版本进入 extractor revision，使旧解析缓存失效。
2. **Agent 在线读取**：`read_file` 的 `auto` 保持概览，提示未读图片；
   `pdf_mode=image, pages=N` 调用同一生产服务。单次最多一页，超出页数明确提示续读。
   混合页保留原生文字层，并另列 OCR 文字。原始 PDF + 明确页码直接提交，
   不依赖实际 bwrap 沙箱中缺失的 `pdfseparate/pdfimages`。
3. **取证结果**：`corpus_fetch` 的完整、紧凑、分页结果与 Web 文档 API 对含 OCR
   的正文标记 `ocr_unverified`。文字可用于检索和辅助读取；不能据此宣称已人工逐字核对。

OCR 提取文字不代表重建表格或理解曲线。原有图片/表格缺口不自动清除，继续经过
`build → check → publish → 索引更新/激活`。方向未知保留缺口；服务超时或失败使
构建失败，不生成可复用的成功检查点。在线读取保留原生文字并明确返回不完整状态。
现有生产索引、发布代次和原文件没有被这次组件启用改写。

## 配置和后续新增研报

当前 `.env` 和运行中的 Web API 已设置以下配置（密钥不写入文档）：

```dotenv
READDOC_OCR_URL=http://127.0.0.1:8780
READDOC_OCR_KEY=<由部署生成的 Bearer 密钥>
READDOC_LOCAL_OCR_RELEASE=rapidocr-prod-dd340f6c8a6592ff
CORPUS_LOCAL_OCR_ENABLED=1
CORPUS_LOCAL_OCR_RELEASE=rapidocr-prod-dd340f6c8a6592ff
```

API 新建的任务继承这些配置。独立语料 CLI 必须显式加载业务环境；继续使用现有
正式清单和准入流程，例如：

新增来源的授权登记使用 `corpus.cli admit`；用户接受图片/表格覆盖不完整时使用
`corpus.cli text-publication`。这两个入口不会自动发布或清除原始缺口。
完整 JSON 格式、命令顺序和增量索引范围见
[新增研报固定命令流程](../corpus-ingestion-operations.md#新增研报的固定命令流程2026-10-31含-ocr)。

```bash
uv run --env-file .env python -m plugins.corpus.cli plan --manifest <新增清单.json>
uv run --env-file .env python -m plugins.corpus.cli build --manifest <新增清单.json>
uv run --env-file .env python -m plugins.corpus.cli check --build <build_id>
```

数据库 DSN/目标库沿用正式发布操作规程，按需传 `--dsn`；不得为了跳过缺口而改目标
或自行签署人工复核。通过已有门禁后再按现有程序 publish、更新索引与激活。
未加载业务环境的通用 CLI、测试和其他部署默认不启用 OCR。此接入没有新增自动监控
上传目录的调度器，新增研报仍由既有业务触发构建。

## 部署和运行

代码位于 `plugins/local_ocr/`，镜像构建入口是：

```bash
uv run python tools/local_ocr_release.py build
uv run python tools/local_ocr_release.py start
```

构建要求本机已有冻结基础镜像
`sha256:141ee6ffbc6d0ec0c025f9deccbf93ae832f6721ef90018de93312b6dfc36c1b`。
构建会校验冻结模型配置、正文处理和方向判定代码哈希；服务代码另生成生产版本。
`start` 用于尚不存在同名容器的首次启动，不自动删除或替换已有容器。

当前运行镜像：
`sha256:85671e83e43b537dbfc543bfa903f0441ec9fb8a4d68a6e236efa84df8443ddc`。
容器 `frontier-local-ocr`，端口仅绑定宿主回环地址；只读根文件系统、非 root 用户、
2 CPU、4 GiB、单请求执行、单页 90 秒。HTTP 客户端预算 100 秒，整份研报构建预算
600 秒（页间检查）。忙时返回 429，由调用方明确重试；没有后台持久队列。

结果与原始输入保存在 `data/local-ocr-production/results/<artifact_id>/`。
结果键绑定服务版本、PDF SHA-256 和页码；成功/未知/空结果可复用，超时/错误可重试。
`worker.log` 和 `response.json` 提供排障信息；目录含研报正文，按业务数据权限和备份
策略管理。密钥在 `data/local-ocr-production/token`，不得提交。

```bash
curl --fail http://127.0.0.1:8780/healthz
docker inspect frontier-local-ocr
```

`/healthz` 只确认服务进程和版本；模型执行以真实 PDF canary 为准。
本次检查：3 页 49/49 冻结文字核对项匹配；另 1 页方向未知且未误报成功；
实际 bwrap 读取与服务全文一致；正式读取器样本保留 3 个原生单元，补充 537 个 OCR
单元并保留原图片缺口。原始核验数据位于 `data/local-ocr-production/canary/`。
相关回归 218 项通过；preflight、两阶段 import smoke、符号检查、针对性 Ruff/Pyright
均通过。启用后正式语料检索与原文回读 smoke 通过，API healthz/readyz 均为 200。
不含密钥的版本、源码哈希与验收摘要见 `config/ocr-production-release.json`。

## 本机启用记录与回滚

`data/local-ocr-production/runtime-activate.json` 和 `post-activation.json` 保存本机
进程与健康检查记录。启用前确认没有 queued/running 任务，并备份了原 `.env`、
进程环境与五项 OCR 设置，目录 `data/local-ocr-production/activation-backup/`，
备份权限 0600。当前本机回滚命令：

```bash
uv run python -m data.local-ocr-production.activate rollback
```

这是本机留存的部署脚本，依赖历史本机运行管理工具；仅恢复五项 OCR 设置并在无
运行中任务时重启 API，不回退语料数据库或删除 OCR 结果。新环境应使用自身部署系统
管理上述五项配置和 API 进程。紧急停用语料 OCR 可设 `CORPUS_LOCAL_OCR_ENABLED=0`，
在线读取同时恢复原 `READDOC_OCR_URL/KEY` 并清空本地版本设置，再重启服务进程。

## 上云边界

本次启用的是当前本机生产服务，没有创建云资源。上云时需要分发完整模型镜像、
持久结果卷与密钥，将服务地址改为云内可达地址，并在真实云沙箱中复跑同一 canary。
容器网络内的 `127.0.0.1` 不等于宿主回环地址；不能原样复制地址后宣称完成迁移。

历史旁路版本与证据保持冻结。生产读取器接线已发生变化，旧旁路命令可能因其源文件
哈希锁拒绝运行；不得为了绕过校验改写旧证据，应另建对应的新旁路版本。
