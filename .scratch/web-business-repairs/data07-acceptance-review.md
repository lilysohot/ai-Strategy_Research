# DATA-07 与 DATA-12 B 阶段验收复核

日期：2026-10-03。结论：**暂不通过验收**。

基线：`ec24664156d56affdf3ac084d6bf97a9a0f0a19d`，审核本轮未提交的 DATA-07、通知基础及其 UI/测试；包含新增未跟踪文件。未审计其他语料任务，也不将 DATA-08、监控 C 阶段或生产部署列作本轮缺陷。

此前 108 项 PG、74 项前端单测以及单研究浏览器成功路径的通过记录仍然有效，但不足以证明下列并发与恢复场景正确。之前 issue 的 resolved 结论撤回，改为待修复。

## Standards：运行控制和事务一致性

### S1 [P1] 数据库标记停止，没有停止活 worker

位置：[input_requests.py:190](../../server/input_requests.py#L190)。

创建请求只废弃 outbox 并写 `stopped/input_required`。`dispatch_outbox.abandon_for_run` 对 dispatched 记录直接返回；创建路由没有调用 orchestrator 的 stop/wait_stopped。已启动 worker 仍运行，完成后 `orchestrator._persist_run_result` 调用 `store.update_run_result` 无条件覆盖终态。因而页面显示等待补数时，模型仍可能继续分析并最终把 Run 改为 completed/failed。

依据：DATA-07 要求“原 Run 以 input_required 原因结束”；现有 `dispatch_outbox.py:344` 明确已 dispatched 的任务由编排器/worker 负责取消。修复应可靠停止 worker，防止迟到结果覆盖结束原因。回归必须覆盖 running/dispatched，不限 queued。

### S2 [P1] 过期扫描覆盖已提交的回答终态

位置：[input_requests.py:534](../../server/input_requests.py#L534)。

`expire_due` 无锁读 pending，再按主键写 expired。回答可在截止前取得锁并通过时效检查，截止后仍在事务内；过期扫描读到旧 pending 后等待锁，最终覆盖已提交的 answered。普通列表/详情 GET 都触发扫描。

隔离 PG 已复现：回答事务提交 answered，扫描 flush 后最终为 expired。复现隔离了已通过时效检查后的回答事务锁/提交阶段。修复需锁后重新判断或有状态条件的原子更新，覆盖回答/取消/到期竞争。依据：DATA-07“过期、取消、已回答……有冲突结果”。

无独立的风格/启发式重构问题。上述均是可影响用户状态的正确性问题。

## Spec：业务语义与需求覆盖

### R1 [P1] 撤回明确值后，旧值仍能触发续接

位置：[input_requests.py:265](../../server/input_requests.py#L265)。

`_merge_collected` 复制旧 collected；遇到 pending_clarification/estimated/assumed 只跳过，不撤销旧字段，歧义标志也不持久化。已复现：先提交资金 80000 → 将该字段改为待澄清 → 下一次只提交目标价 28；结果保留旧资金且 complete=True。用户明确撤回的数据重新成为有效事实。

依据：DATA-07“只有所需字段完整且无歧义才续接”；PRD 禁止不确定资金进入有效计算。应持久保存字段待澄清状态/删除旧有效值，并在后续回答继续阻断，直到该字段重新明确。

### R2 [P1] 自增通知游标不等于提交顺序，会漏事件

位置：[business_events.py:69](../../server/business_events.py#L69)，`store.BusinessEvent.cursor`。

同一用户的不同研究可以并发写事件。PG 序列在 flush 时分配编号，而非提交时分配。已复现：事务 A 获得 1 未提交；B 获得 2 并提交；查询推进到 2；A 再提交；after=2 永远读不到 1。HTTP 补读与 SSE 都使用这条查询，已读 through 也可能标记尚未看到的低编号事件。

依据：DATA-12“分页/补读与实时订阅……不丢已持久事件”。应使游标推进与可见提交顺序一致，并增加跨研究并发提交测试。

### R3 [P1] 请求详情迟到响应会覆盖当前选择

位置：[BusinessRequestCenter.vue:74](../../web/src/components/business/BusinessRequestCenter.vue#L74)。

切换请求时只更新 selectedId，保留旧 selectedDetail；selected 优先使用旧详情，加载期间仍可提交。快速切换 B/C 时，较迟返回的 B 也能覆盖 C。列表选择、表单对象和提交 request_id 因而可能不一致。

依据：UI-11“覆盖……迟到响应”，UI-01 跨研究切换不串旧异步响应。应清空旧详情、加载期间禁用提交，并用请求标识或取消机制丢弃过期响应。

### R4 [P2] 列表首屏截断，没有续页或增量通知

位置：[BusinessNotificationCenter.vue:40](../../web/src/components/business/BusinessNotificationCenter.vue#L40)，[BusinessRequestCenter.vue:61](../../web/src/components/business/BusinessRequestCenter.vue#L61)。

通知只调用一次 after=0/limit=100，后端升序返回，事件 101 起无法访问；页面没有 SSE/增量轮询，刷新仍读最早 100 条。补数列表同样只载入最新 100 条，忽略 has_more，较早 pending 请求会被新请求挤出界面。

依据：DATA-12 游标连续补读；UI-07 持久请求可查询回答。应支持分页/续读、服务端状态筛选及事件增量更新；测 101 条以上与查询/订阅交接。

### R5 [P2] 通知没有定位所属研究和请求

位置：[BusinessNotificationCenter.vue:101](../../web/src/components/business/BusinessNotificationCenter.vue#L101)。

按钮只发送区域名，未传 research_id/request_id/run_id，父组件也只切区域。当前在研究 A 时点击研究 B 的“打开研究”仍回到 A；“去补充”默认打开请求列表首项。

依据：UI-09“全局通知可回到所属研究”，DATA-12“通知可定位研究、规则和 Run”。应按实体 ID 导航，并用两个研究/多个请求做浏览器验收。

### R6 [P2] pending 请求不展示部分回答和剩余字段

位置：[BusinessRequestCenter.vue:238](../../web/src/components/business/BusinessRequestCenter.vue#L238)。

回答历史只在非 pending 分支显示；pending 表单仍列全部原始字段，重新载入清空输入，也没有使用 collected。部分提交成功后用户看不到已经保存的值、回答记录或剩余待补项。

依据：UI-07“展示已提交回答、剩余待补项”。应在待补状态展示历史和有效已收集字段，并明确哪些仍需填写。

## 证据与重新验收范围

- [复现脚本](evidence/audit-data07.py)：直接调用当前服务函数，用临时 PG 确认 S2/R2；纯函数确认 R1。数据库由脚本创建并 finally 删除，无现有实例改动。
- [本轮输出](evidence/data07-audit.log)。其他项为逐路径代码核查，未宣称完成相应浏览器/活 worker 动态复现。
- S1 增加真实 worker 停止及迟到终态验证；S2/R2 增加受控并发测试；R1 增加三轮回答撤回测试；R3—R6 增加延迟响应、分页、跨研究导航及部分回答浏览器测试。
- 本轮未修改业务实现，仅记录审计结果、复现证据并撤回完成状态。

轴内统计：Standards 2 项（最高 P1）；Spec 6 项（最高 P1）。合计 8 项，5 项 P1、3 项 P2。
