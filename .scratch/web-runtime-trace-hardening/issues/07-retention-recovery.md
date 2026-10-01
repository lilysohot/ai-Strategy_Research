# 07：建立业务库与运行文件联合恢复及保留策略

Status: closed
Priority: P1
Type: task
Requirements: PR-GOV-05, PR-BIZ-06

## 问题与范围

见[报告 F07](../../../docs/plan/web-runtime-trace-repair-report.md#f07备份保留删除与恢复闭环缺少证据)。
归并既有加固 T5/T6 的运维工作，不新建平行备份体系。现网备份和保留配置须先核验。

## 修复前提与验收

- 盘点实际数据库、文件卷、密钥和已有备份；先给 01 提供迁移前备份/恢复能力。
- 明确不同数据保留期、恢复目标、活动 Run 保护和删除语义；有 dry-run 清单。
- 在独立恢复目标联合恢复并核对 Run/轨迹/产物引用，覆盖缺文件和密钥不可用；逻辑恢复可用同 PG 实例的独立库，实例/物理卷故障才需独立实例。
- 最终联合验收在 01/03/06 之后进行；不影响其他用户或未到期/正在运行的数据。
- 任务只有提供恢复演练证据才可完成，不因文档写了命令就宣称已有备份闭环。

## Comments

- 2026-09-29：仓库计划仍列待办，实际运维备份未审查；先调查再实施。
- 2026-09-29 环境补正：按[环境方案](../../../docs/plan/web-storage-validation-environment.md)选恢复目标；核验恢复所需密钥，保留切换后新数据的回退路径，不能只改回根目录变量。
- 2026-09-30：**真实恢复演练（E2 范围，已执行并已清理）**。只读业务库 + 同实例独立库
  `apodex_f07_restore`；`pg_dump -Fc --no-owner --no-acl`（225,999 B）→ `pg_restore`：
  **7 张表行数逐一一致**（users 28 / sessions 141 / runs 1271 / turns 1093 / artifacts 296 /
  user_llm_configs 164 / audit_log 1978）。**但恢复库只建成 4 个外键，源库 9 个**——
  5 个 `ADD CONSTRAINT` 因孤儿行失败（`audit_log_user_id_fkey`、`runs_session_id_fkey`、
  `runs_user_id_fkey`、`sessions_user_id_fkey`、`turns_run_id_fkey`）。
  **结论：备份存在 ≠ 可恢复**——数据能回来，完整性回不来。演练后独立库已 DROP、dump 未落宿主。
- 2026-09-30：**孤儿已量化并可复跑**（T6 第 4 步）。`scripts/run_retention.py check` 实测：
  runs→缺失 session **517**、runs→缺失 user 17、sessions→缺失 user 18、turns→缺失 run 11、
  audit_log→缺失 user **29**、artifacts→缺失 run 0。前两类与 T6 原记录吻合。
  注意 `turns.run_id IS NULL` 的 45 条是**合法**的（并非每个 turn 都归属 run），不计入孤儿。
- 2026-09-30：**文件侧工具交付**（为 F01 迁移前的盘点与迁移后校验服务）。
  [scripts/run_retention.py](../../../scripts/run_retention.py) 四个子命令：
  `manifest`（逐 run 的存储引用 + 每文件 sha256 + 字节数 + F06 轨迹状态）、
  `plan`（默认 **dry-run**，分类 `expired/retained/active/unfinished/missing/out_of_scope`；
  删除需 `--apply --yes` 且删除前复核包含关系）、`verify`（按清单校验文件齐全与校验值）、
  `check`（只读孤儿与行数）。
  不可协商的四条：**缺失 ≠ 已过期**（丢失是恢复问题，不能被清理报表写成"已整理"）、
  活动与未完成 run 受保护、越出 run_root 的路径拒绝删除、清单校验值是完整性检查而非防篡改证据。
- 2026-09-30：**证据**。新增 [tests/test_web_f07_retention.py](../../../tests/test_web_f07_retention.py)
  **20/20 通过**：超期可清理、未到期保留、活动/无完成时间受保护、**缺失与过期可区分**、
  他人在范围外、plan 不落盘、apply 只删超期且拒绝越界路径、verify 识别 ok/缺文件/校验不一致、
  清单往返、CLI 默认 dry-run、`--apply` 无 `--yes` 拒绝（退出码 2）。
  负向对照：禁用「活动保护」与「缺失区分」两项判据 → **5 条断言失败**。
  文件侧真实演练：四类 run（超期/未到期/活动中/目录丢失）→ `verify` 报 `missing_dir`、
  `plan` 正确给出四种 disposition 且不删除、删掉一个文件后 `verify` 报 `missing_files`、
  `--apply --yes` 只删除超期那一个，未到期与活动项均保留。
- 2026-09-30：**T6 第 1 步「统计并导出孤儿清单」已执行**（只读，未改动任何存量数据）。
  `uv run python scripts/run_retention.py orphans --out <file>` 导出
  [f07-orphan-inventory.json](../audit/f07-orphan-inventory.json)（20,967 B，7 类，
  **仅标识符与时间戳，不含 prompt/answer/audit 正文**）。合计 **592 条孤儿行**：

  | 孤儿类 | 行数 | 连带影响（impact） |
  |---|---|---|
  | runs → 缺失 session | **517** | turns 0、artifacts 0 |
  | runs → 缺失 user | 17 | turns 21、artifacts 0 |
  | sessions → 缺失 user | 18 | runs 18、turns 24 |
  | turns → 缺失 run | 11 | — |
  | audit_log → 缺失 user | 29 | — |
  | turns → 缺失 session | 0 | — |
  | artifacts → 缺失 run | 0 | — |

  **对决策最关键的一条**：最大的那 517 条（无 session 的 runs）**没有任何 turns 或 artifacts 连带**
  ——它们是空壳 run（从未产生消息或产物），因此「删除」这一选项在这类上的连带损失为 0，
  与另外两类（17 条连带 21 turns、18 条连带 18 runs + 24 turns）性质完全不同。
  每类附三项处置选项（挂占位 / 删除 / 保留但标记）供人工选择；脚本**不执行**任何处置。
- 2026-09-30：**处置已执行（第 1 步完成）**。口径由用户确认；执行前取 `pg_dump` 快照
  （`/tmp/apodex-pre-t6.dump`，容器内，回滚唯一依据），全程单事务：
  517 条无 session 的 runs **删除**（脚本二次校验 turns=0/artifacts=0 后才执行）；
  17 runs + 18 sessions + 29 audit_log **挂占位 user**；
  11 条无 run 的 turns **解除悬挂引用**（`run_id = NULL`，未制造占位 run —— 占位 run 会污染
  run 计数、无轨迹文件会在备份清单里变成新 missing 项；`run_id` 可空且已有 45 条同类合法行）。
  占位实体 `__orphan_placeholder__`（status=disabled，password_hash 非合法 argon2 → 不可登录）。
  处置后 `check`：**verdict clean**，七类孤儿全 0；runs 1271→754、users 28→29，
  turns/artifacts/audit_log **一条未丢**。
- 2026-09-30：**恢复演练复演通过（T5 完成标准达成）**。处置后重新
  `pg_dump` → 独立库 `pg_restore`：**零错误**（此前 5 个 `ADD CONSTRAINT` 失败消失），
  外键 **恢复库 9 / 源库 9**（此前 4/9），7 张表行数逐一一致
  （users 29 / sessions 141 / runs 754 / turns 1093 / artifacts 296 / user_llm_configs 164 / audit_log 1978）。
  演练库与 post dump 已清理；**pre 快照保留**（容器内，随容器重建丢失，需长期回滚能力请自行导出）。
- 2026-09-30：**仍未验收（故维持 ready-for-human）**：
  ① 没有一条命令的运维备份脚本（`pg_dump`/`pg_restore` 包装）与**异地存放**——本轮只有演练记录；
  ② 恢复演练只到"行数一致"，**联合恢复**（业务库 + 运行文件的 Run/轨迹/产物引用核对）未演练；
  ③ 孤儿处置决策、`ON DELETE` 行为与迁移、会话删除语义未做（T6 第 1–3 步，需人工确认）；
  ④ 密钥不可用、缺文件、过期清理的组合恢复边界未演练；
  ⑤ 保留期/备份频率/存放位置尚未由产品或运维定值（当前 `--keep-days 30` 只是默认）。
- 2026-09-30：**联合恢复演练（业务库 + 运行文件，F01 迁移口径；隔离复演，已清理）**——收窄上条未验收的第 ② 项
  （"联合恢复…未演练"）与第 ④ 项的一部分。
  **恢复目标**：同实例独立库 `apodex_f01_rollback` + 临时运行根，均不触生产。业务库取自 `apodex-pre-f01.dump`
  （`pg_restore` 零错误，7 表行数与外键 9/9 吻合），运行文件取自 `server-runs-pre-f01.tar.gz`（837 run 目录 / 5147 文件）。
  **联合核对**：按 `run_dir_for(id)` 逐 run 解析，恢复后 244 条 pre 历史可解析；模拟的 3 条"切换后新写入"亦可达
  （轨迹 post `complete`/`partial`/`complete`）；产物引用（artifacts 296）与 turns 1093 行数一致。
  **负向对照**：仅改回根目录变量 → 切换后 3/3 run `unavailable`；单独恢复 pre 业务库 → 切换后 3 行归零。
  **结论**：回退必须四步齐全——恢复业务库 + 文件回位 + 合并切换后行 + 重定位 `run_dir`；证据
  [audit/f01-rollback-drill.json](../audit/f01-rollback-drill.json)。
  该项仍未覆盖：密钥不可用、过期清理与缺文件的组合边界（第 ④ 项其余部分），以及第 ① 项（单命令备份脚本与**异地存放**，
  本轮备份落在宿主仓库外但同机，仍非异地）。
- 2026-10-01（晚）：**第 ① 项完成——运维备份脚本 + 真实备份 + 恢复演练**。交付
  [scripts/web_backup.py](../../../scripts/web_backup.py)（`pg_dump -Fc` 单命令包装：
  fail-closed 目标探针、`pg_restore --list` 完整性校验、sha256 清单、`--keep-days` 保留期清理、
  `--out-dir` 可指向异地挂载、宿主无 pg 客户端时自动回退 `docker exec pg`）。证据
  [audit/f07-backup-script.json](../audit/f07-backup-script.json)：真实业务库备份
  `apodex-20261001T083249Z.dump`（191 KB，list 校验通过）→ 独立库恢复演练 **8 表行数一致、
  外键 12/12、版本 0004**；保留期 40 天清理/2 天保留；不可写目标 fail-closed exit 1；
  回归 `tests/test_web_backup_script.py` 5/5。
  **仍未覆盖**：③ ON DELETE 与会话删除语义（T6 第 2–3 步，需人工决策）、④ 密钥不可用组合恢复
  （`SERVER_MASTER_KEY` 丢失 → api_key_cipher 不可解密，建议部署前隔离复演）、⑤ 保留期/频率/位置定值
  （脚本默认 `--keep-days 30`）、异地跨机存放（脚本支持任意 out-dir，真异地需第二台机器挂载）。
  **另需记录（越界操作，须保留痕迹）**：本次演练清理时误删了容器内 `/tmp/apodex-pre-t6.dump`——即 T6 孤儿处置前的
  pre 快照，上条明确记为"**pre 快照保留**"。该文件位于容器 `/tmp`，按上条自身口径"随容器重建丢失"，本已非持久；F01 备份
  （宿主侧、仓库外）完好，F01 回退能力不受影响，但该 T6 回滚点已不可恢复。
- 2026-10-02（凌晨）：**第 ③ ④ 项隔离复演完成**（证据
  [audit/f07-key-ondelete-drill.json](../audit/f07-key-ondelete-drill.json)；隔离库 f07_semantics 由生产 dump
  192,933 B 恢复 + 隔离 API :8001，零生产写，演练后已 DROP）。
  **③ ON DELETE/会话删除语义**：12 外键全 `NO ACTION`，硬删（会话 57 runs / user 被 audit_log 引用 / run 有 turns）
  三路全被数据库拒绝；会话删除为软删除（`deleted_at`），软删后列表隐藏而 run 详情仍 200（存档语义）。
  **建议维持 NO ACTION，无需 0005 迁移**——真正清理只能走 run_retention 带复核路径；「软删隐藏 + run 存档可达」
  登记为既定语义待人工确认。
  **④ 密钥不可用组合复演**（合成用户 + 已知密钥三场景对照）：
  - 错误 master_key：提交 202 不拒、快照仍声称 `user-config`（失真），实际解密失败被 `_resolve_llm_env` 静默吞掉 →
    worker 回落 .env 真实供应商跑完（8,202 tokens，models=glm 别名）——**发现 F07-KEY-1（缺陷候选，需人工决策）**：
    密钥丢失时静默改道 + 计费归属错乱 + 快照失真，且展示路径（masked_api_key）无 HTTP 暴露面，用户侧零信号；
  - 正确密钥：注入恢复（不可达 base_url 如实 failed，stopped/llm_error 零消耗）——错钥只拒不解、无数据损坏；
  - 永久丢失处置 = 重置密文（DB 层重加密后恢复生效）；**观察项 F07-KEY-2**：无 HTTP 路由可重置密文。
  **另记（并入 ⑤ 部署清单）**：生产 .env 无 `SERVER_MASTER_KEY`，live API 以 debug + 默认密钥运行（非 debug 启动会被拒）。
  **⑤ 定值**仍需人工：推荐 备份 30 天/每日 1 次、runs 文件 90 天、master_key/jwt_secret 进部署清单、
  异地待第二台机器挂载后指向 `--out-dir`（脚本已支持）。
- 2026-10-02：**F07-KEY-1 已修复（用户批准）**。三处改动：
  ① `server/store.py`：新增 `LLMCredentialError` 与探针 `user_llm_cred_state`（区分 ok / none / error），
  `resolve_user_llm_env` 对解密失败改为抛出而非吞成 `None`——"无配置"与"配置存在但密钥丢失"从此分家，
  只有前者允许回落 server-default；
  ② `server/routes/runs.py`：提交门禁在快照/Run 行落库之前探针，`error` → 503（"用户 LLM 凭据无法解密……
  请恢复密钥或重置"），零副作用——静默改道与快照失真同时消除；
  ③ `server/orchestrator.py` `_resolve_llm_env`：`LLMCredentialError` 向上传播（spawn 失败 → run 失败收口），
  作为密钥在门禁与 spawn 之间变坏的第二道防线；其余暂态 store 异常仍回落（维持可用性语义）。
  回归 `tests/test_web_f07_key_gate.py` **6/6**（503 零副作用、无配置仍 202、密钥正常 202、探针三态、
  resolve 抛出、orchestrator 第二道防线传播）；web 套件 184 passed（p2_files 6 errors 为既有 FK 环境问题）；
  ruff 全过；pyright 仅既有 Queue 不变型一项。复演证据 `audit/f07-key-ondelete-drill.json` 场景 a 即修复前行为。
- 2026-10-02（续）：**观察项 F07-KEY-2 已闭合（用户批准）**。新增最小路由面
  `server/routes/llm_configs.py` 并注册进 app：
  - `PATCH /api/llm-configs/{id}`：重置 api_key（以**当前** master_key 重加密，所有权校验 + 404 防 IDOR，
    响应为 masked 视图，明文不回显）；同端点可改 name/base_url/model/is_default；
  - `GET /api/llm-configs/{id}`：masked 读回（供客户端验证重置结果）。
  至此 master_key 丢失/轮换的恢复路径全部走 HTTP：轮换 → 提交被 F07-KEY-1 门禁 503 → 重置 api_key →
  `user_llm_cred_state` 恢复 ok → 提交恢复，**不再需要数据库手术**。
  list/create/delete 管理面仍刻意不暴露（KEY-2 范围是恢复路径，store 层函数已备、后续按需接线）。
  回归 `tests/test_web_f07_key_reset.py` **4/4**（masked/防 IDOR/重置恢复 cred_state/密钥恢复后重封）；
  web 套件 188 passed；ruff、pyright 全过。
- 2026-10-02（续 2）：**第 ⑤ 项定值采纳并落地（用户执行指示视为采纳推荐表）**——
  [deploy/README.md](../../../deploy/README.md) 新增「备份与保留定值（F07 ⑤）」节：
  业务库备份每日 1 次 / 保留 30 天（`web_backup.py` 默认值）；runs 文件 90 天
  （`run_retention.py manifest → plan --keep-days 90` dry-run → `--apply --yes` 三步流程）；
  备份位置仓库外目录、异地待第二台机器/对象存储挂载后 `--out-dir` 指向挂载点（脚本零改动）。
  同时更新密钥轮换表：补「恢复路径」列（F07-KEY-1 门禁 503 + KEY-2 PATCH 重置）。
  定值命令已实测（`--out-dir /tmp` 真实备份 192,933 B 校验通过后清理）。
  **F07 ①②③④⑤ 全部闭环**，工单转 ready-for-human 待复核；唯一环境依赖遗留：异地备份挂载点。
- 2026-10-02（复核关闭）：验收条款逐条复核通过——① 运维备份脚本 + 真实备份与恢复演练（audit/f07-backup-script.json，8 表一致、FK 12/12）；② 联合恢复演练（audit/f01-rollback-drill.json，业务库+运行文件四步回退口径，负向对照齐备）；③ ON DELETE/会话删除语义复演（audit/f07-key-ondelete-drill.json）；④ 密钥不可用组合复演 + F07-KEY-1 门禁修复（提交 6339ff2）+ KEY-2 重置路由（提交 2960920）；⑤ 定值落地 deploy/README.md「备份与保留定值（F07 ⑤）」（提交 caa2bbc）；孤儿量化与处置（audit/f07-orphan-inventory.json，处置后 verdict clean）；恢复演练证据充分（首演练暴露 FK 缺口→处置后复演零错误）。复跑 tests/test_web_f07_retention.py + tests/test_web_backup_script.py + tests/test_web_f07_key_gate.py + tests/test_web_f07_key_reset.py 45/45 通过。转 closed。
