# I3-2 补料独立复核（2026-09-18）整改清单与执行记录

对象：同目录 [review.md](review.md)（write-once，未改动）登记的 F1—F5 与「已登记人工项」6 条。
编号命名空间 **`RM-I32-*`**；与 `RM-*`（I2-5）、`RM-I28-*`（I2-8/I2-4）、`RM-FC-*`（I2 全链路）
互不相通，**不得混引**。

## §0 口径与放行条件

- 本轮只改 I3-2 补料侧（生成器、验证器、候选/核对单/裁决单、验证报告、台账文案）与冻结链；
  **未改**评分器 `plugins/corpus/scoring.py`、守卫、I0A-4 金标字节（评分器仍按 r21 绑定核验）。
- `review.md` 为 write-once，本清单是**另起文件**的整改记录，不回写复核报告。
- 关闭判据：① 表中 `RM-I32-1—9` 全部实施且证据可复跑；② `validate_i0c_freeze.py` exit 0；
  ③ M5 只读复核 20 块零 miss/error；④ I3-0 基线 46 passed 与独立探针 10 passed 不回归。
  **U 项（RM-I32-10）不属于 A 侧可关闭范围**。
- 纪律：候选 ≠ 金标；本轮**不跑**真实链路（PG 联测属 I3-1 与正式冻结之后），不得据合成观测
  自证"补料完整"。

## §1 总表

| 编号 | 对应 | 级别 | 状态 | 落点 |
|---|---|---|---|---|
| RM-I32-0 | F4 前置裁定 | P1 | 已裁定并入规格 | 台账 §I3-2、tasks §3.6 |
| RM-I32-1 | F1 只证数字不证要求 | P1 | 已实施 | 要求覆盖账 + 批准状态单列 |
| RM-I32-2 | F2 丢表格身份 | P1 | 已实施 | `locator` row/col + `constraints`；反例 P1/P2 |
| RM-I32-3 | F3 无关强制目标假失败 | P2 | 已实施 | 日期掩码 + 字母边界 + 逐次出现 + 三层角色；反例 P3—P5/P7 |
| RM-I32-4 | F4 分母口径文案 | P1 | 已实施 | `contract` + 核对单 + 裁决单 + 台账 + tasks |
| RM-I32-5 | F5 往返自检 ≠ 完整性 | P2 | 已实施 | 自检三段 + 完整性门 + 反例 P6/P8 |
| RM-I32-6 | 人工项 1（`company-004` 的 `13.40`） | P1 | 已实施（待裁决） | 数值等价入队 + quote 不改写；探针 P9 |
| RM-I32-7 | 人工项 2/3/4（`company-008`/`industry-006`/`macro-004`） | P1 | 已实施（待裁决） | 完整 quote/定位预览 + 按来源首选 + IDF 排序 |
| RM-I32-8 | 人工项 5/6（负例覆盖 + 人工状态矛盾） | P2 | 已实施（待裁决） | `negative_check` + `human_status_conflicts` |
| RM-I32-9 | 收口（重冻 + 回归） | P2 | 已实施 | `i0c-r23` + 验证器 r23 块；validate exit 0 |
| RM-I32-10 | 待 U 逐项裁决 | — | **未关闭** | 裁决单 36 项 + 2 道缺标注 + 6 负例 + 状态澄清 |

## §2 逐项

### RM-I32-0（F4 前置裁定）——EvidencePass 分母

- 现状：台账原写"逐 item（60 条）vs 槽位聚合（宽）由 U 二选一"，与架构 §12.3
  「满足全部证据的题数 / 证据题数」冲突。
- 裁定（实施方作出并写入规格，理由留存）：**分母 = 逐题**；item 条数与槽位聚合只作诊断展示。
  理由：架构 §12.3 已定义验收合同，台账属转述错误；若要用槽位聚合降低必需证据要求，
  须先改架构的验收契约，不在补料单里选。
- 落点：生成器 `contract.evidence_pass_denominator`；核对单与裁决单首段；台账 §I3-2 与
  执行清单行；tasks §3.6。

### RM-I32-1（F1）——要求覆盖账

- 实施：`evidence_requirement` 按子句切分为**数值要件**与**定性要件**；每题输出
  `requirement_clauses` / `requirement_facets`；定性要件一律不自动批准，只给锚点建议并进入
  `pending_human`；`machine_status` ∈ `machine_ready` / `pending_human` / `blocked`，
  且**批准状态单列** `adjudication.status`（默认 `pending`）。
- 效果（实测）：复核点名的五处漏条件现已显式可见——`macro-003` 的"通胀下行有限"条件句
  （→ `macro-038-claim-001#3` 首选锚点）、`macro-005` 的两个堵点、`macro-006` 的样本边界、
  `macro-008` 的样本/风险限定（→ `macro-060-claim-001#4` 首选锚点）、`industry-001` 的注2 口径。
- 余项：`macro-003`「强就业降低加息顾虑」与 `macro-004`「本文聚焦前四者」在冻结标注中
  **无承载 item** → 题级 `blocked`，需补标注或由 U 裁定（RM-I32-10）。

### RM-I32-2（F2）——单元格身份

- 实施：表格 item 的 `row/col/cell/unit/period` 进 `constraints`；`row:/col:` 写入 `locator`
  （与 `page:N` 并列）。`EvidenceTarget.matches` 要求 locator token 全集包含 → 同值不同单元格
  不可互换。约定写入 `contract.structural_identity`：**I3-1 必须由权威侧产出**这些 token
  （`read_pg.fetch_cell` 的页/行/列），不得由适配器从金标回填。
- 证据：`industry-001` 三条 required 分别带
  `row:纯碱 col:价格分位` / `row:纯碱 col:价差分位` / `row:纯碱 col:开工率`；
  反例 P1（只给 `page:10`）与 P2（用价差分位顶价格分位）均**必须失败**。

### RM-I32-3（F3）——必需/可替代分层

- 实施：① 日期/期间先掩码（`industry-004` 的 `01/07/27/26` 不再命中各产品行）；
  ② 数值 token 边界收紧到字母（`8230CF` 不再命中 `8230`）；
  ③ **同一数值的每一次出现都是独立要件**（`0.0%` 出现两次 ⇒ 两个不同单元格），
  不再因去重而少取一列；
  ④ 覆盖全部数值要件的最小集合为 `required`（IDF 加权重叠排序 + 未占用优先），
  其余命中降 `supporting`（不计入必需判定），定性锚点降 `suggested`（批准前不计入必需）。
- 证据：`company-005` 现为 `required={company-028#0,#1}`、`supporting={company-024#2}`，
  `company-060#2`（8230CF）不再出现；`industry-004` 的必需集合由脚注锚点构成，
  反例 P4（只给注1+注2）通过、P3（缺注2）失败；P5 证明可替代证据缺失不判失败。

### RM-I32-4（F4）——文案修正

- 落点见 RM-I32-0；另在核对单/裁决单显式写"item 覆盖统计是诊断，不是分母"。

### RM-I32-5（F5）——自检三段

- 实施：`i3s2_verify_candidates.py` 输出 `self_consistency` / `regression_probes` /
  `completeness_gate` 三段，判定分开打印；完整性门要求"全部正例已批准 + 无未决要件 +
  无待补标注 + 负例覆盖已确认"，当前 `ready=false`（0 题获批、24 题被拦）为**正确状态**。
- 独立反例 9 项（全部通过）：P1 结构身份必需、P2 同值错列、P3 漏脚注、P4 最小正确证据、
  P5 可替代非必需、P6 漏条件、P7 型号后缀边界、P8 重复来源入口拒绝、
  P9 数值等价显式入队且 quote 未改写。

### RM-I32-6（人工项 1）——`company-004` 的 `13.40`

- 实施：数值等价匹配（`Decimal` 规范化比较）：要求 `13.40` 与原文 `13.4` 视为同一数值，
  目标入队 `value_equivalence` 待人工确认；**原文 quote 保持 `13.4` 不改写**。
- 该题不再因"未命中 token"降级；`partial` 状态随规则一并废弃。

### RM-I32-7（人工项 2/3/4）——预览材料修复

- 实施：预览取消 60 字符截断，改为**完整 quote + 槽位/来源/页码/行列定位**；
  定性锚点按 IDF 加权重叠排序（通用公司名不再压过"强推/维持/首次覆盖"）；
  多来源题保证每个来源都出首选。
- 效果：`company-008` 的首选锚点为 `company-008-claim-001#4`（维持·强推）与
  `company-018-claim-001#3`（首次覆盖·优于大市）；`industry-006` 预览给出完整 PTFE 段
  （含 2027 年推出），不再截断；`macro-004` 给出 `macro-039-claim-001#1`（五主体）等候选，
  未覆盖的"四路径/前四者"显式列为待补。

### RM-I32-8（人工项 5/6）——负例与人工状态

- 实施：负例题输出 `negative_check`（误报/伪造引用/分母 + `human_basis` 是否仍写
  "需真人确认全文覆盖"）；来源槽位扫描出 `human_status_conflicts`——
  `macro-039-claim-001` 的 `human_basis` 写"待真人复核"但已有 `reviewer/reviewed_at`，
  已进裁决单 §4 待澄清（不擅自否认既有签认，也不抹去矛盾）。
- 负例仍不进三指标分母（既有合同，不是新豁免），裁决单 §3 提供覆盖确认栏。

### RM-I32-9（收口）

- 新增生成器修订脚本 `i3s2_remediation_freeze.py`；扩展 `validate_i0c_freeze.py` 的 r23 块
  （父指向、登记项、绑定白名单、禁止 `plugins/`/`tests/` 越界）。
- 冻结 **`i0c-r23`**（parent=r22）：绑 6 补料产物 + 3 本轮归档件 + 验证器 + 2 台账；
  `validate_i0c_freeze.py` **exit 0**（血缘 r23→…→i0a5）。
- **冻结前置**（脚本强制）：规则版本 = `evidence-mapping-4`、输入哈希与冻结 gold 实际字节一致、
  自洽 0 failed、反例 0 failed、`completeness_gate.ready is False`、已批准题数为 0。
  任一条不满足即拒绝出包——这是"不得据未过验证冻结"的机器化。
- 归档（write-once，字节与 r22 绑定一致）：`evidence-targets-candidates-v3.json`
  (`ac3560a255ea…`)、`evidence-targets-review-v3.md` (`9b4c06ebf7e3…`)、
  `evidence-targets-verification-v1.json` (`fda412bfb827…`)。

### RM-I32-10（未关闭，交 U）

1. 24 道正例**逐项**裁决：`evidence-targets-adjudication.md` §2 共 36 项
   （定性锚点、数值等价、多来源覆盖、答案侧口径）；
2. `macro-003`/`macro-004` 的两处要件无承载 item → 补人工标注或裁定；
3. 6 道负例 `evidence_required=false` 批准（`company-010`/`industry-010`/`macro-010`
   的全文覆盖确认）；
4. `macro-039-claim-001` 人工状态矛盾澄清；
5. 裁决结果回填 `i3-2/evidence-targets-decisions.json` 后，由验证器完整性门复核；
   `ready=true` 时必须**另建冻结修订**并同步台账，不得复用 r23。

## §3 明确不做

- 不改 `plugins/corpus/scoring.py` 与守卫（F4 的冲突是文案，不是评分器缺陷）；
- 不改 I0A-4 冻结金标 / 不复述候选业务结果 / 不用候选结果倒推答案；
- 不跑 PG 联测（属 I3-1 与正式冻结后；本轮零 PG、零模型、零来源正文读取）；
- 不再对数字匹配启发式做无边界调参——30 题规模按"固定映射 + 人工裁决"收口。
- 不修 `.scratch/` 脚本的静态类型噪声：这些文件不在 CI lint 范围
  （CI 只 lint `frontier_agent/ apodex/ benchmarks/ workflows/ plugins/ deploy/ tools/ scripts/`），
  且诊断同属"动态 JSON `dict[str, object]` 取键"这一类（HEAD 版 12 项、本版 47 项，无新类别）；
  脚本行为由实跑 + 9 条反例 + 冻结门验证。**冻结后若要改字节必须另建修订**，故本轮不追改。

## §4 复现命令

```bash
cd /home/administrator/FrontierAgent
env -u PYTHONPATH uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_evidence_targets.py
env -u PYTHONPATH uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_verify_candidates.py
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

## §5 证据指纹（sha256）

| 件 | sha256 |
|---|---|
| `i3-2/evidence-targets-candidates.json` | `3399458ce0e4cd417ca2740d6fbdfe1758d56a4108fd164fbd286d1961659439` |
| `i3-2/evidence-targets-review.md` | `9488c6cdc8135e51412f2e971763a3292b3f9907640d8935eb5d913b92216d24` |
| `i3-2/evidence-targets-adjudication.md` | `07a20dbe40d0084766eeaa5d41b75372a347c20fea2f12bb5c2b07b56a95b54a` |
| `i3-2/evidence-targets-verification.json` | `f1da1b3f74ac6d36dfc514dcd50309357e6353bb9b398c99fdd86208026e3eb3` |
| `i3s2_evidence_targets.py` | `fc4f2703d4659b6dc8e985e332fff15851dbae173597adee10a6018f62d0ca1f` |
| `i3s2_verify_candidates.py` | `0c7b3923d72fdbd724e759cd6447819ea9c588183ac567cc7da8c64e8ebe2d00` |
| `freezes/i0c-r23.json` | `6ed26728a0d83a020485dd1a55b76cfe012d5fcf73fcbc293793b511126d910b` |
| `freezes/validate_i0c_freeze.py` | `969bb65b0f7539317a78f227331180a62f1c844443103517cd6d038aa04e9a92` |

## §6 事实基线（本轮实测）

- 候选（`evidence-mapping-4`）：30 题 ⇒ machine_ready **3** ／ pending_human **19** ／ blocked **2**
  ／ 负例 **6**；目标 54 条 = 必需 **35** ／ 可替代 **4** ／ 待批准锚点 **15**；
  裁决队列 **36** 项；已批准 **0**。
- 自检：`self_consistency.failed = 0`；`regression_probes` **9/9 passed**；
  `completeness_gate.ready = false`（0 题获批、24 题被拦）。
- 冻结链：`i0c-r23`；`validate_i0c_freeze.py` **exit 0**。
- 门禁：M5 只读复核 **20 blocks / misses=[] / errors=[]**；`tests/test_corpus_scoring.py`
  i3 守卫 env **46 passed**；I3-0 独立复核探针 **10 passed**。

**注意**：`completeness_gate.ready=false` 是候选阶段的**正确**状态；
`self_consistency` 通过**不等于**补料完整，不得据此宣告 I3-2 完成（M6 未放行）。
