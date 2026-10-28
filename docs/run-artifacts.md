# Run artifacts and timestamps

Interactive runs keep their user-visible state and deliverables together below
the directory passed with `--cwd`:

```text
<cwd>/.apodex/
├── runs/
│   └── <session-id>/
│       ├── session.json       # resumable conversation checkpoint
│       ├── trace.jsonl        # ordered LLM and tool event trace
│       ├── engine.log         # warnings and failure diagnostics
│       ├── trajectories/      # workflow and sub-agent trajectories
│       ├── workspace/         # run-private clones, drafts, and scratch files
│       └── outputs/           # persistent user deliverables
└── runtime/
    └── native/                     # native-only caches and temporary state
        ├── cache/
        ├── dependencies/
        ├── home/
        ├── inputs/
        └── tmp/
```

`runs/` has the same host layout in native, Docker CLI, and Docker Compose
mode. The active `workspace/` and `outputs/` directories are exposed through
the stable `/workspace` and `/outputs` paths. The directory passed with
`--cwd` remains the project/coding root; it is mounted at `/project` in Docker
and is no longer used as scratch space. Benchmark and Harbor runs retain their
own result-tree layout because their harness owns artifact collection.

## Session IDs and time zones

New session IDs use the launching system's local wall clock and include its
numeric UTC offset:

```text
20260812-153045+0800-react-ab12
```

The offset makes a directory name understandable without silently losing the
instant it represents. Native mode reads the system time zone directly. The
Docker launchers pass the host's current offset into the container, so Docker
and native runs created at the same time use the same clock.

Persisted `created_at` metadata and event timestamps remain canonical UTC. This
keeps machine processing, ordering, and cross-time-zone comparison unambiguous;
only human-facing directory names and session-list timestamps use local time.

For unattended Compose invocations that bypass `docker/run.sh`, export the host
offset first. Compose falls back to `+0000` when it is unavailable and displays
the host run root relative to the project:

```bash
export APODEX_LOCAL_UTC_OFFSET="$(date +%z)"
docker compose run --rm agent
```

The helper launchers set `APODEX_HOST_RUNS_ROOT` to an absolute host path. This
value is only shown to the user: it is the path the TUI prints as `Host:` and
the one a resumed follow-up hands to the model. A direct Compose run instead
shows `.apodex/runs`, relative to the repository where Compose was invoked.

## Finding and resuming a run

Use `frontier-agent --resume` or `/sessions` rather than manually scanning the
tree. `/log` prints the active trace location. For direct inspection:

```bash
run_dir="/path/to/project/.apodex/runs/<session-id>"
tail -f "$run_dir/engine.log"
python -m json.tool "$run_dir/session.json"
```

Older checkpoints under `~/.apodex/sessions` and the previous native runtime
tree are still discovered and can be resumed. They are not renamed or moved;
after an old session is resumed, subsequent checkpoints use the unified run
directory under the selected `--cwd`.


## Web research receipts and task progress

Agent Team stores its post-loop coordinator recovery in
`<web-run>/run/agent/trajectories/main_finalization.jsonl` (and its JSON snapshot).
This separate stream joins coordinator and member streams in Web replay and
usage aggregation. Its start/end span covers one logical recovery call, including
any internal fallback; it does not enumerate provider retries. Missing usage
makes the run's usage status partial even when other calls were metered.
Cancelled member loops flush their latest snapshot and emit an `end` record with
`stopped_by="cancelled"`; a complete trace is not a claim of completed research.

Web workers keep corpus aliases beside their consumption ledger under
`<web-run>/run/corpus/tool-refs/` and `search-refs/`. These writable directories
are selected by `CORPUS_TOOL_REF_ROOT` and `CORPUS_SEARCH_REF_ROOT` in the worker;
the installed source tree can remain read-only. The parent carries hash-checked
receipts from committed runs in the same research into the next run, bounded to
4096 files / 16 MiB. Missing receipts still require fetching the source again.
Receipt availability never substitutes for source or delivery verification.

The Web single-agent profile enables `research_convergence`. Previous task IDs
remain addressable but are excluded from the current round's progress until an
explicit `add_task`/`update_task` resumes them. Tasks can retain `kind`
(research/verification/delivery), `done_when`, `notes`, `gap`, and `evidence_refs`.
The notes and pointers are model declarations, not verification verdicts.

After each acquisition batch, another discovery search requires a progress
update naming what was learned and the remaining gap. Completed research tasks
or the time reserve trigger finalization, which blocks discovery searches while
allowing exact source fetches, manifest repair and artifact production. The
180-second reserve is independent of the maximum turn count and cannot extend
the outer run deadline. One reasoning-only interruption after evidence acquisition
may continue through the same authorized tool loop, within the remaining reserve;
repeat failure keeps the existing deterministic partial fallback. Corpus and
investment publication checks continue to apply.
