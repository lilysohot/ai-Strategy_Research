# 09 · `TOOL_META` 条目

Type: task
Status: closed
Blocked by: 08

**Goal**: 给两个新工具配上超时、类别与输出限界，避免巨额输出撑爆上下文。

**Work**
在 `plugins/tools/meta.py:46` 的 `TOOL_META` 追加：

```python
"position_sizing": ToolMeta(is_read_only=True, concurrency_safe=True, timeout=5,
                            category="finance"),
"strategy_lint":   ToolMeta(is_read_only=True, concurrency_safe=True, timeout=5,
                            category="finance"),
```

**参数说明**
- `is_read_only=True`：两者都是纯函数，不写状态
- `concurrency_safe=True`：无共享状态，可并行调用
- `timeout=5`：纯算术，秒级足够；给 5s 是容忍极端机器的余量
- `max_result_chars` 留 0（不限）：两者输出都是小 JSON，截断反而有害
- `result_is_ranked` 留 False：不是排序结果
- `category="finance"`：与已有 `create_finance_sandbox` 等保持一致

**参考**：P0b 的检索类工具另需 `max_result_chars=8_000` 与 `result_is_ranked=True`
（`_overflow.py:173` 据此用 head-only 截断——排序结果的尾部是最差条目）。

**Acceptance**
- `get_tool_meta("position_sizing").category == "finance"`
- 超长入参不会导致工具挂起（timeout 生效）
- ruff 全绿

## Comments
