# I1 修复后二次复核

日期：2026-09-16。只审查和测试，未修业务代码、未修改统一台账、未覆盖上轮证据。

## 结论

**针对上轮具体反例的修复有效：原始 15 个失败用例和 5 个对照现均通过。** 当前正式测试亦通过。但「具体反例转绿」不等于「对应约束完整闭合」：有限同类边界复验仍有 9 项失败、2 项对照通过，重复执行结果一致。

建议认可已经完成的修复，不认可台账中「F1—F7 全部修复、作为可信前置完全放行」的强结论。继续局部收口，无需换模型、改变三类材料范围或推倒架构。

## 1. 本轮证据与范围

| 检查 | 实测结果 | 证据 |
|---|---|---|
| 原目录原始 acceptance probes，本轮不改测试 | 20 passed，0.39 秒 | original-probes.xml |
| 当前 contract/readers/clean/chunk/admission/remediation/source 七文件 | 142 passed，24.07 秒 | current-suite.xml |
| 同类边界补测（第一次） | 9 failed、2 passed，0.37 秒 | remaining-boundaries.xml |
| 同一补测（第二次） | 9 failed、2 passed，0.31 秒 | remaining-boundaries-repeat.xml |
| I1 守卫合成自检 | 24/24 passed | guard-selfcheck.json |
| 限定实现文件 Ruff | All checks passed | 本轮命令输出 |

142 = 原五文件 110 + 正式 remediation 15 + source 17。原始 20 与正式 remediation 15 有重复，不相加宣称额外独立覆盖；142 不包含 19 项 guard pytest，因此与台账 161 的分母不同。I1-6 本轮仅顺带回归其现有 17 项测试，不代表对 source 接收/归档协议做了新一轮全面审计。

所有业务测试均在收集前加载 I1 守卫，使用 env -i、禁用插件自动加载及项目 conftest。只读守卫批准的 6 份开发材料；新增补测均为合成文件/内存对象。无模型调用、数据库连接、真实留出读取或正式原文修改。未重跑全库 Pyright、全库 import smoke、财务/检索非回归、PG/CLI E2E；不复述台账中的这些结果为本轮实测。

本次使用 diagnosing-bugs 的原反例复跑和 codebase-design 的接口不变式检查。前者确认已修场景，后者促使补测调用者仍可绕过的接口约束。没有进入修复阶段。

## 2. 对上轮 F1—F7 的逐项判定

| 项目 | 已确认修复 | 尚未闭合 | 结论 |
|---|---|---|---|
| F1 发布/当前决定 | 重放旧 admission 不再回退指针；旧决定发布被拒；局部 scope 不匹配被拒 | 同 scope 不核对 build.decision_id；相同提交重试仍增加 generation | 部分修复 |
| F2 所有权/重试上限 | 已登记 job 时缺少 owner/token 被拒；过期接管不再超过 max_attempts | 当前 token 已过期仍可写；无 job 放行；publish 无所有权门 | 部分修复 |
| F3 PDF 次序 | 同页标题与正文交错反例通过，改为有序发射 | 未宣称所有复杂版式均正确 | 本轮目标通过 |
| F4 读取缺口 | 大幅图片混合页进入台账；DOCX 嵌套表被递归读取 | 小于 25% 的图片无台账；DOCX 表内图片仍未记账 | 部分修复 |
| F5 审核链 | 非法 pending 枚举被拒；独立环不再旁路唯一有效链 | 本轮原反例和现有用例无失败 | 本轮目标通过 |
| F6 保真验证 | 非空原文清空、反向映射被拒；增加映射单调性 | 不把通过扩大为全格式原文覆盖保证 | 本轮目标通过 |
| F7 表格/标题/context | 两张 MD 表分组正确、末尾标题保留、长表头不再抛超限错误 | 为避免超限移除 context 后，续块没有表头引用或 title | 部分修复 |

这是对上轮建议的完成度核查，不是新增业务目标。原来的 20 项检查也存在覆盖不足：例如 F2 原用例只验证不携 token 的旧写入，未验证「携带正确但已过期的 token」。本轮明确补齐，而不将上轮样例冒充完整规范。

## 3. 剩余问题（已执行反例）

### R1 · P1：发布仍不核对 build 的批准版本；重试不幂等

位置：`plugins/corpus/preparation/repository.py:275`、`:315`。对应上轮 F1。

- build 绑定 d0，新增 d1，二者 scope 都为 None；publish(source, d1, old_build) 仍成功。这不是当前决定检查能替代的 build 身份核验。
- 两次完全相同的 publish 调用，generation 从 1 变为 2。提交成功但响应丢失后的重试没有稳定操作身份。

建议：核对 build.decision_id、scope 兼容关系、verified 状态和 expected generation，明确已提交操作的幂等身份。如果业务允许复用旧构建，必须有显式兼容性验证，不能仅因 scope 相同就默认允许。若相同 publish 本意是新激活而非重试，应另设可区分两者的操作身份。

### R2 · P1：权威写入 fencing 只完成一部分

位置：`repository.py:431`～`:452`、`:275`。对应上轮 F2。

- 对固定时间取得的 token，heartbeat(now+121s) 已返回过期拒绝，随后 put_units 携同一 token 仍成功。
- 没登记 job 的 build，可以无 token 写入。实现明确写了「轻量路径/既有测试」兼容放行；这是实际行为，不是测试环境报错。
- PUBLISHED job 被另一 worker 接管后，publish 仍可不携 owner/token 调用成功。

归因：_require_stage_ownership 未检查 lease_until，且 job 不存在直接 return；publish 没接这个门。有效 token、错误 token 两个对照分别成功/拒绝，说明新校验确实生效，但未覆盖完整协议。

建议：统一权威提交入口，运行中、未过期、当前 owner/token 必须同时成立。I1 使用可注入时钟，I2 使用数据库时钟；无 job 拒绝。测试夹具也走相同协议，不为旧测试留业务旁路。发布还需当前 admission/generation 约束，不能只补一个 token 字段。

### R3 · P1：图片缺口仍会静默漏记

位置：`readers/pdf_reader.py:375`、`readers/docx_reader.py:55`～`:79`。对应上轮 F4。

- PDF 混合页只记录面积达到 25% 的图片。合成页插入目标矩形 400×200、页大小 600×800 的中等图片（插入时可能保比例缩小），仍得到 issues=空、仅正文 kept。
- 把图片放进 DOCX 的表格单元格，结果同样没有图片内容或缺口。新递归处理了嵌套表格，未复用段落中的 drawing/pict/object 检查。

建议：面积阈值可以决定复核优先级，不能决定区域是否进入台账。小图可以经明确规则记为装饰噪声，不必一律阻断整篇或 OCR，但不能完全消失。正文、表格单元格、嵌套元素共用对象枚举和缺口规则。

### R4 · P1：长表头超限修复牺牲了续块的列头关系

位置：`chunk.py:270`～`:282`。对应上轮 F7。

同一份原长表头夹具现在不再报错，符合旧反例断言；但数据续块实际为 unit_ordinals=(3,), title_text=None, section_path=()，没有表头 ordinal/context 引用。代码注释中的「退化为仅 title 关联」在无表标题时不成立。

建议：不必复制整个表头文本，但要保留 context/header 引用及表归属；正文预算与上下文预算分开。不能用「表头在另一个块出现过」证明当前命中块的数字可解释。若当前接口表达不了，先显式复核，而非输出无标记的普通块。

### R5 · P2：政策版本绑定建议未完成

位置：`admission.py:236`～`:249`。对应上轮报告 §6.4，不是新业务需求。

仅含 policy_rev=v999-not-implemented、frozen=true、auto_decision.enabled=false 的 JSON 被成功装载，并继续采用硬编码 v1 规则/领域。应拒绝未支持版本或严格绑定可执行规则和内容哈希。当前 v1 的旧测试通过不能证明未来政策升级安全。

上轮 §6.5 的其他静态建议也尚未完整落实：known 来源日期仍不强制 evidence_refs，ReviewedDecision 仍不显式承载材料类型/研究领域；本轮未对这些新增失败计数，保留为后续接口收口事项。

## 4. 版本和状态记录建议

1. 当前台账 180 行及任务清单摘要写「F1—F7 全部修复」。建议追加本轮证据，改为「旧 20 项通过；F3/F5/F6 本轮目标通过；F1/F2/F4/F7 待边界收口」，保留历史通过结果，不覆写前一轮报告。
2. parser/clean/chunk 行为已改变，但可见 READER_*_REV、CLEAN_REV、CHUNK_REV 仍是上一轮的 `*-1`。下一次冻结/缓存复用前应升级或将代码/配置哈希纳入版本；不能让相同版本标签无说明地产出不同结构。尚未执行真实发布，不声称已发生线上版本污染。
3. 本轮不支持完全放行 I1-1～I1-5 的整改验收或 M4，更不授权 PG/清库。可以继续准备 I1-7，但应先修好发布/所有权协议再作为可信依赖接入。

不需要新增模型预算或用户材料；优先修 R1/R2，再修 R3/R4，最后收口 R5、版本指纹和元数据契约。在此期间继续使用合成夹具及批准开发集，保持留出隔离。下一轮只复跑同口径用例和受影响门，不无限扩展测试范围。

## 5. 复跑方法

在 WSL 的仓库根目录执行：

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  PYTHONPATH=/home/administrator/FrontierAgent \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  CORPUS_GUARD_PHASE=i1 \
  CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json \
  .venv/bin/python -B -m pytest --noconftest -c /dev/null \
  -p no:cacheprovider -p plugins.corpus.preparation.guard_pytest \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-i1-retest/test_remaining_boundaries.py \
  -q --tb=short
```

当前为 9 failed、2 passed。替换目标为上一轮目录中的 test_acceptance_probes.py 则为 20 passed。七个正式测试文件使用同样环境与守卫参数。不要覆盖本目录已生成的运行证据。

## 6. 实现 SHA-256

| 文件（plugins/corpus/preparation/ 下） | SHA-256 |
|---|---|
| repository.py | f348ea8dd192d4447182629bf49d9e746e27e5673162ed9862806314eafe61f3 |
| contract.py | 48890a1774faa9eebfea0c566eb7f3ff4938913c1158f6b3755eb7c5986c610e |
| admission.py | c3a729ef7102f71c802e84e9166a5ece86bb36d410369470872b863812d9db2a |
| clean.py | a5b1b5987bb9bf753c84365b03311f5336527965085a3f77b14c1e0ab196fff6 |
| chunk.py | 5b4dbbe89b963cc5bda313e734bef0491dd37de392ad2cef74c4fb17e71c8558 |
| readers/pdf_reader.py | 95d3005773094bf5bb68ba20b763781f925354c3339abeb25b331fa2781cb464 |
| readers/docx_reader.py | e6dba1939915ae285d0643c23d394eb08b4a25f8c51163115daed3412d2d8074 |
| readers/md_reader.py | 7a82d45ebfe63c3afe5012c4ec4e6a6ce658444f49a8ae9086a7e11f8b97560e |
