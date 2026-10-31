# DDOG 数字错误定位与短数字告警修复

**确认了一处识别原因和一处告警缺口：方向分类器把正向的短数字误旋转 180°；正文组件又因文本不足 6 字符而跳过其低置信度告警。** 沿用原模型，关闭方向分类后，本次固定 19 个单元格从 15/19 提升至 19/19。该结果只覆盖两行助手转写样本，不代表全表、未见文档或人工验收通过。

## 可复现的失败与对照

输入使用首批旁路冻结的 DDOG 第 7 页副本。先查看源页，再固定 q/q growth 与 consensus difference 两整行共 19 个非空单元格（含 15 个原本正确的对照）；坐标、源 PDF 哈希和转写见 [number-cells.json](number-cells.json)。转写未经人工确认。

在仓库根目录执行以下回放，已观察到 `correct=15,total=19`，退出码 1：

```bash
python3 experiments/rapidocr-shadow-20261031/diagnose_numbers.py replay \
  --candidate experiments/rapidocr-shadow-20261031/outputs/20261030T165838Z/results/pages/ddog-p07/candidate.json \
  --assert-exact
```

随后去掉正文路由和后处理，只用原始 300 DPI 页面及相同 RapidOCR small 配置运行，仍得到相同四处错误。带中间轨迹的第二次整页运行与基线的文字、框、分数完全一致。推理在固定镜像、断网容器中完成，使用副本只读挂载；没有改写首批结果和人工决策。

| 固定位置 | 助手对照值 | 原路径 | 关闭方向分类 | 表格裁剪，保留方向分类 |
| --- | --- | --- | --- | --- |
| q/q growth · Q4 2026 | 7.3% | 73% | 7.3% | 7.3% |
| q/q growth · Q4 2027 | 8.5% | 85% | 8.5% | 8.5% |
| consensus difference · Q4 2026 | 11.9% | 1.9% | 11.9% | 11.9% |
| consensus difference · FY 2026 | 6.3% | 63% | 6.3% | 6.3% |
| 其余 15 个单元格 | 原对照值 | 15/15 | 15/15 | 15/15 |

诊断前列出三个假设：整页检测/裁剪影响、方向分类错误、识别模型本身的限制。分别改变单个变量：`no-cls` 只关分类；`table-crop` 只改输入区域，不改变 DPI 或模型。两者均达到 19/19。由于 no-cls 已使用相同模型恢复全部固定值，未继续添加单元格 oracle 识别或更换模型。

## 根因证据与界限

`trace-cls` 捕获分类阶段输入和输出，四个失败位置的方向预测均为 180°，分类置信度约 0.90–0.99；逐像素比较确认输出确实等于输入的 180° 旋转。no-cls 的整页检测框与 baseline 完全相同，排除了此对照中检测框变化的干扰。

因此，这四处错误有直接证据指向方向分类误旋转，而非坐标重排删字。裁剪表格也能改善这个样本，但其检测框和分类输入同时随裁剪变化，不能据此独立归因于分辨率不足。

没有把“全局关闭方向分类”改为默认设置：倒置文字、旋转页面、其他未见表格及完整行列关系尚未验证。该候选尚未成为自动纠错或正式读取策略，原始错误保留在冻结结果中。

## 已完成的告警修复

实验正文组件 `body_reader.py::_quality_issues` 原先仅对长度至少 6 的低置信度文本发出提示，漏过 `73%`、`85%`、`63%`。现在低于 0.8 且包含数字的短文本也会保留原文字、分数和坐标并提示复核；普通短词仍使用原过滤规则。

两个新增测试先失败、后通过，覆盖真实短数字模式、坐标回链、原文不变、0.8 边界、普通短词和单字符数字。整套正文组件 25 项测试通过。对原始整页 OCR 回放：告警从 3 项变成 16 项，包含这三个短数字，输出文字逐字不变。

另有文档读取 20 项、试运行编排 5 项测试通过；Ruff E9/F、diff、符号检查通过，framework 447/447 与 eval 496/496 导入通过，仓库 preflight 通过。对照页 25 个本地链接及 HTTP 访问通过。preflight 仅验证仓库配置，不是 OCR 准确性或线上沙箱验收。

`11.9% → 1.9%` 的 OCR 置信度约 0.903，仍不会被低置信度门槛捕获。**告警修复不是准确性保证，也不是正确数字的自动选择器。**

## 产物、复现与下一道关口

- [独立对照页面](outputs/number-diagnosis-20261031/review.html)：19 个原图局部与各候选结果。
- [摘要证据](number-evidence.json)：模型/镜像哈希、各模式结果、方向轨迹、告警回放和输入检查。
- `outputs/number-diagnosis-20261031/` 保存 baseline、no-cls、table-crop、trace-cls 的原始 JSON；不加入 Git。

真实推理复现（输出必须使用新的目录；baseline/trace-cls 预期退出 1，no-cls/table-crop 预期退出 0）：

```bash
bash experiments/rapidocr-shadow-20261031/diagnose_numbers.sh baseline /absolute/path/experiments/rapidocr-shadow-20261031/outputs/new-number-run
bash experiments/rapidocr-shadow-20261031/diagnose_numbers.sh no-cls /absolute/path/experiments/rapidocr-shadow-20261031/outputs/new-number-run
```

与首批快照相比，82 个读取器/配置文件中仅实验 body_reader.py 有预期改动；生产读取器未改。首批归档的摘要、清单、记录、宿主检查、助手初查哈希一致，输入副本哈希一致，6 页人工决策继续 pending。历史 host-checks 是原试运行时点的记录，未用本轮代码覆盖它。

下一道关口是：在未见表格与旋转/倒置对照页上验证方向处理策略，并由人工复核首批结果；这两项尚未完成。当前仍仅具备隔离旁路能力。
