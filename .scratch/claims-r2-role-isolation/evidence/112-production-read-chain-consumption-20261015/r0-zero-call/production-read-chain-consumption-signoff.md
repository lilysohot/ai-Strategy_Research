# 第一笔经生产读链的真实消费冒烟 — 立项签认件（112 号）

- 日期：2026-10-15；状态：**草案待签**（签名栏留空，签认后以签名栏为准）
- 被签对象：`production-read-chain-consumption.proposed.json`（草案哈希见 MANIFEST.json）

## 一、签认覆盖（covered）

1. **范围**：两源各有界 1 题，共 2 次 M_main 运行；查询走**生产 store root（gen-2 head）**；工具白名单只含 `corpus_semantic_query` + `corpus_submit_manifest`（A4 enforce）。
2. **五条预注册判据**（C1–C5）：查询记录实际送达 / A4 verified / 零抽取调用 + 零生产 PG 写入 / 缺口命中返回覆盖状态 / HTTP 只读验收。
3. **止损规则**：任一判据未过即停下报裁，不现场放宽、不换题、不补跑（106 号 D3 先例）。

## 二、需你填写（未预填）

- **预算 ceiling**：`proposed.json` 的 `budget.ceiling_tokens` 当前为 **null**。参照 43 号实测：2 题 = 6 成功响应 + 1 stalled + 4 次工具调用；`max_turns=8`、并发 1。请给出 token 上限或明确上限口径。
- **两个问题的文本**：冻结后不改（我按 43 号先例拟单源单事实题，待你确认或指定）。

## 三、不覆盖（does_not_cover）

- 不声明整篇覆盖、研究质量或生产放行（生产放行已由 108 号签认件覆盖）；
- 不改动生产 store、生产 PG、已签门/契约/金标/发布件任何字节；
- 不含补抽、金标修订、relations 抽取、web 前端页面、claims 进 PG 写链、e6_holdout。

## 四、签认

```
reviewer:xyl
adjudicator:xyl 
signed_on:2026-10-15
```

（签名后由零调用脚本出生效件；未签拒绝、哈希漂移拒绝、生效件不可覆盖重出。）
