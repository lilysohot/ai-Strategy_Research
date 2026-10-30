# RapidOCR small：独立正文读取实验

2026-10-30。代码、结果及报告均在本实验目录；目录由仓库现有规则忽略。没有生产入口、依赖、环境变量或缓存变更。

## 接口

`body_reader.read_page(path, page, *, enabled=False, native_reader, ocr_reader=None)` 接受一页和两个读取函数，返回包含以下字段的字典：

- `text`、`source`：最终候选文字及来源；原生文本通过检查时逐字符保留。
- `native_text`、`native_quality`、`route_reason`：保留原生读取结果和路由依据。
- `ocr_original`：调用 OCR 时保留整个原始结果。
- `lines`：重排后的识别行，含原始 ID、像素四点坐标、归一化矩形、置信度及文字。
- `layout`：自动检测的栏间位置；没有检测到则为空。
- `status`、`needs_review`、`issues`：执行情况和需要核验的证据。`needs_review` 仍然返回文字，不等于执行失败或错误已修复。

`native_reader(path, page)` 返回字符串。`ocr_reader(path, page)` 必须自行限制执行时间，返回 `status/text/lines/boxes/scores/render_pixels`，或抛出 `TimeoutError`。示例适配器位于 `experiment.py`；它用 pypdf 读取原生文字，再按需在独立子进程执行既有 small OCR worker。核心模块只依赖 Python 标准库。

原生门槛适用于中英文，包含非空字符数 160、文字比例 0.45、中文字符 60 或英文词 40，以及未映射字形比例 0.01。它是启发式门槛，不能证明正文完整。标题页和短正文可能多跑一次 OCR；含足够文字的部分残缺层也可能被误放行。读取原生层报错会显式返回错误，不自动猜测 PDF 可修复。

自动分栏根据重复段落左边缘和右侧文字推断单个栏间位置，全宽文字划分上下区域。没有文档 ID、固定页面裁剪框或人工真值参与路由。所有已识别行保留一次；没有图表语义分析、图片问答或严格正文区域分类。因此图表标签、页眉、侧栏仍可能出现在候选文字里，多栏混合版式仍需验证。

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
