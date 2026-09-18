# I1—I2-2 独立复核（2026-09-17）

## 结论

方向未偏离：统一解析/清洗/切块、canonical units、版本化构建、独立 PG 存储 Adapter、隔离演练、零模型等边界仍成立。上轮 I0-C 反馈已实质落实（九表、人工审核与来源级检查点、scope_ref、attempt 历史、发布状态幂等、精确隔离目标）。

但当前不支持“I2-2 完整验收通过”的状态。建议登记为实现已交付、独立复核发现缺口待整改；不自动撤销历史 M4 对 i1-r3 的放行，也不宣称 M5 通过。I2-3 可做不依赖这些缺口的准备，但优先修复安全门与存储协议，不把已知问题推迟到最后验收。

本次未修改实现、任务台账、冻结文件、DDL 或现有测试。仅新增本审核报告与同目录反例探针；未连接 PostgreSQL、未清理数据、未读取留出正文、未调用模型。采用 diagnosing-bugs 方法构建最小失败信号；本轮是审查，不进入修复阶段。

## 本次实际执行

| 项目 | 本次结果 | 边界 |
|---|---|---|
| 当前 validate_i0c_freeze.py | exit 0 | 验证器本身存在 F4 漏检，不能单独作为完整证明 |
| 独立逐文件 SHA-256 核对 | i1-r4 38/38；i0c-r2 11/11 匹配 | 未发现当前文件漂移；与验证器未来能否拦住漂移是两回事 |
| I1 11 个业务测试文件 + 现行链路/历史有效边界/协议探针 | 241 passed，29.46s | i1 守卫、env -i、无网络、无 conftest/插件自动加载；不含 3 个历史验收节点 |
| guard 测试 | 19 passed，2.85s | 受控普通环境，未传任何数据库凭据 |
| Ruff：preparation + PG 测试文件 | All checks passed | 不是运行时正确性证明 |
| 新增独立反例 | 6 failed、1 passed，0.24s | 执行真实应用方法，替代连接/游标；无真库写入，不等价于真实并发测试 |
| 现有 PG 15 项测试 | 本轮不重跑 | 发现清理 fixture 在校验前 TRUNCATE，见 F1；15 passed 仅为既有材料声明 |
| I2-1 DDL 26 项报告 | 查阅现存报告与其冻结绑定 | 非本轮数据库内省；报告 all_ok 不扩张为完整 SQL 约束/并发验收 |

## 必须整改的发现

### F1 · P1：测试清理先于目标核验

位置：`tests/test_corpus_preparation_repository_pg.py:68-78`。

autouse `_clean_tables` 直接 `psycopg.connect(DSN)` 后 TRUNCATE 九表，先于 `store` fixture 创建 PgStore 及其目标校验。只要环境变量非空就可执行；守卫即使限定 host:port，也没有约束同实例内数据库名。若连接串误指具有同名表的其他库，会在拒绝前清空数据。

探针 `test_cleanup_rejects_wrong_database_before_truncate` 将连接替换为假连接，声明错误数据库并记录 SQL，实际第一条就是 TRUNCATE，未做目标核验。没有对任何真实数据库执行清理。

修正要求：所有破坏性测试 setup 先校验实例、数据库、schema 和授权范围；明确“被批准的专用空测试库”前提；尽可能采用事务回滚或独立临时测试范围。补错误数据库/同端口不同库/缺守卫的负例；PgStore 连接失败与测试结束应显式释放连接。

### F2 · P1：合法部分章节发布必然抛 IndexError

位置：`plugins/corpus/preparation/repository_pg.py:732-763`。

build 查询只 SELECT `source_id, decision_id` 两列，后续在 admission.scope_ref 非空时却读取 `build_row[2]`。全篇 scope=None 短路，现有测试只覆盖这一支；合法部分范围同样无法发布，不是正确的业务拒绝。

探针 `test_publish_accepts_matching_scope[pages:1-2]` 复现 `IndexError: tuple index out of range`；同一探针 scope=None 对照通过。假游标按实际 SQL 选择列数返回，并未绕过 publish 校验方法。

修正要求：读取并校验真实 build.scope_ref，补“相同 scope 成功、不同 scope 拒绝、部分准入配全篇 build 拒绝”的真库用例，验证引擎全链。

### F3 · P1：租约校验使用等待行锁之前的时间

位置：`repository_pg.py:214-220,525-533`，同类顺序存在于 publish/acquire/heartbeat/finish。

先 `_db_now`，再 `SELECT ... FOR UPDATE`，最后使用旧时间验租约。若等待行锁期间跨过 lease_until，即便没有接管，旧持有者仍可能通过过期校验。探针将取锁过程模拟为跨过过期点，实际没有抛出拒绝异常。该探针证明应用层取时顺序问题，不冒充真实 PG 竞争实验。

而 `_db_now` 使用 `now()`，它是事务开始时刻，不会因同一事务内重查而刷新。因此修复不应仅调换一行：需要在取得必要锁后使用真实数据库当前时间，并界定长事务写入/提交的有效租约规则。[PostgreSQL 18 时间函数文档](https://www.postgresql.org/docs/18/functions-datetime.html#FUNCTIONS-DATETIME-CURRENT)

补真实双连接锁等待跨 TTL、等待后接管、heartbeat 延迟以及过期旧 token 提交测试。租约判断与 activation 时间可采用不同时间语义，不要机械统一。

### F4 · P1：当前冻结验证器不检查仍生效的继承实现

位置：`freezes/validate_i0c_freeze.py:73-75,83-122`。

当前只逐文件检查 i0c-r2 的 11 项绑定；i1-r4 只检查快照文件/父链，不检查其仍被 PG 引擎使用的 engine、repository、contract、guard 等现行字节。r1 的活文件可演进不能推导为所有继承依赖无需核对。

探针只在内存中模拟 `Path.read_bytes(engine.py)` 字节漂移，磁盘完全不改；验证器仍返回成功。本轮另外手工核对 r4 全部 38 项，均匹配，所以这是验证器漏检，不是发现现有实现被篡改。

修正要求：计算“继承绑定 + 明确覆盖/退役”的有效 manifest，核对全部当前依赖；新增未修改依赖漂移、遗漏绑定、当前修订缺失反例。不要重新要求已合法替代的历史活路径匹配旧哈希，也不要修改历史快照消灭失败。

### F5 · P2：Build 的 JSONB 往返破坏同输入幂等

位置：`repository_pg.py:120-133,470-482`。

quality_report 输入为 JSON 字符串；写入转 JSONB，读回按 sort_keys 重新编码，put_build 再按 dataclass 原始字符串相等比较。原本合法的键序/空格在读回时改变，同一个输入对象重放被判“build 冲突”。现有 fixture 刚好采用与读回相同的排序和空格，掩盖问题。

探针使用合法 `{"oversized_chunks":[],"gap_regions":[]}`，调用真实 put_build 复现冲突。

修正要求：定义且统一 JSON 规范化语义或按解析后的对象比较，保留真正内容变化的拒绝行为；MemoryStore 与 PgStore 执行相同契约用例。

### F6 · P2：job checkpoint 返回类型违反 Store 契约

位置：`repository_pg.py:238-249`；`contract.py:624`（checkpoint 为 str | None）。

PG JSONB 解码结果直接塞入 Job.checkpoint，实际是 dict，而内存实现及声明要求 JSON 字符串。探针检查类型与 json.loads 可消费性，类型断言失败。现有 job 生命周期测试只检查 state/error，未检查 checkpoint 往返。

这尚不证明当前引擎的来源级恢复已坏（source checkpoint 的另一读路径已转回字符串），但证明两种 Store 并非宣称的逐方法可替换。

修正要求：规范化 job checkpoint 的编解码并补同内容重试、失败恢复、不同 attempt 检查点测试。

## 另外的工程与验收观察

1. 真并发还不能由现有 15 项串行测试证明。`publish/retire` 读取 current_decision_id 没有锁住来源行，随后才锁 publication；初次发布时 publication 行可能根本不存在，两个事务可能各自预计算 generation=1。还应检查 register/put 的“先查后插”竞争、接管后 max(attempt) 读取的一致性。这些是静态风险，需 I2-5 双连接交错实验确认，不能当作本轮已真库复现。
2. DDL 校验主要比较列名、PK/FK 集合和部分表达式；未完整核对列类型、NULL/CHECK、FK 目标列、索引完整定义。`jobs_single_running_partial_unique` 仅检查字符串含 WHERE/running，尚不能证明 UNIQUE、键列、谓词全部正确。应补结构漂移反例。
3. 状态摘要未统一：总计划第 126 行仍写 I0-C 待执行/M3—M8 未放行，第 213 行仍写 M3—M8 未通过，与第 146—185 行当前台账冲突。明确标注历史段落即可，不要覆盖历史实测。I2-1 第 184 行仍写 teardown 未执行，与 I2-2 已 teardown→re-apply 的后续事实也应建立 superseded 注释。
4. 不能因当前实现问题退回“整包自由抽取”，也无需增加模型预算或新研报。本轮问题集中于 PG Adapter、运行安全和验收门，而非清洗路线失效。

## 后续顺序

1. 先修 F1（测试前校验）与 F4（有效冻结依赖检查），使复测可信且安全。
2. 修 F2/F3/F5/F6，保留反例，统一 Store 行为用例。
3. 在明确批准的隔离目标补真 PG 复测与双连接竞态测试；不得连接原库，不重新跑含 TRUNCATE 的现有测试来探测目标。
4. 新建冻结修订并保存命令输出/结果 XML；复测当前有效 I1 与 I2，不修改旧 gold，不用历史预期失败抵消新失败。
5. 回填“已交付 / 待整改 / 独立复核通过”的区别；M5 仍须 I2-3～8，尤其 CLI 和旧消费者接线，不能提前宣告全链打通。

## 反例复现命令（不连接数据库）

仓库根执行，预期当前版本为 `6 failed, 1 passed`；红色断言描述待修复行为。

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  PYTHONPATH=/home/administrator/FrontierAgent \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  CORPUS_GUARD_PHASE=i1 \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json \
  .venv/bin/python -B -m pytest --noconftest -c /dev/null \
  -p no:cacheprovider -p plugins.corpus.preparation.guard_pytest \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260917-i2-independent-review/test_review_probes.py \
  -q --tb=short
```
