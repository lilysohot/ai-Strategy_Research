# Spec: CLI → Web parity

Replicate the CLI/TUI panes and workflows in the web app.

- **Design doc**: [docs/plan/cli-web-parity.md](../../docs/plan/cli-web-parity.md)
- **Reference CLI**: `apodex/tui/` + `apodex/observers.py` + `docs/tui-user-guide.zh-CN.md`
- **Tracker**: `.scratch/cli-web-parity/issues/`

## Pre-requisite investigations (all resolved 2026-09-03)

| # | Question | Answer | Impact |
|---|---|---|---|
| 1 | Does the `tui` profile include a todo tool? | **Yes** — `apodex/profiles/react.yaml:18` lists `todo_write` in `tools:` | Plan board (P2.4) is feasible |
| 2 | Is `thinking_delta` wired end-to-end? | **Yes** — `loop_types.py:124` field, populated `_call.py:399`, delivered `agent_loop.py:532`. Anthropic maps `thinking_delta`; OpenAI-compatible path splits inline `<think>` tags (`_streaming.py:337-345`). `AgentBus` already consumes it (`bus.py:195`) | Thinking streaming feasible; GLM reasoning availability to be confirmed at runtime |
| 3 | Do apodex approval hooks work outside the TUI? | **No** — `apodex/task_runner.py:248`: "The session always owns the UI+approval observer (TerminalObserver)". The web worker runs `BenchmarkSession` directly, so approvals are **not** wired | Approval gate (P3.2) needs a new observer in the worker, not reuse |
