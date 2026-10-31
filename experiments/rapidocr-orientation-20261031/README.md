# 第二批旁路：方向处理回归

沿用固定 RapidOCR small 镜像和现有实验正文组件。3 份未见研报各 1 页，覆盖英语访谈表、财务表格与中文正文混合页、中文正文；另加 1 页明确标为合成的正负号/单位对照。每页 0°、顺时针 90°、180°，分别开启和关闭文字方向分类，共 24 次新进程 OCR。

选择依据是版式和历史样本去重，不依据 OCR 分数。三个真实 PDF 的哈希均不在历史 68 份索引及首批 3 份旁路样本中，不代表它们尚未正式入库。合计 49 个真实页面仅处理 3 个，其他页在 manifest 中列出。

## 输入与复现

运行需 Linux/WSL、Docker、Python/PyMuPDF；宿主产物生成还需 Pillow。仓库依赖通过 uv 管理。固定镜像：

`sha256:141ee6ffbc6d0ec0c025f9deccbf93ae832f6721ef90018de93312b6dfc36c1b`

使用与第一批相同的 `config.py` 和模型权重，不下载新模型、不改变生产代码。`prepare.py` 按冻结 SHA-256 从 `data/corpus-incoming/20261026/` 选取文件，并依赖本机历史索引 `/mnt/c/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/inventory.json` 及第一批 manifest。克隆仓库不包含这些输入、镜像或历史原始结果。

```bash
uv run python experiments/rapidocr-orientation-20261031/prepare.py
bash experiments/rapidocr-orientation-20261031/run.sh
uv run python experiments/rapidocr-orientation-20261031/finalize.py
python3 -m unittest discover -s experiments/rapidocr-orientation-20261031 -p test_experiment.py -v
```

`outputs/batch2/` 保存本次冻结输入和结果。已有 results 时拒绝重新 staging/运行；finalize 拒绝覆盖 results 内已有 evidence.json/review.json，保护运行和人工记录。已归档的根目录 evidence.json 保留，复现结果单独写入 results。不要为了重跑删除已有人工结果；为下一批复制实验配置并指定新目录。

## 评分边界

- 34 个真实检查项和 6 个合成检查项由助手看图转写，在任何新 OCR 前冻结；只忽略空白，符号差异仍保留。不匹配不必然代表数字语义错误，需要原图复核。
- 财务表数值/合成整行按 exact 比较，SaaS 金额单位/正文摘录按指定区域中的完整子串比较；评分不是全文 CER，也不是表格结构识别准确率。
- 先渲染完整页面再旋转像素，显式强制 OCR，属于方向压力测试。正常页面还运行实际 native/OCR 路由；这两类结果单独保存，不把强制 OCR 宣称为正常原生路径的行为。
- `unrotate` 只将识别框映射回源页评分，不向 OCR 提供正确方向，也不借此自动修正文档。
- 同一区域匹配约束防止其他位置同值掩盖遗漏；但命中所有抽查项也不能保证正文完整、全表对应关系及最终阅读顺序。
- 评分只能证明所标注范围。用户上轮的“核实基本没问题”不自动成为本批的人工验收结论。

## 隔离与产物

容器断网、根文件系统只读、2 CPU / 4 GiB、单页新进程 90 秒超时；挂载只读样本副本和实验/读取器代码，仅 results 可写。不挂载正式库或凭据，不连接线上服务。

三页现有 auto/text/image 共 9 个输出逐页前后核对。finalize 复核原件、副本、源码及结果哈希。原始 PDF、完整 OCR、图片和机器运行产物只留本地，不入 Git。

结论见 [REPORT.zh-CN.md](REPORT.zh-CN.md)，逐页对照见 [review.html](outputs/batch2/results/review.html)，人工状态见 [review.json](outputs/batch2/results/review.json)。本批没有发布、默认参数切换或正式入库操作。
