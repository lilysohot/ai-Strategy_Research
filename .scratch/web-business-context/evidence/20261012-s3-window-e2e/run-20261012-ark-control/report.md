# S3 验收：跨轮窗口的前缀性质（issue 01 §12.5 / §12.8）

两臂同一份代码，唯一差别是 `REPLAY_MAX_TURN_STEP`（treatment 5 = 新默认，control 0 = 迟滞前）。
每臂 45 轮、每轮一个独立 worker 子进程；载体是数据库（S2）。

- **通过：False**

| 判据 | 结果 |
|---|---|
| C1_complete_both_arms | FAIL |
| C2_carrier_moved_every_turn | PASS |
| C3_prompt_within_budget | PASS |
| C4_cut_flaps_once | FAIL |
| C5_memory_written_once_per_cut | PASS |
| C6_arms_differ | FAIL |
| C7_prompt_plateaus | PASS |

| 口径 | 值 |
|---|---|
| 平均复用率 treatment（全 44 次转换） | 83.0% |
| ├ 前缀保持轮（39 次） | 89.8% |
| │ ├ ≥80% 的轮 | [2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22, 24, 25, 26, 27, 28, 30, 32, 33, 36, 37, 38, 39, 40, 44] |
| │ └ 端点侧 miss（我方前缀连续却未命中） | [9, 31, 34, 42, 43, 45] |
| └ 裁剪轮（构造性 miss，system+tools only） | [17, 23, 29, 35, 41] |
| 每个裁剪轮之后的复用（两轮） | {"17": [0.9841, 0.9903], "23": [0.9865, 0.9925], "29": [0.9892, 0.3425], "35": [0.9894, 0.9939], "41": [0.3559, 0.3418]} |
| 摘要块变化次数（裁剪 5 次） | 4 |
| stopped_by | {"treatment": ["no_tool"], "control": ["no_tool"]} |

逐轮 prompt / cache_read 见 `results.json` 的 `detail`。
