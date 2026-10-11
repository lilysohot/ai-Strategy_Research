# S2 验收：会话状态归位（issue 01 §11.7）

- 两臂各 3 轮，**每轮一个独立进程**（`--turn N` 分次调用）；treatment 正常，control 每轮后删掉库中会话行。
- 模型与端点取自服务器 `.env`（跑前探针确认其上报 `prompt_tokens_details.cached_tokens`）。
- 判定：**PASS**

## 判据

- PASS — `P1_treatment_replays_from_turn_2`
- PASS — `P2_dump_gone_and_row_stored_every_turn`
- PASS — `P3_control_has_no_carrier`
- PASS — `P4_turn3_reuses_80pct_of_turn2_prompt`
- PASS — `P5_stored_prefix_matches_previous_turn`
- PASS — `P6_three_separate_processes`

## 判据明细

```json
{
  "treatment": {
    "1": {
      "prompt_tokens": 16346,
      "cache_read_tokens": 16000,
      "replay": "skipped",
      "stored_messages": 3
    },
    "2": {
      "prompt_tokens": 16608,
      "cache_read_tokens": 16256,
      "replay": "used",
      "stored_messages": 5
    },
    "3": {
      "prompt_tokens": 16870,
      "cache_read_tokens": 16512,
      "replay": "used",
      "stored_messages": 7
    }
  },
  "control": {
    "1": {
      "prompt_tokens": 16343,
      "cache_read_tokens": 16000,
      "replay": "skipped",
      "reason": "no_payload"
    },
    "2": {
      "prompt_tokens": 12659,
      "cache_read_tokens": 12288,
      "replay": "skipped",
      "reason": "no_payload"
    },
    "3": {
      "prompt_tokens": 12668,
      "cache_read_tokens": 12288,
      "replay": "skipped",
      "reason": "no_payload"
    }
  },
  "turn3_reuse_of_turn2": 0.9942196531791907,
  "pids": [
    53826,
    53872,
    53948
  ]
}
```
