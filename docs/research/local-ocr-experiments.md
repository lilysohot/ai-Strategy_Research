# 本地 OCR 实验归档

截至 2026-10-31，已完成 Tesseract、RapidOCR small/medium、小规模扩展、正文路由及 Poppler 版式验证。**当前尚未通过自动启用验收，未接入生产读取或入库。**

最新结论见 [Poppler 与未见版式验证](../../experiments/rapidocr-poppler-20261030/REPORT.zh-CN.md)：原生文字按行串列、局部正文遗漏检测仍需修复。下一步应先完善原生文字坐标重排与正文覆盖检查，不能仅凭字数或关键词命中判断完整性。

## 实验顺序

1. [初始方案评估](local-ocr-integration-assessment.zh-CN.md)及[官方资料记录](pymupdf-ocr-sources.md)（历史设计，不代表当前测试结论）。
2. [PyMuPDF/Tesseract 隔离测试](../../experiments/ocr-smoke-20261019/REPORT.zh-CN.md)。
3. [RapidOCR 双样本比较](../../experiments/rapidocr-smoke-20261019/REPORT.zh-CN.md)。
4. [small 扩展至 26 页](../../experiments/rapidocr-expanded-20261030/REPORT.zh-CN.md)。
5. [正文组件 26＋4 页复测](../../experiments/rapidocr-body-20261030/REPORT.zh-CN.md)。
6. [Poppler 与新增 8 页验证](../../experiments/rapidocr-poppler-20261030/REPORT.zh-CN.md)。

## Git 归档范围

保留实验代码、配置、固定参考、报告、逐页评分和关键检查结果；不纳入原始 PDF、样本副本、模型、图片、完整原始 OCR 输出及机器环境快照。`experiments/` 的通用忽略规则保留，所需文件由明确清单纳入版本控制，新增运行产物仍被忽略。

历史原始运行产物保留在本次实验的 Windows 工作区 `C:/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/`，没有删除。部分逐页报告中的图片/原始文字链接仅在该工作区完整可用。克隆仓库不包含这些数据，也不保证无需准备样本即可重放历史运行；准备方式和模型镜像依赖见各实验 README。

这些报告测量的是源分支当时的代码及明确记录的容器环境。合入另一分支不会自动证明该分支生产环境通过 OCR 集成验收。

独立正文模块的接口检查可在仓库根目录运行，无需 OCR 权重或第三方包：

```bash
python3 -m unittest discover -s experiments/rapidocr-body-20261030 -p test_body_reader.py -v
```
