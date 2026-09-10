"""B6：黄金题评测锁死 Recall@5 = 100%（**仅在与当前样本匹配时判定**）。

依赖 PG 语料库；PG 不可用或无数据时跳过——不让 CI 因缺料而红。

⚠️ **这份题是人工绑定样本语料的**：每题 ``expects`` 指向具体的 ``doc_id`` 前缀 / 标题子串。
   一旦语料样本被整体替换，这些锚点就不存在了，Recall 必然为 0——
   **那不是检索退化，而是标尺与被测对象不匹配**。
   所以本测试先做**锚点存在性检查**：

   - 一份锚点文档都匹配不上 → **skip**，并提示重建 ``GOLDEN_SET``；
   - 部分匹配 → 照常判定（此时掉分是真实信号，值得追查）；
   - 全部匹配 → 严格断言 Recall@5 = 100%。

这份题同时是「是否上向量」的判据输入：哪类题掉分，就说明当前 FTS 在哪类语义上不够。
当下 Recall@5 = 100%，所以 pgvector 保持"留位不建列"。
"""

from __future__ import annotations

import pytest

from plugins.corpus.golden import GOLDEN_SET, format_golden_report, run_golden
from plugins.corpus.service import get_service


def _pg_ready() -> bool:
    try:
        return get_service().stats()["documents"] > 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_ready(),
    reason="PG 语料库不可用或无数据（默认 postgresql://postgres:postgres@localhost:5432/postgres）",
)


def _anchors_present(svc) -> int:
    """统计「至少一个期望文档仍在库中」的题目数。

    判定必须按**单份文档**做：标题命中与 doc_id 前缀命中要落在同一条记录上，
    否则会误判为"锚点仍在"。
    """
    docs = svc.list_documents()
    covered = 0
    for question in GOLDEN_SET:
        for matcher in question.expects:
            found = any(
                matcher.title_contains in str(doc.get("title") or "")
                and (
                    not matcher.doc_prefix
                    or str(doc.get("doc_id") or "").startswith(matcher.doc_prefix)
                )
                for doc in docs
            )
            if found:
                covered += 1
                break
    return covered


def test_golden_recall_at_5_is_full() -> None:
    svc = get_service()

    covered = _anchors_present(svc)
    if covered == 0:
        pytest.skip(
            f"黄金集绑定的样本语料已不在库中（0/{len(GOLDEN_SET)} 题的锚点文档存在），"
            "Recall 失去意义。请按新样本重建 plugins/corpus/golden.py 的 GOLDEN_SET。"
        )

    report = run_golden(svc, top_k=5)
    # 一旦任何一类掉到 100% 以下，说明检索退化或语料结构变了，
    # 必须先解释再调阈值——这是 P0b 验收的硬指标。
    assert report.recall == 1.0, format_golden_report(report)
