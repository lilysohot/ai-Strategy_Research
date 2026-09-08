# 07 · `strategy.json` schema 与落盘

Type: task
Status: closed
Blocked by: 03, 05

**Goal**: 定义策略卡的权威结构，并让 Agent 能稳定产出它。
这是「机器校验」与「人读报告」两条链路的共同源头。

**Work**
定义 schema 常量（建议 `plugins/corpus/strategy_schema.py`，含版本号与校验入口）。
在 `docs/tittel/trading-strategy-platform-feasibility.md:185-207` 基础上按 P0 收窄
（去掉 portfolio 聚合，强化 evidence 溯源）：

```jsonc
{
  "version": 1,
  "capital_total": 1000000,
  "position": {
    "symbol": "600519.SH",
    "thesis": "……",                        // 定性判断，LLM 产出
    "evidence": [                          // 每条必带出处，可逐字溯源
      {"source_ref": "stub:R01", "page": 1,
       "quote": "……逐字原文……", "kind": "fact"}   // fact | forecast | opinion
    ],
    "entry": {"low": 1420, "high": 1450},
    "stop_loss": 1310, "target": 1720,
    "invalidation": "季度营收同比转负",      // 可证伪，必填
    "horizon": "3-6M",                     // 必填
    "sizing": {
      "risk_budget_pct": 1.0, "shares": 300, "amount": 435000, "weight_pct": 43.5,
      "computed_by": "position_sizing@v1"  // 硬闸②
    }
  },
  "lint": {"passed": true, "errors": [], "warnings": []},
  "disclaimer": "本研究性推演不构成投资建议，不涉及任何交易执行。"
}
```

**落盘约定**
- Agent 写 `/outputs/strategy.json`（结构给机器）+ `/outputs/report.md`（给人）
- 复用现有 `create_file` 工具落盘，走 T2.9 产物链（`<run_dir>/ws/outputs/` 扫描入库）
- `/outputs` 是 `FRONTIER_AGENT_OUTPUTS_DIR`，已由 worker 预检保证指向 run 目录

**关键约束**
- `evidence[].quote` 必须是**逐字原文**（P0a 来自 stub 研报，P0b 来自 `corpus_fetch`）
- `kind` 三值区分是精度红线：**fact 与 forecast 混用视为答案错误**
- `sizing` 只能来自 `position_sizing` 的返回，**禁止手填**

**Acceptance**
- schema 常量可被 05 的 `strategy_lint` 与将来的离线校验脚本共同引用（单一定义）
- P0a 产出的 `strategy.json` 能被 `strategy_lint` 校验通过
- `report.md` 中关键数字后可追溯（P0a 阶段至少带 `source_ref`，如 `[stub:R01 p1]`）

## Answer

`plugins/corpus/strategy_schema.py`。

**为什么放在 `plugins/corpus/` 而不是别处**：规格 §7 的 `python -m plugins.corpus.verify`
与 §4.2 的 `python -m plugins.corpus.ingest` 已经把它定为资料库的包位置。
⚠️ 该包在 P0a 必须保持**纯标准库**——`tools/import_smoke.py --stage 1` 会
遍历导入 `plugins` 下每一个模块，P0b 才需要的 `pymupdf` / `jieba` 一旦被
顶层导入就会让 stage 1 变红。（已验证：294/294 模块导入通过。）

内容：

- 常量：`POSITION_SIZING_ID="position_sizing@v1"`、`STRATEGY_LINT_ID`、
  `EVIDENCE_KINDS=(fact, forecast, opinion)`、`HORIZONS`、
  `RISK_BUDGET_MIN/MAX_PCT`、`DEFAULT_LOT_SIZE`、`DEFAULT_MAX_WEIGHT_PCT`、
  `TUNABLE_PARAM_BUDGET`、`MIN_RISK_REWARD`、`DISCLAIMER`。
- 函数：`build_strategy_card()` / `dump_strategy_json()` / `position_of()` /
  `sizing_of()`。
- `dump_strategy_json` 用 `ensure_ascii=False`：evidence 的 quote 是中文原文，
  转义成 `\uXXXX` 后人工不可核，而这份文件本来就是给人核的。
- `HORIZONS` 定为 `1-5D / 1-4W / 1-3M / 3-6M / 6-12M / 12M+`——
  规格只写了「预设枚举」没给值，这是本实现选定的封闭集合。
- 05 的 `strategy_lint` 与将来的离线校验脚本共用同一套常量；
  `tests/test_strategy_lint.py::test_card_built_from_schema_passes_lint`
  把「schema 常量 / 构建函数 / 校验器」三者钉在一起，防止各写一份字面量后分叉。

落盘仍由 Agent 用 `create_file` 写到 `/outputs/strategy.json`（无新代码）。
`tests/test_p0a_chain.py::test_card_sizing_is_byte_identical_to_the_tool_result`
锁死「sizing 与 position_sizing 返回逐字段一致」。

## Comments
