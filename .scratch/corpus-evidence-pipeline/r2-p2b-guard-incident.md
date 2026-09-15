# P2-B 执行偏差：回归入口漏装外联阻断

日期：2026-09-14。状态：入口已修复并重新验证；数据库影响核查未完成，P3 暂停。

## 事实与责任

本轮授权是零模型、零数据库外联的 P2 离线工作。执行代理新增 `p2b_guard.py` 后，直接调用了
冻结的 `p0_baseline.suite()`，误以为该函数包含外联阻断。实际阻断位于旧脚本 `main()`，不是
`suite()`。新入口当时只在 snapshot 分支调用 `block_external()`，遗漏三个 suite 分支。
这是本轮执行入口的错误，不是原研报格式问题，也不是旧公共模块发生了变化。

首次 core 显示 531 passed、1 deselected，isolation 显示 170 passed；与旧基线的 36/1 项 PG
跳过不一致，触发复核。检查源码确认漏装阻断。随后立即停止新增数据库访问，仅检查本地代码、
已有测试记录，并完成离线入口修复。未用首轮额外通过的 PG 项更新 P0-PG 状态。

## 已确认的访问范围与未确认影响

- 首轮 core 的 36 项 PG 依赖测试实际通过；不能再声称本轮 PostgreSQL 连接为 0。
- 既有测试使用配置的 `dsn()`，并非本轮预先核准的独立 PG 实例。未输出连接串或凭据，未为
  追查此事重新连接数据库；当前不能确认该实例是否仅供测试。
- `test_corpus_a1_ingest_search.py`、`test_corpus_audit.py`、`test_corpus_claims.py`、
  `test_corpus_metadata.py` 的夹具在固定 schema `corpus_a1check`、`corpus_d5audit`、
  `corpus_d2check`、`corpus_d6meta` 中执行建表、合成数据写入和测试，开始/结束会执行
  `DROP SCHEMA ... CASCADE`。另有 `corpus_d2c_*`、claims_v2、`corpus_evidence_test_*`
  随机 schema 的创建/写入/清理；isolation 重复执行了一次 EvidenceRun PG 往返测试。
- 这些操作不是本轮获准的临时 SQLite 测试。固定 schema 开始前是否已有其他内容、清理后
  是否完全恢复，缺少执行前数据库快照，不能确认。若此前确有内容，删除不保证可恢复，须依赖
  数据库备份/日志；本轮没有尝试恢复、再次清理或修改数据库。
- `CorpusService.init_db()` 还调用扩展/全文检索配置的 prerequisites；仅凭 search_path 使用
  测试 schema，不能证明所有库级对象零变化。源码不能替代数据库侧影响核查。
- `test_corpus_golden.py` 和 `test_corpus_verify_b7.py` 会从现有语料读统计、文档、检索结果及
  原文块；因此首次记录中的 `real_corpus_tests: excluded` 不准确（只排除了指定文件/用例）。
  没有主动打开留出源文件，但数据库采样身份未记录，不能宣称留出内容暴露严格为 0。
  这些内容没有用于修改 R2 的语义规则、金标或阈值，也没有提交给真实模型。
- 首轮测试通过表示断言和 teardown 没有报告失败，不是数据库无影响证明。

## 证据作废与保留

以下三个文件原样保留，但**不得用于零外联、PG 保护、语义非回归或阶段放行**：

| 文件 | 首轮结果 | 处置 |
|---|---|---|
| `p2b-core-tests.json` | 531 passed，1 deselected | 无阻断，作废 |
| `p2b-platform-tests.json` | 110 passed | 同一缺陷入口，重跑替代 |
| `p2b-isolation-tests.json` | 170 passed | R2 禁用但 PG 未阻断，作废 |

上述文件的 `db: disabled before native driver` 是旧 suite 的静态标签，并非阻断实际执行证据，
本轮不得沿用该标签作出判断。`p2b-validation-final.xml` 是早期 210 项测试记录，已被含入口
反例的 213 项最终记录替代；两次不能累加。

## 修复与复验

只修改本轮新建 `p2b_guard.py`，不修改冻结的 P0 工具或旧测试：

1. 在任何 suite 的 pytest 收集之前调用 `p0.block_external()`：固定不可用 DSN，Python
   socket audit hook 拒绝连接，并在进入原生 libpq 之前替换 `psycopg.connect` 为拒绝函数。
2. 三个 suite 各增加“阻断先于测试收集”的入口回归检查；不能把阻断放到 collection 后。
3. isolation 对旧 R2 和新私有 R2 都执行 import poison 正控并检查没有私有模块加载。
4. 用新文件重跑，不覆盖首次记录。新结果：core 495 passed / 36 skipped / 1 deselected；
   platform 110 passed；isolation 169 passed / 1 skipped。跳过原因为离线 PG 阻断。
5. 原行为快照在独立、有阻断且禁用新旧 R2 的进程中生成，与 P0 SHA 完全相同；原 2336 个
   受保护文件及冻结资产仍一致。这些只证明代码及离线行为，不追溯证明数据库零影响。

## 恢复推进前需要的条件

P2 的技术测试通过与阶段放行分开：本轮仍标 `P2 partial / impact review pending`，不进入 P3，
不读取更多开发或留出材料、不冻结模型预算。需要用户确认本轮测试所用 PG 实例的用途，并授权
一次只读影响核查；核查目标是连接身份、测试 schema 残留、库级对象及数据库日志/备份记录，
不自动 DROP、修复、恢复或迁移。没有事前快照时，报告必须保留无法证明的部分。
