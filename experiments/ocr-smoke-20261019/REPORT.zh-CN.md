# 本地 OCR 隔离小样本测试报告

日期：2026-10-19。结论：**隔离与本次覆盖的原流程行为检查通过；识别质量不支持默认接入生产。** 没有修改生产 OCR 逻辑、项目依赖、锁文件、配置或现有虚拟环境。

## 样本与方法

用户提供的两份 PDF 均为单页图片型文档，原生可提取文字为 0。因此两份均测试完整第 1 页，无需再抽页。

| 标识 | 用户文件 | 原始图片像素 | 特点 |
|---|---|---|---|
| user1 | 【电报解读】格芯与迈威尔共同推进下一代光学连接技术，机构称光.pdf | 1030 × 2492 | 长截图、彩色标题、水印、中英文术语 |
| user2 | 【机构调研】这家底层芯片平台供应商业绩创历史同期新高.pdf | 680 × 630 | 低清截图、芯片参数、英文名称与百分比 |

原件位于 WSL Ubuntu 的 `/home/administrator/FrontierAgent/data/corpus/`。实验仅使用逐字节复制并校验 SHA-256 的副本；原件没有挂载给 OCR 容器。副本：[user1](samples/user1.pdf)、[user2](samples/user2.pdf)。

基线比较两条本地路径：

- PyMuPDF 内置 Tesseract：整页 `full=True`，300 DPI，`chi_sim+eng`，独立进程。
- Poppler 渲染 + Tesseract CLI：同为 300 DPI、相同语言顺序和同一组语言数据，CLI 使用 `--psm 3`，独立进程。

每份文档、每条路径重复三次，合计 12 次真实样本 OCR。每次新建 worker；操作系统文件缓存未清空，因此不是三次完全冷启动。耗时统计为三次中位数，包含进程启动、PDF 打开、渲染和 OCR。

另有两页可核对原文的中英文控制页（原生文字、扫描图）进行 12 次 OCR，以及空白页、缺语言包、损坏文件、运行中强制超时探测。控制 PDF 不是用于替代真实样本质量评估的证据。

在查看真实 OCR 输出前，从原图人工转录 8 个片段，共 445 个去空白字符，并选择 18 个关键名称/参数用于对照。[人工参考](manual-checks.json)

片段 CER 使用去空白、保留大小写和标点后的最小编辑距离；按全文中最佳连续片段做宽松对齐。它可能在内容缺失时对齐到错误位置，因此仅是抽查诊断指标，不是全文准确率，也不能证明没有漏段落。所有参考及对齐结果保存在 [详细核对结果](outputs/real-samples/manual-evaluation.json)。

## 300 DPI 基线结果

| 样本 | 路径 | 单页中位耗时 | 采样峰值进程树 RSS | 抽查片段 CER | 关键项精确出现 |
|---|---|---:|---:|---:|---:|
| user1 | PyMuPDF | 14.459 秒 | 290.2 MiB | 4.98%（11/221） | 12/12 |
| user1 | Poppler + CLI | 11.455 秒 | 288.6 MiB | 8.60%（19/221） | 12/12 |
| user2 | PyMuPDF | 7.718 秒 | 231.8 MiB | 8.48%（19/224） | 3/6 |
| user2 | Poppler + CLI | 4.573 秒 | 246.6 MiB | 44.64%（100/224） | 2/6 |

各组合的三次文字输出均一致。稳定重现不等于识别正确。

这里的内存是每 20 ms 采样一次、求进程及其子进程 RSS 之和后的峰值；可能漏掉极短峰值，共享页也可能重复计算。不是精确分配峰值或整台宿主机/容器总内存。三次样本不足以给 P95、吞吐或最低配置保证。

### 影响使用的具体错误

**user1：正文可读，但名称与标题仍会误读。** PyMuPDF 在开头句子中将“格芯”分别识别为“格世”“格六”，另有标题“格必”、正文小标题“铜线”识别为“鲍绕”等错误。CLI 同样出现“格心”等错误，水印附近的小标题有缺失。

12/12 关键项仅意味着这些字符串在全文某处出现，不能证明它们在所有句子中都正确。公司名在正文中有一次正确，也不能抵消标题或结论句中的误读。

**user2：关键数值发生实质性错误。** 原图的 `6.4TOPS/W@INT8` 在 PyMuPDF 300 DPI 输出中变为 `56.4TOPSAW@@INT8`；底部 `+4.80%` 变为 `+4.60%`。`7.8TOPS/W@INT8` 的单位和字符也未保持准确。CLI 300 DPI 的相关段落出现大量乱码，不能用于可靠参数提取。

本实验不使用 LLM 对错误进行猜测修复。原始 OCR 结果完整保留：

- user1：[PyMuPDF](outputs/real-samples/user1-p1-pymupdf.txt) / [CLI](outputs/real-samples/user1-p1-cli.txt)
- user2：[PyMuPDF](outputs/real-samples/user2-p1-pymupdf.txt) / [CLI](outputs/real-samples/user2-p1-cli.txt)

## 150 DPI 补充检查

基线发现关键数字错误后，仅改变渲染 DPI，再对每个样本/后端运行一次。这是探索性检查，不能与三轮中位耗时等同看待。

| 样本 | 路径 | 单次耗时 | 抽查片段 CER | 观察 |
|---|---|---:|---:|---|
| user1 | PyMuPDF | 11.096 秒 | 8.60% | 比 300 DPI 更差 |
| user1 | CLI | 6.145 秒 | 23.08% | 比 300 DPI 更差 |
| user2 | PyMuPDF | 6.455 秒 | 8.48% | 核心单位、公司名和百分比仍有错误 |
| user2 | CLI | 3.531 秒 | 5.80% | 正文明显改善，但两组完整芯片参数和公司名仍未精确识别 |

第二份原图仅 680 × 630 像素。扩大渲染尺寸不会增加原图细节，本次结果也显示 DPI 不是越高越好。不同渲染器及底层引擎版本均可能影响结果，不能根据这两个样本宣布某条路径全面优于另一条。

补充结果：[指标](outputs/real-samples/dpi-evaluation.json)、[原始记录](outputs/real-samples/dpi-probe.json)。

## 隔离与原流程检查

| 检查 | 结果 | 证据/范围 |
|---|---|---|
| 现有文件完整性 | 通过 | 780 个既有文件 SHA-256 未变，git status 与测试前一致 |
| 两份用户原件完整性 | 通过 | 原件测试前后 SHA-256 一致 |
| 实验输入副本完整性 | 通过 | 每次运行前后副本哈希一致 |
| 原读取器控制页输出 | 通过 | 原生/扫描 × auto/text/image，共 6 组，在 baseline 与 candidate 环境中输出一致 |
| 原读取器真实页输出 | 通过 | 两份真实页 × auto/text/image，共 6 组输出一致 |
| 原生文字可读 | 通过 | 检查正文中文及订单号，避免“两边都空”造成假通过 |
| OCR 未被悄然启用 | 通过 | 原流程 auto 继续标记扫描页未读；未配置远程接口的 image 继续报告未配置 |
| 空白页与异常区分 | 通过 | 空白页返回 empty，缺语言包/损坏 PDF 返回 error |
| 运行中超时 | 通过 | 记录 OCR_STARTED 后强制终止，约 0.51 秒返回；没有遗留 worker |
| 样本运行网络 | 隔离 | Docker `--network none`，不挂载 API key/.env，不调用远程 OCR/vision |

证据：[文件完整性](outputs/isolation-after.json)、[原件完整性](outputs/originals-after.json)、[控制检查](outputs/verification.json)、[真实运行检查](outputs/real-samples/checks.json)。

原读取器来自当前工作区 `plugins/tools` 的只读挂载，使用当前 `_doc_reader.py` 中列出的源码片段经 stdin 执行，没有修改其实现。本测试没有实际集成新后端，因此这些结果证明实验没有改变已覆盖行为，不构成未来集成后的完整回归保证。主 Agent、远程 OCR/vision、多种沙箱和并发负载仍未进行端到端验证。

## 环境及本次暴露的安装问题

- Docker 限额：2 CPU、4 GiB RAM；read-only root、no-new-privileges、drop ALL capabilities；独立临时工作目录。
- Python 3.12.14；PyMuPDF 1.28.2；系统 Tesseract CLI 5.5.0；Poppler 25.03.0。
- `chi_sim` / `eng` 使用容器中同一组 traineddata，摘要已记录；PyMuPDF 内置引擎与系统 CLI 不保证为同一构建。
- baseline 虚拟环境只有 pypdf，没有 PyMuPDF；candidate 环境含实验需要的包。未使用/修改生产虚拟环境。
- 精确镜像 ID：[image-id.txt](outputs/image-id.txt)。实际 Python、Debian 依赖及语言包哈希：[environment.json](outputs/real-samples/environment.json)、[Python 锁定清单](outputs/real-samples/requirements-resolved.txt)、[Debian 清单](outputs/real-samples/debian-packages.tsv)。

初次精简容器漏装 `poppler-data`，导致控制用原生中文 PDF 无法正确渲染；只在实验镜像补齐后重跑。初始失败输出保留在 `outputs/initial-missing-poppler-data/`，不混入最终比较。这说明未来安装检查应包含真实中文 PDF 的渲染，而不能只看 `pdftoppm --version`。

## 对项目的判断

1. **暂不改现有流程，不默认启用这套配置。** 两份实际文件中已经出现会改变事实的数字误读，不能把 OCR 非空结果当作读取成功。
2. **可以继续保留独立实验后端。** 资源开销在本次限制内可控，但长截图单页已经需要约 11–15 秒；生产接入仍要整次 deadline、页面缓存及失败状态。
3. **后续质量优化仍在实验目录完成。** 比较中文语言模型/图像预处理/区域识别，并扩充到低清、表格、公式和图表样本。不要仅依据此次两页的速度决定引擎。
4. **若未来接入，保持显式选择和回退。** 普通文字 PDF 保留原文字层；低清扫描、标题、水印或关键参数未核对时保留可见的能力限制。置信度或文本长度不能独立保证数字准确。
5. **上线验收应增加当前真实案例。** 至少覆盖 `6.4` 不变成 `56.4`、完整单位、百分比、公司名、原流程输出、进程退出、输入哈希与缓存失效；今天的隔离通过不能替代未来代码变更后的回归。

实验脚本、输入副本、输出和报告均在 Git 忽略的 `experiments/ocr-smoke-20261019/` 中。本次不提交、不合并、不改生产运行配置。复现实验说明见 [README](README.md)。
