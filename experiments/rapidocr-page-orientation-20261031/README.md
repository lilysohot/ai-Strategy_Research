# 整页方向判断与校正：隔离实现

`page_orientation.orient_image(rgb, engine)` 只接收 RGB 图片与原 RapidOCR small 引擎，不接收文件名、测试旋转角度、预期文字或答案。没有生产读取器接线，没有正式入库接口。结果仍须人工复核。

流程：

1. 使用原检测模型找文字框。长宽比至少 2.5 的框至少 3 个，横/竖权重多数至少 0.8，才确定横竖轴；否则 unknown。
2. 在该轴的两个相反方向上运行 OCR，关闭单行方向分类。每个框权重有上限。
3. 仅使用至少 6 个字母/汉字、文字占比至少 0.5、识别置信度至少 0.85、横向长宽比至少 2.5 的行作为方向锚点。纯数字完全不投票。
4. 最佳方向须有至少 3 个锚点、分布在至少 2 个纵向带，且相对次优方向的证据权重优势至少 0.25；否则 unknown。阈值在首次真实回归前冻结。
5. 返回方向决定、两个候选及证据；确认方向时返回校正方向的文字和映射回输入图的框。`needs_review` 始终为 true，定向不代表文字正确。

识别分数和证据权重差只用于候选比较，不是经过校准的正确概率。没有用目标财务数字挑选方向，也没有自动改写任何数值。

本版本针对整体一致的直角旋转页面。非直角倾斜、局部旋转、竖排文字、极少文字、纯数字页以及其他语言均未建立通用保证。混排/低证据页应拒绝自动定向；没有方向决定时不生成权威校正结果，保留输入及候选。

## 固定回归

使用已知 DDOG 第 7 页、第二批 SaaS/PLTR/Copilot 三页及合成符号页，各执行 0°/90°/180° 共 15 例，沿用之前冻结的 59 个检查项，合计 177 次检查。另加入空白、纯数字、上下方向均衡混排三个合成拒绝判断对照。

这是已知问题回归，不是全新样本准确率评测。检查项由助手转写，不是人工验收；全表对应、全文阅读顺序和完整性仍需核对。测试角度只由回归脚本用于构造图像和评分，不传给定向模块。

## 运行

需要 Linux/WSL、Docker、宿主 PyMuPDF/Pillow，以及前两批已归档的本地 PDF、图片和检查项；克隆 Git 不含这些原始产物。固定镜像与前两批相同：

`sha256:141ee6ffbc6d0ec0c025f9deccbf93ae832f6721ef90018de93312b6dfc36c1b`

在仓库根目录执行（Python 依赖使用 uv 管理）：

```bash
uv run python experiments/rapidocr-page-orientation-20261031/prepare.py
bash experiments/rapidocr-page-orientation-20261031/run.sh
uv run python experiments/rapidocr-page-orientation-20261031/finalize.py
python3 -m unittest discover -s experiments/rapidocr-page-orientation-20261031 -p test_page_orientation.py -v
```

所有输出独立写入 `outputs/v1/`。prepare/run/finalize 拒绝覆盖已有输入、结果或人工复核记录。复现应使用新的运行目录/实验副本，不删除已有人工结果。归档 evidence.json 保持原样；复现证据保存在新运行 results 内。

容器断网、只读根系统和输入、2 CPU / 4 GiB，单页 90 秒进程超时。固定源代码、参数和输入哈希，原模型权重不变。不挂载正式数据库、凭据或线上服务。

结论见 [REPORT.zh-CN.md](REPORT.zh-CN.md)，对照页为 [review.html](outputs/v1/results/review.html)。原始 PDF、图像和完整 OCR 输出只保留本地，不纳入 Git。
