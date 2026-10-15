# 生产 PG/web 读链（生产放行门）立项（108 号）· 签认件

状态：草稿，**未签认**。`status = draft_pending_human_signature`。
零模型调用；**不写生产库任何表**（活动 build 已在位）；不改 95–107 号任何已落地产物。
U 于 2026-10-15 指示执行本项目；生产放行判定（里程碑放行）仍须 U 具名签认。

## 一、题目

把已放行的生产 PG 活动 build（`postgres`.corpus，8 源 8 发布全 active，zhparser 全文索引在位）
与已签认发布的 84 条 claims（106 号）接到 web 读链上，完成生产放行门前最后一段：
**claims 生产落位 → server HTTP 读链端点 → 端到端验收 → 常驻测试与落地记录**。

## 二、现状（零调用探查，见 current-state-scan.json）

- 生产 PG 活动 build + 全文索引**已在位**（M7 I4-4 重建、i0c-r5n 链内放行）：8 sources / 14 builds /
  8 publications 全部 active_build_id 非空；`corpus_chunks.search_tsv` + GIN + zhcfg 在位。
- 读链代码可用：`CORPUS_TARGET_DB=postgres` 下 `CorpusService.search` 实测返回命中；
  不设该 env 时 fail-closed 拒绝（守卫未放宽，实证记录在 scan 件）。
- claims 语义发布件仅在 106 号 evidence 目录的 live-store；`CORPUS_STRUCTURED_ROOT` 为空 ⇒
  服务侧与 agent 工具默认读不到 claims。
- server/ 零 corpus HTTP 端点；agent 工具（corpus_search 等）不是 HTTP 读链。

## 三、计划（S1–S4，全程零模型调用，生产库零写入）

| 步 | 内容 |
|---|---|
| S1 | 生产 claims store 落位：`data/corpus/structured-store`（git-ignored 数据目录约定），把 106 号两份已签裁定桥输入重放为**合并单 store**（plan→execute→publish 全走既有门，零调用），先在临时 root 复算 publication_id 与 106 号已发布件逐一比对一致后再落正式 root；`.env` 的 `CORPUS_STRUCTURED_ROOT` 指向正式 root |
| S2 | `server/routes/corpus.py` 读链端点：`GET /api/corpus/status`（读链/目标库/store 状态）、`GET /api/corpus/search`（band 检索）、`GET /api/corpus/documents/{doc_id}`（取证回读）、`GET /api/corpus/claims/{source_id}`（query_semantic，purpose=cite/compare/calculate）；全部挂 `get_current_user`（与既有路由同鉴权），语料侧 fail-closed 错误原样透传为 5xx/4xx，不吞 |
| S3 | 端到端验收：起后端，真实 JWT 经 HTTP 命中上述端点，验生产检索命中 + 两源 claims 三用途查询 |
| S4 | 常驻测试（server 层路由测试 + 语料侧回归）+ 落地记录 + MANIFEST |

## 四、验收判据（执行前写死）

1. 临时 root 重放的 publication_id 与 106 号已发布件**逐一相同**；正式 root 两源 claims 均可
   `query_semantic` 读出且三用途许可数与 106 号回填后一致（7/7/7 与 8/3/3）；
2. 四个端点均未带 token 返回 401；带 token 后 status/search/claims 全部 200 且数据来自
   生产库/生产 store；
3. 零模型调用；生产 PG 零写入（可由 corpus_publications.generation 与 activated_at 不变证明）；
4. 95–107 号与 106 号 bridge 输入/冻结件字节未动；
5. `pytest -k corpus` 与 server 层测试全绿；ruff/pyright 干净。

## 五、放行判定

本件执行完毕只形成**落地记录**；「生产放行门」是否放行由 U 具名签认
（独立复核 + U 签认，实施方不自宣）。

## 签名

reviewer:    xyl      adjudicator:     xyl     signed_on: 2026-10-15
