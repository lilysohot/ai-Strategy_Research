# Fixed-report synthesis evaluation

This is an experimental evaluation seam, not a workflow or a production prompt.
Both arms use `get_main_system_prompt` with the same fixed member reports. The
candidate appends `candidate.txt`. No research tools, task-board transitions or
publication guard run here. It therefore tests synthesis in isolation.

`cases.json` freezes 12 cases before the first comparison: four minimal adaptations
of run `d7fc8735fa314644a50443ab99963947` and eight synthetic transfer/control cases
across other domains. They are curated examples, not a representative random sample.
Holdout means not used to formulate the candidate; these rubrics are visible to
maintainers and cannot remain an unseen test set after iterative tuning.

```bash
uv run python -m benchmarks.team_synthesis.run \
  --out results/team-synthesis-v1 --repeats 2 --concurrency 1
```

This makes 48 generation calls. The optional `--judge` adds 24 diagnostic judging
calls using the same team profile and token budget. Begin at concurrency 1.
Reuse the same command to resume;
completed valid calls are reused only if frozen inputs match. A changed prompt,
case set, runner, profile or config requires a new output directory. No automatic
retry promotes truncated/empty responses into valid samples.

Generation never receives the scoring rubric. Baseline/candidate order and judge
labels are randomized with a recorded seed. Judge inputs contain only anonymous
answers, the question, source reports and case-specific rubric. Three separate
binary scores measure fidelity, useful reasoning/recommendations and attribution.
Positive controls require direct arithmetic and creative recommendations: blanket
caution is not a successful answer. Review judge explanations and raw answers
before interpreting scores. The built-in judge shares the generator's model and
is explicitly **not independent validation**, even though labels are hidden.

For a second blinded grading pass, explicitly configure `JUDGE_MODEL`,
`JUDGE_API_KEY`, and `JUDGE_BASE_URL` (no fallback to generation credentials), then:

```bash
uv run python -m benchmarks.team_synthesis.judge \
  --source results/team-synthesis-v1 --out results/team-synthesis-v1-external-judge \
  --max-tokens 8192
```

This reuses the exact frozen answers and rubrics, and writes separate verdicts.
Use a different model and inspect disagreements; an external model is still a
fallible judge, not human ground truth. The first pass starts at concurrency 1;
concurrency can be raised after confirming successful calls. Resuming does not
change the fixed samples or regenerate completed answers.
The separate judge defaults to 8192 output/reasoning tokens: the first experiment
found that 3000 truncated several judgments. Truncated calls are errors, not zero
scores or passes. A changed judge budget requires a fresh judge output directory,
but reuses the source generations; keep the earlier failed records for audit.

The output manifest stores exact cases/prompts, hashes, randomization, git state
and settings. Per-call records retain messages, actual model, output, usage,
latency and errors. `summary.json` reports paired deltas and development/holdout
counts separately. Repeated generations are not independent task families. Token
usage is retained; dollar cost is not estimated without a verified tariff.

Do not promote a candidate based on this diagnostic set alone. After manual review,
use independent grading and new unseen cases, then paired end-to-end team runs with
fixed inputs/budgets. Include verification dispatch success, useful answer coverage,
unsupported factual upgrades, publication behavior, latency and token usage. A
better factual score accompanied by lost useful analysis is a regression to examine.
