# 本地 OCR 独立旁路入口

此入口把已冻结的原生文字坐标重排、覆盖检查和整页方向 OCR 接在一起，供小批次人工辅助读取。它是 Linux/WSL 上的显式运维命令，不是 `read_file` 的新模式，也没有接入 Web 自动调用、incoming 监听或正式入库。

## 默认关闭与运行

在仓库根目录执行：

```bash
uv run python tools/ocr_shadow.py
```

返回 `disabled`，不读取 PDF、不启动 Docker、不创建运行目录。只有该次调用显式带 `--enable` 才执行，没有持久开关或后台调度。

准备 JSON 清单，精确指定输入文件内容哈希和一开始就选定的页码：

```json
{
  "documents": [
    {
      "path": "/absolute/path/report.pdf",
      "sha256": "实际文件的完整 SHA-256",
      "pages": [2, 4]
    }
  ]
}
```

```bash
sha256sum /absolute/path/report.pdf
uv run python tools/ocr_shadow.py --enable --manifest /absolute/path/request.json
```

一批最多 6 页，文件最多 100 MiB，拒绝重复、非法页码和哈希不符。页码超出 PDF 范围在隔离 worker 内记为错误。清单和路径由操作者指定，不自动扫描目录、取最新文件或判断入库状态。

## 运行环境和版本

依赖本机 Docker 和已存在的固定镜像，镜像与源码哈希锁定在 [ocr-shadow-release.json](../../config/ocr-shadow-release.json)。不自动拉镜像、下载模型或安装依赖。主服务环境无需安装 RapidOCR。

启动前验证源码和镜像身份；运行时复制输入、冻结模块和既有 reader 源码，再验证副本哈希。算法与模型参数沿用已验收版本，不修改 experiments 中的实现。源码有漂移时拒绝运行；不要为绕过拒绝而盲目更新锁定清单。

每页使用独立容器：断网、只读根目录、2 CPU、4 GiB、128 PID、单线程 ONNX。只挂载输入副本、冻结代码（均只读）和本页独立结果目录（可写），不挂载原始输入目录、数据库、仓库全树、凭证或 Docker socket。`/tmp` 与 `/workspace` 为受限临时文件系统。

宿主为整页设置 120 秒上限，包含渲染、三个旧读取路径对照、原生读取及 OCR；超时会尝试删除该次生成的容器，并保存 `host-failure.json`。清理失败有显式字段，不能当作正常完成。批次间有非阻塞文件锁，避免同一 checkout 同时跑多批。没有配置远程 OCR/视觉端点，因此基线仅代表此隔离配置下的现有读取行为。

## 输出与复核

结果保存在独立的 `data/ocr-shadow-runs/<随机运行ID>/`，不覆盖旧批次：

- `manifest.json`：实际使用的版本、源码哈希、输入哈希和页码。
- `pages/<页ID>/result.json`：正文模块结果、完整方向证据、覆盖缺口与质量提示。
- `source.png`、`candidate.txt`、`baseline-auto/text/image.txt`：原图、正文候选与旧读取对照。
- `reference-<角度>.txt`：方向候选，仅供人工参考。
- `review.html`、`review.json`、`summary.json`：对照页、复核记录和运行状态。
- `frozen/` 与 `inputs/`：本次实际使用的只读挂载副本，便于追溯。

`orientation_unknown` 必须保持可见，正文候选保留原生文字，不能用某一方向候选悄悄顶替；其候选文字仍单独保存。已确定方向的 OCR 先转换坐标，再进入冻结正文模块的排序与质量检查。原生正文走独立文字检测的覆盖检查；缺口只标记，不自动猜测补全。

所有新运行都标为待人工复核、`eligible_for_ingestion=false`；`needs_review` 不代表准确率通过。失败页保持 error/timeout 等状态，批次为 incomplete、命令返回非零。方向未知属于已记录的人工处理边界，命令可以正常完成，但不能自动放行。

人工接受必须绑定具体文件哈希、页码和结果版本；可登记“仅用于旁路人工辅助读取”，不能扩展成全文准确、自动取数或正式入库批准。此前 4 页的有限接受结论见 [人工复核记录](../research/ocr-shadow-human-review-20261031.json)。新批次不会因这条历史记录而自动获批。

## 停用与发布边界

停止显式调用即可停用，没有对正式系统的切换或持久状态需要回滚。保留已生成证据；不要删除正在运行容器所用目录。旁路目录已在 Git 忽略范围内，PDF 和全文 OCR 不提交。

当前实现未向在线 worker 安装依赖、未自动发布模型工具、未修改既有 `auto/text/image` 返回值，也未写入正式语料库。若将来接到 Web/定时入口，需单独实现受控调度和结果访问，再验证服务身份、资源限额与实际工具执行路径；不要把本地 Docker 接口暴露给沙箱内的 Agent。
