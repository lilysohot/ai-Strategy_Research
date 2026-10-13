# 评分器直接读取签认契约 v4.3

Issue 45 将 P03 评分器的门真源从代码内嵌快照改为签认契约文件：

`evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json`

该文件既有 SHA-256 为 `d7b4f8a81ef42e3cd5d619eae92bc34df7b7aa683d34aeba4f1a22719ae69a2f`，本次没有修改其字节。

## 验收结果

评分器现在从同一文件直接读取：

- 六项 `threshold_source.effective` 门阈值：0.85 / 0.80 / 0.80 / 40 / 20 / 0；
- `review_assertions` 中恰好 11 个 `NT-I*` 哨兵。

缺文件、非法 JSON、schema 错误、非签认状态、签认信息缺失、阈值缺失或类型错误、哨兵数量错误均失败关闭。回归还通过临时契约把 overall recall 改为 0.90、把 `NT-I48` 换为 `NT-I99`，证明 loader 消费所选文件内容，而不是继续使用代码常量。

冻结 P03 以 `--no-write` 复算，结果逐项保持：

```json
{
  "verdict": "PASS",
  "failed_criteria": [],
  "recall": "41/48",
  "precision": "30/31",
  "per_source": {"源1": 0.909, "源2": 0.808},
  "sentinel": "11/11",
  "delta_matched": 7
}
```

## 验证

- `pytest tests/test_corpus_contract_gate.py -q`：22 passed。
- `pytest tests/test_corpus_contract_gate.py tests/test_corpus_structured_scoring.py tests/test_corpus_structured_scoring_adjudicated.py -q`：65 passed。
- `ruff check plugins/corpus/structured_scoring.py tests/test_corpus_contract_gate.py tools/check_freeze_chain.py`：通过。
- `pyright plugins/corpus/structured_scoring.py tools/check_freeze_chain.py`：0 errors。
- `python tools/check_freeze_chain.py`：`ok=17 covered=8 drift=0 needs_ruling=0`。

模型调用、抽取调用、生产 PostgreSQL 访问均为 0。冻结金标、签认契约及既有评分产物均未改写。
