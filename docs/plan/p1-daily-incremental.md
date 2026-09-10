# C 组：每日增量 + 跑批台账 · 细化方案

| 项 | 内容 |
|---|---|
| 版本 / 状态 | **v1.0 · 待评审** |
| 上游 | [p1-corpus-scaleup.md](./p1-corpus-scaleup.md)（C1 / C2）· [data-layer-architecture.md](./data-layer-architecture.md) v2.0 |
| 目标 | 往 `data/corpus/` 丢文件 → **自动入库**，且**每一次跑批都可回溯** |
| 依赖 | A1–A4 已完成（跳过未变 / 失败带原因 / CLI / 生成列）· S3 已完成（备份） |
| 不在范围 | 语料内容解析质量（D1 表格抽取）· 同系列取代（E1）· 可视化看板（G3） |

---

## 0. 先读这段：这份方案到底要解决什么问题

### 一句话

**让你丢进 `data/corpus/` 的研报，自动变成「能被 Agent 搜到」的状态。**

### 关键认知：放进文件夹 ≠ 能被搜到

用图书馆打比方：

| 图书馆 | 我们的系统 |
|---|---|
| 书架上的书 | `data/corpus/` 里的 PDF |
| 图书馆的目录卡片 | PostgreSQL 里的记录 |
| **编目员把新书登记进目录** | **跑一次 `ingest`（跑批）** |
| 书在书架上，但目录里查不到 | **文件在文件夹里，但没入库** |

只有登进目录的书才借得到；同理，**只有入库的研报，`corpus_search` 才搜得到**。
把文件复制进文件夹，**不会**自动进数据库——中间必须跑一次 `ingest`。

### 真实例子：今天已经发生过两次（都是偶然发现的）

| 时间 | 目录里 | 库里 | 差 |
|---|---|---|---|
| 第一次核对 | 19 个文件 | 17 份 | **2 份从没入库**，Agent 完全搜不到 |
| 放了一批新文件后 | 57 个文件 | 23 份 | **34 份静静躺着**，直到手动跑 `ingest` 才生效 |

**没有任何报错。** 表现只是「资料里没有这份研报」——会让人以为库里本来就没收，
而不是「没收进去」。这就是**沉默的失败**，也是本方案真正要消灭的东西。

### 做完之后，日常变成什么样

| | 流程 | 风险 |
|---|---|---|
| **现在** | 放文件 → 记得手动跑命令 → 才生效 | **忘了就一直不生效** |
| **做完后** | 放文件 → 定时自动入库 → 到点就能搜到 | 忘了也没关系 |

### 那「台账」是干嘛的

每次跑批留一份工作日志：

> 今天扫了 57 份，新增 34 份，跳过 23 份（没变），失败 0 份。
> 若有失败 → 记录**哪份文件、什么原因**（如「解析失败：PDF 已损坏」）

- **没有台账**：只知道「好像跑过了」，失败也不知道是哪份 ⇒ **报告悄悄丢失**
- **有台账**：任何一次跑批都能回查，失败项带文件名 + 原因

### 如果暂时不做，会怎样

不会坏，但下面两件事会一直存在：

1. 每次加文件都得手动跑一条命令——**忘了就搜不到**；
2. 失败是**静默**的——某份报告没入库，你不会收到任何提示。

⇒ 语料越多、加得越频繁，这个风险越大。

---

## 1. 目标与验收

一句话：**你只管往 `data/corpus/` 放文件，剩下的自动完成；任何一次跑批事后都能查到"跑了什么、成了多少、哪份失败、为什么"。**

| # | 验收标准 |
|---|---|
| 1 | 放入 N 个新文件后跑批，**只解析这 N 份**（已入过的跳过，不重复解析） |
| 2 | 每次跑批都有台账记录：开始/结束时间、耗时、各类计数、触发方式 |
| 3 | **任一次跑批的失败项都能查到文件名 + 原因**（而不是"失败了 3 份"这种无信息量的统计） |
| 4 | 二次跑批 **0 新增**（幂等） |
| 5 | 跑批**不可重入**：同一时刻只允许一个跑批在跑 |
| 6 | 数据库不可达时**明确失败**（退出码区分），且台账记下 `error`，不静默装作成功 |
| 7 | 台账随 `pg_dump` 一起被备份 |

---

## 2. 现状盘点：已经有什么，还缺什么

### 已具备（A 组已完成的产物，直接复用）

| 能力 | 位置 | 说明 |
|---|---|---|
| 跳过已入库未变文件 | `CorpusService.ingest_dir` + `_known_hashes` | 按 `(source_path, content_hash)` 预检，二次跑批 0 新增 |
| 失败带文件名 + 原因 | `IngestStats.failures` | `[(path, reason), ...]`，并落 `logger` |
| 跑批 CLI | `python -m plugins.corpus.service ingest` | 内部先 `init_db()` 再 `ingest_dir()` |
| 入库即索引 | `blocks.tsv` GENERATED 列 | 无需事后重建索引 |
| 份数自核对 | `stats()` 的 `corpus_files` / `fully_ingested` | 不预设目标值，与目录实际文件数比对 |

### 还缺（本次要做）

| 缺口 | 后果 |
|---|---|
| 没有**定时** | 全靠手动跑（现在就是我在手动跑） |
| 没有**台账持久化** | 统计只在 stdout / 日志里，**事后查不到** |
| 没有**并发保护** | 同时跑两个会互相干扰（虽然幂等，但浪费且计数混乱） |
| 没有**明确的退出码语义** | 调度器无法判断"成功 / 有失败 / 整个挂了" |
| 没有**"文件正在被拷贝"的保护** | 拷贝一半的文件会被解析成失败，且失败是**假的** |

---

## 3. 方案设计

### 3.1 总体形态

```
调度触发（或手动）
    │
    ▼
corpus-service ingest --trigger <manual|cron|scheduler>
    │
    ├─ ① 取 advisory lock（拿不到 → 退出码 2，记"已有跑批在跑"）
    ├─ ② 写台账：started_at
    ├─ ③ 扫描目录 → 跳过"近期写入中"的文件 → ingest_dir()
    ├─ ④ 写台账：各项计数 + failures 明细 + status
    └─ ⑤ 按结果退出：0 ok / 1 warn / 2 error
```

**设计原则：不新增常驻进程。** 跑批是一次性命令，由外部调度器触发。
这与 §2.1 定的「进程内服务层」一致——常驻守护进程只增加运维面，不解决实际问题。

### 3.2 台账设计（存数据库，双写一份 JSON）

**主存数据库**的理由：与语料同库 ⇒ **随 `pg_dump` 一起备份**（验收 #7）；
可 SQL 查询；由服务层收口，不外泄。

**同时落一份 JSON 到磁盘**（`data/corpus_runs/runs.jsonl`）的理由：
数据库挂了的时候仍然能看最近一次跑批发生了什么——**诊断路径不能依赖被诊断的对象**。

> 实现说明：原计划写 `<date>.json`（一天一个文件），实际改为 **`runs.jsonl` 追加写**。
> 理由：一次跑批一行，天然支持追加，不需要"读-改-写"，也不会因并发跑批互相覆盖。
> 实测也验证了这个价值——模拟数据库不可达时，数据库里没有记录，
> 但 `runs.jsonl` 里留下了完整的失败原因。

```sql
CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id             BIGSERIAL PRIMARY KEY,
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz,
    duration_ms        integer,
    root               text NOT NULL,           -- 语料目录
    total              integer NOT NULL DEFAULT 0,
    added              integer NOT NULL DEFAULT 0,
    skipped_duplicate  integer NOT NULL DEFAULT 0,
    skipped_unchanged  integer NOT NULL DEFAULT 0,
    needs_ocr          integer NOT NULL DEFAULT 0,
    empty              integer NOT NULL DEFAULT 0,
    failed             integer NOT NULL DEFAULT 0,
    status             text NOT NULL,           -- ok | warn | error
    error              text,                    -- status=error 时的异常信息
    trigger            text NOT NULL DEFAULT 'manual'  -- manual | cron | scheduler
);
CREATE INDEX IF NOT EXISTS idx_ingest_runs_started ON ingest_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS ingest_failures (
    run_id  bigint NOT NULL REFERENCES ingest_runs(run_id) ON DELETE CASCADE,
    path    text    NOT NULL,      -- 失败文件
    reason  text    NOT NULL       -- 失败原因
);
CREATE INDEX IF NOT EXISTS idx_ingest_failures_run ON ingest_failures (run_id);
```

> 两张表都进 `init_db()`，幂等（`IF NOT EXISTS`）。

### 3.3 并发安全：PG advisory lock

用数据库锁而不是文件锁——**跨进程、跨机器都有效**，且不需要额外依赖：

```python
LOCK_KEY = 0x636F7270  # 'corp'
if not cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]:
    # 已有跑批在跑 → 记一条 error 台账？不，直接退出码 2 并写日志
```

`pg_try_advisory_lock` 拿不到就立即返回，不阻塞——调度器触发的重叠跑批应该**快速失败**而不是排队。

### 3.4 触发方式（三选一，需先确认环境）

| 方案 | 做法 | 优点 | 风险 / 前提 |
|---|---|---|---|
| **A. Windows 任务计划程序**（**推荐**） | 计划任务执行 `wsl -e bash -lc "cd ~/FrontierAgent && uv run python -m plugins.corpus.service ingest --trigger scheduler"` | **不依赖 WSL 常驻**；Windows 开机即调度；你本就在 Windows 侧 | 需要 WSL 能被非交互调用（一般可以）；PATH 里要有 `wsl` |
| B. WSL cron | `crontab -e` 加一行；需 `service cron start` | 纯 Linux 习惯 | **WSL 会话关闭后 cron 可能停**；需额外配置开机启动 |
| C. 先只做手动 + 台账 | 不做定时，随时手动跑 | 零风险，先把可回溯做出来 | 达不到"全自动" |

**建议路径**：先落地 **C1a（幂等跑批 + 台账 + 锁 + 退出码）**，跑稳几天后，再按 A 接调度（或先按 C 用着）。
理由：把"跑批本身可靠"和"谁来触发它"解耦——**触发方式随时可换，跑批质量不能返工**。

> ⚠️ **待确认（方案第一步）**：运行环境是 WSL + Windows Docker，需确认
> ① `wsl.exe` 能否被计划任务非交互调用；② WSL 内是否有 `cron`/`crontab`。
> 这一步决定了最终选 A 还是 B（不影响 C1a 的实施）。

### 3.5 "文件正在被拷贝"的保护

拷贝一个大 PDF 时跑批，会解析到**写了一半的文件** → 解析失败 → 台账里留下一条**假失败**。

做法：跳过 `mtime` 在最近 `N` 秒内被修改的文件（默认 60 秒，可配 `--min-age`）。
这些文件**下一次跑批会被正常处理**（因为那时它们已写入完成且 hash 未入过库）。

> 为什么用"跳过"而不是"重试"：重试会让单次跑批时长不可控；
> 跳过 + 下次自然补上更简单，且失败原因不会被污染。

### 3.6 退出码与告警语义

调度器只能看退出码，所以必须区分清楚：

| 退出码 | 含义 | 台账 `status` | 处理 |
|---|---|---|---|
| **0** | 全部成功（无失败、无空文档） | `ok` | 无需处理 |
| **1** | 跑批完成，但**有失败 / 空文档 / 需 OCR** | `warn` | **需要人看**：查 `failures` |
| **2** | 跑批没跑起来（PG 不可达 / 拿不到锁 / 目录不存在） | `error` | **必须处理**：基础设施问题 |

### 3.7 保留与清理

台账默认保留 **90 天**（`--prune-runs 90`），超期记录连同 `ingest_failures` 级联删除。
磁盘上的 JSON 目录同样按天数清理。

---

## 4. 任务拆分

| # | 任务 | 状态 | 内容 | 验收 |
|---|---|---|---|---|
| **C1a** | **跑批任务化** | ✅ **已完成**<br>2026-09-09 | ① 新增 `ingest_runs` / `ingest_failures` 两表（进 `init_db`）<br>② `ingest` 子命令增加 `--trigger` / `--min-age`<br>③ advisory lock 防重入<br>④ 落台账（含 failures 明细）+ 双写 JSONL<br>⑤ 退出码 0/1/2 语义 | **实测**：连跑两次第二次 `added=0`；并发跑批退出码 2；损坏文件→`failed=1` 且台账记下文件名+原因 |
| **C2a** | **台账查询** | ✅ **已完成**<br>2026-09-09 | `runs [--limit N]`、`failures [--run ID]` 子命令 | **实测**：`failures` 能列出 `path` + `reason` |
| **②** | **一键脚本** | ✅ **已完成**<br>2026-09-09 | `scripts/ingest-corpus.sh`（WSL/终端）<br>`scripts/ingest-corpus.bat`（Windows 双击） | **实测**：跑通，结束打印最近 5 次跑批 + 结果提示 |
| **C1b** | **定时接入** | ⬜ 未开始 | 按 §3.4 确认结果接 A 或 B | 放一个新文件 → 到点后自动入库（`documents` +1） |
| **C2b** | **保留清理** | ⬜ 未开始 | `--prune-runs 90`，级联删除 + 清理 JSONL | 超期记录被清理，近期保留 |

**实施顺序（已按此执行）**：`C1a → C2a → ②`（已完）→ `C1b`（等环境确认）→ `C2b`。

### 已知限制（实测发现，记在这里避免踩坑）

| 限制 | 说明 |
|---|---|
| **刚放进来的文件要等 60 秒** | `--min-age 60` 会跳过最近 60 秒内被修改的文件（防止解析到拷贝一半的 PDF）。<br>所以**刚拷完就跑会看到「0 新增」**——脚本现在会明确打印 `skipped_fresh` 提示，稍等再跑一次即可，下次跑批也会自动补上。 |
| **台账的 `empty` 只统计本次解析到的** | 存量问题（如那份 0 字符的高盛 PDF）不会在后续跑批里重复报警。<br>要看存量异常请用 `stats` 的 `by_status`。 |
| **`.bat` 依赖 WSL 默认发行版** | 脚本里写的是 `wsl -e bash -lc "cd ~/FrontierAgent && ..."`，假定默认发行版就是本项目所在发行版；若不是，需改成 `wsl -d <发行版名>`。 |

---

## 5. 风险与未决问题

| 风险 | 说明 | 应对 |
|---|---|---|
| **PG 容器没起来** | Docker 未启动时跑批必失败 | 退出码 2 + 台账记 `error`；调度器可配置失败重试；**不静默装成功** |
| **假失败（文件拷贝中）** | 见 §3.5 | 跳过 mtime 过新的文件，下次自然补上 |
| **语料目录被误移走** | `iter_corpus_files` 会返回空 → `total=0` | 台账记 `total=0`，退出码 0 但**视为异常**：考虑 `total=0` 时记 `warn` 提示 |
| **单次跑批耗时随增量增长** | 只解析新增，所以耗时与**增量**相关，与总量无关 | 这正是 A3 的价值；台账里记录 `duration_ms` 可观察趋势 |
| **未决：触发方式** | WSL / Windows 二选一 | 见 §3.4，待环境确认 |
| **未决：空文档怎么办** | 如高盛茅台 PDF（0 字符） | 记 `empty` 计数并出现在 `warn`；**是否自动重试待定**（重试对扫描件没用，需 OCR） |

---

## 6. 验收清单

- [ ] 放 N 个新文件 → 跑批 → 只解析这 N 份（`added=N`，其余 `skipped_unchanged`）
- [ ] 台账有记录：时间、耗时、各项计数、触发方式
- [ ] 失败项**带文件名 + 原因**，可用 `failures` 子命令查到
- [ ] 二次跑批 `added=0`
- [ ] 并发跑批被锁挡住（退出码 2）
- [ ] PG 不可达时退出码 2，台账记 `error`
- [ ] 台账随 `pg_dump` 备份（`pg_dump` 模式包含这两张表）
- [ ] 定时触发后，新文件自动入库
