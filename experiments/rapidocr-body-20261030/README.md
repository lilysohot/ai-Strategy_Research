# RapidOCR small：独立正文读取实验

2026-10-31 更新：组件已加入原生坐标重排与独立覆盖检查，仍未接入生产。10 月 30 日的报告和 outputs 是旧实现的历史证据，不代表当前代码。新验证入口、结果及限制见 [坐标与覆盖修复](../rapidocr-layout-20261031/README.md)。代码与报告按明确清单跟踪，完整运行产物仍被忽略。

## 接口

`body_reader.read_page(path, page, *, enabled=False, native_reader, ocr_reader=None, coverage_reader=None)` 接受一页和读取适配器，返回包含以下字段的字典：

- `text`、`source`：最终候选文字及来源；原生坐标与原始文字一致时按区域重排，否则保留原始文本并要求复核。
- `native_text`、`native_quality`、`route_reason`：保留原生读取结果和路由依据。
- `ocr_original`：调用 OCR 时保留整个原始结果。
- `lines`：重排后的行及原始 ID；OCR 行含像素四点坐标和分数，原生行含归一化矩形和词框，不伪造 OCR 分数。
- `coverage`：独立可见文字检测与原生词框的几何覆盖结果；`matched` 也不代表全文语义正确。
- `layout`：自动检测的栏间位置；没有检测到则为空。
- `status`、`needs_review`、`issues`：执行情况和需要核验的证据。`needs_review` 仍然返回文字，不等于执行失败或错误已修复。

`native_reader(path, page)` 可返回字符串，或 `{text, lines: [{text, rect, word_rects}], page_points}`。仅有字符串时原生覆盖未知，需要复核；坐标采用显示页面左上角原点、0–1 归一化矩形。`native_adapter.py` 使用 Poppler 的 `-layout` 与 `-bbox-layout` 提供这个结构。`coverage_reader(path, page)` 返回 `{status: 'ok', source: 'raster_text_detection', rects, render_pixels}`，检测必须来自独立渲染图像；不得用原生框冒充覆盖证据。

`ocr_reader(path, page)` 必须自行限制执行时间，返回 `status/text/lines/boxes/scores/render_pixels`，或抛出 `TimeoutError`。旧 `experiment.py` 中的 pypdf 字符串适配器仍兼容，但原生结果不再自动获得 `ok`。核心模块只依赖 Python 标准库。

原生门槛适用于中英文，包含非空字符数 160、文字比例 0.45、中文字符 60 或英文词 40，以及未映射字形比例 0.01。字数只决定候选路线，不能证明正文完整；通过后继续检查原文/坐标一致性及可见文字覆盖。缺证据、检测失败、方向不一致或疑似缺口都需复核。标题页和短正文可能多跑一次 OCR；读取原生层报错会显式返回错误。

自动分栏根据重复段落边缘递归划分区域，支持双页内部继续分栏；跨栏文字划分上下区域，同基线片段按横坐标排序。没有文档 ID、固定页面裁剪框或人工真值参与路由。所有输入行保留一次；没有图表语义分析或严格正文区域分类。图表标签、页眉、侧栏仍保留在候选文字中，表格和目录关系不承诺恢复。

异常规则只标记低置信度行、碎片词、重复单位字母、数字间易混淆字母和未映射字符，不替换任何数字或文字。规则有误报和漏报可能，没有声称能发现全部识别错误。

## 复现

在仓库根目录使用 PowerShell：

```powershell
python -X utf8 -m unittest discover -s experiments/rapidocr-body-20261030 -p test_body_reader.py -v
./experiments/rapidocr-body-20261030/run.ps1 prepare
./experiments/rapidocr-body-20261030/run.ps1 run
python -X utf8 experiments/rapidocr-body-20261030/replay.py
python -X utf8 experiments/rapidocr-body-20261030/evaluate.py
```

`run` 会重新执行并覆盖本实验的输出；先存档已有结果再做另一轮。依赖之前三轮实验目录和已经构建的固定镜像，未提供自动联网安装。`evaluate` 还会只读访问原始 WSL 语料，核对 68 个文件哈希。

镜像固定为 `sha256:7b9dce41dbd71a8a1b5a5e1b269075004def90965f02468223b203df7f3f8880`。与前次扩展测试使用同一 RapidOCR 3.10.0、ONNX Runtime 1.31.0、PyMuPDF 1.28.2、pypdf 6.21.1 及 small 检测/识别权重，详见前次 `outputs/environment.json` 与 `outputs/requirements-resolved.txt`。300 DPI 渲染、25MP 页预算，RapidOCR 默认缩放上限 2000，单线程 ONNX；每页启动新进程。

运行环境：2 CPU 配额、4 GiB 内存、无 GPU、串行执行；OCR 子进程 65 秒限时，整页实验进程 90 秒限时。根文件系统和代码/样本/既有实验/生产读取代码只读，只有本实验 outputs 和临时目录可写；网络完全禁用，未挂载原始语料目录。未调用付费服务。内存测量是每 20ms 采样的进程树 RSS，不能当作容器总内存或最低部署内存。

## 证据

`REPORT.zh-CN.md` 是结果和局限说明；`PAGE_REVIEW.zh-CN.md` 列出逐页来源、错误、耗时和异常。`outputs/results.json`、`outputs/checks.json`、`outputs/evaluation.json`、`outputs/known-errors.json` 保留机器可读证据。

26 页继续使用前次已核验参考片段，4 页新增参考在推理前固定。新增参考的一处人工抄录错误另记于 `reference-errata.json`；冻结文件未改，逐页指标同时保留原始参考分数与核验后分数。未把已知失败行事后加入主要 CER 来改写比较基准；它们单独列在异常审计里。

生产集成尚未执行。若后续接入，应让现有 PDF 页级读取入口显式调用这个独立组件，保持原生优先和原有输出协议；将文字与待复核状态同时交给下游，并保留原文和坐标供核验。需在项目实际 Poppler 环境测试、验证更多未见分栏模板及路由漏检，然后再决定启用范围。当前镜像没有 Poppler，生产回归覆盖的是现有 pypdf 回退路径。
