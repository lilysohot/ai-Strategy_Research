# Poppler 路径与未见版式验证

2026-10-30。本实验验证上一轮正文组件在真实 Poppler 读取路径中的局限，保留全部失败证据。没有修改 `body_reader.py` 或生产代码，没有挂接入库、监控或外部 OCR/视觉接口。

## 范围

1. 原 26 页加 8 页未参与前轮 OCR 的 PDF 页面，对现有读取器 auto/text/image 三种模式做 102 项前后比较。
2. 对新增 8 页执行真实 small OCR，并比较原始 OCR、自动分栏结果、Poppler 原生优先结果。原生优先和分栏阶段复用缓存 OCR，不能把它们的运行时间当作端到端推理时间。
3. 在 7 页正文的原生读取返回值中，各删除 25% 和 50% 的符合条件长文本行，共 14 个可控局部缺失案例；保留 PDF 画面不变。不修改 PDF，不冒充真实坏文件，不与真实页面 CER 合并。
4. 用生产 `_pdf_to_images` 函数显式渲染全部 34 页，两轮间清除实验容器 tmpfs 中的图片，比较重新生成的 PNG 哈希。没有视觉接口时，生产 `pdf_mode=image` 并不会自动渲染所有页面，因此不能仅以该模式命令成功代替渲染验证。

新增文件均来自用户既有语料，使用复制件。7 页正文包含左主栏＋右侧栏、右主栏＋左侧栏、双页并排、表格混排、水印和分节标题；另 1 页是目录控制。它们是带原生文字的 PDF，强制渲染 OCR 用于检验版式，并非新增 8 份自然扫描稿。本轮没有新增英文正文模板。

## 环境事实

当前可访问 WSL Ubuntu 主机的 `command -v pdftotext`、`command -v pdftoppm` 均未找到命令。项目 `_sandbox.py` 在远程/Docker 沙箱尝试安装 `poppler-utils`，在 Bwrap/Current 模式跳过该步骤；没有确认用户实际线上沙箱的版本。因此此次是生产读取代码的隔离环境复现，不是线上部署验收。

镜像使用前轮固定 OCR 基础镜像，仅追加 Poppler 包，未挂载 PDF 的构建阶段允许访问软件仓库。推理阶段断网，原文件目录不挂载；生产代码、既有实验、模型和样本只读，仅本实验 outputs 与 tmpfs 可写。

测试镜像 ID：`sha256:141ee6ffbc6d0ec0c025f9deccbf93ae832f6721ef90018de93312b6dfc36c1b`。

Poppler 为 25.03.0（Debian 包 25.03.0-5+deb13u4），Python 3.12.16，2 CPU 配额、4 GiB 内存。small 模型、300 DPI、25MP 页预算和 ONNX 单线程参数沿用前轮。模型推理每页新进程、90 秒上限。更多环境证据在 `outputs/environment.json`。

## 复现

依赖前轮三个 OCR 实验及固定基础镜像。仓库根目录运行：

```powershell
python -X utf8 experiments/rapidocr-poppler-20261030/stage.py
docker build -t frontier-rapidocr-poppler:20261030-5db5 experiments/rapidocr-poppler-20261030
./experiments/rapidocr-poppler-20261030/run.ps1 prepare
./experiments/rapidocr-poppler-20261030/run.ps1 run
./experiments/rapidocr-poppler-20261030/run.ps1 regression
python -X utf8 experiments/rapidocr-poppler-20261030/evaluate.py
python -X utf8 experiments/rapidocr-poppler-20261030/build_report.py
```

再次执行会覆盖本实验输出，应先存档。软件仓库会变化，重建镜像未必与本次镜像相同；精确环境以已保存镜像 ID 和包清单为准。`stage` 与 `evaluate` 需要原 WSL 语料目录可读。`prepare` 只渲染和提取文字，不运行 OCR。

`run` 执行真实 OCR 后再复用结果做路由、分栏和故障注入。第一次运行发现 image 模式没有调用渲染器，因此补充 `regression` 显式调用原渲染函数；该验证已通过，未重复 OCR。当前 `run` 也包含显式渲染，初次输出中 `checks.json` 的 `rendered_pages: 0` 仅表示初次没有覆盖该路径，不能作为图片验证证据。有效图片验证见 `outputs/render-regression.json`（34 页）。

## 指标与限制

人工参考在新 OCR 前固定，按片段最佳匹配编辑距离计算，只忽略空白。计分后 3 页的 4 处人工抄录问题经 240 DPI 源 PDF 裁片核验，记录于 `reference-errata.json`；冻结文件未改。`outputs/evaluation.json`、`outputs/summary.json` 同时保留冻结参考和源图勘误后的分数。没有调整组件规则去适配结果。

片段指标不能证明全文召回，关键词命中不能证明上下文连贯。双页并排样本两侧有相似文字，最佳片段匹配可能由另一侧满足，不能证明两侧都完整。生产 auto 模式会有意把待 OCR 页列为占位提示，因此其片段分数只是该模式输出的诊断值，不应解读为生产 OCR 引擎准确率；计分已排除头部文档结构 metadata。

局部缺失案例只修改注入到模块的原生字符串，模拟“视觉内容存在，但提取器漏掉部分行”。它验证文字门槛的能力边界，不估计真实故障发生率；删除比例针对符合条件的长文本行，不是全页正文比例。

产物集中在本目录，仍由现有 experiments 忽略规则隔离。建议和失败实例见 `REPORT.zh-CN.md`，逐页证据见 `PAGE_REVIEW.zh-CN.md`。
