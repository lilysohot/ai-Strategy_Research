# 启用 A4 阻断约束 — 实施计划

> **【已作废，2026-09-28】** 本计划经评审否决（见 `.scratch/a4-review-20260928/report.md`）：
> C3 即时回验无修正闭环、C4 无报告绑定且多代理共享单文件会互相覆盖、C5 直出/失败回退
> 出口无门、C6 整体标签不能代替逐条处理、C7 异常吞掉使 fail-open 失效，且分层方向错误
> （`workflows/_shared/corpus_gate.py` 会让 plugins 反向 import workflows）。
> 实际执行按修订契约另行落地：`corpus_submit_manifest`（`plugins/tools/corpus_manifest.py`）、
> `publish_boundary`（`plugins/corpus/ledger.py`）、子清单目录 `manifests/`、
> `A4_ENFORCE` **默认关闭**（观测模式）。本文仅存档，不再作为执行依据。

## 摘要

A4 消费账本（`plugins/corpus/ledger.py`）目前为观测模式：四集合采集与 `verify_and_record` 已接线，但 ①`manifest.json`（结论证据清单）无生产者，校验恒得 `draft`；②报告边界只记录不处置。本计划启用阻断：新增专用工具 `corpus_submit_manifest` 作为清单生产者（模型显式提交、工具即时回验、驱动在环修正），并在两条工作流的最终报告边界接「降级发布」阻断（默认启用，`A4_ENFORCE=0` 关回观测模式）。账本无 corpus 活动的 run 一律跳过，非语料基准不受影响。

## 用户已裁决的三个设计决策

1. **边界阻断语义 = 降级发布**：校验未通过时不追加 LLM 调用，附加机器可核验的「证据校验限定」块，`answer_status` 由 `complete` 降为 `partial`。修正依赖在环工具反馈，边界只兜底。
2. **清单生产者 = 专用工具 `corpus_submit_manifest`**：模型提交结论清单 JSON，工具校验 schema、落盘 `manifest.json` 并立即重算校验，逐条问题作为工具结果返回，驱动在环修正后重新提交。
3. **启用方式 = 默认启用 + 环境开关**：`A4_ENFORCE=0`（或 false/off/no）一键回观测模式；前置条件「账本有 corpus 活动才生效」不变。

## 现状（已探明的代码事实）

| 事实 | 位置 |
|---|---|
| `verify_manifest` / `_verify_conclusion` 校验端已实现；结论字段契约 = `id`、`evidence[]{doc_id,locator,quote,purpose}`、`required_dependencies[]`（词表 `DEPENDENCY_PURPOSES`）、`text_location`；`complete` 只记录不参与判定 | [ledger.py](../../../plugins/corpus/ledger.py) L618-743 |
| `verify_and_record` 缺清单 → `PUBLISH_DRAFT`；异常 → 降级 draft；落盘 `manifest_verification.json` | ledger.py L558-585 |
| `get_run_ledger()` 无参即可取同 run 共享账本（键 = `APODEX_RUN_DIR` 或进程单例）；`resolve_artifact_dir()`、`_write_json` 已有 | ledger.py L472-528 |
| `ConsumptionLedgerObserver` 在 `on_loop_end` 完成 delivered 核验并 `verify_and_record`（best-effort） | ledger.py L749-812 |
| agent_team 报告边界：`_run_fast_reporter` 产出 `report_md` → 观测模式 `verify_and_record` → `return {"final_answer": report_md, "answer_status": "complete", ...}` | [reporter.py](../../../workflows/agent_team/nodes/reporter.py) L350-372 |
| stateful_react 最终答案组装：`final_text = result.metadata.get("final_answer") or result.final_content`；`answer_status ∈ {complete, best_effort, not_found}`；此时观察者 `on_loop_end` 已跑完（delivered 已就绪） | [main_agent.py](../../../workflows/stateful_react_agent/nodes/main_agent.py) L1140-1193 |
| 工具绑定伴随注入先例：`web_fetch` 存在则补 `download_file` | main_agent.py L579-580 |
| stateful_react 工具解析：`_tools_for_stateful_react`（profile `agent_tools` 覆盖 或 role pool） | main_agent.py L544-598 |
| agent_team 子代理工具解析：`_sub_tools`（显式列表 / 名字解析 / role pool 三分支） | [subagent_runtime.py](../../../workflows/agent_team/subagent_runtime.py) L867-884 |
| 工具白名单：`_BUILTIN_TOOLS`（加模块 ≠ 可用，必须加白名单） | [plugins/tools/__init__.py](../../../plugins/tools/__init__.py) L44-86 |
| `EvidenceCard` 面向网络来源（`Source.url`），不含 `doc_id`/`locator`，不能用于语料溯源（§A4.3 已知未实现 #1 的根因） | [evidence.py](../../../workflows/_shared/research/evidence.py) L38-51 |
| `@tool` 从运行时类型注解派生 JSON schema；注解不得进 `TYPE_CHECKING`（Gotcha） | frontier_agent/core/tool.py |

## 改动明细

### 1. `plugins/corpus/ledger.py` — 发布门辅助

新增三件（不改动现有观测行为）：

- **`write_manifest(directory, payload) -> Path | None`**：复用 `_write_json` + `MANIFEST_FILENAME`。
- **`enforcement_enabled() -> bool`**：读 `A4_ENFORCE`，值 ∈ {0,false,off,no}（大小写不敏感）→ False；未设或其他 → True。
- **`enforce_publish_boundary(ledger, *, final_text, answer_status, directory=None, resolver=None) -> dict`**：
  - 全程 try/except：任何异常 → `{"action": "observe", ...}` + warning 日志（验证基础设施故障 fail-open，与账本模块 best-effort 哲学一致；**确定性的校验判定结果则执行阻断**）。
  - 无 corpus 活动（`not ledger.offered and not ledger.fetched`）→ `{"action": "skip"}`，原样返回。
  - 调 `verify_and_record(ledger, directory=directory, resolver=resolver)` 得 `status`：
    - `PUBLISH_VERIFIED` → `{"action": "publish", "publish_status": status}`，文本与状态不变。
    - 其他（partial / unsupported / draft）：
      - `not enforcement_enabled()` → `{"action": "observe", "publish_status": status}`，原样（工件已落盘）。
      - 否则 → `{"action": "downgrade", "final_text": <原文 + 限定块>, "answer_status": <降级>, "publish_status": status}`。
        - 限定块（追加在文本末尾，中文，机器可核验）：

          ```text
          ---

          > **证据完整性校验（A4）**：本报告未完全通过结论证据校验（状态：partial）。
          > 以下结论未获「逐字可溯源且完整送达」的原文支持，请按未校验草稿对待：
          > - C3 [quote_not_found]
          > 明细见 manifest_verification.json。
          ```

          逐条列出非 `supported` 结论的 `id + 问题码`（取自 verification 的 `conclusions[].problems[].code`，去重）；draft 情形改用「缺少结论证据清单」文案。
        - `answer_status` 降级规则：`complete → partial`（新值）；`not_found` / `best_effort` 保持原值（已更严重或语义不同），但文本限定块照附。
- **`verify_and_record` 增加可选参数 `extra: dict[str, Any] | None = None`**：合并进写盘的 verification 工件（记录 `boundary_action` / `publish_status`，回放分析直接读工件）。schema_version 不变，纯增量字段。

### 2. `plugins/tools/corpus_manifest.py` — 新工具（清单生产者）

```python
@tool
def corpus_submit_manifest(conclusions: list[dict[str, Any]]) -> str: ...
```

- **入参契约**（= 校验端靶子）：每条结论 `{id?, text_location?, evidence: [{doc_id, locator, quote, purpose?}], required_dependencies?: [...]}`。`id` 缺省自动编 `C{n}`。
- **校验**（schema 层，先于权威校验）：`conclusions` 非空列表；每条 `evidence` 非空且每项三字段齐备；`purpose` / `required_dependencies` 必须属于 `DEPENDENCY_PURPOSES` 词表（杜撰用途直接拒绝，防止依赖核验被空转）。失败 → `{"ok": false, "errors": [...]}`，**绝不 raise**。
- **落盘**：包信封 `{"schema_version": MANIFEST_SCHEMA_VERSION, "produced_at": <iso>, "conclusions": [...]}` → `write_manifest(resolve_artifact_dir(), ...)`；无 run 目录时跳过落盘但仍回验。
- **即时回验**：`verify_manifest(manifest, get_run_ledger())`（默认 resolver 走 `get_service().fetch_verbatim`），工具结果返回：

  ```json
  {"ok": true, "publish_status": "partial", "counts": {...},
   "conclusions": [{"id": "C3", "status": "unsupported",
                    "problems": [{"code": "quote_not_found", "message": "..."}]}],
   "hint": "对非 supported 结论：补充取证（corpus_fetch）、降级表述或从报告中移除，然后重新提交完整清单"}
  ```

- docstring 用 Google 风格说明用途与字段；重复提交整体覆盖 `manifest.json`（以最后一次为准）。

### 3. `plugins/tools/__init__.py` — 白名单

import `corpus_submit_manifest`，加入 `_BUILTIN_TOOLS` 的语料区块（`corpus_search/corpus_fetch/corpus_inventory` 旁，注明只读、仅写 run 工件）。

### 4. 工具绑定 — 伴随注入（复用 web_fetch→download_file 先例）

- **stateful_react**：`_tools_for_stateful_react`（main_agent.py L544-598）两条返回路径统一处理：结果工具集中含 `corpus_fetch` 且不含 `corpus_submit_manifest` 时，从 `all_tools` 补入并记日志。在函数出口做（对 override 与 role pool 两分支都生效）。
- **agent_team**：`_sub_tools`（subagent_runtime.py L867-884）出口统一补（含显式 `sub_agent_tools` 分支——少配即全降级，补齐更稳）。
- **提示词注入**（仅当工具实际绑定时）：
  - stateful_react：main_agent.py system_prompt 组装处（约 L880 `runtime_notes` 之后）追加一段：报告前用 `corpus_submit_manifest` 提交全部语料结论清单；按工具返回的问题修正/降级/移除并重新提交；最终答案不得主张清单标 unsupported 的结论。
  - agent_team：subagent_runtime.py L144-185 的 prompt builder（`manifest_namespace` 同址）加对应段。
  - 主代理/协调者也用 corpus 时同样需要——stateful_react 只有主循环一处；agent_team 若主代理绑定 corpus 工具，在其观察者/提示组装点（main_agent.py L701 附近）同段注入。

### 5. 边界接线 — 降级发布

- **agent_team**：reporter.py L350-361 观测块替换为：

  ```python
  from plugins.corpus.ledger import enforce_publish_boundary, get_run_ledger
  outcome = enforce_publish_boundary(
      get_run_ledger(), final_text=report_md, answer_status="complete",
  )
  report_md = outcome["final_text"]
  ```

  return dict 的 `answer_status` 用 `outcome["answer_status"]`（异常已由 enforce 内部兜底为 observe，无需外层 try）。
- **stateful_react**：main_agent.py L1162（`answer_status` 算出后、return 前）：

  ```python
  outcome = enforce_publish_boundary(
      get_run_ledger(), final_text=final_text, answer_status=answer_status,
  )
  final_text = outcome["final_text"]
  answer_status = outcome["answer_status"]
  ```

  return dict 增加增量字段 `"a4_publish_status": outcome.get("publish_status", "")`（新键，不破坏现有消费者）。
- reporter 失败路径（`report_md` 空 / 生成异常 → `return {}`）不变；阻断只作用于已产出报告。
- ReportSynthesisObserver（stateful_react 的 reporter-enabled 路径）产出的 `final_answer` 同样流经 L1144 的组装点，天然被覆盖。

### 6. 测试

- **tests/test_corpus_ledger.py 扩展**（`enforce_publish_boundary`）：
  1. 无 corpus 活动 → skip，文本/状态原样；
  2. verified → publish，原样；
  3. partial / unsupported → downgrade：限定块含结论 id 与问题码、`complete→partial`；
  4. 缺清单（draft）→ downgrade + 「缺少清单」文案；
  5. `A4_ENFORCE=0` → observe，原样（工件仍落盘）；
  6. resolver 抛异常 → observe（fail-open）；
  7. `verify_and_record(extra=...)` 合并进工件。
- **tests/test_corpus_manifest_tool.py 新建**：schema 拒绝路径（空清单/缺 quote/杜撰 purpose）；quote 可溯源 + delivered → supported；编造 quote → 问题清单返回；重复提交覆盖；全程不 raise；tmp 目录 monkeypatch `APODEX_RUN_DIR` + stub resolver/service。
- **接线测试**（并入 tests/test_runaway_and_repetition_wiring.py 风格）：含 `corpus_fetch` 的工具集解析出 `corpus_submit_manifest`（stateful_react 与 `_sub_tools` 各一）；reporter / stateful_react 边界调用 enforce 的源码级断言。

### 7. 文档

- **docs/data_clean_dos/01-table-recovery.md**：状态行 v2→v3（「A4 阻断已启用（默认开，`A4_ENFORCE=0` 关）」）；§A4.2 补「阻断已启用」小节（降级发布语义、开关、伴随绑定、fail-open 约定、`answer_status=partial` 新值）；§A4.3 已知未实现 #1 改写为已实现（生产者 = `corpus_submit_manifest`）。
- **docs/data_clean_dos/README.md**：v4→v5；§5 执行状态加「A4 阻断启用」行；§6 验收记录加测试行。

## 假设与决策记录

- **`answer_status` 新值 `partial`**：现有消费方（smoke harness 等）读答案文本而非状态值；若某评分管线 gate 在 `complete` 上会受影响——回放对照时用 `A4_ENFORCE=0`。风险已在文档记录。
- **阻断范围**：仅「账本有 corpus 活动」的 run；browsecomp 等非语料基准天然豁免。
- **fail-open 边界**：验证基础设施异常 → 观测放行；确定性判定（quote 编造、缺清单等）→ 执行降级。与「先观察误报再阻断」的演进路径一致，误报可通过开关快速回退。
- **清单以最后一次提交为准**：模型修正后重新提交整个清单，`manifest.json` 整体覆盖，避免增量合并的歧义。
- **agent_team 显式 `sub_agent_tools` 也补伴随工具**：少配即全降级，补齐并记日志比静默缺失更稳。

## 验证

```bash
uv run pytest tests/test_corpus_ledger.py tests/test_corpus_manifest_tool.py tests/test_runaway_and_repetition_wiring.py -q
uv run pytest apodex/tests -q
uv run ruff check . && uv run ruff format .
uv run python -m tools.import_smoke --stage 1
uv run pyright
```

可选实测：`A4_ENFORCE=1` 复跑 1 题 smoke（观察 trace 中清单提交、工具回验问题与边界动作），对照 `A4_ENFORCE=0` 确认开关回退有效。
