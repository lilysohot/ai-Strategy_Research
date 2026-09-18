# I3-2 裁决单二轮复核（A1—A5）整改清单与执行记录

对象：同目录 [review.md](review.md)（write-once，未改动）登记的 A1—A5。
编号命名空间 **`RM-I32R2-*`**（I3-2 第二轮整改）；与上一轮 `RM-I32-*`、`RM-*`、`RM-I28-*`、
`RM-FC-*` 互不相通，**不得混引**。

## §0 口径与关闭判据

- 只改 I3-2 补料侧（新增共享文本层、改写生成器/自检、新增裁决应用器、裁决单、台账）与冻结链；
  **未改** `plugins/corpus/scoring.py`、守卫、I0A-4 金标字节（评分器仍按 r21 绑定核验）。
- 关闭判据：① 表中 `RM-I32R2-1—8` 全部实施且证据可复跑；② `validate_i0c_freeze.py` exit 0；
  ③ M5 只读复核 20 块零 miss/error；④ I3-0 基线 46 passed 与独立探针 10 passed 不回归；
  ⑤ **A1 原复现路径（改状态即开门）在整改后仍不得开门**（见 §3 实测）。
- 纪律：候选 ≠ 金标；本轮不跑真实链路（PG 联测属 I3-1 与正式冻结之后）；不得据合成夹具自证补料完整。

## §1 总表

| 编号 | 对应 | 级别 | 状态 | 落点 |
|---|---|---|---|---|
| RM-I32R2-0 | A2 前置裁定（审批件为唯一凭据） | P1 | 已裁定并入规格 | 台账 §I3-2、tasks §3.6、`contract.approval_path` |
| RM-I32R2-1 | A1 完整性门可跳过未决项 | P1 | 已实施 | 门改由审批件计算；反例 P10/P11/P12 |
| RM-I32R2-2 | A2 决策 JSON 未接通 + 模板表达不全 | P1 | 已实施 | 新增 `i3s2_apply_decisions.py`（审批件→投影→门）；反例 P13/P14 |
| RM-I32R2-3 | A3 锚点仅词面相近即被当完整证据 | P1 | 已实施 | `adequacy`/`uncovered_terms`/`union_uncovered_terms` + residual 门；反例 P15 |
| RM-I32R2-4 | A4 覆盖账不是完整语义账 | P2 | 已实施 | 按段并行登记数值与限定 + 整题验收 24 题入册 |
| RM-I32R2-5 | A5 展示与角色定义 | P2 | 已实施 | `required/supplementary/suggested`、source_coverage 直接展示锚点、清除旧批次数字、四类待填项 |
| RM-I32R2-6 | 收口（重冻 + 回归） | P2 | 已实施 | `i0c-r24` + 验证器 r24 块；validate exit 0 |
| RM-I32R2-7 | 待 U 逐项裁决 | — | **未关闭** | 要件 40 + 整题 24 + 负例 6 + 状态澄清 1 |
| RM-I32R2-8 | 补标注路径的可执行性 | P2 | 已实施（按设计阻断） | `补标注` 必须指向新 source-gold 版本，否则保持未决 |

## §2 逐项

### RM-I32R2-0（A2 前置裁定）——审批件是唯一凭据

- 裁定（实施方作出并写入规格，理由留存）：**批准只能经
  `evidence-targets-decisions.json` → `i3s2_apply_decisions.py` → `evidence-targets-approved.json`
  + `approval-report.json`**；候选文件里的 `adjudication.status` 降级为信息字段。
  理由：复核实测"改状态即放行"，说明状态字段承担了它不该承担的验收职责；审批件必须绑定
  候选/query/source gold 哈希，才谈得上"针对哪一版预期批准"。
- 落点：生成器 `contract.approval_path` + 每题 `adjudication.note`；裁决单 §0/§6；台账与 tasks。

### RM-I32R2-1（A1）——完整性门

- 实施：门（`i3s2_apply_decisions.evaluate`）逐项核对
  ① 要件裁决覆盖（每个 `item_id` 一条 `facet_decisions`，`decision` 合法、`reason` 非空）；
  ② 有答案题**整题验收**（`question_reviews.decision=批准` 且 `reviewed_against_requirement=true`）；
  ③ 负例（`negative_reviews.decision=批准` 且 `full_text_coverage_confirmed=true`）；
  ④ 来源槽位状态澄清（`resolution` ∈ {残留描述, 实质未决}，实质未决即阻断）；
  ⑤ 锚点覆盖度（`partial` 须改选/补标注或 `residual_accepted=true` + 理由）；
  ⑥ 审批件输入哈希未过期；⑦ 空 `reviewer`/`reviewed_at` 直接阻断。
  **`adjudication.status` 不参与任何一条**。
- 反例（P10—P14）：全题状态改 `approved` 且无审批件 → `stage=no_decisions`、`ready=false`；
  空审阅人 → blocked；要件缺项 → blocked 并列出未决 item_id；负例未确认 → blocked；
  审批件哈希过期 → blocked。P16：完整合成审批件可开门并产出批准投影（证明门不是死门）。

### RM-I32R2-2（A2）——审批链路

- 实施：新 `i3s2_apply_decisions.py`；审批件字段覆盖复核点名的四类内容：
  `question_reviews`（含 `machine_ready` 题整题批准）、`negative_reviews`（覆盖结论与依据）、
  `human_status_clarifications`、`supplement`（新增引文引用 + `source_gold_revision`）、
  `based_on`（候选/query/source 三重哈希）。
- 模板表达力：`补标注` 必须给 `supplement`，且**指向的 item 必须尚不存在于冻结 source-gold**
  （否则提示改用批准/改选）；即使形式合法，只要 `source_gold_revision` 不是已冻结版本，门保持阻断
  ——"新引文必须来源核验后建新标注版本，不能从题目要求生成伪原文"由此机器化（RM-I32R2-8）。
- `驳回` 语义：只驳回候选锚点，原题要求仍留在覆盖账 → 该 item 记为未决，门不放行（不会因为
  "驳回"而删掉要求）。

### RM-I32R2-3（A3）——锚点覆盖度

- 实施：共享文本层算词元（ASCII/数字 token + 过滤后的 CJK 二元组，日期先掩码）；每条锚点给
  `adequacy`（full/partial）与 `uncovered_terms`；面级给 `union_uncovered_terms`
  （多锚点未覆盖集合的**交集**，避免把"另一锚点已覆盖"的词算成缺口）。
  两道降噪：文档频率 ≤ max(2, 20%×item 数) 才算判别性；二元组按字序包含即视为覆盖
  （去掉"五主体/五个主体"这类切分差）。
- 效果（实测）：复核点名的五处已显式标为部分覆盖并列出未覆盖词元——
  `macro-004-03`（四路径/化债/财政支出/缓解…）、`macro-005-01`（堵点/税负/拖累/收入…）、
  `macro-006-01`（偏头部/国企/全国…）、`industry-003-01`（预测列/区分/分开）、
  `industry-006-01/03`（援引/供应链消息、来源/保留/限定）；`industry-002-02`、`industry-004-01/02`、
  `industry-008-01` 的首选已是脚注/R32 单元格，纯碱/R134a 等裸值只作 `search_hint`（不进可批准集合）。
- 面级/条目级双展示：裁决单每条锚点标"首选/备选（仅供检索线索）"与"完整覆盖/部分覆盖"。

### RM-I32R2-4（A4）——覆盖账

- 实施：`evidence_requirement` 先按 `；;。` 切子句；**子句既有数值又有标记时再按逗号拆段**
  （这样"报告称…超过60%"与"必须区分附条件判断、市场预期和正式决定"分离，后者单独立项），
  其余子句不再无差别逗号切分（避免"约四个月""均下降"被切成无锚点假缺口）。
  每段**并行**登记数值要件与定性要件；答案侧口径另记 `answer_constraints` 并标注核验落点 I3-5。
- 效果（实测）：`macro-003` 的"区分"要求、`company-001` 的"标明是报告预测"、`industry-003` 的
  "2026E为预测列"、`macro-007` 的两个公式等均已入账；`blocked` 收敛为复核认定的 2 题
  （`macro-003` 强就业、`macro-004` 本文聚焦前四者）。
- 配套：裁决单新增**有答案题整题验收**（24 题）一节，明确"要件裁决完成 ≠ 整题验收完成"，
  并要求对照冻结 requirement 逐段核对——机器的覆盖账不承担完整性证明。

### RM-I32R2-5（A5）——展示与角色

- `supporting` → **`supplementary`（补充，非必需）**，契约声明"本版不声明任何替代/等价关系"；
  生成器/核对单/裁决单同步改词。
- `source_coverage` 条目直接展示锚点候选（此前 `company-008` 三个 source_coverage 项下为空，
  现分别显示 `company-008-claim-001#4`（维持·强推）与 `company-018-claim-001#3`（首次覆盖·优于大市））。
- 清除旧批次数字：`contract` 里"60 条 item"表述改为不依赖具体条数；裁决单首段改为四类待填项
  （要件 40 / 整题 24 / 负例 6 / 状态澄清 1）。
- 裁决项类型化提示：`answer_constraint`（只需依据，无需 chosen）、`value_equivalence`、
  `unmatched_value`（补标注/改选）、按来源 `source_coverage`、其余要件各给不同"决定口径"；
  应用器对 `answer_constraint` 的"批准"不要求 chosen（否则该类型无法批准）。

### RM-I32R2-6（收口）

- 新增 `i3s2_remediation_r24_freeze.py`（冻结前强制：规则版本 v5、输入哈希一致、自洽/反例 0 failed、
  审批件不存在、`approval-report` 为 `no_decisions`/`ready=false`）。
- 冻结 **`i0c-r24`**（parent=r23）：绑 `i3_2_tooling`(4) + `i3_2_assets`(5) + `i3_2_archive`(4) +
  验证器 + 2 台账；`validate_i0c_freeze.py` **exit 0**。
- r23 被同名覆盖的字节已归档并在 r24 绑定：`candidates-v4.json`、`review-v4.md`、
  `adjudication-v1.md`、`verification-v2.json`（哈希与 r23 绑定逐一核对一致）。

### RM-I32R2-7（未关闭，交 U）

- 要件裁决 **40** 项 + 整题验收 **24** 题 + 负例覆盖 **6** 题 + 来源状态澄清 **1** 项；
- 其中 `macro-003`「强就业降低加息顾虑」、`macro-004`「本文聚焦前四者」需补标注；
- `partial` 锚点 9 条需改选/补标/写 residual；
- 回填审批件并通过门（`ready=true`）后**另建冻结修订**，不得复用 r24。

### RM-I32R2-8（补标注路径）

- `补标注` 在门内被设计为**先阻断**：形式必须给 `supplement`（slot/item_index 须在该题候选来源范围内、
  且指向冻结标注中尚不存在的 item），并声明新 `source_gold_revision`；在新区块版本形成之前一律未决。
  这样"用题目要求生成伪原文"或"用已有 item 冒充新引文"都无法开门。

## §3 A1 复现路径实测（整改前后对照）

同一复现脚本（把候选 `adjudication.status` 全改为 `approved`，不带审批件）在整改后：

```text
A1-a 全题 status=approved 且无审批件 -> no_decisions ready= False
A1-b 部分题 status=approved -> no_decisions ready= False
required buckets: {"facet_decisions": 40, "question_reviews": 24, "negative_reviews": 6,
                   "human_status_clarifications": 1}
```

即：**原漏洞路径已关闭**；门期望的四类裁决数量由门自己算出来，U 不能少的项被逐一点名。

## §4 复现命令

```bash
cd /home/administrator/FrontierAgent
env -u PYTHONPATH uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_evidence_targets.py
env -u PYTHONPATH uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_verify_candidates.py
env -u PYTHONPATH uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_apply_decisions.py
env -u PYTHONPATH uv run python \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py; echo "EXIT=$?"
```

M5 只读复核与 I3-0 门（i3 守卫 env）：

```bash
env -u PYTHONPATH uv run python -c "
import runpy;from pathlib import Path
BASE=Path('.scratch/corpus-evidence-pipeline/ingestion-rebuild').resolve()
v=runpy.run_path(str(BASE/'audits/20260918-m5-review/verify_matrix.py'))
r=v['verify'](BASE/'audits/20260918-m5-review/evidence');print(len(r['blocks']),r['misses'],r['errors'])"
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH=$PWD PYTHONDONTWRITEBYTECODE=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 CORPUS_GUARD_PHASE=i3 \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3.json \
  .venv/bin/python -B -m pytest --noconftest -c /dev/null -p no:cacheprovider \
  -p plugins.corpus.preparation.guard_pytest tests/test_corpus_scoring.py -q
```

## §5 事实基线（本轮实测）

- 候选（`evidence-mapping-5`）：30 题 ⇒ machine_ready **2** ／ pending_human **20** ／ blocked **2**
  ／ 负例 **6**；目标 54 条 = 必需 **35** ／ 补充 **4** ／ 待批准锚点 **15**（partial 9）；
  要件裁决队列 **40** 项；机器已批准 **0**。
- 自检：`self_consistency.failed = 0`；`regression_probes` **16/16 passed**；
  `completeness_gate` = `stage=no_decisions`、`ready=false`。
- 裁决应用器：`stage=no_decisions`、`ready=false`，期望裁决 `{facet_decisions:40,
  question_reviews:24, negative_reviews:6, human_status_clarifications:1}`。
- 冻结链：`i0c-r24`；`validate_i0c_freeze.py` **exit 0**。
- 门禁：M5 只读复核 **20 blocks / misses=[] / errors=[]**；`tests/test_corpus_scoring.py`
  i3 守卫 env **46 passed**；I3-0 独立复核探针 **10 passed**。

## §6 证据指纹（sha256）

| 件 | sha256 |
|---|---|
| `i3-2/evidence-targets-candidates.json` | `43ed1199672fc6bc963fc4f77df77e45ac350c85daa48d0154d2df4794c1abe5` |
| `i3-2/evidence-targets-review.md` | `d4b837cd158a331d098eb3aa32e0cf34d02752abd475653d9882e8af86e162e4` |
| `i3-2/evidence-targets-adjudication.md` | `778f651c4f88cbe099565ad030c2d2c3198d3b24ba5754e82181157f40e65f34` |
| `i3-2/evidence-targets-verification.json` | `e212bf9a824dbd8771fd7779625b4ad7baf59ab9631ad700469271bcbb93a23d` |
| `i3-2/approval-report.json` | `59a34df0a906afbbf1e620a8008eb84f903ee045da3c8b7ad1bc1cdca9df4e7c` |
| `i3s2_textutil.py` | `a5c763a3a36ace35b6e775ad6da3171df36747ceebe39a23d50ef9e83154f2f0` |
| `i3s2_evidence_targets.py` | `b0b5c694527630c178429ae0ac0fb9ba563f52c35ce03503f48f7bb2f56ac025` |
| `i3s2_verify_candidates.py` | `04a50cb7b1321eedb4cd180dbb114bbfad67cddc3d3f679396cc6f58821f8f76` |
| `i3s2_apply_decisions.py` | `ae9d91ef614a20f99a1da0af63e1a0611f79da0bca48ba7e8dfcbe4990292faf` |
| `freezes/i0c-r24.json` | `f91a7ad51a389094862a6d24ac936f22a77387fe782ade83b114b1c24edb0189` |
| `freezes/validate_i0c_freeze.py` | `f31abb8381e80ac089ff7eae3b926eb410a8010a6c8a364dc91e7e9dabc5c255` |

**注意**：`ready=false`（候选阶段）是**正确**状态；`self_consistency` 与 16 条反例通过**不等于**
补料完整，也不等于已有任何一项人工批准（本轮机器批准数为 0）。
