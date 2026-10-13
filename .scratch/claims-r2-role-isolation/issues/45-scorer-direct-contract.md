# 45 · 评分器直接读取签认契约

Status: completed
Execution: 已完成
Type: implementation / regression
Blocked by: 33 修订基准过门、41 items 链口径冻结

## 问题

`plugins/corpus/structured_scoring.py` 虽已把内嵌常量追平到签认契约 v4.3，但运行时仍以代码快照为真源。契约与实现若分别修改，只能靠事后等值测试发现漂移，尚未兑现 OPEN-1=A「评分器改读契约阈值」。

## 实现

- 评分器从签认的 `scoring-contract-v4.3.json` 直接读取 `threshold_source.effective` 的六项阈值。
- 11 个 `NT-I*` 哨兵从同一契约的 `review_assertions` 直接枚举，不再在评分器中重复列出。
- 缺文件、非法 JSON、schema 不为 v4.3、状态不为 `frozen_signed`、签认信息缺失、阈值缺失/类型错误、哨兵不是恰好 11 项时均抛出 `ScoringInputError`，失败关闭。
- 冻结链校验器改为验证默认路径指向当前签认契约，并验证默认 requirements 与从该文件即时加载的结果相同。
- `material_items_target_total=48` 只作为既有诊断分母元数据保留；它不是六项质量门阈值。

## 回归与验证

- 先加入直接读取测试，修复前因 loader/路径符号不存在而红；实现后覆盖自选文件阈值与哨兵变化、缺文件和六类无效契约失败关闭。
- 契约门测试：22 passed。
- 相关评分测试：65 passed。
- Ruff：相关实现、测试与冻结链工具通过。
- Pyright：评分器与冻结链工具 0 errors。
- 冻结链：`ok=17 covered=8 drift=0 needs_ruling=0`。
- 冻结 P03 `--no-write` 重算保持逐项不变：PASS；recall 41/48；precision 30/31；源1 0.909；源2 0.808；sentinel 11/11；delta_matched 7。

执行期间模型调用、抽取调用和生产 PostgreSQL 访问均为 0；签认契约、冻结金标与既有评分产物字节未改。
