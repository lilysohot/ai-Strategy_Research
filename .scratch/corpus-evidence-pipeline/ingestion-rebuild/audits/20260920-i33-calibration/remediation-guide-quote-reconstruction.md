# 修改指导：kept 页文本中的引文插断（I3-3 校准 · company-001 坐标级实锤）

- 生成时间：2026-09-20
- 状态：**草案 / 待 U 裁决后实施**（本文只是修改指导，不含已实施的代码改动）
- 适用范围：`audits/20260920-i33-calibration/evidence-diagnosis.json` 中 `cause = exact_quote_not_in_kept_page_text` 的 **34 条**目标
- 证据级别：只读复算（连隔离 PG 读 kept 单元 + 读冻结金标），**未改动任何被绑字节**

## 0. 阅读须知（边界，先看这里）

1. 本文**不改金标**。金标引文在原 PDF 中逐字存在（见 §2.1 截图对照），因此修复方向唯一：**修摄入侧**。
2. 本文**不改评分器**（`plugins/corpus/scoring.py`）、**不改生产检索路径**、**不写回** `evidence-diagnosis.json`。
3. 任何改动若触及被绑字节 → 必须走「新修订重绑 → 两门复跑」；静态门与语料族回归基线（`uv run pytest tests/test_corpus_*.py -q` → **651 passed / 12 skipped**）不得回归。
4. 完成/M6 放行只能由**独立复核 + U 具名签认**给出，实施方不得自宣。
5. 验收必须**逐条转绿**，不接受"整体分布改善"式的模糊结论。

## 1. 一句话结论

34 条「引文在 kept 页文本里逐字搜不到」中，**32 条的原因是"库里的页文本被按坐标顺序拼接后结构被破坏"**：

- **主因（25 条）**：摄入拼接采用**单栏阅读顺序**（单元按 y 坐标从上到下排、用 `\n` 连接），遇到**双栏 / 浮动侧栏**版式时，右栏的块会被按纵坐标**夹进左栏句子的中间**；
- **次因（7 条）**：CJK–拉丁字符间的文本层空格在提取/清洗中被吞掉，导致与金标书写形式对不上（内容一字不差）；
- **待单独核（2 条）**：含 1 条页眉标题块拼接、1 条疑似被清洗掉的披露句，需先诊断再决定是否属本类。

**关键判断：这不是"原 PDF 缺内容"，也不是检索或评分的问题；34 条里有 32 条可以在不动金标、不放松判据的前提下，靠摄入侧修复直接转绿。**

## 2. 实锤证据

### 2.1 现场 A：company-001 / e4（华创证券 · 贵州茅台 · 第 1 页）

金标引文（冻结件 `i3-2/query-gold-scoring-v1.jsonl`）：

```
我们维持26-28 年EPS 预测值
67.74/70.77/73.84 元，维持一年目标价2030 元和“强推”评级。
```

库里第 1 页 kept 单元（直读隔离 PG，只读）：

| 单元 | 文本 | bbox（x0, y0, x1, y1） | 判定 |
|---|---|---|---|
| unit81 | `…综上，茅台经营向上明确，底层逻辑未变，我们维持26-28年EPS预测值` | **(41, 594, 381, 616)** | 左栏（x≈41–381），句子**前半** |
| unit82 | `相关研究报告` | **(394, 611, 455, 621)** | **右侧栏**（x≈394 起），浮动框标题 |
| unit83 | `67.74/70.77/73.84 元，维持一年目标价2030 元和“强推”评级。` | **(41, 616, 310, 627)** | 左栏，句子**后半** |

按 y 排序拼接（现状实现）→ unit81 → unit82 → unit83：

```
我们维持26-28年EPS预测值      ← 左栏，前半
相关研究报告                    ← 右栏块，被夹进来（致命）
67.74/70.77/73.84 元，维持一年目标价2030 元和“强推”评级。   ← 左栏，后半

```

**几何事实**：右栏块 unit82 的纵坐标区间 `y=611–621` 恰好落在左栏两行 `y=594–616` 与 `y=616–627` 之间。也就是说，"按 y 排"这个顺序**在物理上就是错的**——它把两份不同的阅读流交错在了一起。

**与原始版面/截图对照（人工目视，U 已提供第 1 页截图）**：该页为双栏版式，左栏是“投资建议”正文（该句为左栏倒数第二行 + 最后一行），右栏自上而下为“市场表现对比图”“相关研究报告”列表框。截图中被高亮选中的《贵州茅台（600519）重大事项点评：再提价注入信心…》即该列表框条目。**原 PDF 中该句完整连续；是拼接顺序造成了插断。**

次要差异（同一案例）：PDF 文本层渲染为 `我们维持 26-28 年EPS 预测值`（数字与中文之间有排版空隙），金标忠实保留 → `26-28 年EPS 预测值`；库内文本为 `26-28年EPS预测值`（空格被吞）。

### 2.2 现场 B：company-008 / a-1（同一来源，第 1 页页眉区）

金标引文：

```
贵州茅台（600519）2026 年中报点评 
 
 强推 （维持）
```

库里该页页眉区被拆散，并与图例（`-3%`／`-15%`／`25/08`／`沪深300`／`贵州茅台`）等短块交错穿插进正文流，同样无法逐字命中。**这是同族问题的第二种形态：页眉/标题块与正文流未做区域隔离。**

### 2.3 现场 C：company-007 / e1（第 7 页，待核）

金标引文：

```
贵州茅台的控股股东茅台集团持有本公司的控股股东华创云信4.06%的股
份。
```

该页（评级说明/免责声明页）按页拼接文本中找不到该句，需单独诊断是"被清洗规则丢弃"还是"跨行/跨块合并失败"。**在诊断清楚前不得动手修改。**

## 3. 影响面：34 条逐条分型

本次只读复算的口径：

- **A 类**：金标引文去掉全部空白（`\s+`）后，可在 kept 页文本中去空白后逐字命中 → 纯空白映射问题；
- **B 类**：去空白仍不命中，但引文按 `\n；;。` 切出的**每个子句**都能在去空白页文本中逐字找到 → 内容全在、只是**被别的块插断**；
- **C 类**：子句也有找不到的 → 待单独核。

结果：

| 分型 | 条数 | 含义 |
|---|---:|---|
| 引文含 `\n` | **34 / 34** | 全部是跨行/跨块的引文 |
| A 去空白后逐字命中 | **7** | 内容一字不差，仅空白差异 |
| B 子句全在但被插断 | **25** | 内容全在，被别的块夹断 |
| C 待单独核 | **2** | company-007 e1 (p7)、company-008 a-1 (p1) |

**A + B = 32 条属于"结构/顺序/空白"问题，是本次修复的现实目标。**

## 4. 根因拆解

| 编号 | 根因 | 对应条数 | 性质 |
|---|---|---:|---|
| R1 | **无分栏/阅读顺序重建**：页内单元仅按 y 排序拼接，双栏、浮动侧栏、图注会被夹进正文句内 | 25（含 R3） | 版式重建缺失（主因） |
| R2 | **空白保留映射缺失**：CJK–拉丁间空格、行尾空白在提取/清洗中被吞或改写 | 7 | 清洗规则过强 |
| R3 | **页眉/标题/图例块未做区域隔离**：短块与正文流混排，破坏标题类引文的连续性 | 含于 25 | 版面分区缺失 |
| R4 | **待核**：p7 披露句疑被清洗（或跨块合并失败） | 2 | 未定，先诊断 |

## 5. 修改指导（按优先级）

> 每条包含：现象 → 判定方法 → 建议修法 → 必带反例 → 禁止事项。实施时**一次只做一条**，每条独立入链。

### FIX-1（P0）页内阅读顺序重建：栏聚类 + 浮动块处理

- **现象**：§2.1 —— 右栏 `相关研究报告` 被夹进左栏句子中间。
- **判定方法**：对同一页单元做 x 投影，若能稳定分出两组互不重叠的 x 区间（本例：左栏 x≈41–381、右栏 x≈394–468），则该页是双栏页。
- **建议修法**：
  1. 拼接前先做**栏聚类**（按 x 区间聚类，不写死 `390` 这类单页常量；用页内自适应阈值，例如对 x 中心做一维聚类），**栏内**按 y 排序，再**按栏顺序**拼接；
  2. 横向跨度覆盖多栏的单元（跨栏标题、通栏表格、页眉）作为**分栏边界**处理，而不是当作普通单元；
  3. 尺寸/位置异常的浮块（如右栏小标题框、图注、水印）标记为**侧栏/浮块**，不与正文流混拼，或单独成段并明确标注区域来源。
- **必带反例（回归样本）**：
  - 华创茅台第 1 页：修复后 `相关研究报告` **不得**出现在 `我们维持26-28年EPS预测值` 与 `67.74/70.77/73.84 元` 之间；
  - 单栏文档（docx/md 及其他单栏 PDF）拼接结果**逐字节不变**（这是最容易回归的一侧，必须有对照样本）；
  - 通栏表格页（如第 1 页“主要财务指标”表、第 3 页财务预测表）不得因分栏而被切碎。
- **禁止**：不得为了让某条引文命中而对该文档/该页做**特例硬编码**；不得改动单元集合本身（增删单元、改 `status`）。

### FIX-2（P0）空白保留映射：给"被吞掉的空格"建档

- **现象**：A 类 7 条 —— 去掉空白后逐字命中，但原样搜不到（`26-28 年EPS 预测值` vs `26-28年EPS预测值`）。
- **判定方法**：取 A 类 7 条逐条比对"金标空白位置"与"库内实际字节"，归纳出**规则清单**（不是逐条打补丁）。
- **建议修法**：
  1. 先把当前清洗流水线里所有会改写空白的位置**列全**（提取后、清洗中、入库前），逐项标出"吞 / 留 / 归一"；
  2. 形成**空格保留映射表**（CJK 与拉丁/数字边界、百分号与单位边界、行尾、制表符），输出**可解释的规则**，而不是"看起来更整齐"；
  3. 若清洗确需归一化，则必须**同时**在匹配层记录等价口径（见 FIX-5），且两边分开计量。
- **必带反例**：§2.1 的 `26-28 年EPS 预测值` 与 `26-28年EPS预测值` 两种形态必须**都可被判定为同一文本**，且该判定要**可解释、可复现**。
- **禁止**：不得在修复 A 类时顺手把文本改成"能搜到金标"的形态（那是拿结果反推数据）；不得直接改金标引文。

### FIX-3（P1）页眉/标题/图例块与正文流的隔离

- **现象**：§2.2 —— 页眉标题 `贵州茅台（600519）2026 年中报点评` + 评级 `强推（维持）` 与图例短块交错。
- **判定方法**：定位页内 y 最上/最下的横幅区（页眉/页脚），检查其中的短块是否与正文流混排。
- **建议修法**：把页眉/页脚/图例/页码识别为**独立区域**，输出顺序固定（页眉 → 正文 → 页脚），不参与正文流的 y 排序。
- **必带反例**：不得把页码、页脚声明（如 `证监会审核华创证券投资咨询业务资格批文号…`）并入正文段落；不得把 `强推（维持）` 这类评级标记从页眉里丢掉（干净 ≠ 删除）。

### FIX-4（P1）先诊断、后动手：2 条 C 类

- **company-007 e1 (p7)**：确认该披露句在 PDF 文本层是否存在、是否被判为 `noise`、是否跨块拆分。
- **company-008 a-1 (p1)**：已定性为 FIX-3 的页眉问题，按 FIX-3 处理。
- **禁止**：在未拿到"该句在 PDF 文本层可见"的证据前，**不得**把它写成"文档缺失"，也不得为此改 gold 或改 locator。

### FIX-5（P2，配套而非替代）匹配层的空白等价，必须单独立账

- 若摄入侧无法完全保留原始空白，可在**匹配层**引入"空白等价"判定，但必须：
  1. 只做**空白**等价（不得放宽为模糊/编辑距离/语义匹配）；
  2. 判定结果**可解释**（能指出是哪些空白位置差异）；
  3. **单独计量**（"摄入侧修复转绿 N 条 / 匹配侧等价转绿 M 条"两笔账分开报），避免用匹配放宽掩盖摄入缺陷。
- **禁止**：不得把 FIX-5 当作 FIX-1/FIX-2 的替代；不得用等价规则去迁就金标书写形式。

## 6. 验收判据

| 判据 | 目标 |
|---|---|
| `exact_quote_not_in_kept_page_text` | 34 → **≤ 2**（仅允许 C 类残留，且需逐条给出诊断结论） |
| 逐条转绿 | A 类 7 条 + B 类 25 条**逐条**从"未命中"转"逐字命中"，须给出逐条清单，不接受抽样 |
| 单栏文档回归 | 拼接结果逐字节不变（对照样本必须列出） |
| 语料族回归 | `uv run pytest tests/test_corpus_*.py -q` 仍为 651 passed / 12 skipped |
| 冻结链 | 新修订重绑 + 两门（`validate_i0c_freeze.py`、`validate_i3_2_completion.py`）复跑通过 |
| 金标 | **零改动**（sha256 不变） |

**重要提醒——验收口径的边界**：本项修复只解决"34 条逐字命中"，**不等于 I3-3 通过**。README 已写明顺序：先解决 34 条保留/映射 + 6 条 locator 接线，**再**谈有界召回与负例策略。修复后重跑评分仍应如实报告两轮结论，不得以此项进展宣称门通过。

## 7. 复现与验收命令（只读）

> 重跑注意：`evidence-diagnosis.json` 是 **write-once**（`calibrate.py` 中 `write_once`：已存在且内容不同即 `RuntimeError: write-once conflict`）。
> 因此修复后重跑诊断，必须**新建审计目录/新修订**，或先归档旧诊断件，**不得**就地覆盖。

```bash
cd /home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration
```

复算 34 条分型（A/B/C）：

```bash
uv run python - <<'PY'
import json, re, sys
sys.path.insert(0, '.')
import calibrate
release = calibrate.load_module(
    'region_release_diagnosis',
    '/home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-region-review/release.py')
dsn = release.connect()
from plugins.corpus.preparation.repository_pg import PgStore
from plugins.corpus.preparation.contract import UnitStatus

BASE = '/home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild'
ident = json.loads(open('source-identity-map.json').read())
diag = json.loads(open('evidence-diagnosis.json').read())
recs = {r['query_id']: r for r in map(json.loads, open(BASE + '/i3-2/query-gold-scoring-v1.jsonl').read().splitlines())}

def norm(s):
    return re.sub(r'\s+', '', s)

rows = [r for r in diag['targets'] if r['cause'] == 'exact_quote_not_in_kept_page_text']
cache = {}
with PgStore(dsn) as st:
    def ptext(src, page):
        k = (src, page)
        if k not in cache:
            b = ident['active_builds'][src]
            if b not in cache:
                pages = {}
                for u in st.get_units(b):
                    if u.status is UnitStatus.KEPT:
                        pages.setdefault(u.location.page, []).append(u.raw_text)
                cache[b] = pages
            cache[k] = '\n'.join(cache[b].get(page, []))
        return cache[k]

    a = b = c = nl = 0
    for r in rows:
        t = [x for x in recs[r['query_id']]['evidence_targets'] if x['target_id'] == r['target_id']][0]
        q = t['quote']
        pg = int(r['required_locator'][0].split(':')[1])
        txt = ptext(r['source_id'], pg)
        if '\n' in q:
            nl += 1
        if norm(q) in norm(txt):
            a += 1
        else:
            parts = [p for p in re.split(r'[\n；;。]', q) if len(norm(p)) >= 6]
            if parts and all(norm(p) in norm(txt) for p in parts):
                b += 1
            else:
                c += 1
                print('C_todo', r['query_id'], r['target_id'], 'p' + str(pg))
print({'total': len(rows), 'quote_has_newline': nl, 'A_blank_only': a, 'B_clause_interleaved': b, 'C_todo': c})
PY
```

查看 company-001 第 1 页单元的坐标与文本（定位插断块）：

```bash
uv run python - <<'PY'
import json, sys
sys.path.insert(0, '.')
import calibrate
release = calibrate.load_module(
    'region_release_diagnosis',
    '/home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-region-review/release.py')
dsn = release.connect()
from plugins.corpus.preparation.repository_pg import PgStore

ident = json.loads(open('source-identity-map.json').read())
src = '6f14cc145b798b3716bad47829c05d89d8a5e5955179f11d196ed9b9b8538f11'
with PgStore(dsn) as st:
    units = [u for u in st.get_units(ident['active_builds'][src]) if u.location.page == 1]
for i, u in enumerate(units):
    t = u.raw_text
    if ('相关研究报告' in t) or ('26-28' in t) or ('67.74/70.77' in t):
        bb = u.location.bbox
        print(f'unit{i} status={u.status} bbox=({bb[0]:.0f},{bb[1]:.0f},{bb[2]:.0f},{bb[3]:.0f})')
        print(repr(t))
PY
```

## 8. 附录 A：34 条逐条清单（复算结果，供修复后逐条对账）

| # | query_id | target_id | page | 分型 |
|---:|---|---|---|---|
| 1 | company-001 | e4 | p1 | B |
| 2 | company-001 | a-2 | p1 | B |
| 3 | company-002 | e1 | p1 | B |
| 4 | company-002 | e2 | p1 | A |
| 5 | company-002 | e3 | p1 | B |
| 6 | company-004 | e2 | p1 | B |
| 7 | company-004 | a-2 | p1 | B |
| 8 | company-004 | a-3 | p1 | B |
| 9 | company-007 | e1 | p7 | **C** |
| 10 | company-008 | a-1 | p1 | **C** |
| 11 | company-008 | a-2 | p1 | B |
| 12 | company-008 | a-4 | p1 | B |
| 13 | industry-003 | a-3 | p10 | B |
| 14 | industry-005 | e1 | p1 | B |
| 15 | industry-005 | e2 | p1 | B |
| 16 | industry-007 | e2 | p1 | B |
| 17 | industry-008 | e1 | p1 | B |
| 18 | industry-008 | a-2 | p10 | B |
| 19 | industry-008 | a-4 | p1 | B |
| 20 | macro-001 | e1 | p1 | B |
| 21 | macro-001 | e2 | p1 | B |
| 22 | macro-001 | a-3 | p3 | B |
| 23 | macro-002 | e1 | p1 | B |
| 24 | macro-002 | e3 | p1 | B |
| 25 | macro-002 | e4 | p1 | B |
| 26 | macro-003 | e1 | p1 | B |
| 27 | macro-003 | a-2 | p1 | B |
| 28 | macro-003 | a-4 | p1 | B |
| 29 | macro-005 | e1 | p1 | A |
| 30 | macro-006 | e1 | p1 | A |
| 31 | macro-006 | e2 | p1 | A |
| 32 | macro-006 | a-3 | p1 | A |
| 33 | macro-007 | e1 | p2 | A |
| 34 | macro-007 | e3 | p2 | A |

> 注：`macro-002 e4`、`macro-003 a-2`、`macro-003 a-4` 三条引文长度达 699 字符（长段），修复后应优先复核其拼接完整性。

## 9. 附录 B：诊断口径与三分类判定来源

原诊断脚本对每条缺失目标问三个是非题，得到三分类：

```
39:40:audits/20260920-i33-calibration/diagnose_evidence.py
cause = "returned_quote_missing_required_locator" if quote_returned else (
    "retained_quote_outside_selected_chunks" if quote_kept else "exact_quote_not_in_kept_page_text")
```

- `quote_returned`：引文出现在本轮**返回的证据块**中 → 缺 locator（6 条，接线层）；
- `quote_kept`：引文在**该页 kept 单元全文**中 → 未进选中块（14 条，检索层）；
- 否则 → 页文本里逐字搜不到（34 条，本项目，摄入层）。

本次复算只在第三类内部再做 A/B/C 细分，**不改变**首次诊断的三分类结论，也不改变"两轮都不通过"的评分结论。

## 10. 不得做的事（红线汇总）

1. 不得改金标引文/分数/locator 去迁就现状（"洗绿"）；
2. 不得为让引文命中而做文档级/页级特例硬编码；
3. 不得改单元集合（增删单元、改 `status`、改 `quality_report` 形状）；
4. 不得用匹配层放宽代替摄入侧修复，或把两者的收益混为一笔账；
5. 不得就地覆盖 `evidence-diagnosis.json`（write-once）；
6. 不得在本项未完成前宣称 I3-3 或 M6 有任何放行意义。
