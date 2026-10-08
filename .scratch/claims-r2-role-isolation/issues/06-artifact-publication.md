# 06 · 工件保存、语义发布与跨运行回读

Status: ready-for-human
Execution: 已验收
Type: task
Plan: W3；R2-S2/S3（文件试点，不代表生产 S5）
Blocked by: 无本地任务依赖（05 已验收）
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

让合格角色结果经受控文件 Adapter 发布，并在另一研究运行中可发现、核验和读取；独立发布与后到冲突不破坏版本一致性。

## 前置与外部门

05 已验收，01 已固定根目录配置键/索引结构/发布写入策略。仅写测试临时目录或明确实验输出；不迁移生产数据库，不修改旧 corpus_evidence_runs。

## 范围与预期文件

- 文件 store/发布固定落在 `plugins/corpus/structured/store.py`；不可变对象在
  `objects/sha256/`，发布 manifest 在 `manifests/`，权威 head/generation 在
  `index/structured.sqlite3`，`cache/heads/` 仅为可重建缓存。角色校验使用 v1 contract。
- tests/test_corpus_structured_store.py、tests/test_corpus_structured_publication.py。
- 不可变 raw/角色工件、校验和、执行账引用、逐角色覆盖和语义发布 manifest；研究消费账/报告清单不存入此目录。
- 跨角色映射区分确定对应、疑似、未关联和字段冲突；规则版本与证据绑定。

## 验收条件

- [x] 同一输入的不同模型运行保留独立身份；文件存在不等于发布，旧加载器不能成为新 JSON 回读路径。
- [x] 精确引用、原文依赖与用途检查通过才进入可用清单；未关联不算一致，同 locator 多命题不误合并。
- [x] Claims 可先发布 P1，R2 后到冲突发布 P2 收紧受影响用途；失效 items 的关系不能继续以有效状态提供。
- [x] 首轮单发布写入者或已冻结的父版本检查生效，双路提交无丢更新；断电/崩溃不暴露半份清单，历史可诊断复现。
- [x] 来源更新、规则升级、撤回与过期分开处理；不以“最新一次失败”覆盖旧合格历史，更不能把旧结果当新 build。
- [x] 关闭写端、切换 cwd 和研究 run 后可按配置根目录和发布索引读取；不依赖内存对象/临时 cwd，不全盘搜索。
- [x] 缺目录、权限不足、损坏哈希、未知 schema、未发布和撤回分别报错；检查零模型、无自动重抽。
- [x] 路径解析限制在配置根目录，工件引用不允许越界；读端不获得后台写权限，不泄露 raw 密钥信息。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_store.py tests/test_corpus_structured_publication.py -q
uv run ruff check plugins/corpus tests/test_corpus_structured_store.py tests/test_corpus_structured_publication.py
```

必须包含两个进程/两个 cwd 的真实文件回读测试、发布竞态和损坏工件反例，不能仅复用进程内字典。

## 非目标

不恢复旧 evidence 表，不将 JSON 试点冒充生产 PG 保存，不修改来源正文或建设全库缓存治理。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
- 2026-10-03：用户明确要求执行 06；本票已认领并进入实现。继续限定为合成夹具与本地
  临时文件 store，真实模型调用和生产数据库访问保持为 0；不顺带执行 07。
- 2026-10-03：用户要求开启执行。前置核查确认 05 仍为 `ready-for-agent` / 未开始，且仓库中
  不存在本票依赖的 `plugins/corpus/structured/ledger.py`、structured CLI、执行账测试或
  `index/structured.sqlite3` Schema。06 的发布事务需与 05 共用该索引并引用稳定的
  batch/task/attempt，无法在不猜测账本接口的情况下满足父 generation、并发写入和执行账引用
  验收。因此本票保持 `needs-triage` / 未开始 / `Blocked by: 05`，未创建 store/发布代码，
  未调用真实模型，未访问生产数据库。需先执行并验收 05，或由用户明确调整任务顺序和接口边界。
- 2026-10-03：05 经回塑、双轴复核和最终门禁后已验收闭环，稳定执行账、复合 batch/task/attempt
  作用域及只读核查入口现已具备；本票解除本地依赖并转 `ready-for-agent`。Execution 仍为未开始，
  本次没有执行 06、没有创建发布/store 实现，真实模型调用和生产数据库访问仍为 0。
- 2026-10-03：实现完成并转 `ready-for-human / 待验收`。新增
  `plugins/corpus/structured/store.py`，在 05 的同一 `index/structured.sqlite3` 中登记不可变
  publication、逐工件 batch/task 引用及 source/build 权威 head/generation；manifest 先原子落盘，
  `BEGIN IMMEDIATE` 内比较冻结父版本并切换 head，`cache/heads` 仅在提交后尽力刷新且读端从不依赖。
  读端以 SQLite `mode=ro` 按配置根目录精确定位，校验 manifest/对象/角色 payload/快照/原文区间、
  必要依赖、用途、关系上游与端点，不调用旧 `load_evidence_run`，不扫描 cwd，也不返回凭据配置。
- 2026-10-03：跨角色规则固定为 `cross-role-map-v1`；confirmed/suspected/unlinked/conflict 分开，
  exact span 参与映射，同 locator 非重叠命题不合并。Claims P1 可先发布；R2 后到的可验证 value/
  factuality 冲突形成 P2，当前视图撤去受影响 compare/calculate 而保留历史 P1；缺失或失效 items
  的 relations 在发布前拒绝。来源更新、规则升级、撤回和过期使用独立 lifecycle，旧 build/head
  与历史 manifest 保留，失败的新发布不切换旧 head。
- 2026-10-03：精确验收命令原样通过：`19 passed`；指定 Ruff 命令 `All checks passed`。
  扩展 `tests/test_corpus_structured_*.py` 回归 `227 passed`；定向 Pyright `0 errors`；import smoke
  为 framework `379/379`、eval `428/428`；symbol closure 为 `0 missing` / 478 文件；
  `git diff --check` 通过。测试覆盖两个独立读进程/两个 cwd、配置根目录、父版本双写竞态、
  提交前/后崩溃窗口、损坏 manifest/角色工件、未知 schema、权限、未发布、撤回/过期、路径
  symlink 越界及只读 DB mtime。所有业务路径显式拒绝网络、真实模型和生产 CorpusService。
- 2026-10-03：全仓 Pyright 另报 5 个既有非 06 路径错误：`deploy/huggingface/app.py` 缺
  gradio、`scripts/run_retention.py` 3 项类型错误、`server/orchestrator.py` 1 项 Queue 类型错误；
  本票定向 Pyright 与全部相关测试均通过，未越界修改这些文件。交付指纹：`store.py`
  `24a060efc68103715f692e752950b0e5c941087fe9dcf32efb6b1752ca49f61d`；`ledger.py`
  `4968f7ef49830759af9576a6c68e08e1ae6352086a8fed0adeab7501d9955a4d`；
  `test_corpus_structured_store.py` `5c19ef1cc179846486ff583ffe0306839039eeae7c7c31f703c1ee12ebd77102`；
  `test_corpus_structured_publication.py`
  `1343e2fb0e707d276f0564c9653a7f122e668a97c78a522e5e9dc4a6e4a881b7`。真实模型调用 0、
  生产数据库访问 0；未执行真实模型 preflight，也未启动 07。
- 2026-10-03：用户要求按回溯审核结果修复。以下修订记录替代上文的完成性判断与旧文件指纹，
  不删除历史记录；本轮基线为 `522358c4345d2b94cb86f7bba3c1d50cfaab6edf`，开始时工作区干净。
  继续保持 `ready-for-human / 待验收`，没有代替人工验收或解除 07 的依赖。
- 2026-10-03：已修复跨角色比较。新发布使用 `cross-role-map-v2`：先验证原子命题的精确跨度和
  原文支持的主体/指标/期间，再比较有确定性依据的 quantity/unit、factuality、polarity、condition、
  attribution；金额用 Decimal 和冻结单位表比较，`15 + 亿元`、`15亿元`、`150000万元` 不再误冲突。
  否定冲突撤去 compare/calculate；值缺失、自由文本无法解析、明确 unknown 字段和多命题/主体歧义
  保持 suspected，并在 manifest 留 `CROSS_ROLE_COMPARISON_UNPROVEN`。调用方不能手动把疑似提升为
  confirmed。没有改写任何 EvidenceRun/MaterialRun 原始 payload，没有增加模型调用。
- 2026-10-03：规则历史与缓存已修复。保留 v1 校验分支供 `allow_historical=True` 诊断复现；旧规则
  head 的普通消费明确返回 `publication_rule_upgrade_required`，必须通过 `rule_upgrade` 产生 v2
  新版本。测试实际切换 v1→v2，核对 P1 历史视图不变及 P2 用途恢复。缓存采用原子替换，刷新时在
  writer lock 下重读权威 head，验证 P2/撤回以及 P1 延迟回调不能写回旧缓存；manifest 仍不可变。
- 2026-10-03：补齐测试证据。新增隔离子进程 helper，不继承父进程凭据；子进程在业务导入前阻断
  socket/DNS、HTTP、dotenv 加载，并阻断 CorpusService 数据库连接，另有 blocker 自测。真实写进程
  退出后由两个不同 cwd/研究运行的进程回读；双进程父版本竞争仅一个提交成功；真实 `os._exit(73)`
  覆盖 manifest 落盘后和 DB 提交后两个崩溃窗口。关系夹具现在有实际 present 关系：发布 P1 后替换
  items，旧关系不能挂接新 artifact，拒绝的发布不动旧 head，P2 不再提供旧关系，历史 P1 可诊断；
  撤回后普通读取拒绝。权限测试新增非 root POSIX 子进程读取 chmod(0) manifest，验证权限专属错误。
- 2026-10-03：环境修复复核。上轮“环境已恢复”不准确，实际发现 45 个已安装包的 console_scripts
  缺失。本轮用 Linux uv 按锁文件重装对应 35 个依赖包，随后重建本地项目入口；未改锁文件、未使用
  pip、未删除虚拟环境。修复后 Python `3.12.14`，54 个已登记 console_scripts 均存在且可执行。
  首次离线 sync 因构建依赖 hatchling 缓存缺失退出 1（未安装）；添加 `--no-install-project` 后
  离线恢复依赖退出 0；最后正常 sync 构建项目退出 0。只允许 uv 环境准备联网，业务测试保持零外部调用。

### 2026-10-03 修复验收命令与结果

所有命令从 WSL `/home/administrator/FrontierAgent` 执行，`uv` 为
`/home/administrator/.local/bin/uv`。表中为完整 Linux 命令（Windows 外层仅 `wsl -d Ubuntu --exec`）。

| 命令 | 退出码 | 结果 / 范围 |
| --- | --- | --- |
| `uv run pytest tests/test_corpus_structured_store.py tests/test_corpus_structured_publication.py -q` | 0 | 41 passed，06 专项，无跳过 |
| `uv run pytest tests/test_corpus_structured_*.py -q` | 0 | 249 passed，全部 structured 回归 |
| `uv run ruff check plugins/corpus tests/test_corpus_structured_store.py tests/test_corpus_structured_publication.py tests/_corpus_structured_subprocess.py` | 0 | All checks passed；包括新增 helper |
| `uv run pyright plugins/corpus/structured/store.py` | 0 | 0 errors / 0 warnings |
| `uv run python tools/import_smoke.py --stage 1` | 0 | framework 379/379 |
| `uv run python tools/import_smoke.py --stage 2` | 0 | eval 428/428 |
| `uv run python tools/check_symbols.py` | 0 | 0 missing / 478 files |
| `git diff --check` | 0 | 无空白错误 |
| `uv run pyright` | 1 | 5 个既有非 06 错误：gradio 缺失、run_retention 三项、orchestrator Queue 一项；本轮未修改这些文件 |

最初新增数量/否定回归命令 `.venv/bin/python -m pytest tests/test_corpus_structured_publication.py -q -k comparison_preserves`
退出 1（5 failed），修复后原反例通过；后续扩为 13 组并纳入上述 41 项。缓存刷新测试也先捕获
generation 2/缓存 1 的失败，再验证修复。

环境恢复完整命令（退出 0）：

```bash
uv sync --offline --frozen --inexact --no-install-project \
  --extra sandbox --extra document-readers --extra eval --extra dev --group web \
  --reinstall-package Pygments --reinstall-package babel --reinstall-package cffi \
  --reinstall-package charset-normalizer --reinstall-package courlan --reinstall-package datasets \
  --reinstall-package dateparser --reinstall-package debugpy --reinstall-package dirhash \
  --reinstall-package distro --reinstall-package fastapi --reinstall-package harbor \
  --reinstall-package htmldate --reinstall-package httpx --reinstall-package httpx2 \
  --reinstall-package huggingface_hub --reinstall-package idna --reinstall-package jsonschema \
  --reinstall-package litellm --reinstall-package markdown-it-py --reinstall-package nodeenv \
  --reinstall-package numpy --reinstall-package pdfplumber --reinstall-package pymupdf \
  --reinstall-package pypdfium2 --reinstall-package pyright --reinstall-package pytest \
  --reinstall-package python-dotenv --reinstall-package shortuuid --reinstall-package tld \
  --reinstall-package tqdm --reinstall-package trafilatura --reinstall-package typer \
  --reinstall-package uvicorn --reinstall-package websockets
uv sync --frozen --inexact --extra sandbox --extra document-readers --extra eval --extra dev --group web
```

当前 SHA-256（命令 `sha256sum plugins/corpus/structured/store.py tests/test_corpus_structured_store.py tests/test_corpus_structured_publication.py tests/_corpus_structured_subprocess.py`，退出 0）：

- `store.py`: `1877171544745ba939bcb873bf69f2bd70edab4859096d9e36287892f001c004`
- `test_corpus_structured_store.py`: `e1b10faa675f1abbe2b07a28033bd3ce194025ea94ab55eede58e37a8db51ced`
- `test_corpus_structured_publication.py`: `dacc9b93a73d058bb2acbd207cf5d56944a6e2eaa190163dbbb1686bb779ab65`
- `_corpus_structured_subprocess.py`: `cf11ab2af8bd17ac98b752e70a7833592a6583fe364e76fb594d9b0374d44c66`

限制与外部门：v2 只确认受支持的、原文绑定的原子数值语法，不把任意自然语言或表格多命题强行
归一；超出确定性规则的记录保持 suspected/unlinked，不代表一致性已通过。复杂条件/归属没有可比
字段时不猜测；这不是模型语义准确率验收。历史诊断显式使用旧规则，不能将旧诊断用途当新发布许可。
POSIX 权限用例在 root/非 POSIX 环境会跳过，本次 WSL 非 root 实跑通过。实际物理断电未模拟，验证的是
无 Python finally 的进程退出与 SQLite 恢复。共享 ledger 私有基础设施提取仍属设计建议，本轮不扩大为
05 存储 API 重构。真实模型调用 0、生产库访问 0；按 spec §5 未运行真实模型 preflight，未执行 07，
不得以本地回归替代主计划阶段签认。

- 2026-10-03：用户确认修复后验收通过。06 的 8 项验收条件、专项 `41 passed`、structured
  扩展回归 `249 passed`、指定 Ruff、定向 Pyright、两阶段 import smoke、symbol closure 与
  `git diff --check` 证据均已核对；当前交付指纹与上文修复验收记录一致。全仓 Pyright 的 5 个
  既有非 06 错误继续作为外部门保留，不影响本票闭环。票据 Execution 更新为 `已验收`；
  真实模型调用 0、生产数据库访问 0，未执行 07，也未代替主计划阶段签认。
- 2026-10-08：登记 PDF 表格发布限制。未经显式 `verified_complete` 核验的 `reader-pdf-*` 表格
  工件可以原样保存以供审计，但其 packet 为 `partial / table_untrusted_or_incomplete`，不能产生
  可发布 Claims/items/relations，也不能以“文件已保存”提升为 accepted publication。后续若完成
  人工或独立程序核验，须生成带新快照身份的新工件再走发布门，不得原地修改旧工件或追溯放行。
