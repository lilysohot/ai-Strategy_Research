# 07：建立业务库与运行文件联合恢复及保留策略

Status: ready-for-human
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
- 2026-09-30：**仍未验收（故维持 ready-for-human）**：
  ① 没有一条命令的运维备份脚本（`pg_dump`/`pg_restore` 包装）与**异地存放**——本轮只有演练记录；
  ② 恢复演练只到"行数一致"，**联合恢复**（业务库 + 运行文件的 Run/轨迹/产物引用核对）未演练；
  ③ 孤儿处置决策、`ON DELETE` 行为与迁移、会话删除语义未做（T6 第 1–3 步，需人工确认）；
  ④ 密钥不可用、缺文件、过期清理的组合恢复边界未演练；
  ⑤ 保留期/备份频率/存放位置尚未由产品或运维定值（当前 `--keep-days 30` 只是默认）。
