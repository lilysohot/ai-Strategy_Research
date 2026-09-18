# I0 首批交付：状态回溯与目标对齐复核

日期：2026-09-15。性质：本次工作区的时点审计，不是新的执行计划或数据库授权。
任务状态真源：[统一执行计划的细任务台账](../../../../../docs/plan/claims-market-closed-loop-plan.md#i0-execution-ledger)。
验收依据：[任务清单 §3.0—3.1](../../../../../docs/plan/corpus-ingestion-rebuild-tasks.md)、
[架构 v1.1 §2.1/§12](../../../../../docs/plan/corpus-ingestion-rebuild-architecture.md)。

## 1. 结论与范围

方向未偏离：新增 `preparation` 守卫独立于模型语义链，阶段配置区分盘点与内存开发，
准入建议没有冒充人工批准；未在这批实现中建设第二套解析/索引/观点主链。
但 **I0G-1 仅部分实现，拒绝契约未通过，不能勾选完成，也不能放行后续运行**。
这是已有安全边界没有落实、测试没有覆盖实际入口的问题，不是推翻整个清洗/入库架构的证据。

本次审查读取代码、计划与既有元数据报告；实际测试仅操作独立临时合成文件。
未连接 PG、未运行盘点脚本、未读取真实来源或留出正文、未调用业务模型、未入库/建索引/清库。
未修改守卫、既有测试、阶段配置或历史报告。临时合成文件由测试自动清理；原始语料不变。
本轮使用 `codebase-design` 核对任务契约与实现边界，按 `diagnosing-bugs` 保留可重复的反例；
因此状态回填区分“有实现”“已验证”“可放行”，不根据文件存在或报告自述直接标完成。

## 2. 可复现的验证证据

- 旧 [守卫报告](../../i0-guard-report.json) 声称自检 12/12、pytest 10/10；其中四个代码文件和两份配置的 SHA-256 与当前文件 **6/6 一致**。报告不是因为版本不匹配而被否决，而是原测试覆盖不足。
- 本次仅重跑安全子集：**7 passed，3 deselected**。排除外部域名连接、自检中的同类连接，以及读取真实 `data/corpus/index.db` 的用例；未将其写成“全套重验通过”。
- 新增 [离线反例脚本](guard_counterexamples.py)：[第一轮](guard-counterexamples-run1.json) 与 [第二轮](guard-counterexamples-run2.json) 均为 **3 passed、9 failed**，退出码均为 1；结果绑定实现、配置、测试及诊断脚本哈希。
- C11/C12 仅通过 `sys.audit` 重放 socket 审计事件，**没有实际建立连接或查询 DNS**。这证明钩子的判定缺口，不冒充真实 PG/操作系统隔离验收。

在项目根目录的 WSL 环境中复现反例（不带 `--out` 不写报告；带该参数时只允许创建新文件）：

```bash
.venv/bin/python -I -B .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/2026-09-15-status/guard_counterexamples.py
```

本次既有测试安全子集命令：

```bash
/usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH=/home/administrator/FrontierAgent PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest --noconftest -c /dev/null -p no:cacheprovider tests/test_corpus_preparation_guard.py -q -k 'not selfcheck and not external_socket and not source_write'
```

此命令避免加载无关根 conftest/自动插件，只是限定单元测试子集，不代表完整项目或旧业务流程非回归。

| 反例 | 预期 | 实测 | 定位与归因 |
|---|---|---|---|
| C01 / C10 / C12 | 绝对禁读路径、禁止模块、IPv4 审计事件被拒绝 | 3 项通过（正控） | 当前同一 Python 进程内的部分拒绝机制有效 |
| C02 / C03 | 相对禁读路径、相对受保护写入被拒绝 | 2 项未拒绝 | [guard.py](../../../../../plugins/corpus/preparation/guard.py) 第 262 行：相对路径直接返回，未按工作目录归一化后判定 |
| C04 | 删除受保护文件被拒绝 | 未拒绝 | `_audit` 只处理 `open/socket.connect`；`os.unlink` 不受现有文件保护分支约束。只删除了临时合成文件 |
| C05 / C06 | 未绑定开发来源时拒绝正文读取 | 2 项未拒绝 | 第 270—275 行：空 allowlist 关闭过滤，空 read_roots 使所有路径不受读取限制；与 i1 配置“空即全部拒绝”注释相反 |
| C07 / C08 | CLI 目标与普通子进程继承禁读约束 | 2 项均可读取临时禁读文件 | 第 590 行 `os.execvp` 替换进程后不重装 Python audit/import trap；普通子进程也没有自动安装。环境变量投毒不能替代这些约束 |
| C09 | 已声明守卫阶段但缺配置时报错 | 静默不安装 | [guard_pytest.py](../../../../../plugins/corpus/preparation/guard_pytest.py) 第 24—25 行把部分声明也当成未选择守卫；应与“两变量都未声明”的普通测试兼容场景区分 |
| C11 | I1 deny_all 拒绝 Unix socket 连接事件 | 未拒绝 | guard.py 第 252—253 行明确放行非 IPv4/IPv6；不足以支持“I1 无 PG/无网络”的完整承诺 |

三项核心归因：路径/配置实际语义比任务契约宽；进程内钩子被误当成跨进程边界；
测试验证了手动 `install` 后的子进程，却没有验证包装命令及其派生进程自动获得约束。
现有 pytest 早装测试的断言写在测试函数体内，也不足以单独证明测试模块顶层/早期插件均被覆盖。

## 3. 不止第一步：实际资产盘点

以下是对既有文件的审阅，不是本次新执行了这些任务；文件中的授权陈述属于历史记录，
本次未独立复核其原始批准消息或重新验证在线环境，也不据此扩大权限。

| 任务 | 已见产物与事实 | 不能记为完成的原因 |
|---|---|---|
| I0G-1 | guard/pytest 接线、两阶段配置、旧自检报告及测试存在 | 上述 9 项拒绝契约未通过；修复并新版本重验前不放行 |
| I0A-1 | [inventory](../../i0-inventory.json)、[findings](../../i0a1-inventory-findings.json)、[脚本](../../i0a1_inventory.py) 存在；findings 哈希与 inventory 绑定一致，记录 errors=0 | 记录可保留为历史目录观察，不能继承失效的守卫放行。脚本有显式 host/port 检查及连接级只读设置，现有 SQL 为 SELECT；本次没有发现据此证明发生数据库破坏的证据。消费者/后台写入完整性、精确目标与执行边界仍需复核；unknown 应显式保留并阻断对应物理决定，不要求先猜出答案 |
| I0A-2 | [dev-manifest](../../dev-manifest.json) 与 [review-queue](../../review-queue.json) 各 73 条；全部 review_required，无已填完的人工终态；三类各两份仅是候选 | 开发范围/格式与留出隔离未冻结，无获准构建分母。73 是递归“类来源文件”计数，包含 4 份 `.audit/*.md` 和 `data/corpus/README.md`，不能直接称为 73 份研报。89 库记录、73 文件及 78 份旧快照的差异不能只靠总数解释 |
| I0A-3 | [admission-policy](../../admission-policy.json) 为 frozen=false，auto_decision=false | 6 个特征表达式为空，正反例/人工批准待补；是合理的政策草案，不是冻结契约 |
| I0A-4 | [source-gold](../../source-gold.jsonl)、[query-gold](../../query-gold.jsonl) 均 records=[]；[baseline-bindings](../../baseline-bindings.json) 有部分绑定 | 两文件目前是多行 JSON 占位对象，尚非逐记录 JSONL；不能被当作可直接消费的金标。5 类财务/公式/客户表/正文/宏观绑定仍 pending_locate_and_hash，旧检索适用范围亦未冻结 |
| I1-8 | i1.json 预置配置与共用插件存在 | 只是 I0G-1 的前瞻草稿；M1 未过、来源未绑定且空配置拒绝失败，不等于 I1 已启动或本项已完成 |

不得因为发现守卫缺口，就反向断言以前一定发生了模型调用、留出泄露或数据库写入；
这里只能判定**现有边界和测试不足以证明这些行为被禁止**。已有盘点记录不删除、不篡改为新批准。
`background_writers=无` 只反映已查到的库内机制与一次活动快照，不证明宿主定时任务/所有外部写入者不存在。
“本轮留出未指定”不能撤销历史留出身份；来源清单校正时应先继承/核对既有隔离资产。

## 4. 如何收口，且不扩大任务

1. **优先修复 I0G-1 并复核，不先推进 I0A/I1。** 明确受支持的执行入口、进程树和文件/网络约束；补相对路径、删除/重命名、空来源清单、CLI/子进程、部分 pytest 配置及 Unix/native 连接边界的拒绝测试。纯 Python hook 的保护范围必须如实写明，未受控命令拒绝运行；不能只改注释或降低测试预期。
2. 修复时仍保留“不选择守卫的普通旧测试不受影响”。区分未启用与配置不完整；对实际测试收集和批准的子进程入口验证。自检改为不需要公网 DNS 的合成信号；新报告追加版本和哈希，不覆盖旧 12/12 报告。
3. 守卫通过后，按**已有授权的精确范围**复核 I0A-1 的运行证据/消费者与共库清单，核定哪些只读观察可复用、哪些需重测。真实连接、备份/恢复和源文件读取仍分别服从原任务前置，不由本审计授权。
4. I0A-2 先纠正机器候选清单和继承旧审核/留出身份，再向人工交付明确的本批决定；不要把 73 个候选全部升级为全库字段标注任务。review_required 是合法未决记录，可继续隔离；但用于本批构建的三类各≥2 份必须有有效准入与格式覆盖。
5. 政策与金标按原 I0A-3/4/5 次序完成，保留占位文件的历史，不把助手候选写成金标。M1 未过不启动 I1，M2/M3 等更不因目录/文件已存在而通过。

本轮只完成状态追溯和诊断，**没有实施上述修复或启动下一阶段**。截至此次复核，没有新增可宣告
整项完成的基础链路任务；M1—M8 均未放行。旧业务流程非回归只在之后按冻结资产另验，
本次代码未改不等于整个已有实现已获得全项目非回归结论。
