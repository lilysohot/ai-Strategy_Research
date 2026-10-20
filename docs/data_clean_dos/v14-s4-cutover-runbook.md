# V14 S4 生产切换与回滚 Runbook

状态：`PLAN_READY_NOT_EXECUTED`  
生产基线：[v14-s4-production-baseline.json](v14-s4-production-baseline.json)  
冻结清单：[v14-s4-production-freeze.json](v14-s4-production-freeze.json)  
校验清单：[v14-s4-production-freeze.sha256](v14-s4-production-freeze.sha256)

## 1. 切换结论

本次采用**代码来源正规化、数据面不变**的切换方式。当前生产进程所使用的语料可执行代码与
`corpus-v14-s4-rc1` 相同；RC1 相对进程启动时的推定提交只增加冻结文档。因此首次切换不执行
DDL、不重建语料、不修改 `corpus_publications`，`CORPUS_TARGET_DB` 始终保持 `postgres`。

评测库 `v14_s2_quote_corpus` 含 12 份 holdout 来源，与生产 8 个活动来源交集为 0。它只能作为
评测证据，禁止成为生产指针，禁止把其中来源随 RC1 发布到生产。

## 2. 已冻结生产基线

| 项目 | 当前值 |
|---|---|
| 数据库 | `postgres.corpus`，PostgreSQL 18.6 |
| 活动来源 | 8 |
| 来源／构建 | 8 sources / 14 builds |
| 原文单元／检索块 | 7,128 units / 1,214 chunks |
| 活动发布指纹 | `5475ac32885611fde9b34adefd44f58ee53b01577646e8b959f56fb306b25ed1` |
| job | 42 succeeded / 0 running |
| 旧链表 | documents、blocks、claims、runs 等均为 0 |
| 保留表 | `public.docs=3`、`public.chinese_docs=3` |
| 当前服务 | WSL 本地 uvicorn，端口 8000；`healthz=200`、`readyz=200` |
| RC1 | tag `corpus-v14-s4-rc1` → `58260fbc60ad65129bbb98a47c07defc0850622f` |
| 回滚代码 | tag `corpus-prod-pre-rc1` → `d06ad598d64ced3052da383a12f3ad5101491a63` |
| 新备份 | `postgres.dump`，SHA-256 `25736bd…84efcf`；隔离恢复计数一致 |

## 3. 切换前硬门

全部满足才能进入维护窗口：

1. 从 RC1 tag 建立新的干净 checkout；不得复用当前含未提交改动的主工作区。
2. `git rev-parse corpus-v14-s4-rc1` 必须为 `58260fbc60ad65129bbb98a47c07defc0850622f`；候选清单
   SHA-256 必须为 `5951a6e9328d4ce889f3cbf351c0f3159b5c4f5bce23f71c2332e0a5d8eba823`。
3. 重新执行只读快照。数据库必须为 `postgres`、9 张 corpus 表、8 个活动发布、0 个 running job；
   活动发布指纹必须仍为冻结值。任何漂移都停止切换并重新评审。
4. 当前 8000 实例的 `/healthz`、`/readyz` 均为 200。
5. 新备份文件哈希匹配，`restore-verification.json` 为 `matches_production_baseline=true`。
6. 明确维护窗口和负责回滚的人；由于本机没有反向代理，8000 端口替换会产生短暂停机。

建议的干净 checkout 位置为 `/home/administrator/FrontierAgent-rc1`。依赖使用 `uv sync --frozen`
并按仓库说明安装 `sandbox`、`document-readers` 与 Web group；密钥继续来自现有运行环境，不写入
checkout 或冻结工件。

## 4. 预启动与只读 canary

1. 在干净 checkout 上保持 `CORPUS_TARGET_DB=postgres`，先启动 `127.0.0.1:8001` canary。
2. 校验 `/healthz`、`/readyz` 均为 200。
3. 对生产 8 个活动 build 逐一执行只读 `corpus status --build <build_id>`；必须全部仍为 active，
   不得产生 job 或 publication 变化。
4. 使用既有已批准开发材料的只读检索／取回样本，每个 company、industry、macro 至少 2 条；
   不使用 12 份 holdout，不调用回答模型或 Judge。必需来源和引文锚点须 100% 送达。
5. 连续观察 15 分钟。数据库表计数、活动发布指纹和 WAL 之外的业务状态必须保持不变；WAL 变化
   不能单独判失败，但本次 canary 不应产生 corpus 表写入。

任一硬门失败，停止 canary，不进入端口 8000 切换。

## 5. 正式切换

本机无反向代理，采用短维护窗口进程替换：

1. 停止接收新任务并等待当前请求结束，记录旧 uvicorn 父子进程与开始时间。
2. 向旧 8000 进程发送正常终止信号，最多等待 30 秒；不得先强杀。
3. 从干净 RC1 checkout 以现有命令启动端口 8000：
   `uv run --group web uvicorn server.app:app --host 0.0.0.0 --port 8000`。
4. 60 秒内完成 `/healthz`、`/readyz` 和数据库身份检查；随后执行 6 条只读 canary。
5. 记录新 PID、checkout、tag commit、启动时间和生产快照；开始两小时强化监控。

整个步骤保持 `postgres.corpus` 的 8 个 active build 不变。任何涉及 `v14_s2_quote_corpus`、DDL、
publish 或 rebuild 的动作都不属于本次切换。

## 6. 回滚触发与步骤

以下任一项立即回滚：

- health/readiness 连续两次非 200，间隔 30 秒。
- 数据库不是 `postgres`，活动发布数量不是 8，或活动发布指纹变化。
- 任一 corpus authority、哈希、locator、跨 build 校验错误。
- `corpus_search`／`corpus_fetch` 连续 3 次错误，或 15 分钟错误率超过 2% 且样本数不少于 50。
- 6 条必需 canary 中任一来源或引文锚点未送达。
- 监控方案中的红线持续达到规定窗口。

回滚顺序：

1. 停止接收新任务，正常终止 RC1 进程。
2. 从 `corpus-prod-pre-rc1` 的干净 checkout 重新启动同一 8000 命令；数据库环境仍指向
   `postgres`。
3. 校验 `/healthz`、`/readyz`、8 个活动发布和冻结指纹。
4. 因数据面未变，常规回滚不得恢复数据库。只有确认发生非预期数据库写入或损坏时，才进入灾难
   恢复：先停写，再用 `postgres.dump` 在隔离库恢复并对账，最后按单独批准替换生产。
5. 保存失败窗口日志、错误样本和新旧进程身份，不改写冻结结果。

## 7. 数据重建的后续独立步骤

如需让生产 8 份材料获得 S0–S2 的新解析结果，应另开数据面变更：在 `postgres.corpus` 内生成新的
不可变 build，逐来源核验字符、结构、引用和检索，再逐个翻转 `active_build_id`。每次只切一个来源，
上一来源稳定后才继续；其回滚是把该 source 的 publication 指针恢复到本基线记录的 build。
这不属于 RC1 首次代码来源正规化。
