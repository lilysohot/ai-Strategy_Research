# 本地 OCR 实验归档

截至 2026-10-31，已完成 Tesseract、RapidOCR small/medium、小规模扩展、正文路由、Poppler 版式验证、原生坐标/覆盖修复回归及首批真实研报旁路试运行。**当前尚未通过自动启用验收，未接入生产读取或入库。**

首批结果见 [首批旁路试运行](../../experiments/rapidocr-shadow-20261031/REPORT.zh-CN.md)：从 incoming 目录选取未出现在历史 68 份 OCR 样本中的 3 份研报，冻结 6 页并独立运行；18 项现有读取路径对照未改变，逐页人工记录仍待登记。5 页原生路径提示涉及页脚和品牌文字，1 页 OCR 表格出现数字错误，尚不能直接用于取数。实际线上沙箱版本尚未确认，本轮仍属于固定镜像隔离复现。

后续 [第二批方向回归](../../experiments/rapidocr-orientation-20261031/REPORT.zh-CN.md)已完成：三份未见研报各一页加合成符号对照，共 24 次 OCR；正向与 90° 抽查通过，但 180° 真实项开启分类 32/34、关闭分类仅 4/34。两种设置均有相同的数字错误，组合验收未通过，未进入灰度或正式入库。

[整页定向实现与已知回归](../../experiments/rapidocr-page-orientation-20261031/REPORT.zh-CN.md)已通过 18/18 案例：15 个识别案例方向正确、177 次固定检查匹配，空白/纯数字/混排三个对照返回 unknown。沿用原模型，模块只接收图像；尚未接入正式读取器。

[未见图片页冻结验收与收敛](../../experiments/rapidocr-holdout-20261031/REPORT.zh-CN.md)完成 4 份研报各 1 页，56/56 冻结参考检查匹配、3 页方向正确、1 页方向未知并保留人工候选，12 项现有路径对照未变。本轮未发现重大事故，停止常规扩样调参，冻结“图片文字辅助读取、结果独立保存、人工复核”的范围；小字字符错误、表格行列关联和稀疏页自动定向仍是已知边界。运行时人工结论为 pending，后续有限接受与工程接线见下文，未发布或正式入库。

后续 [收敛后工程接线](ocr-shadow-integration-20261031.md)：用户已接受上述 4 页用于旁路人工辅助读取，结论独立登记，原始评分不改写。已核实本机实际 Web worker 使用 bubblewrap、环境未装 RapidOCR/ONNXRuntime，并提供默认关闭的独立 Docker 旁路命令；冻结原生重排/覆盖和整页 OCR 已串联。没有切换 Web 正式读取或入库，也不再新增常规质量扩样。

[原生坐标重排与覆盖检查](../../experiments/rapidocr-layout-20261031/REPORT.zh-CN.md)修复了已知侧栏/双页串列；原 14 个字符串遗漏及新增 14 个文字/坐标同时遗漏案例均触发可追溯提示。覆盖仍包含非正文区域，未建立误报/漏报率。此前只检查 corpus/originals，未发现新样本；本轮扩大到 `data/corpus-incoming/20261026/` 后找到新试验输入。“新增”仅指未见于历史 OCR 样本，不代表尚未正式入库。

## 实验顺序

1. [初始方案评估](local-ocr-integration-assessment.zh-CN.md)及[官方资料记录](pymupdf-ocr-sources.md)（历史设计，不代表当前测试结论）。
2. [PyMuPDF/Tesseract 隔离测试](../../experiments/ocr-smoke-20261019/REPORT.zh-CN.md)。
3. [RapidOCR 双样本比较](../../experiments/rapidocr-smoke-20261019/REPORT.zh-CN.md)。
4. [small 扩展至 26 页](../../experiments/rapidocr-expanded-20261030/REPORT.zh-CN.md)。
5. [正文组件 26＋4 页复测](../../experiments/rapidocr-body-20261030/REPORT.zh-CN.md)。
6. [Poppler 与新增 8 页验证](../../experiments/rapidocr-poppler-20261030/REPORT.zh-CN.md)。
7. [原生坐标与覆盖修复：34 页回归、两组缺失注入](../../experiments/rapidocr-layout-20261031/REPORT.zh-CN.md)。模型未更换，识别回放复用历史结果，8 页文字检测为本轮新运行。
8. [真实研报首批旁路：3 份、6 页、独立结果、待人工复核](../../experiments/rapidocr-shadow-20261031/REPORT.zh-CN.md)。沿用 small 模型，新运行文字检测/OCR，原件及正式库不写入；本轮产物位于当前仓库该实验的 `outputs/20261030T165838Z/`。
9. [DDOG 数字错误诊断与短数字告警修复](../../experiments/rapidocr-shadow-20261031/NUMBER-DIAGNOSIS.zh-CN.md)。四个固定失败单元格确认被方向分类误旋转 180°；同模型关闭分类、或表格裁剪均使两行助手转写的 19 个单元格达到 19/19。默认分类参数未改，未见/旋转样本和人工验收尚未完成。
10. [第二批：未见研报与 90°/180° 旋转回归](../../experiments/rapidocr-orientation-20261031/REPORT.zh-CN.md)。同模型测试发现全局关闭分类在倒置页明显退化；下一步需验证整页方向判断，不以候选一致自动判定数字正确。
11. [整页方向判断与校正：18 个已知回归](../../experiments/rapidocr-page-orientation-20261031/REPORT.zh-CN.md)。整页文字证据定向后关闭逐行分类，修复 DDOG/PLTR 已知错误；低证据页面拒绝定向，生产默认设置未改。
12. [未见图片页：4 份、56 项冻结检查与收敛决定](../../experiments/rapidocr-holdout-20261031/REPORT.zh-CN.md)。模型与算法不变，结束继续扩样调参；unknown 不计自动通过，保持独立输出与人工复核。
13. [工程旁路入口、实际环境核对与有限人工接受](ocr-shadow-integration-20261031.md)。复用冻结实现，新增默认关闭的独立命令，结果与正式流程隔离。

## Git 归档范围

保留实验代码、配置、固定参考、报告、逐页评分和关键检查结果；不纳入原始 PDF、样本副本、模型、图片、完整原始 OCR 输出及机器环境快照。`experiments/` 的通用忽略规则保留，所需文件由明确清单纳入版本控制，新增运行产物仍被忽略。

历史原始运行产物保留在本次实验的 Windows 工作区 `C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/`，没有删除。部分逐页报告中的图片/原始文字链接仅在该工作区完整可用。克隆仓库不包含这些数据，也不保证无需准备样本即可重放历史运行；准备方式和模型镜像依赖见各实验 README。

这些报告测量的是源分支当时的代码及明确记录的容器环境。合入另一分支不会自动证明该分支生产环境通过 OCR 集成验收。

独立正文模块的接口检查可在仓库根目录运行，无需 OCR 权重或第三方包：

```bash
python3 -m unittest discover -s experiments/rapidocr-body-20261030 -p test_body_reader.py -v
```
