# I3-1 环境预检（Step 7）

- 生成：2026-09-19T18:48:25+08:00；授权：U（2026-09-19 会话：『授权执行下一步任务』）
- 本轮：只读预检：入口清点 + 环境探测 + 前置判定 + 隔离目标定义 + 运行计划；未运行 E2E
- **更新（B1 已解除）**：U 重启数据库后 `corpus-db` healthy；E2E **已真实执行**（6 份来源：**2 可发布 / 4 缺口阻断**，4305 单元 / 767 切块，检索核验通过），见 `audits/20260919-i3-1-e2e/i3-1-e2e-final.md`。下方『环境探测』为**当时快照**，保留存证。

## 一、结论：两个阻断，都在你手上

| 阻断 | 现状 | 需要你 |
|---|---|---|
| **B1 隔离 PG** | `127.0.0.1:543` 与 `:5432` 均拒连；本机无 postgres 二进制；本 WSL 未接 Docker；`sudo` 需交互 | 三选一：① 开 Docker Desktop 的 WSL 集成；② 给可交互 sudo（我装 postgres 并在 `.scratch/` 建私有集群）；③ 直接给一个可达的**非生产** DSN |
| **B2 开发范围** | `dev-manifest` 73 份来源终态全为 `review_required`；3 类候选只是建议 | 批准 3 类×≥2 份（见下）＋ docx 缺口定性 |

## 二、环境探测（只读）

- PG：unavailable；探测 [{'host': '127.0.0.1', 'port': 543, 'reachable': True}, {'host': '127.0.0.1', 'port': 5432, 'reachable': True}]
- 本地二进制：{'postgres': False, 'initdb': False, 'pg_ctl': False, 'psql': False, 'pg_isready': False}
- Docker：unavailable
- sudo 免密：False
- 隔离目标（I2-01 冻结）：`127.0.0.1:543` / 库 `i2_sandbox_corpus`（env `CORPUS_I2_DSN`）

## 三、入口清点（E2E 链路已实现）

- CLI：`uv run python -m plugins.corpus.cli <plan|build|check|publish|status|rebuild-plan>`（六个子命令；退出码 {'ok': 0, '输入非法': 2, '目标/守卫拒绝': 3, '门未过': 4, '目标不存在': 5}）
- 目标 fail-closed：--dsn 或 CORPUS_I2_DSN 必须显式声明；未声明即拒绝（exit 3），不隐式连库
- 生产实例拒绝：连接后校验 current_database == sandbox_db，且实例含 apodex 库即判生产实例拒绝写入
- search/fetch/verify：库 API：plugins/corpus/preparation/search_pg.py:search_chunks / read_pg.py（证据句柄）；**无 CLI**——I3-1 需一个 runner，可复用/扩展 audits/20260918-i2-fullchain-review 的自写全链路回路脚本（属 I3-1 前置，本轮登记不实现）

## 四、开发范围（未冻结）

- 清单：`.scratch/corpus-evidence-pipeline/ingestion-rebuild/dev-manifest.json`（73 份来源；{'pdf': 58, 'md': 13, 'docx': 2}）
- 状态：**NOT_FROZEN** —— I3-1 完成标准要求『冻结开发范围』；当前 73 份来源终态均为 review_required，需 U 逐条判定（M1 前置）
- 建议的 3 类×2 份：
  - company：2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张慧-公司研究-业绩点；2026-09-06_2026.09.06-国信证券-光力科技-300480-2026年中报
  - industry：2026-08-13_2026.08.13-长江证券-国内研报-长江证券-化工专题-景气投资；2026-09-06_2026.09.06-华福证券-华福证券-基础化工行业新材料周报-英伟
  - macro：2026-09-06_2026.09.06-华创证券-宏观专题-从分化到收敛-可能的路径与挑；2026-09-06_2026.09.06-光大证券-2026年8月美国非农数据点评-强非农
- 格式矩阵缺口：docx（光模块，材料类型未决）与 md（投委会报告，材料类型未决）若被 U 排除，则开发范围无 DOCX/MD 样本——按架构 §12.1 该格式真实门未通过，不得静默缩范围
- 全部在盘：True；与留出交集：[]

## 五、i3-e2e 阶段守卫（草稿，未启用）

- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json`（自检 load_phase_config=True；留出根与 `guards/i3.json` 逐字一致=True；6 份开发来源在盘=True）
- 网络仅允许 `127.0.0.1:543`；模型侧沿用封锁（`openai` 等）；`guards/i3.json` 未改动
- 启用条件：U 批准 3 类×≥2 份开发来源并生成 dev-scope-manifest.json；隔离目标可达（127.0.0.1:543 / i2_sandbox_corpus）；目标库身份校验通过（非生产实例）

## 六、模型与预算

- I3-1 链路未见模型依赖（stage 实现与 cli 均为本地解析/编排）（grep 命中 18 条）
- 本轮无需模型预算；若准入/解析在真实样本上需要外部服务，将另立清单再请授权（不擅自调用）

## 七、前置判定

| 前置 | 状态 |
|---|---|
| I3-2 冻结与完成门 | **met**（i0c-r31；validate_i3_2_completion 10/10 pass；具名签认（xyl）入链） |
| I2 全链路复核 F1 闭环 | **met**（缺口分级/坐标，已于 i0c-r15 闭环（台账 I3-1 行注明）） |
| 隔离 PG | **blocked**（environment.postgres） |
| 冻结开发范围 | **blocked**（dev_scope.status=NOT_FROZEN） |
| i3-e2e 阶段守卫 | **prepared**（guards/i3-e2e.json（草稿+自检），启用条件见 guard.i3_e2e） |

## 八、运行计划（B1/B2 解除后即可执行）

0. `corpus plan --manifest <dev-scope-manifest.json>` → 只读可发布性预检：逐来源缺口分级；无 PG 写入、无模型；exit 0/2
1. `corpus build --manifest <…> --archive-root <…> --owner i3-e2e` → 登记→准入→解析→清洗→切块；产出 build_id；写入隔离库
2. `corpus check --build <build_id>` → 门判定；blocking 缺口按 gaps 机读处置；exit 0/4
3. `corpus publish --build <build_id> --operator i3-e2e` → 仅 acknowledged 缺口可发布；generation 记操作者
4. `corpus status --build <build_id>` → 状态与 gaps 一致；published_with_gaps 可见
5. `<runner> search/fetch/verify（库 API，待接线）` → 真实检索命中 + 证据句柄取回 + 完整性校验；**不得复用合成分数**

记录要求：
- 记录领域×格式矩阵与实际覆盖（缺格式门未过）
- 每步原始输出、build_id、DSN 目标、守卫哈希一并入新审计目录
- 结果不得直接放行 I4；I3-3/I3-4 校准与 I3-5 非回归另做

> 本报告与 i3-e2e 守卫均为**新建未绑定**文件：本轮不改任何冻结修订，故不进冻结链；待 U 批准后随 I3-1 首个修订一并绑定

