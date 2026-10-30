import json
from pathlib import Path
root=Path(__file__).resolve().parent;out=root/'outputs'
summary=json.loads((out/'summary.json').read_text(encoding='utf8'))
rows=json.loads((out/'evaluation.json').read_text(encoding='utf8'))
manifest={r['id']:r for r in json.loads((root/'manifest.json').read_text(encoding='utf8'))}
layout=json.loads((out/'layout-diagnostic.json').read_text(encoding='utf8'))
audit=json.loads((out/'posthoc-audit.json').read_text(encoding='utf8'))
checks=json.loads((out/'checks.json').read_text(encoding='utf8'))
repeats=json.loads((out/'repeat-checks.json').read_text(encoding='utf8'))
assert summary['pages']==26 and summary['ok']==26
assert checks['baseline_outputs_equal'] and checks['baseline_case_count']==78
assert all(r['text_identical'] and r['statuses']==['ok']*3 for r in repeats.values())
assert json.loads((out/'isolation-after.json').read_text())['changed_files']==[]
assert json.loads((out/'source-isolation-after.json').read_text())['changed_files']==[]

report='''# RapidOCR small 研报扩展测试

2026-10-30。**small 值得保留为正文识别引擎，但当前默认整页输出尚不适合直接启用为生产兜底。下一步应优先补正文分栏、文字层完整性检查与关键事实校验。**

本次沿用隔离环境测试 14 份报告、26 页，其中 24 页为新增样本，2 页为上轮回归样本。23 页有正文；2 页财务表和1页引用目录只作运行与非正文输出对照。用户原始 PDF、既有代码、配置和依赖均未改动。

## 运行结果

| 项目 | 结果 |
| --- | --- |
| 首轮完成 | 26/26 页，零超时、零执行失败 |
| 单页耗时 | 中位数 10.10 秒，P95 18.80 秒，最长 19.66 秒 |
| 首轮累计 worker 耗时 | 288.63 秒，约 4 分 49 秒，不含人工核对、环境准备和复跑 |
| 内存 | 采样进程树峰值最大 782.1 MiB |
| 环境 | 2 CPU 额度、4 GiB 内存上限，无 GPU，断网识别 |
| 稳定性 | 5 个代表页各运行三次，三次文本完全一致 |

采用 RapidOCR 3.10.0、ONNX Runtime 1.31.0，PP-OCRv6 small 检测与识别模型及方向分类模型的 SHA256 均与上轮一致。Python 为 3.12.16，上轮为 3.12.14；旧镜像已不存在，本轮用固定的依赖清单重建，基础镜像摘要及实际镜像 ID 均已记录。这里的耗时是每页新进程，包含导入、渲染、模型加载和 OCR，不代表常驻服务吞吐量或整机最低配置。

## 正文与关键事实

共核对 48 个固定正文摘录、3341 个非空白字符。错误率计算包含错字、符号、插入和阅读顺序干扰，**不是全文逐字准确率，也不是只衡量文字识别模型的指标**。

| 正文类型 | 页数 | 摘录字符 | 编辑错误率 |
| --- | ---: | ---: | ---: |
| 中文 | 16 | 1772 | **0.73%** |
| 英文 | 5 | 1230 | **17.56%** |
| 中英混排 | 2 | 339 | **1.18%** |
| 合计 | 23 | 3341 | 6.97% |

其中，真实扫描/图片页的中文正文为 6 页，摘录错误率 0.36%；英文扫描正文为 4 页，错误率 18.88%。含原生文字层的 13 页也强制渲染做 OCR，用于验证路由和质量变化，不能把它们当作新增真实扫描件。

127 个预选公司名、数字、日期、单位及技术名词检查项，严格完整出现 **124/127，97.64%**。其中两项只是区间连接号由 en dash 变成普通连字符；补充统计统一这些符号后为 **126/127，99.21%**。仍然错误的是 `6.4TOPS/W@INT8` → `6.4TOPS/WW@INT8`。词项在页面任意位置出现不等同于上下文或每次出现都正确。

48 个预选摘录都未达到“编辑距离占比 ≥50%”的整段丢失告警阈值，但人工复核发现了摘录外的正文乱码，因此不能据此声称正文没有遗漏。

## 影响接入的具体问题

### 正文与侧栏交错

英文券商报告会把左侧正文与右侧分析师联系方式、预测表、图表标签按行交错输出。关键单词可能都在，完整句子却已被打断。这是本轮英文高错误率的主要来源。

为定位原因，仅利用已有 OCR 坐标，人工圈定四页的正文主栏并重新排序，没有重跑模型或修正文字：

| 页面 | 默认整页摘录错误率 | 人工选主栏后 |
| --- | ---: | ---: |
| 贝特利报告第1页 | 3.57% | 0% |
| 高盛茅台方案六第1页 | 30.84% | 0.31% |
| 摩根大通中国人工智能第1页 | 9.94% | 0.55% |
| 高盛茅台方案五第1页 | 34.62% | 0% |

这是**事后人工区域诊断**，不计入主测试结果，也不代表已实现自动分栏。它说明应优先解决正文区域和阅读顺序，当前证据不足以认定需要换成更大的 OCR 模型。

### 存在文字层仍可能缺失中文

兴业证券报告第2、3页能提取出大量数字，但可见中文正文几乎没有进入原生提取结果。这两页固定正文摘录的原生编辑错误率合计 74.19%，small OCR 为 0%。因此不能只用“文字层存在”或“字符数超过阈值”决定跳过 OCR。

其余 11 个含文字层页面的固定摘录，现有原生提取均完整匹配；强制 OCR 反而会引入错误。接入时需要保留可靠的原生正文，仅对扫描页或文字提取明显不完整的页补充 OCR。

### 摘录以外仍有正文行乱码

- 台达电子报告第1页的一行英文营收占比说明，含 `~8.3%/~12.2%` 和 `2026/2027`，被识别成 `esa / m s nnp` 一类乱码，模型分数约0.642。该页原生文字正确，覆盖原生结果会降低质量。
- 高盛茅台方案五第3页的一行 EPS 说明，含 `2026/27/28E EPS` 和 `c.1~3%`，被识别成 `2o2 o s o et`，模型分数约0.696。该页属于扫描件，单靠主栏排序无法修复。
- 上轮低清中文样本的单位仍多出一个 `W`，对应行置信分数约0.990。高分不能替代数字和单位核对。

默认分数阈值为0.5；调高阈值会把部分乱码隐藏成缺行，不能据此提高正文保留质量。上述案例均保留原页预览、原始文字框、分数和识别文本。

## 验收与隔离

在识别前设定的实验门槛中，完成率、时间、内存、中文摘录错误率和固定摘录丢失告警均通过；**英文摘录错误率 ≤3% 和严格词项完整率 ≥98% 未通过**。这些是本轮自定工程筛选门槛，不是行业标准。事后符号归一化和人工分栏结果没有替代主测试分数。

- 既有 780 个受检文件内容和 Git 状态保持不变。
- 语料目录内 68 个原始 PDF 校验值保持不变，14 份测试副本也保持不变。
- 当前 reader 在两个独立 Python 环境中执行 26页×auto/text/image，共 **78 个输出完全一致**。
- 空白页返回 empty、损坏文件返回 error、强制截止返回 timeout；无遗留 OCR worker，实验容器已退出。
- 真实 PDF 的渲染和识别均使用 `--network none`。模型下载构建阶段未带入 PDF；样本与生产 reader 通过只读路径挂载，输出仅写入独立实验目录。

该验证覆盖 reader 行为和文件隔离，不等于完整应用端到端上线回归。样本为有目的选取，来源存在重复；无需 GPU 的结论仅适用于本轮 small 串行测试。

## 下一步接入范围

建议继续以 small 做独立实验组件，先实现以下三个环节，再复测相同样本及新增保留样本：

1. **页级质量判断**：保留完整原生正文，识别扫描页及“有数字、缺正文”的文字层问题。路由失败不能覆盖原有内容。
2. **正文区域和阅读顺序**：自动区分正文、侧栏、页眉页脚、图表。保留扫描图片里的正文，图表语义暂不解析。
3. **异常保留和局部重试**：对乱码行、疑似缺行和异常数字单位保留坐标与原文，标记或重试局部区域；禁止按猜测自动改写数字。超时和错误作为明确状态返回。

本轮没有改动生产入口、安装主项目依赖或开启任何 OCR 开关。当前最值得投入的是以上处理环节，暂不升级 medium 或接入按次计费的视觉模型。

## 复核文件

- [逐页核对](PAGE_REVIEW.zh-CN.md)：26页清单、原页预览、原始识别文本、逐段参考与匹配输出。
- `outputs/summary.json` 和 `outputs/evaluation.json`：主指标与每个摘录的编辑距离。
- `outputs/layout-diagnostic.json`：人工主栏诊断，独立于主结果。
- `outputs/posthoc-audit.json`：单位错误、正文乱码和符号归一化补充统计。
- `reference-frozen.json`：识别前固定参考；`reference-errata.json`：源文复核发现的一个漏抄字及区间连接号更正，原始固定参考及哈希保留。
- `outputs/checks.json`、`outputs/isolation-after.json`、`outputs/source-isolation-after.json`：隔离和兼容性检查。
- `README.md`：复现方式、配置及指标限制。
'''
(root/'REPORT.zh-CN.md').write_text(report,encoding='utf8')
review=['# RapidOCR small 逐页核对','',
        '主指标使用固定摘录和有记录的源文勘误。每页图片为识别前渲染；下列“匹配输出”是半全局编辑距离找到的最佳连续片段，可能含串列插入。非正文对照页不计算正文错误率。','',
        '| 页面 | 内容 | 原文类型 | 正文错误率 | 耗时 |',
        '| --- | --- | --- | ---: | ---: |']
for row in rows:
    m=manifest[row['id']]
    cer=f"{row['edits']/row['reference_chars']:.2%}" if row['reference_chars'] else '非正文对照'
    review.append(f"| {row['id']} | {m['name']} 第{m['page']}页 | {row['source_type']} | {cer} | {row['wall_seconds']:.2f}s |")
for row in rows:
    key=row['id'];m=manifest[key]
    preview=(out/'previews'/f'{key}.png').as_posix()
    text=(out/f'{key}.txt').as_posix()
    pdf=(root/'samples'/f"{m['doc_id']}.pdf").as_posix()
    review.extend(['',f'## {key}', '',f"{m['name']}，第{m['page']}页。",'',
        f'[原页预览]({preview}) · [OCR 原文]({text}) · [PDF 副本]({pdf})','',
        f"耗时 {row['wall_seconds']:.3f}s；采样峰值 {row['peak_mib']:.1f}MiB；正文编辑数 {row['edits']}/{row['reference_chars']}；缺失严格词项：{', '.join(row['missing_keys']) or '无'}。"])
    for index,e in enumerate(row['excerpts'],1):
        review.extend(['',f"### 片段 {index}",'',f"参考：{e['reference']}",'',
                       f"OCR 匹配：{e['matched']}",'',f"OCR 编辑距离 {e['edits']}；原生提取编辑距离 {e['native_edits']}。"])
(root/'PAGE_REVIEW.zh-CN.md').write_text('\n'.join(review)+'\n',encoding='utf8')
print('Written REPORT.zh-CN.md and PAGE_REVIEW.zh-CN.md')
