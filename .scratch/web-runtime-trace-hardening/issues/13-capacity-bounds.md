# 13：轨迹读取与事件缓冲缺少容量边界

Status: ready-for-human
Priority: P2
Type: task
Requirements: PR-RUN-02, PR-GOV-02

## 问题与验收

代码证据、影响、修复建议和完整验收见[报告 F13](../../../docs/plan/web-runtime-trace-repair-report.md#f13轨迹读取与事件缓冲缺少容量边界)。

- 实施前用隔离环境和合成数据固定触发条件，记录修复前行为。
- 按报告验收正常、失败和恢复路径，补充历史兼容性与回退影响。
- 只有动态验证通过才能关闭；源码检查不能替代端到端验收。

## Comments

- 2026-09-29：遗漏复核补充。源码路径已核对，动态复现与修复尚未执行。
- 2026-10-01：已实施并动态验证（证据 `audit/f13-capacity.json`）。修复前基线：合成轨迹 20,000 行 / 2,328,688 B 下 `trajectory_tail` 每轮 poll 全文件重扫（2 轮迭代 40,000 行）、订阅队列无界（灌 10,000 条 delta 后 qsize=10,000）、`/trace` 全量同步读跑在 event loop 上。修复：relay 字节偏移增量读 + `_locate_offset` 游标转换 + `trajectory_page` 分页（limit=0 保持历史全量契约）、订阅队列 maxsize=256（满时丢 droppable delta、终态/哨兵挂 waiter）、`/trace` 改 `asyncio.to_thread` + after/limit。修复后：tail 总字节读 == 文件大小（每字节只读一次）、队列封顶 256 且终态/哨兵必达、分页游标无重叠无缺口。断行 defer / 终态可解析残尾 / 截断重扫 / 满队列降级均有回归覆盖（`tests/test_web_f13_capacity.py` 8 passed）。gates：web 套件 206 passed（6 error 为 p2_files FK 既有环境问题）、ruff 全绿、pyright 仅 orchestrator.py:304 既有错误。待人工复核后关闭。
