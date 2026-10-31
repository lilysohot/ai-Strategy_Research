# OCR 收敛后工程接线

本阶段完成默认关闭的独立命令入口，将已冻结的原生文字重排、覆盖检查和整页方向 OCR 串联，继续独立保存结果。没有增加模型、修改识别阈值或新增质量扩样。操作说明见 [旁路入口指南](../guide/local-ocr-shadow.md)。

## 人工结论

用户明确回复：**“4 页均可用于旁路人工辅助读取”**。已登记 [带范围的复核记录](ocr-shadow-human-review-20261031.json)，并更新上一轮本地 review.json 和对照页。

这条结论只接受上一轮四页的辅助读取用途；不代表每个字符、表格结构和自动取数正确，也不批准正式入库。上一轮 evidence/summary 中的 pending 保留为执行时快照，后续人工结论单独记录，不改写冻结评分证据。

## 当前本机实际环境

通过只读 `/proc` 与 Docker inspect 观察到：

- 本机 8000 端口的 API 使用此 checkout 的 `.venv/bin/python`，解释器为 Python 3.12.14；不是 OCR 固定镜像里的 `/opt/rapid/bin/python`。
- 观察到实际 Web worker 的 bubblewrap 父进程和隔离后的 Python 子进程；子进程的 mount/PID/user namespace 与 API 不同，启动环境包含 `SERVER_SANDBOX_BACKEND=bwrap`。这比只读默认配置更强，但不是向在线任务注入 OCR 后的端到端验证。
- 从该 worker 可见的虚拟环境元数据核实：PyMuPDF 1.28.2、pypdf 6.16.2，**没有 RapidOCR 和 ONNXRuntime**。worker 可见的 PDF reader 文件哈希与当前 checkout 一致；不据此声称已经加载的所有 Python 模块都与磁盘一致。
- 独立旁路容器继续使用已验收的固定镜像。实际 inspect 确认网络 none、只读根目录、2 CPU、4 GiB，仅 `/out` 绑定目录可写。

因此本阶段在宿主显式启动独立 OCR 容器，不向在线服务安装包，也不修改它的环境。其他机器/远端部署没有核实；当前本机 worker 的 OCR 工具路径也尚未端到端启用。原始只读观察保存在忽略目录 `data/ocr-shadow-preparation/environment.json`。

## 接线行为

新增 [tools/ocr_shadow.py](../../tools/ocr_shadow.py) 和 [_ocr_shadow_worker.py](../../tools/_ocr_shadow_worker.py)。默认执行只返回 disabled；显式 enable 才读取清单、验哈希并执行最多 6 页。输出限定到独立目录，逐页隔离和超时，批次互斥。

冻结模块按 [版本清单](../../config/ocr-shadow-release.json) 复制运行。未知方向只保存候选，外层状态为 `orientation_unknown`；原生文字回退不把它掩盖为成功。已确定方向的坐标转换到校正后的页面空间，交给原正文模块排序；原生正文路径保留坐标重排和覆盖提示。所有页面保持禁止自动入库。

正式读取器、Web 自动读取、incoming 监听和入库命令均未接入；本次交付的是可复用的**独立命令旁路**，不是在线默认 OCR 发布。

## 工程验收

使用上一轮已冻结的 4 个图片页，加首批已有 NOW 第 1 页验证原生分支，不新增未知质量样本。最终数值与产物路径见 [接线证据](ocr-shadow-integration-evidence-20261031.json)。类型检查修正了适配器的可选依赖声明和局部变量标注后，重放相同 5 页核实最终锁定版本；这不是新一轮算法调参。

实测 5 页完成：纯走势图维持未知方向，另 3 个图片页进入人工复核；NOW 第 1 页走 native，保留 35 个坐标行并提示 `native_coverage_gap`，不自动补读缺口。四个图片页的完整方向证据与上一轮逐项相同，冻结检查仍为 **56/56**；五页 **15/15** 个旧 auto/text/image 输出与之前结果哈希一致。

最终产物位于 `data/ocr-shadow-runs/f61d7cca8ca248a9913dd0ca2b3fb586/`。最后一次 Ruff 仅补充导入区空行，最终 worker 与执行副本的 AST 完全一致，执行清单和当前源码哈希分别留存；没有因此再次重跑识别。前一次接线调试产物独立保留，没有覆盖。

19 项针对性测试覆盖默认关闭无副作用、页数/哈希限制、方向未知、坐标转换、失败状态、隔离挂载、超时清理和拒绝自动批准；与既有 reader bundle 测试合计 39 项通过。变更文件 Ruff 与 Pyright 通过；符号检查、两阶段导入检查及实际 preflight 调用通过。其他任务并行修改的运行/团队代码没有纳入或回滚。

本阶段可以交付独立旁路命令。常规扩样调参保持结束；下一步如要扩大使用，工作应转向接入受控运维/Web 调度及真实工具路径验收，而不是继续比较模型。正式入库维持关闭。
