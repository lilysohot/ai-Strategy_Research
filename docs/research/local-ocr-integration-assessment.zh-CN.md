# FrontierAgent 本地 OCR 接入评估

评估日期：2026-10-19。状态：设计建议，尚未实现、安装或进行 OCR 性能实测。

## 结论

建议增加可选的本地文字 OCR 后端，保留现有 Poppler 文本读取、远程 OCR 和视觉模型路径。PyMuPDF + Tesseract 适合做清晰印刷体扫描件的离线识别，不能等同于现有远程 OCR 的结构化输出，更不能替代图表理解。

对于本项目，直接在 `_ocr_page()` 内加入几行 PyMuPDF 调用并不够：线程并发、图表语义、沙箱依赖、超时及缓存均会影响结果正确性。推荐在现有 PDF 路由下设置小型 OCR 接口，本地 PyMuPDF 实现在独立子进程内运行。首阶段显式启用，先支持 Linux/WSL2 与项目运行容器。

同时保留一个值得对照实测的方案：沿用 Poppler 渲染，调用 Tesseract CLI。它复用已有工具，避免新增 PyMuPDF Python 依赖及其线程限制。若目标只需要文字，PyMuPDF 并非必需；若需要 OCR 文字坐标以及后续 PDF 操作，PyMuPDF 更有整合价值。

## 当前代码的事实

以下结论来自本工作区实际代码，而非仅依据注释；工作区原有变更未被修改。

| 位置 | 当前行为 | 接入含义 |
|---|---|---|
| [`read_file.py`](../../plugins/tools/read_file.py) | reader 源码经 stdin 传入沙箱的 `python3 -`；外层超时 120 秒；允许传递 `READDOC_` 前缀环境变量 | 依赖必须装在实际工具解释器中；新 worker 不能假定能导入宿主仓库 |
| [`_doc_reader.py`](../../plugins/tools/_doc_reader.py) | 多个 reader fragment 拼接成单文件执行 | 新 OCR fragment 需加入拼接；不能照普通包随意使用相对导入 |
| [`_reader_pdf.py`](../../plugins/tools/_reader_pdf.py) 的 `_overview_page()` | `auto` 只提取普通文字，扫描/图像等页标记未读 | 默认概览不应因装了 OCR 而变成全书识别 |
| 同文件 `_deep_page()` | `image` 模式按路由调用 OCR，或提取文字后补充图表视觉结果 | 接入应发生在深读，不增加新的模型工具 |
| 同文件 `_pdf_route_decide()` | 无文字、数学字体、乱码、大图、矢量图及稀疏视觉页均归类为 `ocr` | `ocr` 是历史路由名，不代表这些页都适合 Tesseract |
| 同文件 `_map_pages()` | 默认用两个线程并行处理页面 | 线程里不能直接并发运行 PyMuPDF |
| 同文件 `_ocr_page()` | HTTP 请求 PDF；消费 `text_with_img_link` 或 `text`；`<img>` 标记驱动图表视觉调用 | 本地纯文本没有这些标记，不可把“没有标记”解释成“没有图表” |
| 同文件 `_ocr_page()` | 每次 HTTP 请求允许 300 秒，503 最多六次尝试 | 已经与外层 120 秒存在预算冲突；接入应统一剩余时间预算 |
| [`_reader_core.py`](../../plugins/tools/_reader_core.py) 的 `main()` | PDF `image` 或带 `pages` 的读取绕过全文缓存 | 分页续读会重新执行昂贵深读；需要独立页面结果缓存 |
| `_reader_pdf.py` 的 `_ocr_workdir()` / `_pdf_to_images()` | 中间文件按文件名 stem + 页码存放，存在即复用 | 同名不同路径、原文件更新可能复用错误页面；新增缓存必须解决文件身份问题 |
| [`pyproject.toml`](../../pyproject.toml) | Python >=3.12；`document-readers` 含 pypdf，不含 PyMuPDF | 本地 OCR 需要可复现的可选依赖和锁文件 |
| [`_sandbox.py`](../../plugins/tools/_sandbox.py) | E2B bootstrap 列表已含未固定版本的 PyMuPDF，但没有对应语言数据安装步骤 | “某环境装有 PyMuPDF”不等于 OCR 可用，也不代表其他后端可用 |
| 同文件环境过滤 | 默认不透传 `TESSDATA_PREFIX`；read_file 额外放行 `READDOC_` | 优先使用 `READDOC_OCR_TESSDATA` 并显式传入 PyMuPDF |
| [`tests/test_document_bundles.py`](../../tests/test_document_bundles.py) | 已有经 stdin 执行 bundle 的测试；PDF 样例为 blank page | 可复用测试入口，但它不能验证扫描件识别能力 |

## 能力与适用范围

PyMuPDF 使用 MuPDF 内置的 Tesseract 支持；官方预编译包的 OCR 需要外部语言数据，不需要 `pytesseract`。显式指定 tessdata 时可以不依赖外部 Tesseract 可执行文件进行目录发现。[官方说明](https://github.com/pymupdf/PyMuPDF#how-does-ocr-work-in-pymupdf-does-it-require-a-separate-tesseract-installation)

`get_textpage_ocr()` 返回供提取/搜索使用的 TextPage；后续需传入 `textpage`。部分 OCR 可能把识别文本放在原文字后面，不能直接假定阅读顺序正确；得到 TextPage 不等于修改并保存原 PDF。[接口文档](https://pymupdf.readthedocs.io/en/latest/page.html#get_textpage_ocr)

| 内容 | 本地后端定位 | 产品输出要求 |
|---|---|---|
| 清晰中英文印刷体扫描页 | 首阶段主要目标 | 返回文字，注明 OCR 来源 |
| 原生文字 PDF | 保留 Poppler 路径 | 不重复 OCR，避免精度和速度退步 |
| 乱码文字层 | 可尝试整页 OCR | 保留失败状态，不把空结果称为成功 |
| 多栏、表格、合并单元格 | 可读出部分文字；结构需额外处理和验证 | 不承诺恢复成可靠 Markdown 表格 |
| 数学公式、复杂图表 | 不能将普通字符识别当作理解或 LaTeX 转换 | 优先现有高能力后端/已配置视觉模型，否则明确能力限制 |
| 手写、低清、倾斜和印章遮挡 | 必须按真实样本评估 | 不以“有非空文本”作为准确率证明 |

Tesseract 官方指出表格识别需要额外布局分析；图像清晰度、倾斜等也影响质量。[质量指南](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html)

## 方案对比

| 方案 | 收益 | 成本/限制 | 建议 |
|---|---|---|---|
| 在线程内直接调用 PyMuPDF | 改动表面较小 | 官方明确不支持多线程；可能崩溃；难以中断 C 层 OCR | 不采用 |
| PyMuPDF 独立子进程 | 可取文字与坐标；崩溃隔离；可强制超时 | 新依赖、语言包、worker 协议、缓存及超时管理 | PyMuPDF 接入的推荐方式 |
| Poppler + Tesseract CLI 子进程 | 复用现有渲染；Tesseract 支持文本/TSV/hOCR | 需管理渲染文件及像素坐标；没有 PyMuPDF 的 PDF 操作接口 | 文字 OCR 的对照候选 |
| 本机常驻 `/ocr` HTTP 服务 | 可以沿用现有远程调用协议 | 增加服务生命周期、端口和多环境访问；纯文本返回仍不具备图表标记 | 单机首版不优先，多客户端共享时再考虑 |
| 用 PyMuPDF 全量替换 PDF reader | 长期有机会统一部分 PDF 操作 | 波及多栏重排、表单、附件、OCG、Tagged PDF 和既有行为 | 超出本次增量接入范围 |

来源：[PyMuPDF 并发限制](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html)、[Tesseract 命令行输出格式](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)。

## 推荐的接入设计

### 保持现有工具契约

`read_file` 的 `auto/text/image`、`pages`、`offset`、`save_to` 参数不变：概览保持轻量，text 保持仅文字层，image 才执行深读。修正目前部分注释与实际深读流程不一致的说明。

OCR module 的接口只接收文件、页码、已解析配置和剩余 deadline，返回有限结果：`status`、`text`、`backend`、`warnings`、图表信息是否已知。不要为了两个后端搭建通用插件注册系统。

- 远程 Adapter 保留原服务输出与 `<img>` 语义。
- 本地 Adapter 将文件路径与页码发给独立 worker；由 worker 在自己的主线程打开 PDF、OCR、返回 JSON。
- 本地结果应明确“图表信息未知”，不能伪造 `<img>` 标记或置信度。
- 通用编排负责选择后端、缓存、超时及错误状态；PDF 层负责页标题和视觉补读。

可以新增 `_reader_ocr.py` fragment 并纳入 bundle。worker 以短小固定源码经 stdin 启动，参数走结构化载荷/独立 argv；避免依赖 stdin 主程序的可导入性和闭包 pickling，因此不直接把现有 lambda 塞给 ProcessPoolExecutor。

### 配置与兼容策略

以下变量为提案，当前代码尚未实现：

| 配置 | 建议语义 |
|---|---|
| `READDOC_OCR_BACKEND` | `auto / remote / pymupdf / off`。首版缺省 auto 保持兼容：有 URL 用 remote，无 URL 保持未配置；本地需显式选择 |
| `READDOC_OCR_LANG` | 部署时显式选择；中文场景示例 `chi_sim+eng` |
| `READDOC_OCR_TESSDATA` | 工具运行环境内可读的语言数据绝对路径 |
| `READDOC_OCR_DPI` | 首版从 300 开始验证，配置须有限制并结合最大像素数 |

首版 worker 并发固定为每次读取 1 个，单页上限、整次 deadline 和像素上限先作为内部策略，不暴露大量调参入口。保留 `READDOC_OCR_URL/KEY`。显式 local 失败时不偷偷切换 remote；remote 失败也不悄然降低质量，返回可诊断的降级信息。

`off` 只关闭文字 OCR；已有 vision 配置仍可产生网络调用。不能把“本地 OCR”描述成整条 Agent 工作流离线，主模型及视觉模型是否联网是独立配置。

### 路由与图表衔接

1. 普通文字页继续使用原文字层和现有图表补读。
2. 扫描/乱码页在启用本地后端时 OCR。空结果与执行失败分开标记，保留原文字层回退。
3. 数学字体路由不应无条件用本地 OCR 替代已有高能力路径。配置了 vision 时按需要整页识别公式/内容，而非只用现有 figures-only 提示；未配置时说明公式没有可靠读取。
4. 本地 OCR 对扫描页的图表信息是未知。配置了 vision 时，可在显式 image 深读下保守做一次图表补读，不以缺失 `<img>` 作为跳过条件；无 vision 时说明只识别文字、图表结构未读。原 PDF 图像覆盖率无法可靠区分整页扫描正文和扫描图表。
5. OCR 正文与视觉补充分别注明来源；整页视觉重读和本地正文不要无差别拼接，避免重复和冲突。

### 资源、超时和缓存

- 外层目前只有 120 秒。建立整次读取的共享 deadline，给路由、渲染、OCR、vision 和结果输出分配剩余时间。子进程必须先于外层到期并被回收；不能只设置 HTTP/单页超时。
- 批量页数超出预算时保留已完成页，并列出未处理页及下一次 `pages` 范围；不能静默截断后宣称读完。`max_chars` 是输出分页额度，不能充当计算额度。
- 每次读取 1 worker 不代表整台机器只有 1 worker。Agent Team 多次并行 read_file 仍会叠加；需要利用既有执行限制，并在支持的运行后端做整机压力验收。
- worker 显式限制 OpenMP 线程数，防止“页面进程数 × 引擎线程数”放大；不得假设所有沙箱继承宿主设置。
- 渲染前根据页面尺寸与 DPI 计算像素预算。A4 300 DPI 约 870 万像素、RGB 原始缓冲约 25 MiB；这只是单个图像缓冲，不是 OCR 总内存。DPI 翻倍，像素数约四倍。
- 页面缓存键包含文件内容身份、页码、后端与版本、语言数据版本/摘要、DPI、解析策略版本；视觉补充独立包含视觉端点/模型和提示版本。不在缓存名或日志中写 API key。
- 同名文档及文档修改必须失效，更新目前按 stem 保存的裁页/PNG 机制；使用原子写入，失败结果不作为长期成功缓存。分页续读在同一输入和配置下必须得到稳定内容。

## 安装与发行范围

建议增加独立可选 extra（例如 `ocr-local`），而不是放入基础运行依赖。固定实际验收版本进入 `uv.lock`；语言包也固定来源与版本/摘要。阅读时缺少依赖只报告缺项，不临时执行 pip 下载。

| 环境 | 要处理的内容 |
|---|---|
| Linux/WSL2 native | 在工具实际使用的 Python 环境安装 extra；安装/定位 `eng`、`chi_sim` 数据；保留 Poppler；Windows 宿主安装不能代替 WSL 内安装 |
| bubblewrap | 语言包目录必须在已有可见目录或明确的只读挂载中；优先系统 `/usr/share` 路径；宿主 HOME 中的数据不应假定可见 |
| 主 Docker / GPU 镜像 | 按需启用 extra 并在构建阶段加入语言包；验收工具用户及其 overlay venv，而非只测 root/宿主 import |
| E2B | 已安装 PyMuPDF 但语言包不完整；需要模板预置、版本统一、远端环境传递和 bundle 执行实测；宿主 `READDOC_` 不一定自动进入 SDK 环境 |
| Hugging Face demo | 当前 Dockerfile 明确限制工具执行；先确认产品是否开放文档读取，再决定增加依赖，不默认扩大首版范围 |
| 原生 Windows | 项目安装文档未纳入发布支持矩阵；PyMuPDF 支持 Windows 不等于整个项目支持原生 Windows |

来源：项目 [`Dockerfile`](../../Dockerfile)、[`GPU Dockerfile`](../../docker/sglang-gpu.Dockerfile)、[`HF Dockerfile`](../../deploy/huggingface/Dockerfile)、[`Linux/WSL2 指南`](../install/linux.md)、[`_sandbox.py`](../../plugins/tools/_sandbox.py)。

发行依赖还存在许可证差异：本仓库 LICENSE 是 Apache-2.0，PyMuPDF 提供 AGPL/商业许可，Tesseract 是 Apache-2.0。不能把新增 PyMuPDF 依赖视为与现有依赖完全相同，也不能认为拆成子进程即可消除许可问题。首阶段保留可选集成，并在决定默认打包前核对项目的发行方式。[PyMuPDF 许可](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)、[Tesseract 仓库](https://github.com/tesseract-ocr/tesseract)

## 资源预算与验证门槛

官方未提供适用于所有文档的最低内存规格。建议用 2 vCPU、4 GB RAM 的 Linux 环境作为低配验收点，给 OCR 留出约 1–2 GB 空闲；Windows + WSL2 整机从 8 GB 起步更合理。仅 OCR 无 GPU 要求，依赖及少量临时文件先预留约 1 GB，文档/缓存另计。这些是待测工程预算，不包含本地 LLM，也不是保证值。

对照测试至少包含：清晰中英文扫描、双栏、扫描表格、公式、图表、倾斜低清、原生文字、乱码、空页、加密/损坏文件、同名不同目录和原文件更新。各类可先选 3–5 页，不以一种合成英文样例代表全部文档。

记录文字错误率（中文 CER/英文 WER）、关键数字准确率、表格/公式完整性人工评价、冷启动、单页 P50/P95、峰值 RSS、缓存命中耗时及并发总资源。表格/公式只统计能力差距，不给出未验证的高质量承诺。PyMuPDF 与 CLI 对照使用相同语言模型、DPI、样本和资源配额；远程 OCR 记录其模型/服务版本，避免不可比。

上线前必须验证：

1. `auto/text` 不触发 OCR，未安装本地依赖时旧路径可用，既有 remote 配置行为保持一致。
2. 真实扫描页经完整 stdin bundle 和实际沙箱返回可用中英文，页码准确，输入 PDF 不被修改。
3. 缺语言包、失败、空结果、超时、损坏文件有清晰状态；OCR worker 被回收。
4. 图表/公式不会因本地返回非空文本而被错误标成完整读取。
5. 同名文件、源文件更新、语言/DPI/版本更改不会返回旧缓存；offset 续读不重复 OCR 且不跳字。
6. 大幅面/长文档受预算约束，未完成页被明确报告；单任务和 Agent Team 并行情况下内存均受控。

## 分阶段实施

**第一阶段：能力验证。** 在 Linux/WSL2 的实际工具环境，验证 PyMuPDF worker 和 Poppler + Tesseract CLI，形成上述样本基线，确定引擎和发行依赖。此阶段不替换现有 PDF reader。

**第二阶段：可选接入。** 实现小型 OCR module、进程 worker、配置检测、完整状态及图表衔接；补齐共享 deadline、文件身份和页面缓存。更新 `read_file` 说明、依赖/锁文件及 bundle 测试。

**第三阶段：部署验收。** 验证 native/bwrap/主容器与工具用户；通过后再决定 E2B/GPU 镜像和默认启用范围。E2B 现有 PyMuPDF 安装不作为通过验收的证据。

整体工作量为中等：核心识别调用很小，主要成本在保持原功能正确、跨沙箱可用及失败可诊断。当前证据支持进入第一阶段，不支持直接宣称“已接入”或“全面替换远程 OCR”。

补充一手来源核对见 [PyMuPDF OCR 资料笔记](pymupdf-ocr-sources.md)。
