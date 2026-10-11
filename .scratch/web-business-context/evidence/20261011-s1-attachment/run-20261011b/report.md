# S1 验收：带附件一轮 + 纯文本一轮（issue 01 §10.7）

- 模型：`deepseek-flash`；口径：`runs.usage_json`（`server/usage.py`）；同一绑定研究（会话）内两轮。
- 第 1 轮带真实附件（`inputs/brief.md`）并把路由构造的说明文本交给 worker；第 2 轮纯文本。
- 判定：**PASS**

| 轮 | 附件 | prompt_tokens | cache_read_tokens | llm_calls | summary.replay | usage_json.replay | dump(messages) | 前缀=上一轮 dump |
|---|---|---|---|---|---|---|---|---|
| 1 | True | 16414 | 128 | 1 | skipped: no_payload | skipped | 3 | None |
| 2 | False | 16953 | 16384 | 1 | used | used | 5 | True |

## 判据

- PASS — `C1_note_not_in_system_prompt`
- PASS — `C2_note_in_user_message`
- PASS — `C3_system_prompt_identical_across_turns`
- PASS — `C4_turn2_replay_used`
- PASS — `C5_turn2_prefix_matches_turn1_dump`
- PASS — `C6_turn2_cache_read_ge_80pct_turn1_prompt`

## 判据明细

```json
{
  "reuse_ratio_turn2": 0.9981722919458998,
  "turn1_prompt_tokens": 16414,
  "turn2_cache_read_tokens": 16384,
  "system_prompt_len": [
    7749,
    7749
  ],
  "system_prompt_diff": null,
  "usage_json_carries_replay": true
}
```
