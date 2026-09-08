# AGENTS.md — FrontierAgent

Guidance for coding agents operating in this repository. It complements (and does
not replace) [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md),
[docs/README.md](docs/README.md), and [docs/framework.md](docs/framework.md).
Python ≥ 3.12, dependency manager is **uv** (never pip-install into the repo).

## Environment setup

```bash
uv sync --frozen --extra sandbox --extra document-readers --extra eval --extra dev
cp .env.example .env          # OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL
```

Extras are deliberate: base deps run the framework and workflows only; `sandbox`
and `document-readers` add file tools, `eval` adds datasets/Harbor/judges, `dev`
adds pytest/ruff/pyright. `plugins` adds optional third-party tool SDKs.

## Common commands

**Run the TUI.** Interactive terminal against a project directory. `--mode react`
is one stateful agent; `--mode agent_team` is coordinator plus parallel
sub-agents. Add `-p "<task>"` for one-shot, `--no-tui` for line mode, `--yes` to
auto-approve, `--resume` to continue a session.
```bash
uv run frontier-agent --mode react --cwd /path/to/project
```

**Run a single test.** Pytest is configured with `asyncio_mode = "auto"` and
`testpaths = ["tests", "apodex/tests"]`, so any selector works without markers.
Use `uv run pytest tests/test_stateful_workflow.py -q -k name` while iterating.

**Test subsets.** `uv run pytest apodex/tests -q` covers TUI/CLI; `uv run pytest
tests -q` covers workflows and framework; `uv run pytest -q` runs both.

**Lint and format.** Ruff, `line-length = 100`, `ANN` (annotations) enforced
outside tests/benchmarks. CI lints only `frontier_agent/ apodex/ benchmarks/
workflows/ plugins/ deploy/ tools/ scripts/`.
```bash
uv run ruff check . && uv run ruff format .
```

**Type check.** `pyrightconfig.json` is the shared source of truth with VS Code
Pylance; `tests`, `apodex/tests`, and the `_reader_*`/`_writer_*` fragments are
ignored.
```bash
uv run pyright
```

**Pre-flight gates.** `preflight.py` makes one cheap LLM call through the real
code path so a bad provider fails once instead of per question. `import_smoke.py
--stage 1` imports `frontier_agent`/`plugins`/`workflows` with `benchmarks`
imports forced to fail, enforcing the layering rule; `--stage 2` adds the eval
tree. `check_symbols.py` verifies symbol closure. Run all three before submitting.

**Benchmark smoke run.** One question per subprocess, resumable via completed
`result.json`. Subcommands live in `benchmarks/public/runner/`. Inspect with
`check_progress`; dataset files download separately via
`benchmarks/public/scripts/download_datasets.py`.
```bash
uv run python -m benchmarks.public.runner.run_subprocess \
  --benchmark browsecomp --pipeline stateful-react-agent --profile default \
  --limit 1 --concurrency 1 --out ./results/smoke
```

**FrontierSearchBench.** Three separate steps with an external scorer — see
[docs/eval-frontier-search.md](docs/eval-frontier-search.md). Collection must run
behind an OS-level read boundary that hides
`benchmarks/frontier_search_bench/eval/`, or the run is invalid.
```bash
export JUDGE_API_KEY=... JUDGE_BASE_URL=...
uv run python -m benchmarks.public.runner.run_subprocess --benchmark frontier_search \
  --pipeline stateful-react-agent --profile default --no-shuffle --concurrency 10 \
  --out ./results/frontier_search
uv run python -m benchmarks.public.runner.export_frontier_search \
  ./results/frontier_search --out ./results/frontier_search/frontier_agent.json
uv run python -m benchmarks.public.runner.score_frontier_search \
  --models frontier_agent=./results/frontier_search/frontier_agent.json \
  --out ./results/frontier_search/official_scores
```

## Repository architecture

Five top-level packages with intentional boundaries. The framework never imports
the eval layer, and CI enforces that with a two-stage import smoke.

```text
frontier_agent/   generic loop, scheduling, registries, AgentBus, observers
plugins/tools/    tool implementations, OSS allowlist, sandbox policy
workflows/        ReAct + Agent Team plugins: specs, nodes, profiles, prompts
apodex/           terminal CLI/TUI, approvals, sessions, traces, launch strategies
benchmarks/       public harness + bundled FrontierSearchBench / FrontierChallenge
```

### Workflow execution path

`workflows/` is plugin-driven. `frontier_agent.scheduling.workflow_loader.load_workflow_plugins`
scans every subpackage of `workflows/` and calls its `register(ctx)` function;
`benchmarks/public/` separately discovers module-level specs. Registration must be
idempotent and must not import the eval tree.

A workflow exports a `PipelineSpec`
(`frontier_agent.models.pipeline_spec`) declaring `nodes`, `transitions`,
`entry_point`, `terminal_nodes`, and `agent_definitions`. Each `NodeDefinition`
carries a `role_id`, a dotted `node_function` path resolved at runtime, a
`ContextPolicy` (`include_fields` or a `filter_fn`; `filter_fn` wins), and
`output_fields` merged back into pipeline state. `TransitionSpec.to_phase` of
`__END__` (or landing in `terminal_nodes`) terminates the run.
`frontier_agent.scheduling.scheduler.Scheduler.execute` is the entry point; it
yields `(phase, state)` tuples and enforces wall-clock budget.

Agent nodes call the domain-neutral ReAct kernel,
`frontier_agent.core.runtime.loop.agent_loop.run_agent_loop`, which binds tools
and session identity, calls the LLM, parses tool calls, executes authorized tools,
notifies observers, and applies compaction. The implementation is split into
`_bind`, `_call`, `_streaming`, `_response`, `_runaway`, and `_tool` beside it;
`core/runtime/loop/llm_client.py` is the stable compatibility facade. Workflow
semantics — planning, terminal-tool behavior, reporter routing, recovery — stay
outside the kernel, in the workflow package.

### Observers and guardrails

`frontier_agent.core.loop_types` owns `BaseObserver` (no-op base, callbacks are
optional), `LoopConfig`, `Intervention`, `ToolCallIntervention`, and the context
types. Callbacks (`on_llm_attempt`, `on_llm_delta`, `on_llm_response`,
`on_tool_call`, `on_tool_result`, `on_turn_end`, `on_compaction`, `on_loop_end`,
`on_loop_cancelled`) return an `Intervention` to stop, retry, replace content, or
continue without consuming turn budget. Authorization observers must fail closed;
telemetry and cleanup stay best-effort. Reusable observers live in
`frontier_agent.components.observers` (repetition guards, budget, deadline,
trajectory, console/SSE). Guardrail wiring per workflow is documented in
`workflows/agent_team/README.md`.

### Registries, tools, teams

Registries live in `frontier_agent.core.runtime.registries`: `AgentRegistry`,
a type-indexed DI container (`services`), and `WorkflowContext` (the facade
handed to `register()`). **The tool registry is not in the framework** —
`plugins/tools/__init__.py` holds `ToolRegistry` and an explicit `_BUILTIN_TOOLS`
allowlist of 24 names. Adding a Python module under `plugins/tools/` does *not*
make it agent-accessible; it must be added to that allowlist.
`frontier_agent.core.tool` provides the `Tool` dataclass and `@tool` decorator,
which derives the JSON schema from type annotations and Google-style docstrings.

Team coordination is `frontier_agent.components.agent_bus` (`AgentBus` for
task submission, messaging, report collection, cancellation; `SpawnGuard` for
depth, parallelism, and budget limits). `components/finalization` holds
`ResearchWall`/recovery, and `components/middleware/llm` holds the LLM proxy
chain.

### Infrastructure

`frontier_agent.infra.config` exposes `FrontierAgentConfig` / `get_config()`,
loading `.env` then `config.yaml` with `${VAR}`, `${VAR:-default}`, `${VAR?msg}`
expansion and mtime-based reload. `infra/providers.py` reads
`config/providers.yaml` (`FRONTIER_AGENT_PROVIDERS_PATH` overrides). LLM clients
are `infra/openai_client.py`, `infra/openai_responses_client.py`, and
`infra/anthropic_client.py` (includes a Bedrock path), with
`infra/llm_adapter.FallbackLLM` for failover.

Sandbox backends (`sandbox_backend` config) are `auto` (probe bubblewrap, fail
with guidance), `bwrap`, and `container`. **There is no unisolated host
fallback**; authorization and sandbox setup are fail-closed. Implementations live
in `plugins/tools/_sandbox.py`. File and shell tools share one task-scoped
sandbox: `/inputs` read-only, `/workspace` working state, `/outputs` the only
persistent deliverable location, with `/outputs/scratch` reserved for
intermediates.

`frontier_agent.state.event_store.sqlite.EventStore` is deliberately a **no-op
in-memory** implementation in this distribution; persisted traces, cost tracking,
and checkpointing are owned by the `apodex` layer instead (see below).

### Terminal layer (`apodex/`)

Entry point is `apodex.cli:main`, exposed as both `frontier-agent` and the
compatibility alias `apodex`. `apodex/tui/` is Textual (full-screen) with Rich
renderables and the `--no-tui` line-mode fallback; that stack is frozen — do not
add a second widget framework. Supporting modules: `session.py` /
`session_state.py` (checkpointing, `/revert` via `changes.py` journal),
`trace.py` (JSONL trace), `permissions.py` + `fsguard.py` (approval gate with
hard denials that survive `--yes`), `steer.py` (queued interventions), and
`native.py` / `docker.py` (execution strategies; native is the Linux default and
is announced as *not* an OS sandbox). `local_tools.py` reimplements `bash`,
`read_file`, `grep_search`, `glob_search`, `delete_file` against the real working
directory, which is why they differ from the sandbox-backed variants.

Run artifacts land under `<cwd>/.apodex/runs/<session-id>/` with `session.json`,
`trace.jsonl`, `engine.log`, `trajectories/`, `workspace/`, and `outputs/`; see
[docs/run-artifacts.md](docs/run-artifacts.md).

### Benchmark layer

`benchmarks/public/core/registry.py::REGISTRY` is authoritative: each dataset key
maps to a `DatasetConfig` with its default pipeline and scoring mode. Family
modules under `benchmarks/public/families/` are auto-discovered and export
`CONFIGS`. Judges live in `benchmarks/public/judges/`; `run_subprocess.py` runs
one question per subprocess with a process-level timeout and resumable
`result.json` files.

Pipeline IDs are exact registry keys: `stateful-react-agent`, `agent_team`,
`agent_team_report`. Workflows read the selected profile from
`state["metadata"]["profile"]`. File benchmarks are wired through sandbox
metadata (`_dataset_root`, `_sandbox_mounts`, `_sys_prompt_addendum`,
`_collect_outputs`) prepared by the adapter — workflows consume that metadata
rather than importing `benchmarks.public`.

`benchmarks/frontier_search_bench/` holds 41 queries and their official scorers,
which ship ground truth; the FrontierAgent-side adapter is kept outside it in
`benchmarks/public/families/frontier_search.py`. `benchmarks/frontierchallenge/`
is a Harbor-based runtime whose task payload lives on Hugging Face, not in Git
(CI asserts this).

### Gotchas

- Import `run_agent_loop` from `frontier_agent.core.runtime.loop.agent_loop`;
  the `loop` package `__init__` deliberately re-exports nothing.
- There is no `core/observers.py`, `core/context.py`, or `core/llm_client.py`:
  observers are in `core/loop_types.py`, `ContextPolicy` in
  `models/pipeline_spec.py`, permissions in `core/runtime/resources/`.
- Never move tool type annotations into `if TYPE_CHECKING:` blocks — `@tool`
  resolves them at runtime via `typing.get_type_hints` to build the JSON schema
  (this is why ruff's `TC` rule is intentionally unselected).
- `plugins/tools/_reader_*.py` and `_writer_*.py` are source *fragments*
  concatenated and `exec`'d by `_create_file.py` / `_doc_reader.py`, not modules.
- Benchmark concurrency multiplies: total model parallelism is roughly
  `--concurrency` times the Agent Team spawn limit. Start at 1.
- Legacy `swarm` identifiers (`response.swarm.*`, `swarm_main`,
  `load_swarm_profile`) are load-bearing and must not be renamed.

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/<feature-slug>/` in this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles with default label strings (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` at repo root + `docs/adr/`. See `docs/agents/domain.md`.
