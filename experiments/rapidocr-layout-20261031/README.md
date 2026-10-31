# 原生文字坐标重排与覆盖检查

本轮只修改独立实验组件，保留 PP-OCRv6 small。没有注册生产入口、启动监控或写入正式语料库；实际线上沙箱版本仍未确认。

## 实现与输出

- `../rapidocr-body-20261030/native_adapter.py`：同页 Poppler `-layout` 原文和 `-bbox-layout` 词框，较大水平间距拆为不同片段。
- `body_reader.py`：原文与坐标文字按字符多重集核对，保留重复次数；原生与 OCR 共用递归分栏，同基线片段从左到右排序。`native_text` 永远保留原文。
- 原生候选页必须有独立的栅格文字检测证据。使用原模型的 detection-only 调用，与原生词框比较；不运行识别、不更换模型。覆盖是文字框中心线的水平区间并集，低于 65% 时返回疑似缺口位置。
- 无坐标、无检测、检测空结果、异常或页面方向不一致，返回 `coverage=unknown` 和 `needs_review`。疑似缺口保留原生结果和区域证据；本轮未做区域二次 OCR 或自动纠错。
- `matched` 只代表当前检测框的几何匹配，不证明检测未漏字、字符正确、表格结构正确或全文完整。图表标签和徽标也可能触发复核，未建立正文分类器。

## 复现

需要历史实验的 PDF 副本、原始 OCR JSON 及固定镜像。仓库本身不包含这些大文件，缺失时脚本直接失败，不下载或联网补装。

```bash
python3 -m unittest discover -s experiments/rapidocr-body-20261030 -p test_body_reader.py -v

# 第二个参数为新的输出目录；不传时按 UTC 时间创建。不要复用历史输出。
bash experiments/rapidocr-layout-20261031/run.sh \
  /mnt/c/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments

# 原 26 页补充回归，不执行新识别或新检测。
bash experiments/rapidocr-layout-20261031/run.sh \
  /mnt/c/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments \
  experiments/rapidocr-layout-20261031/outputs/regression-new regression
```

镜像固定为 `sha256:141ee6ffbc6d0ec0c025f9deccbf93ae832f6721ef90018de93312b6dfc36c1b`；Poppler 25.03.0、2 CPU、4 GiB、断网、非 root、根文件系统只读、输入与代码只读，仅新输出和 tmpfs 可写。不挂载正式语料库或凭据，不安装依赖。检测保持 300 DPI、25MP、单线程参数，worker 限时 90 秒。

验证包含上一轮 8 页、原 14 个字符串缺失案例，以及新增 14 个文字/坐标同时缺失案例。后一组必须比未注入的同页新增缺口，已有复核状态本身不算检出。识别结果复用历史缓存，不把重排/检测耗时称为整条 OCR 吞吐。

`outputs/<run>/pages/` 保存原文、坐标、候选结果、OCR 原始结果、缺口和复核原因；`scores.json`、`probes.json`、`checks.json` 保存比较结果。原始输出被 Git 忽略，提交范围仅为代码、说明和脱离全文内容的 `evidence.json`。本地本轮最终结果在 `outputs/verified/` 与 `outputs/regression26/`。报告见 [REPORT.zh-CN.md](REPORT.zh-CN.md)。

启用真实新增研报旁路前仍需未参与修复的新模板、完整冷启动的端到端耗时、覆盖误报/漏报抽查与复核结果消费。正式入库继续关闭；本实验不能证明线上部署通过。
