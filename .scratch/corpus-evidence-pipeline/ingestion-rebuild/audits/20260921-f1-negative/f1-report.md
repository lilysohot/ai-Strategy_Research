# F1 负例误报 6→0（M6 硬判据）— 审计报告

- 生成：2026-09-21 14:41；类型：判定层拒检回测（纯消费侧，非冻结回归）
- 语料：index-4-zhcfg-2（8 份 active builds）
- scorer：工作树空白规约（NOT frozen）；0 model_calls；只读 PG
- 关联：spec §6.0/§14.4 判断 4、issues/06-negative-6to0.md
- 状态：§6.0 推迟限制已由 U 2026-09-21 解除并重新立项，本报告为其实施证据

## 一、根因

6 条 no-answer 题（company/industry/macro-009/-010）走**问题全部词元 OR** 检索，
任意单个弱命中的候选（宏观文档里出现"利率/居民/支出/美联储"，化工周报出现"氩气/英伟达/PTFE"，
国信半导体表值出现"8231"）即被拉回；评分侧 `_score_negative` 只判"是否有文档被检索"
（`plugins/corpus/scoring.py`），于是误报。判定侧看不到"命中词元是否构成实质答案"。

## 二、机读归因（验收 2：每题固化 token→命中块）

产物 `f1-attribution.json/.md`。全部 6 题均可归因：OR 检索各命中 244–369 个块、8 个源全中，
且**单元级（句）词元共现密度已很高**（macro-010「中国/居民/支出/新房/购房」同 unit；
macro-009「决定/利率」「美联储/会议/公布」同句；company-010「8231」落入国信表值）。
⇒ 纯"多词元共现 / 实体+限定词"判定门无法闭环 6→0（只能干净兜住 company-009：
全语料无 `光力`/`归母` 等题旨实体），印证 issue 中"①无法完整兜住时补做②"的条件已触发。

## 三、采用杠杆（U 确认 2026-09-21）

**判定层拒检兜底（收紧查询 + 拒检谓词）**，全部落在消费侧/判定层：

- `plugins/corpus/preparation/negative_query.py`（新模块）：
  - `tighten_no_answer_query`：no-answer 题的全部**内容词元**（去停用/去单字）以 websearch AND 连接；
  - `is_relevant_candidate`：拒检谓词，同一单元须满足**全部内容词元**才算实质候选。
- 可行性探针 `f1-probe-tight.json/.md`：6 条收紧 AND 查询**均归零**（语料内无任何单位同时满足全部内容词元）。

**不触 `search_pg.py` / `scoring.py` 字节**；只作用于 no-answer 观测构造；与有答案题 OR 查询 / S1 命中池**完全独立**。

## 四、回测结果（`f1_backtest.py`，只读）

| 指标 | i42 基线 | F1 | Δ |
|---|---:|---:|---:|
| false_positives | 6 | **0** | −6 |
| EvidencePass | 12/24 | 12/24 | 0 |
| S1_candidates（79 目标） | 66 | 66 | 0 |
| S2_doc_topk | 60 | 60 | 0 |
| S4_matched | 44 | 48 | +4 |

6 条负例 retrieved_documents 全部为 **0**。

```
self_check:
  I-M6-1_fp_zero: true        # 任一 no-answer 题 retrieved_documents==0，计分不误报
  I-M6-2_S1_66 : true         # 有答案题 S1_candidates 恒 66 不降
  I-M6-2_S2_60 : true
  evidence_no_regress: true    # EvidencePass 12/24 不低于基线
```

## 五、留存产物

- `f1_attribution.py` → `f1-attribution.json/.md`（验收 2：每题 token→命中块归因表）
- `f1_probe_tight.py` → `f1-probe-tight.json/.md`（收紧 AND 可行性探针）
- `f1_backtest.py` → `f1-summary/.observations/.trace/.score/.funnel-targets.json`（回测与自检）
- `plugins/corpus/preparation/negative_query.py`（产品化 reusable 拒检门）
- `tests/test_corpus_negative_query.py`（11 条永驻测试）

## 六、验收核对

1. 6 题 `retrieved_documents` 0 ✓（f1-summary.negative）
2. 每题 FP 归因表固化 ✓（f1-attribution）
3. `max_false_positives = 0` 通过 ✓（false_positives=[]，self_check.I-M6-1_fp_zero）
4. 有答案题 79 目标漏斗不回归 ✓（S1=66 / S2=60，EvidencePass=12/24）

## 不变式与边界

- 不降 `max_false_positives` 门槛；不改金标与"期望 0"语义；不在本票提升有答案题 EvidencePass（那是 F2）。
- 判定层为纯消费侧新增、不触 `scoring.py` 字节 ⇒ **不新增冻结修订**。
- 回归：corpus 全量 `tests/test_corpus_*.py` 742 passed / 12 skipped；ruff(pyright) clean。