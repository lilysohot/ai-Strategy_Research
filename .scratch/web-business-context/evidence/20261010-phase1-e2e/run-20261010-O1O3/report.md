# 阶段 1 端到端验收（issue 01 §9.9.4）

- 模型：`deepseek-v4-flash-ga-260731`；口径：`runs.usage_json`（`server/usage.py`）；两臂各 3 轮，同一绑定研究内。
- 判定：**PASS**

| 臂 | 轮 | prompt_tokens | cache_read_tokens | llm_calls | replay.decision | dump(messages) | 前缀=上一轮 dump |
|---|---|---|---|---|---|---|---|
| treatment | 1 | 16415 | 14336 | 1 | skipped: no_payload | 3 | None |
| treatment | 2 | 16817 | 16384 | 1 | used | 5 | True |
| treatment | 3 | 17053 | 16384 | 1 | used | 7 | True |
| control | 1 | 16412 | 14336 | 1 | skipped: no_payload | 3 | None |
| control | 2 | 12734 | 12288 | 1 | skipped: no_payload | 3 | False |
| control | 3 | 12731 | 12288 | 1 | skipped: no_payload | 3 | False |

## 判据

- PASS — `R4_some_late_turn_reuses_80pct_of_previous`
- PASS — `R5p_directional_treatment_above_control`
- PASS — `R5p_attributable_delta_ge_half_of_non_shared`
- PASS — `replay_used_from_turn_2`
- PASS — `control_never_replayed`
- PASS — `treatment_prefix_matches_previous_dump`

## 判据明细

```json
{
  "reuse_ratio_treatment": {
    "3": 0.974
  },
  "cache_read_delta": {
    "3": 4096
  },
  "shared_block_tokens": 12288,
  "superseded_criteria": {
    "R5_as_first_written_DELTA_ge_half_previous_prompt": false,
    "legacy_t2_covers_t1_prompt": false,
    "legacy_control_cache_cold": false
  },
  "pass": true
}
```
