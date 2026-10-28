# 语料增量与维护操作说明

本文记录现有新链的实际入口和恢复边界，服务于 I5-2。命令只面向已明确的隔离目标或已获批准的维护窗口；不会自行选择生产库。

## 日常增量

### 正式库入库流程（2026-10-28）

把 PDF 放进 `data/corpus-incoming/<批次>/` 只是待入库，**文件出现不等于已发布，
数据库发布也不等于 Web 已切换新索引**。本项目现行流程如下：

```mermaid
flowchart TD
    A[待入库 PDF] --> B[逐文件 SHA-256 与正式发布记录去重]
    B -->|已发布| C[保留原版本并跳过]
    B -->|新增| D[冻结清单、分类、备份正式库]
    D --> E[原件归档、准入、解析、清洗、切块]
    E --> F[检查原文引用、超长块、图像与表格缺口]
    F -->|检查通过或已有明确的可用文字授权| G[check 后 publish]
    F -->|空正文或未解决的阻断| H[保留状态，处理缺口后再检查]
    G --> I[补齐上下文说明与缺失向量]
    I --> J[生成新版本检索包，保留旧包]
    J --> K[核验旧块不变、新查询和短句柄 fetch]
    K --> L[切换配置并核验 Web search 与 fetch]
```

1. **清点与去重**：读取所有文件的哈希、页数和文字量，与正式库活动来源比对。
   文件名相同不能证明内容相同；重复文件不重新发布，也不重算说明和向量。
2. **冻结与备份**：记录输入清单、用户指令、材料类型、研究领域及现有发布指针，
   对明确目标 `postgres` 做备份。检索范围仅为旧允许清单与本批新来源的并集。
3. **构建正文**：使用 `plan_builds → execute_builds`，原字节按 SHA-256 存入
   `data/corpus-archive/<前两位>/<完整哈希>.pdf`，保留单元、页码、原文哈希及引用。
4. **处理覆盖缺口**：文字 PDF 中的行情截图不自动变成可搜索正文。按已授权的可用
   文字模式登记确切 build 的 `TextPublication` 后，仍走正常检查；不隐藏缺口。
   扫描件如使用 OCR，应另存衍生文件，名称注明 OCR，保存原件与衍生件的哈希关系，
   不将识别文字描述成人工校对原文。
5. **正式发布**：执行 `check_build_publishable → publish_build`。旧来源的活动版本
   和 generation 应逐条不变；待处理和失败构建不冒充已发布。
6. **更新检索包**：沿用当前上下文说明版本与 embedding profile，仅补齐缺失项。
   说明用于索引，返回证据仍来自正文；原 native 投影继续排除表格块。请求失败时
   先查看确切状态，不能清空失败记录后无条件重跑全部请求。
   本批有说明经受控重试后仍未通过数字／归属校验，随后逐段核对原文，只保留章节
   与讨论对象描述。这样的 Codex 校订须单独标记 `agent_source_review` 并保留原拒绝
   记录，仍通过同一校验器；不能冒充原供应商生成结果，也不能改正文来迁就说明。
7. **验收与切换**：比较旧块与旧向量；针对新资料执行查询，使用每段实际返回的
   `ref` 做 fetch 并逐字比对。验证成功后更新 `CORPUS_NATIVE_INDEX`。运行中的
   Web 应在没有 queued/running 任务时切换，并检查 `healthz`、`readyz` 和认证接口。
   业务数据库迁移属于独立事项。

本批可审计脚本位于 `.scratch/corpus-incoming-20261028/`。它是**绑定确切输入清单、
备份和范围的执行记录**，不是自动扫描所有目录的通用发布器；下一批应先重新清点和
冻结清单，不能直接替换文件后重跑旧 `prepare`。

```bash
cd /home/administrator/FrontierAgent
# 以下为本批实际阶段；按先后检查结果，不是无条件一键串行发布。
uv run --no-sync python .scratch/corpus-incoming-20261028/run.py prepare
uv run --no-sync python .scratch/corpus-incoming-20261028/run.py build
uv run --no-sync python .scratch/corpus-incoming-20261028/archive_ocr.py
# 检查 build-results.json，保留 OCR 父子溯源及图表缺口后：
uv run --no-sync python .scratch/corpus-incoming-20261028/run.py publish
uv run --no-sync python .scratch/corpus-incoming-20261028/run.py index
uv run --no-sync python .scratch/corpus-incoming-20261028/verify.py
# 验收通过，并确认现有 API 就绪且没有活动任务后切换：
uv run --no-sync python .scratch/corpus-incoming-20261028/activate.py
```

本批供应商传输结果不确定后的续跑记录在 `context-resume-before/after.json`，
第二次异常及未完成项保存在 `context-final-pending-before.json`、`pending-source-review.json`。
校订依据和结果在 `rejected-source-review.json`、`note-review-before.json` 与
`note-review-applied.json`。对应的 `resume_notes.py`、`apply_reviewed_notes.py` 和
`pack.py` 是绑定本批失败项的恢复步骤，不能当作任意新批次的自动重试入口。

本批逐份结果与 Web 验收见 [正式发布记录](corpus-native-release.md)。

### 2026-10-21 隔离试验记录

2026-10-21 新增 7 份资料的实际操作与逐份结果见
[本批执行说明](../.scratch/corpus-new7-20261021/report.md)。目标为
`vector_pilot_clean7_20261021`，其中 5 份按原生文字发布，2 份扫描件发布为标明来源的本地 OCR 衍生版。
活动范围为 25 份、1,076 块；OCR 文字未经人工逐字校验，原件及父子 SHA-256 关系保留。
这次资料发布没有切换生产库或日常检索默认配置。

本批新增了显式的可用文字发布记录 `TextPublication`：用户接受覆盖不完整时，通过
`Store.put_text_publication` 为确切 build 登记完整图像/表格缺口清单及授权依据，随后仍
执行正常 `check → publish`。记录不可覆盖；原文、默认缺口分级和缺口台账保留。
这不是 `human_gap_review`，不证明图中内容已识别或全文完整。未知缺口、空正文、
未完成阶段、无效引用及超长块继续拒绝。普通 `plan` 不读取 build 绑定的接受记录，
因此仍可能报告缺口；实际放行及依据以登记后的 `check/status` 为准。

本批订阅材料使用显式来源清单 `v3-dev-20261021`，保留真实材料类型；并未自动把所有
历史订阅文件改成已准入。英文长段落切分已升级为 `chunk-6`，跳过小数和常见缩写，
沿句界切分并保留原文引用，原有活动 build 不会因代码版本更新自动改变。

清单是显式 JSON，至少包含 `sources`，每项给出 `path`；可在清单中给出 `archive_root` 和 `policy`。先计划和预检，再构建、检查、发布：

```bash
uv run python -m plugins.corpus.cli plan --manifest <manifest.json> --dsn "$CORPUS_I2_DSN"
uv run python -m plugins.corpus.cli build --manifest <manifest.json> --archive-root <archive-root> --dsn "$CORPUS_I2_DSN"
uv run python -m plugins.corpus.cli check --build <build_id> --dsn "$CORPUS_I2_DSN"
uv run python -m plugins.corpus.cli publish --build <build_id> --operator <operator> --dsn "$CORPUS_I2_DSN"
uv run python -m plugins.corpus.cli status --build <build_id> --dsn "$CORPUS_I2_DSN"
```

`plan` 只做预检；`build` 不发布；只有 `check` 通过后才能 `publish`。CLI 不会隐式连接数据库：应显式提供 `--dsn` 或受控的 `CORPUS_I2_DSN`，并由目标守卫拒绝不在批准范围内的目标。命令没有 `--force` 旁路。

同一来源、相同内容和规则可重跑。解析检查点的读取器版本包含运行时依赖版本，因此旧的裸版本检查点会被安全地失效并重建一次；随后重跑复用检查点，保持相同 `parse_rev` 和 `build_id`。源内容、规则或索引版本改变时，预期会生成新的版本，不能把旧活动版本当作已更新。

## 失败恢复与交接

先查询失败版本，再由恢复计划定位阶段，而不是重新扫描或直接发布：

```bash
uv run python -m plugins.corpus.cli status --build <build_id> --dsn "$CORPUS_I2_DSN"
uv run python -m plugins.corpus.cli rebuild-plan --build <build_id> --dsn "$CORPUS_I2_DSN"
```

交接记录须附上 build ID、source ID、当前 generation、`status` 输出的 `gaps`/`gap_summary`/`recovery`、执行命令和退出码、清单及策略哈希、归档路径、操作者和活动版本。存在 blocking gap、目标守卫拒绝、来源或规则漂移时，停止在该状态；不要用旧表、旧句柄或默认检索绕过。

## 备份与恢复演练

以下是现有 `plugins.corpus.service` CLI 的真实命令。恢复会写入其 `--db` 目标；只能用于已经核验的隔离恢复库，不能把本文当作生产恢复授权。

```bash
uv run python -m plugins.corpus.service backup --out <backup-dir> --mode pg_dump --db "$CORPUS_I2_DSN"
uv run python -m plugins.corpus.service restore --src <backup-dir> --db "$ISOLATED_RESTORE_DSN"
```

`pg_dump` 模式没有客户端工具时会明确失败；`auto` 才允许 CSV 回退。恢复后比较备份 `manifest.json` 中的行数和列清单，并运行新链 `status`、`search`/`fetch` 的隔离验证。备份目录、恢复日志和核验结果应一并交接。

## 保留与 GC

当前没有语料 GC 命令。不得编造或执行“清理旧版本”的自动命令。原始归档、已发布或活动 build、准入/审核决定、检查点、备份和评测工件均是保留对象，不能由本说明删除。

若容量需要处理，只能由维护负责人提出精确对象清单、保留依据、恢复点和批准记录；先在隔离目标演练并留存结果。`_staging` 等执行暂存物也必须先确认未被任何未决 job、恢复计划或审计工件引用。没有这份清单和批准，GC 状态为不执行。

## 旧入口边界

正常写入入口是 preparation CLI 的 `plan`/`build`/`check`/`publish`。旧 `run_ingest` 和旧 evidence 写入已 fail-closed 退休。公开 `search`、`fetch`、`stats` 与文档列表使用活动的新链版本；未知或旧句柄不会回退到旧正文。

历史 claims/财务验证和 R2 仍有显式兼容读取能力，详见[退休矩阵](corpus-ingestion-retirement-matrix.md)。这不是公开读侧的 fallback，也不是运行常规增量的入口。
