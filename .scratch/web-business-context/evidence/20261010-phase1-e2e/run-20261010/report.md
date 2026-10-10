# 阶段 1 端到端验收（issue 01 §9.9.4）

- 模型：`deepseek-v4-flash-ga-260731`；口径：`runs.usage_json`（`server/usage.py`）；两臂各 3 轮，同一绑定研究内。
- 判定：**FAIL**

| 臂 | 轮 | prompt_tokens | cache_read_tokens | llm_calls | replay.decision | dump(messages) | 前缀=上一轮 dump |
|---|---|---|---|---|---|---|---|
| treatment | 1 | 16406 | 0 | 1 | skipped: no_payload | 3 | None |
| treatment | 2 | 12725 | 0 | 1 | skipped: system prompt mismatch | 3 | False |
| treatment | 3 | 12740 | 0 | 1 | skipped: system prompt mismatch | 3 | False |
| control | 1 | 16418 | 0 | 1 | skipped: no_payload | 3 | None |
| control | 2 | 12734 | 0 | 1 | skipped: no_payload | 3 | False |
| control | 3 | 12728 | 0 | 1 | skipped: no_payload | 3 | False |

## 判据

- FAIL — `t2_covers_t1_prompt`
- FAIL — `t3_covers_most_of_t1_t2`
- FAIL — `treatment_replayed_all_turns`
- PASS — `control_did_not_replay`
- PASS — `control_cache_cold`
- FAIL — `treatment_prefix_matches_previous_dump`

## 阈值

```json
{
  "t2_needs": 16406,
  "t3_needs_half_of": 14565.5,
  "control_must_stay_below": 8209.0
}
```
