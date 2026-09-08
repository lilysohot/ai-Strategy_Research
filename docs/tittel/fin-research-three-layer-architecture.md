# 研报数据三层架构技术方案（含技术选型与数据接入）

> 适用项目：FrontierAgent（本仓库）
> 目标：将私有"研报库 + 宏观策略数据"接入 Agent harness，在**不丢失数据精准度**的前提下提供可溯源的检索与取证能力。
> 方案原则：**检索只负责定位，取证永远回到原文/源头；任何 LLM 摘要不得进入证据链。**

---

## 1. 方案总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        离线入库管道（ingest.py，CLI）              │
│  PDF/Word 研报 → 解析(页码保留) → 章节切分 → 三层索引构建           │
│  宏观结构化数据(CSV/Excel/DB) → 直查映射（不切块、不向量化）         │
└─────────────────────────────────────────────────────────────────┘
                    ↓ 落盘
┌──────────────┬──────────────────────┬───────────────────────────┐
│ L1 原文层     │ L2 检索层             │ L3 数值层                  │
│ originals/   │ chunks.db (FTS5 BM25)│ tables.db (SQLite)         │
│ PDF + 逐字    │ vectors.npz (稠密)   │ 规范化数值事实(带出处/单位/  │
│ chunk JSON   │ 混合检索 + RRF 融合    │ 事实-预测标记)              │
└──────────────┴──────────────────────┴───────────────────────────┘
                    ↓ 查询
┌─────────────────────────────────────────────────────────────────┐
│                三个 @tool（接入 FrontierAgent 工具白名单）          │
│  ① query_research_reports  定位（混合检索，返回 source_id+页码）    │
│  ② fetch_report_fulltext   取证（逐字原文，数字唯一合法来源）       │
│  ③ query_report_tables     取数（精确匹配，单位保留）              │
└─────────────────────────────────────────────────────────────────┘
                    ↓
         FrontierAgent ReAct / Agent Team 循环
         （提示词引用纪律 + 去重护栏 + 可选证据审计 Observer）
```

三层职责严格分离：

| 层 | 职责 | 精度承诺 |
|---|---|---|
| L1 原文层 | 唯一证据源，逐字存档 | 数值精度无损 |
| L2 检索层 | 只回答"看哪份报告哪一节" | 允许有损（定位不影响答案精度） |
| L3 数值层 | 表格数值精确匹配 | 精度无损（规范化+保留原始表述） |

---

## 2. 技术选型

### 2.1 文档解析

| 组件 | 选型 | 理由 |
|---|---|---|
| 正文解析 | **PyMuPDF (fitz)** | 速度快（百页研报秒级）、`page.get_text("dict")` 保留页码与坐标、纯 Python 可离线部署 |
| 表格抽取 | **pdfplumber** | 研报财务/数据表格识别最稳；与 PyMuPDF 并行使用（正文 vs 表格各取所长） |
| Word 研报 | **python-docx** | 章节标题可直接按样式提取，零 OCR 成本 |
| 扫描件兜底 | 不做 OCR（一期） | 扫描研报占比低且 OCR 引入数值错误风险，违背精度红线；直接标记 `needs_ocr` 人工处理 |

### 2.2 切块（Chunking）

- **策略**：按章节切分（正则匹配 `一、二、三、` / `1. 2.` 标题），章内 800–1200 token 滑窗，**仅章节边界重叠**（章节完整性优先于跨章上下文）
- **禁止**：入库时任何 LLM 摘要/改写——本项目 [web_fetch.py](../../plugins/tools/web_fetch.py) 已记录过摘要模型对数字密集短页"编造原文没有的百分比"的事故，此为精度红线
- **每个 chunk 必须携带**：`report_id / section_no / section_title / page_start / page_end`，出处元数据与文本不可分离

### 2.3 Embedding 模型

| 候选 | 结论 |
|---|---|
| **BGE-M3（选定）** | 中文研报最优性价比：中英混合支持好、原生稠密+稀疏（ColBERT+sparse）多路输出、可本地部署（无数据外发）、维度 1024 |
| OpenAI text-embedding-3 | 精度可用，但研报属敏感数据需外发 API，且按量计费 |
| Qwen3-Embedding | 备选，中文效果与 BGE-M3 相当 |

部署形态：`sentence-transformers` 或 Xinference/TEI 本地服务；入库与查询必须**同模型同版本**（版本号写入索引元数据，不一致即拒绝查询）。

### 2.4 稀疏检索（关键词/精确词匹配）

| 候选 | 结论 |
|---|---|
| **SQLite FTS5（选定）** | 零运维、单文件、内建 BM25、研报库规模（10⁴–10⁵ chunk）下毫秒级；中文分词用 **jieba 预分词后入库**（FTS5 unicode61 对中文按字切分，预分词后短语匹配质量显著提升） |
| Elasticsearch | 功能强但引入 JVM 运维成本，当前规模不值 |
| Tantivy | 性能好但 Rust 依赖，团队维护成本高 |

### 2.5 向量存储与检索

按数据规模分级，**接口先固定为 `dense_search(qvec, ids, top)`，实现可替换**：

| 规模 | 方案 | 说明 |
|---|---|---|
| ≤ 50 万 chunk（一期） | **npz + NumPy 暴力余弦** | 50万×1024 float16 ≈ 1GB 内存，暴力检索毫秒级，零依赖 |
| 50 万 – 500 万 | FAISS（IndexHNSWFlat） | 单机索引文件，仍零服务 |
| ≥ 500 万 / 多机 | Milvus 或 pgvector | 独立部署，仅替换 `store.py` 实现 |

### 2.6 重排（Rerank，可选二期）

- 选型：**BGE-reranker-v2-m3**（本地，与 BGE-M3 配套）
- 位置：RRF 融合后对 top-20 精排取 top-5
- 精度安全性：rerank 只改变"看哪段"的排序，不修改文本，无精度风险

### 2.7 融合策略

**RRF（Reciprocal Rank Fusion）**，`k=60`：BM25 top-20 ∥ dense top-20 → 融合排序。选 RRF 而非加权分数融合的原因：BM25 分数与余弦分数不可比，RRF 只用排名，免调参且鲁棒。

---

## 3. 数据库选型汇总

| 存储 | 引擎 | 用途 | 选型理由 |
|---|---|---|---|
| `chunks.db` | **SQLite + FTS5** | chunk 元数据 + BM25 全文索引 | 单文件零部署；事务保证入库原子性；FTS5 内建 bm25() 排序；规模内性能足够 |
| `vectors.npz` | **NumPy (float16)** | 稠密向量 | 一期规模下最简、最快、零运维；接口兼容 FAISS/pgvector 升级 |
| `tables.db` | **SQLite** | 规范化数值事实表 | 结构化精确匹配天然是 SQL 场景；`WHERE row_label = ? AND col_label = ?` 精确命中，杜绝模糊 |
| `originals/` | **文件系统** | 原始 PDF + 逐字 chunk JSON | 原文是不可变证据源，用最不可变的方式存：文件 + SHA256 清单 |
| `manifest.json` | JSON | 报告级元数据清单（含文件哈希） | 增量入库与完整性校验的依据 |

**明确不选**：向量数据库不作为接入边界（只作 L2 后端实现）；时序/宏观数据不入向量库（结构化直查）；Elasticsearch/Milvus 一期不引入（规模不匹配）。

---

## 4. 数据接入（端到端管道）

### 4.1 研报接入流程（ingest.py）

```
输入目录约定（任意组织，manifest 记录全量元数据）
~/reports/
   ├─ 2026-08-15_XX证券_2026下半年宏观策略展望.pdf
   ├─ 2026-08-20_YY证券_电力设备周报.docx
   └─ ...

命令：
python -m plugins.tools._fin_research.ingest --src ~/reports [--rebuild] [--verify]

六步管道（除 embedding 外零 LLM 参与，全确定性）：
 ① 扫描与去重：SHA256(文件) 对比 manifest.json，跳过已入库；记录增量清单
 ② 解析：PyMuPDF 逐页提取文本（保留页码 span）/ python-docx 按样式提章节
 ③ 切分：章节正则切分 → 章内 800-1200 token chunk → 逐字写 chunk JSON（L1）
 ④ 索引：jieba 分词 → FTS5 入库；BGE-M3 编码 → vectors.npz（L2）
 ⑤ 数值：pdfplumber 抽表格 → 单元格规范化 → tables.db（L3）
        "2.3%"    → value=2.3,  unit="%"
        "120bp"   → value=120, unit="bp"
        "约2.3%"  → raw="约2.3%" 保留原文
        列头含 E/预测/预期 → kind=forecast，否则 kind=fact
 ⑥ 校验与登记：--verify 抽样验证 chunk 能从 PDF 对应页逐字重现；
    manifest.json 登记 report_id/哈希/页数/as_of
```

**元数据来源约定**：优先解析文件名（`日期_机构_标题.pdf`）；有 API 的研报源（如 Wind/Choice 导出）由导出侧附 sidecar JSON（`同名.json` 存 title/broker/as_of），ingest 自动读取，文件名解析仅兜底。

### 4.2 增量更新与时效

- **增量**：哈希去重后只处理新文件；同 `report_id` 重复入库直接覆盖（幂等）
- **时效标记**：查询结果强制返回 `publish_date` 与 `as_of`；提示词要求 Agent 引用前检查时效，超龄数据需确认是否有更新版本
- **删除**：`ingest --prune --before 2024-01-01` 按 publish_date 清理过期索引（原文可保留）

### 4.3 宏观策略数据接入（独立于三层，直查模式）

宏观数据是结构化时序，**不切块、不向量化**，直接结构化查询：

```
输入形态 A：CSV/Excel 导出（指标 × 日期 × 数值 × 单位 × 修订版本）
  → ingest --macro ~/macro/  → macro.db (SQLite 时序表)

输入形态 B：已有数据库（Wind/Choice/自建库）
  → settings.py 配置连接串 → query_macro_indicator 工具直连（只读账号）
```

`macro.db` 表结构：

```sql
CREATE TABLE indicator (
  indicator_id TEXT,   -- "社融存量同比"
  region TEXT, freq TEXT,          -- "中国","月"
  period TEXT, value REAL, unit TEXT,
  revision INT, source TEXT,       -- 修订版本 + 发布机构
  as_of TEXT                       -- 数据截止时间
);
CREATE INDEX idx_ind ON indicator(indicator_id, period DESC);
```

精度要点：**保留 `revision`**（宏观数据常修订，答案须声明用的是第几版）；`kind` 同理区分实际值/预测值。

---

## 5. 代码结构

```
FrontierAgent/
├─ plugins/
│  ├─ tools/
│  │  ├─ fin_report_search.py      # @tool ① query_research_reports（定位）
│  │  ├─ fin_report_fulltext.py    # @tool ② fetch_report_fulltext（取证）
│  │  ├─ fin_report_tables.py      # @tool ③ query_report_tables（取数）
│  │  ├─ fin_macro_query.py        # @tool ④ query_macro_indicator（宏观直查）
│  │  └─ _fin_research/
│  │     ├─ schema.py              # ReportMeta / SectionChunk / NumericFact
│  │     ├─ settings.py            # 数据路径、模型路径、参数（环境变量可覆盖）
│  │     ├─ store.py               # FinStore：FTS5/npz/SQLite 访问 + embed()
│  │     ├─ retrieval.py           # 预过滤 → BM25∥dense → RRF → Located
│  │     └─ ingest.py              # CLI 入库管道 + --verify + --macro
│  └─ observers/
│     └─ evidence_audit.py         # 可选：on_loop_end 数字溯源审计
├─ plugins/fin_data/               # 数据落地（gitignore）
│  ├─ originals/  chunks.db  vectors.npz  tables.db  macro.db  manifest.json
└─ workflows/stateful_react_agent/prompts.py   # 追加引用纪律条目
```

工具层与实现层通过 `get_store()` 单例解耦，`store.py` 是未来换 pgvector/Milvus/ES 的唯一替换点。

---

## 6. 与 FrontierAgent 的集成点

| 集成点 | 位置 | 改动 |
|---|---|---|
| 工具白名单 | [plugins/tools/\_\_init\_\_.py](../../plugins/tools/__init__.py) `_BUILTIN_TOOLS` | 加入 4 个新工具（不加即 fail-closed 不可见） |
| 输出限界 | 各工具内部 `maybe_overflow()` | 复用 `web_search` 同款机制，保上下文预算 |
| 重复检索去重 | 现有 `DuplicateQueryRollbackObserver` | 零改动自动生效 |
| 引用纪律 | [workflows/stateful_react_agent/prompts.py](../../workflows/stateful_react_agent/prompts.py) | 追加：数字只能来自②③；引用格式 `[report_id p{page}]`；区分 fact/forecast；机构分歧并列呈现 |
| 证据审计（可选） | `sdk_extra_observers`（[task_runner.py](../../apodex/task_runner.py)） | `EvidenceAuditObserver`：终稿数字与本次 loop 工具返回做规范化匹配，未命中标记"未溯源" |
| 交付物 | 现有 `_writer_docx/_writer_xlsx` | 报告写 `/outputs`，数据底稿附来源列 |

**沙箱说明**：四个工具均为原生 tool（宿主进程内执行，读本地库），不经过 bash/run_python_code 的沙箱网络限制；Agent 若要在 `run_python_code` 里直接访问索引，需另行放开本地路径——一期不推荐，取证必须走工具以保留审计轨迹。

---

## 7. 验收标准与实施顺序

验收测试三层各设一道闸：

| 层 | 测试 | 通过标准 |
|---|---|---|
| L1/L3 精度 | `ingest --verify` + 黄金数值问答集 | chunk 逐字可重现；数值查询精确率 **100%** |
| L2 检索 | 30–50 条黄金查询（问题→应命中 report_id+章节） | Recall@5 ≥ 0.9（无 rerank）/ ≥ 0.95（有 rerank） |
| 端到端 | `--mode react` 跑宏观问题 | 每个数字可逐字溯源；fact/forecast 未混用 |

实施顺序（每阶段独立可验收）：

1. **①** schema + store（仅 FTS5）+ ingest + 工具①③ → 数值精确率 100%
2. **②** BGE-M3 embedding + RRF 混合 → 检索验收达标
3. **③** 提示词引用纪律 → 端到端引用可核对
4. **④** EvidenceAuditObserver → 未溯源数字可标记
5. **⑤** Agent Team 分解 + `/outputs` 报告交付 → 完整研报闭环

---

## 8. 精度红线（全程不可违反）

1. 入库管道**零 LLM 参与**（除 embedding）
2. Agent 引用数字**只能**来自 L1 逐字原文或 L3 精确行，**禁止**引用 L2 snippet 或记忆
3. 所有数值保留**单位与原始表述**（`raw` 字段），规范化不可逆丢失时以 raw 为准
4. fact 与 forecast **字段级区分**，混用视为答案错误
5. embedding 模型版本写入索引元数据，**版本不一致拒绝查询**
6. 证据链每一步带出处（report_id + page），EvidenceAudit 对未溯源数字告警
