# 46 · C4 已登记缺口消费闭环

Status: completed
Execution: 已完成并验收
Type: implementation / publication rule upgrade / bounded consumption
Blocked by: 109 P6、112 C1—C3/C5

## 问题

112 号 C4 要求：查询命中 7 条未覆盖 items 金标、12 条 claims 无候选或缺失的 material_relations 时，读链必须返回覆盖状态，消费者不得把空数组解释为“没有风险”或“没有数据”。gen-2 对 relations 已返回 `not_extracted`，但 7+12 个登记缺口只存在于裁定证据中，未绑定到发布清单；查询它们只返回无原因的 `no_match`，所以 C4 尚未通过。

## 冻结执行边界

- 不补抽、不改金标、不启用 relations、不写生产 PostgreSQL。
- 用内容寻址对象把 7+12 个既有裁定缺口绑定到同一 source/build 的不可变发布清单。
- 先在生产 store 克隆上发布与逐条探测；通过后才以 `rule_upgrade` 将两源 head 从 gen-2 推进到 gen-3，artifact、snapshot、mapping、coverage 与质量状态保持不变。
- 逐条探测 19 个登记缺口；每个响应必须含 `CS_PUBLICATION_EXPLICIT_GAPS`。普通词法未命中不得带该码；relations 继续返回 `not_extracted + CS_DEPENDENCY_NOT_READY`。
- 最后各用一个主快照跑一个有界 M_main 问题，强制使用登记原文查询。模型必须明确报告覆盖不足，且不得从空结果推断事实不存在。
- M_main 合计上限 60,000 tokens；每题 `max_turns=4`，串行。达到上限或任一判据失败即停止，不换题、不放宽判据。

## 完成判据

1. 回归、Ruff、Pyright 通过，登记对象篡改时读链失败关闭。
2. 克隆演练与生产发布均满足上述不变量；生产 store 只有不可变对象、manifest、索引 head 的 gen-3 规则升级写入。
3. 19/19 登记缺口、2/2 普通未命中、2/2 relations 缺失探测符合预注册语义。
4. 两个 M_main 答案均消费真实 gen-3 查询结果并明确“已登记覆盖缺口/覆盖不足/不能作否定推断”。

## 结果

- 内容寻址的缺口登记表已绑定到两份 gen-3 `rule_upgrade` 发布；19/19 登记探测、2/2 普通未命中控制、2/2 relations 缺失控制通过。
- 两题有效 M_main 均在 `main_max_turns=4` 的硬闸下只查询一次，消费真实 gen-3 响应并拒绝否定推断；有效轮 17,349 tokens。
- 两组无效轮完整披露：首组虽实际两轮结束，但内部 turn banner 仍为 600；第二组首题因 writer 侧 WAL 侧车在一次宿主读后消失而收到 `structured_index_invalid`。修复为启动每题紧邻执行 `prepare_readonly_access`，并把 `main_max_turns=4` 纳入零调用先验断言。含无效轮累计 43,455 / 60,000 tokens。
- 抽取 attempts 保持 0，生产 PostgreSQL 8 行与 112 号基线逐字相同。

