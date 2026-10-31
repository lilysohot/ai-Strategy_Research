# 真实研报旁路试运行

本实验只处理复制后的选定页面，单独保存结果并等待人工复核。没有正式入库接口，未连接线上沙箱。沿用已修复的原生坐标重排/覆盖检查和现有 small 模型。

本轮结论见 [REPORT.zh-CN.md](REPORT.zh-CN.md)，可提交的摘要见 [evidence.json](evidence.json)。本地人工复核包为 [review.html](outputs/20261030T165838Z/results/review.html)，决策模板为 [review.json](outputs/20261030T165838Z/results/review.json)。原始文件及 outputs 不纳入 Git。

后续 [DDOG 数字错误诊断](NUMBER-DIAGNOSIS.zh-CN.md)确认短数字方向误旋转，并修复实验正文组件的短数字告警；诊断结果单独保存，原批次和人工决策保持原样。

## 本地依赖与复现

- Linux/WSL、Docker、宿主 PyMuPDF；仓库使用 uv 管理依赖。
- 固定镜像 `sha256:141ee6ffbc6d0ec0c025f9deccbf93ae832f6721ef90018de93312b6dfc36c1b`，包含 RapidOCR 3.10、PP-OCRv6 small、Poppler 25.03.0；模型哈希见 evidence.json。
- 输入位于 `data/corpus-incoming/20261026/`；文件模式及选页策略见 stage.py。只选首批 3 份、每份 2 页。
- 历史 68 份 OCR 样本索引来自 `/mnt/c/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/inventory.json`。该位置是本机实验依赖，克隆仓库不包含它；换机器须准备同一索引并调整 stage.py 的 archive 路径。
- 依赖仓库中 body/native_adapter、smoke/config.py 和 ocr-smoke/lab.py，不包含生产接线。

在仓库根目录执行（每次 staging 创建新目录；把输出的目录传给 run.sh）：

```bash
uv run python experiments/rapidocr-shadow-20261031/stage.py
bash experiments/rapidocr-shadow-20261031/run.sh /absolute/path/to/new/run
```

run.sh 使用宿主 `python3` 做哈希后验检查，且拒绝覆盖已有 results 目录，以保护运行证据和人工决策。镜像没有自动构建或下载逻辑。容器断网、根文件系统只读，输入副本只读，仅本次 results 可写；无原始数据目录、数据库或凭据挂载。

```bash
python3 -m unittest discover -s experiments/rapidocr-shadow-20261031 -p test_trial.py -v
```

## 人工复核

打开 review.html，逐页比较原图、现有 text 路径和旁路候选。auto/image 对照、缺口标记、原始坐标与置信度均有链接。review.json 初始全部 pending；组件状态不等于人工结论，助手初查也不会填入人工决定。

人工重点核验遗漏、数字/单位/公司名、阅读顺序以及图表语义。填写复核人、时间、检查项和决定；通过只表示这一页的人工判断，不自动触发发布或入库。DDOG 第 7 页需优先核对数字和表格对应关系。完整报告未处理页在 manifest 中明确列出。
