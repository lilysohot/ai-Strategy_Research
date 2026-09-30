# 05：补齐历史可见推理和完整工具结果阅读

Status: ready-for-human
Priority: P2
Type: task
Requirements: PR-RUN-02, PR-GOV-02
Depends on: 03, 04

## 问题与范围

见[报告 F05](../../../docs/plan/web-runtime-trace-repair-report.md#f05历史轨迹展示缺少可见推理与完整结果入口)。
范围为历史详情的安全展示与按需读取，不把模型未返回的内部推理列为待补内容。

## 修复前提与验收

- 使用 03 的服务端展示投影，按轮次折叠可见推理；未知/未提供明确表达。
- 长工具结果有截断提示和受控展开/分页，关键错误不能只留在不可见的第 300 字符以后。
- 浏览器验证刷新、切研究、历史运行、长文本、无推理、权限失败及键盘操作。
- 不依赖仅存在于实时 store 的内容，不返回加密推理块冒充可读解释。

## Comments

- 2026-09-29：模板和 300 字符截断确认，浏览器复现未执行。
- 2026-09-30：**修复前状态（源码事实，非动态复现）**。`RunDetailView.vue` 的 `shortResult()`
  固定 `slice(0, 300) + '…'`，无截断提示、无继续读取入口；`llm` 模板只渲染
  `content` / `tool_calls` / `usage`，从未读取记录器已保存的 `thinking`。因此「文件有内容、
  页面读不到」与「第 300 字符之后的关键错误不可见」两项均成立。
- 2026-09-30：**实现**。展示逻辑抽到 [web/src/utils/traceView.ts](../../../web/src/utils/traceView.ts)
  （依赖自由，便于无浏览器审计），`RunDetailView.vue` 改为消费它：
  ① 推理按轮次折叠（`<details>/<summary>`，原生键盘可达），且**只有散文型推理才展示**——
  缺失 / 空 / 仅 `thinking_blocks`（加密·签名块）分别给出明确文案，不把签名块当可读解释；
  ② 工具结果保留 300 字符预览，尾部改由「继续读取」按 2000 字符有界解锁，并显式显示
  剩余/总字符数，不再静默截断；③ 切片按 code point，不切断代理对；④ 切换 Run 时重置展开状态。
  类型侧 [types.ts](../../../web/src/types.ts) 补 `thinking?` / `thinking_blocks?`。
  **F03 脱敏边界未移动**：`redactDeep` 仍在组件内对 `result` 生效，`traceView` 不接触脱敏。
- 2026-09-30：**证据**。新增 [audit/frontend-f05-audit.mjs](../audit/frontend-f05-audit.mjs)
  执行真实 `traceView.ts`（无浏览器/网络/模型），**10/10 通过**，覆盖：可见推理原样返回、
  缺失/空/受限各有文案且 `text` 为 `undefined`（不伪造）、加密块不当散文渲染、
  第 400 字符处的错误在首屏不可见但「继续读取」可达、剩余与总数上报、短结果无按钮、
  多字节不被切断、展开单调增长。负向对照：把加密块分支短路 + 恢复旧式静默截断后
  **3 条断言失败**，确认非空测试。
  后端侧新增 [tests/test_web_f05_trace_projection.py](../../../tests/test_web_f05_trace_projection.py)
  **4/4 通过**：`/trace` 的投影保留 `thinking`、不把 `thinking_blocks` 扁平成 `thinking`、
  仍对工具结果脱敏（F03 未回退）、缺文件返回空。
  真实构建 `vite build` 通过（5.13s，输出到临时目录后删除），确认 SFC 模板与 import 可编译。
- 2026-09-30：**仍未验收（故维持 ready-for-human）**：真实浏览器场景未跑——刷新、切换研究、
  历史运行、长文本、无推理、权限失败（404）及键盘操作。本机未安装浏览器自动化依赖
  （E1 已记录该限制）；现有证据为转译真实 TS 的契约审计 + 后端投影单测 + 构建通过，
  不含 DOM 渲染验证。
