# 08 · 工具注册（TUI 下必须改 6 处）

Type: task
Status: closed
Blocked by: 03, 05, 07

**Goal**: 让 `position_sizing` / `strategy_lint` 在 TUI 下真正可用。

**Why it is easy to get wrong**: `apodex` 有**独立于** `plugins/tools/_BUILTIN_TOOLS`
的工具注册表。`apodex/agent_tools.py:80-107` 的 `terminal_tool_registry()` 自称
*"Authoritative name → tool map for what YAML profiles may request"*，且明说
**"an unknown name is a hard error at load time"**。漏一处 TUI 直接起不来。

**Work**

| # | 文件 | 改动 |
|---|---|---|
| 1 | `plugins/tools/__init__.py:34-58` | `_BUILTIN_TOOLS` 追加 `position_sizing`, `strategy_lint` |
| 2 | `apodex/agent_tools.py:80` | 加进 `terminal_tool_registry()`（**不加 = TUI hard error**） |
| 3 | `apodex/agent_tools.py:112-120` | 加进 `_READ_ONLY`（**不加 = 每次调用都要人工确认**） |
| 4 | apodex 的 profile YAML | `tools:` 列表追加 |
| 5 | `plugins/tools/meta.py:46` | `TOOL_META` 加 2 条（见 09） |
| 6 | `tests/test_tool_registry.py:6` | `EXPECTED_TOOLS` 同步（**不同步 = CI 红**） |

**第 4 项注意**
- 改的是 **apodex 的 profile**（`--mode react` 对应的那份），
  **不是** `workflows/stateful_react_agent/profiles/tui.yaml:75`
- CLI **无 `--profile` 参数**（`apodex/cli.py:130-163` 全量参数：`--model --cwd
  --max-turns -y -p --plan --no-color --no-tui --docker --no-sandbox --version`）；
  mode 即 profile（`apodex/session.py:126`）

**Acceptance**
- `uv run frontier-agent --mode react --cwd <dir>` 能正常启动（不死于 unknown tool name）
- 不带 `-y` 时调用 `position_sizing` 不被要求确认（已在 `_READ_ONLY`）
- `uv run pytest tests/test_tool_registry.py -q` 通过
- `uv run ruff check plugins/tools/ apodex/` 全绿

## Answer

实际改了 **7 处**，比清单多一处。前 6 处按清单：

1. `plugins/tools/__init__.py` — `_BUILTIN_TOOLS` 追加两个工具 ✅
2. `apodex/agent_tools.py::terminal_tool_registry()` — 追加 ✅
3. `apodex/agent_tools.py::_READ_ONLY` — 追加 ✅
4. `apodex/profiles/react.yaml` — `tools:` 追加 ✅
5. `plugins/tools/meta.py::TOOL_META` — 追加（见 09）✅
6. `tests/test_tool_registry.py::EXPECTED_TOOLS` — 同步 ✅

**⚠️ 第 7 处（实测修正）：`workflows/stateful_react_agent/profiles/tui.yaml`
的 `agent.agent_tools`。**

清单里「改 apodex 的 profile，**不是** `workflows/.../tui.yaml`」这条与代码不符。
`--mode react` 走的是 native workflow（`apodex/task_runner.py::_run_native_workflow`
→ `BenchmarkSession`），apodex 的 `react.yaml` 只提供 `workflow` +
`workflow_profile` 两个名字，**工具可见性实际由 workflow profile 的
`agent.agent_tools` 决定**
（`workflows/stateful_react_agent/nodes/main_agent.py::_tools_for_stateful_react`；
`docs/tech-stack.md` 亦记「可见性另由 `agent.agent_tools` 控制」）。
不改这一处，两个工具在 TUI 下根本不会出现在模型可见的工具表里。

`benchmark.yaml` / `simple.yaml` 未动，评测路径不受影响（已断言）。

**连带修复**：

- `tests/test_benchmark_kernel_bootstrap.py` 里硬编码的 `== 23` 工具数随之变红。
  已改为从 `get_builtin_tools()` 推导——硬编码数字与 allowlist 重复，
  加一个工具就烂一次，且它并不说明**是哪些**工具。
- `apodex/agent_tools.py` 里刻意**不做** try/except：两个工具与
  `plugins/tools` 同仓同包，起不来说明安装坏了，静默降级只会让 Agent
  退回心算——那正是硬闸②要挡的事。

验证：`terminal_tool_registry()` 含两者；`assess_tool_risk` 对两者返回 `safe`
（即不带 `-y` 也不弹确认）；`get_profile("react").tools()` 含两者；
`load_react_profile("tui")["agent"]["agent_tools"]` 全部可解析、无 missing。

## Comments
