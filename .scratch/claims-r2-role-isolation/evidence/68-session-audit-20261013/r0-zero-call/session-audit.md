# 本会话（65/66/67/68 链）回溯审计报告 — 2026-10-13

**性质**：应 U 要求对本会话全部报告与产物做回溯核查。零模型调用。
**方法**：逐项对照"报告声称 vs 盘上产物"，含哈希复核、计数复核、跨报告一致性。

## 一、已核实一致的项

| 项 | 核验结果 |
|---|---|
| r1-r4 四臂 base 摘要 | 均为 attempts=1、succeeded/invalid——与各报告叙述一致 |
| r6 装配（I06/I41） | raw 15 / mappings 15，与报告一致 |
| r1-repair 修复 | 7/7 记账、packet completed，与报告一致 |
| r4-assembly（base） | raw 16 / mappings 16，与报告一致 |
| 67 预填 | 222 行、matched 33 / duplicate 8 / correct_extra 181、0 空行 |
| 金标范围 | 门 33 权威 48 条（adjudications.json gold_reference）；已签 8 金标全部在范围内 |
| base 段金标 | 12 条、全部 critical（此前"7 条"的口径已在 67 修正） |

## 二、本会话我犯过的错误（按时间序，全部已修复或有登记）

| # | 错误 | 后果 | 状态 |
|---|---|---|---|
| 1 | 探针 fail-open（沿用既有缺陷未察） | 空响应可被判通过 | 已改 fail-closed |
| 2 | 读 `LlmResponse` 不存在的属性（.content/.model/.usage）→ 误判"端点空响应" | 差点否决可用的 treatment 臂 | 0c 原始响应诊断纠正 |
| 3 | REPO_ROOT parents[4] 路径错 | 诊断脚本 CS_CONFIG_MISSING | 已修 |
| 4 | 读 profile.api_key（应为 cfg.credential） | AttributeError | 已修 |
| 5 | LedgerAttempt.role / LedgerTask.error_codes 两次投影崩溃 | 2 次响应丢失风险；1 次实际丢失（base 首次修复调用） | 已修 + 加断点续跑 |
| 6 | assemble 形状错（缺 5 必填字段） | 1 次重跑 | 已修 |
| 7 | duplicate 携带 matched_gold_id | 1 次重跑 | 已按契约剥离 |
| 8 | dataclass 误用 model_dump_json | 1 次重跑 | 已修 |
| 9 | **"203 unresolved" 口径错误** | 报告与 MANIFEST 传播了错误数字 | 67 已修正为 222（19 "accepted" 从未获签署） |
| 10 | **"7 条 critical" 口径错误** | base 段实际 12 条金标全部 critical | 67 已修正 |
| 11 | **空列表空洞真值**（all_slots_accounted 对 [] 返回 True） | 差点误报修复成功 | 人工复核拦下，脚本修正 |
| 12 | 执行器三连坑（plan 指纹 / deadline 过期 / 错误提取入口） | 2 次零调用失败 + 1 次调用走错分支 | 逐个修正 |
| 13 | 修复调用 #1 响应因崩溃丢失 | 浪费 1 次调用 | MANIFEST 如实记录 |
| 14 | r2 报告"base 失败=doubao 能力问题"的结论 | 被 A/B 推翻（deepseek 同样失败） | r3/r4 报告已推翻；r2 报告本体未改（write-once） |

## 三、仍存在的报告间不一致（未就地改，依赖本审计与后续记录）

1. **r2 报告含被推翻的结论**（见 #14）：单独阅读 r2 会被误导。修正以 r3/r4 报告 + 本审计为准。
2. **预注册与授权文件未互链**：`preregistered-two-arm.json` 的 signoff 为 null，实际授权在 md——追溯需人工拼接。
3. **r5 两件工作表哈希漂移**（并行会话就地改写）：MANIFEST.json 记录的是旧字节，SIGNOFF.json 登记了漂移但 MANIFEST 未重建指向新字节。
4. **67 目录命名**："draft_203_prefill" / "prefill-draft-203.json" 实为 222 行——文件名沿用错误口径。
5. **预算台账为近似值**：报告写"treatment ~16/30、control 10/30"，未做逐调用精确对账（探针/验证调用归属臂别易错）。
6. **duplicate 判定的未决依赖**：base 批 3 条 duplicate（I05/I07/I08）与 r5 批 4 条 duplicate（含 I41）的依据是"金标已被池内候选占用"——但**池内不存在任何已签 matched 裁定**。该依赖由 67 预填承接（已提议 I05/I07/I08/I41 的池内配对 matched）——**若你推翻这 4 行预填，对应 7 条 duplicate 裁定需连带重审**。

## 四、未验证/存疑清单（如实列出，未投入核实）

1. 67 预填 33 条 matched 提议为**机械匹配**（difflib ≥0.75），语义等价性未逐条核实——这正是留给人签字的环节。
2. 181 条 correct_extra 的"内容真实性"未核实（机械规则只验证了金标无对应 + evidence_quote 在案）。
3. base 段 12 条金标是否全部属于 48 范围（已签 7 条已验证在范围；其余 5 条未逐一验证）。
4. ef08 槽疑似同样适用 no_independent_proposition——按 U 指示未验证。
5. 各报告中的 token/成本数字未与 usage 记录逐条对账。

## 五、结论

链上产物与报告的核心事实（四臂结果、修复成功、两次装配 31 条、预填 222 行、金标口径 48/12）经复核**成立**。错误集中在**投影层与口径**（字段名、计数口径、文件命名），无一处触及模型调用的真实性或 fail-closed 语义。全部错误已修复或有登记；三处报告间不一致与五项存疑如实列出，待后续版本记录收敛。
