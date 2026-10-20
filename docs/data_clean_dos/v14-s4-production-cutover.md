# V14 S4 生产切换记录

状态：`DEPLOYED_USER_WEB_TESTING`

## 执行结果

2026-10-20 11:37:42（Asia/Shanghai），旧 8000 进程收到正常终止信号并在 30 秒门限内退出。
11:37:45，生产端口 8000 已从冻结工作树 `/home/administrator/FrontierAgent-rc1` 恢复健康与
就绪。新运行代码固定为 tag `corpus-v14-s4-rc1`，提交
`58260fbc60ad65129bbb98a47c07defc0850622f`。

新进程身份：

- launcher PID：`1031549`
- uvicorn worker PID：`1031555`
- cwd：`/home/administrator/FrontierAgent-rc1`
- `/healthz`：200
- `/readyz`：200

切换前后的只读快照完全一致：数据库继续为 `postgres`，9 张 corpus 表、8 个活动来源、14 个
build、7,128 个 unit、1,214 个 chunk、8 个 publication、42 个 job、0 个 running job。
本次没有执行 DDL、rebuild、publish 或 publication 指针变更，也没有连接
`v14_s2_quote_corpus`。

切换后的 6 条只读检索／取回探针全部通过，company、industry、macro 各 2 条；6 个目标来源均
排在第 1 位并成功取回权威正文。模型调用 0，Judge 调用 0。

## 回滚准备

回滚 tag `corpus-prod-pre-rc1` 已建立独立工作树
`/home/administrator/FrontierAgent-prod-pre-rc1`，固定提交
`d06ad598d64ced3052da383a12f3ad5101491a63`，依赖已经按 lockfile 安装。强化监控遇到硬门时会
正常终止 RC1 并从该工作树恢复 8000；常规代码回滚不恢复数据库。

## 监控记录

两小时强化监控从 2026-10-20 11:39:56 持续到 13:39:56（Asia/Shanghai），每分钟检查：

- 8000 健康与就绪；
- 运行进程仍来自冻结 RC1 工作树；
- 数据库身份、9 张表及冻结计数；
- 8 组活动 publication/build 对；
- running job 保持为 0。

强化监控运行至 2026-10-20 12:49:49，共完成 70 个一分钟采样，全部通过，警告 0、硬故障 0。
随后按用户要求停止 watchdog 和任务 heartbeat，以便用户自行执行 Web 测试；生产 8000 未停止，
没有触发回滚。由于强化监控在两小时门限前主动停止，本次不能标记为 `DEPLOYED_2H_PASSED`；
当前状态记录为 `DEPLOYED_USER_WEB_TESTING`。

完整的切换前后快照、探针与进程记录见
[机器可读切换记录](v14-s4-production-cutover.json)。预切换证据见
[只读 canary 报告](v14-s4-canary-report.md)。
