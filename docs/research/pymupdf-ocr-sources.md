# PyMuPDF + Tesseract OCR 一手资料核对

核对日期：2026-10-19。仅核查资料；未安装依赖、运行 OCR 或修改业务代码。

## 引擎、语言包与安装

PyMuPDF 使用 MuPDF 内置的 Tesseract OCR 支持，无需 Python 层的 `pytesseract`。必须能访问语言数据；未显式指定目录时，自动发现过程可能调用 `tesseract` 可执行文件。因此可选择安装完整 Tesseract，也可在使用带 OCR 支持的官方 wheel 时直接配置语言数据目录。以 `tessdata=` 显式传入目录最可控。[PyMuPDF 官方 README FAQ](https://github.com/pymupdf/PyMuPDF#how-does-ocr-work-in-pymupdf-does-it-require-a-separate-tesseract-installation)

官方文档存在表述差异：安装页和 OCR recipe 仍概括为需要单独安装 Tesseract，而安装页的集成 OCR 小节明确写明逻辑已包含、还需语言数据。工程上应锁定 wheel 版本并以一次真实 OCR 冒烟测试确认，不能只检查 `tesseract --version` 或包能否 import。[安装说明](https://pymupdf.readthedocs.io/en/latest/installation.html#enabling-integrated-ocr-support)

语言目录中准备 `eng.traineddata`、`chi_sim.traineddata`，繁体按需加 `chi_tra.traineddata`。`tessdata_fast` 更快，`tessdata_best` 更慢但更准确；fast/best 仅支持 LSTM 引擎。它们不等于独立的大语言模型服务。[官方语言数据说明](https://tesseract-ocr.github.io/tessdoc/Data-Files.html)

## Python 与平台

本次 PyPI 展示的版本为 1.28.2，元数据要求 Python >=3.10；发布文件含 Windows x86-64/ARM64/x86、Linux glibc 2.28+ x86-64/ARM64、Linux musl x86-64、macOS Intel/ARM64 wheel。Python 3.12 在元数据兼容范围内。以目标解释器和实际 wheel tag 为准。[PyPI 元数据与文件](https://pypi.org/project/pymupdf/1.28.2/#files)

注意 README 的 Python 3.11–3.15 说法、安装页仍列出的 Python 3.9 测试名单、PyPI 的 >=3.10 并不完全一致；安装文档平台列表也未列完实际发布的 wheel。不要依赖这些概述来声明完整支持矩阵。[README](https://github.com/pymupdf/PyMuPDF#installation)、[安装页](https://pymupdf.readthedocs.io/en/latest/installation.html#notes)

## OCR 的返回与能力边界

- `get_textpage_ocr(language='eng', dpi=72, full=False, tessdata=None)` 返回 `TextPage`，后续提取/搜索必须传 `textpage=tp`。多语言用 `+` 连接，建议显式设置 DPI；接口没有 `clip` 参数。[Page API](https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_textpage_ocr)
- `full=True` 识别整页；`full=False` 保留原生可读文字。从 1.27.2 起，局部 OCR 覆盖可读文字以外的区域，而非旧版只处理图片。局部 OCR 的新文字接在原生文字后，默认顺序不是阅读顺序；`sort=True` 只是坐标排序辅助手段，不能承诺复杂双栏正确。[Page API](https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_textpage_ocr)
- `TextPage` 支持文本、单词框、块和字典形式，能保留可用于证据定位的坐标；坐标并不等于 OCR 置信度。普通文本输出会丢失这些结构。[TextPage API](https://pymupdf.readthedocs.io/en/latest/textpage.html)
- 上述调用只生成提取结果，不自动给原 PDF 写文字层。输出可搜索 PDF 是另一条流程：逐页渲染为 RGB、无 alpha 的 Pixmap，再用 `pdfocr_tobytes()`/`pdfocr_save()` 生成页面并合并；识别字体和原文样式不一致。[OCR recipe](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html)
- Tesseract 官方承认表格若缺少专门分割/布局分析会有问题；因此识别表内文字不等于恢复正确表格结构。[质量说明](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html#tables-recognition)
- 未找到该集成接口承诺公式转 LaTeX 或图表语义理解。Tesseract 源码有公式区域检测，但不能据此推断能恢复公式语法。工程推论：公式、图表理解仍需专门处理或视觉模型，不能由本地 OCR 接口直接替代。[公式检测源码](https://github.com/tesseract-ocr/tesseract/blob/main/src/ccmain/equationdetect.cpp)、[Page API](https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_textpage_ocr)

## 并发、耗时与资源

PyMuPDF 官方明确不支持多线程使用，可能产生错误甚至使 Python 崩溃。多进程示例由每个进程独立打开文档；不要跨进程共享 Document/Page/TextPage 对象。工程建议：OCR 放独立 worker 进程，先以全局并发 1 起步，再测是否扩容；仅把函数丢进线程池不符合该约束。[官方多进程说明](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html)

Tesseract 自身可能使用多核线程；官方介绍 `OMP_THREAD_LIMIT` 可限制线程，批量多进程时尤其应避免超额占用。这与 PyMuPDF 的 Python 多线程限制是两层问题，具体 wheel 的 OpenMP 构建行为应实测。[Tesseract FAQ](https://tesseract-ocr.github.io/tessdoc/FAQ.html#can-i-increase-speed-of-ocr)

官方 OCR recipe 强调识别远慢于原生提取，建议按页判定是否需要 OCR，并复用同一页的 TextPage。不能把文档中的相对耗时示意当作本项目的吞吐指标。[OCR recipe](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html#how-to-ocr-a-document-page)

在本次查阅的官方安装、FAQ 和质量文档中，未找到统一 CPU/RAM 最低配置；先前“2 核、1–2 GB 可用内存”等只能作为工程试验预算，不能称官方最低要求。官方建议图像至少约 300 DPI 以改善效果；清晰度、倾斜、噪声也会影响结果。[Tesseract 安装](https://tesseract-ocr.github.io/tessdoc/Installation.html)、[质量建议](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html)

资源估算（计算而非官方指标）：A4、300 DPI 约 2480×3508 像素，RGB 原始像素约 24.9 MiB；600 DPI 约为四倍。实际峰值还包含 PDF 解码、语言数据、OCR 中间缓冲与多份图像，所以应限制单页像素、逐页处理，并实测进程峰值 RSS。CPU 部署即可作为起步方案，无需为此专门采购 GPU；此判断不代表所有页面都能在固定内存/时间内成功。

## 许可证事实

PyMuPDF/MuPDF 官方标识为 GNU AGPL v3 或 Artifex 商业许可双授权；Tesseract 仓库标识为 Apache-2.0，依赖组件可能使用其他许可。本笔记不判断 FrontierAgent 的具体使用方式是否满足任何许可证条件。[PyMuPDF 发布元数据](https://pypi.org/project/pymupdf/1.28.2/)、[Tesseract 许可证说明](https://github.com/tesseract-ocr/tesseract#license)

## 集成前必须实测的未知项

在项目目标运行环境固定 PyMuPDF 版本及语言包来源，采集原生中文、纯扫描中英、混合页、双栏、表格、公式、旋转/低清、超大页样本。测每页耗时、峰值 RSS、中文字符错误率、遗漏/重复文字、页码和证据定位，以及超时后进程是否终止。以上是评估设计，尚无本项目实测结论。
