"""D2 P6：文档级元数据派生与入库（d2-claims-design §3.5 可得子集）。

**只做可得且有用途的字段**（§3.5 纪律：19% 可得的字段不许做成核心字段）：

| 字段 | 来源 | 实测可得性（78 份） | 用途 |
|---|---|---|---|
| ``doc_kind`` | 派生（override 优先，否则 §3.1 规则） | 78/78 | 决定插槽；D3/D4 无需重算 |
| ``subject`` | company → 文档级标的；industry/macro → NULL | 3/78 | claim 坐标兜底 |
| ``org`` | 标题 ``日期-机构-…`` 第二段 | 38/78（19 家） | **D4 一机构一票**的 join 键 |
| ``analysts`` | 首块 ``分析师：X`` | 20/78 | 可选溯源字段 |
| ``published`` | ingest 已填（doc_id 前缀）；undated 回退首块日期 | 54 → 59/78 | 时效排序、as_of 偏置 |

**设计上已删除**（§3.5）：版本（研报只有发布日期）、来源系统（语料就是文件系统）、
校验状态（``claim_block_runs.status`` 已承担）。

**正则口径均来自 78 份语料实测**（见各函数 docstring），不做超前泛化：
- 首块机构词检索实测全为误报（"历史研究" / "持牌证券"），故 org 只认标题；
- 执业编号格式 ``X（执业S…）`` / ``X(S0210…)`` 只取姓名段；
- ``undated_*`` 文档的首块日期实测仅 5 份可解析，与 §3.5 "59/78 可解析" 吻合。

非空即覆盖 vs 只回填：``doc_kind`` / ``subject`` / ``org`` / ``analysts`` 以派生为
唯一权威（不存在手工编辑路径），**非空即覆盖**保证幂等；``published`` 里 ingest
已写入的值是 doc_id 事实，**只回填 NULL** 不覆盖。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from plugins.corpus.claims import DOC_KINDS, classify_doc_kind, document_ticker

#: 老库幂等迁移：documents 加四列（新装库由 init_db 一并执行）
DOCUMENTS_MIGRATIONS_SQL = """
ALTER TABLE documents ADD COLUMN IF NOT EXISTS doc_kind  text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS subject   text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS org       text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS analysts  text[];
"""

#: 标题 ``2026.08.17-国信证券-…``：日期前缀 + 机构段（org 的唯一来源）
_TITLE_ORG_RE = re.compile(r"^(20\d{2})\.(\d{2})\.(\d{2})-([^-]+)-")

#: doc_id ``2026-08-17_c195233b`` 的日期前缀（ingest 现行口径）
_DOC_ID_DATE_RE = re.compile(r"^(20\d{2})-(\d{2})-(\d{2})")

#: 正文日期 ``2026/09/08`` / ``2026-09-08`` / ``2026年09月08`` / ``2026年08月31``
_TEXT_DATE_RE = re.compile(r"(20\d{2})[/.年](\d{1,2})[/.月](\d{1,2})")

#: 首块 ``分析师：张向伟（执业S1130525060002）`` / ``分析师：李浩(S0210524050003)``
#: 只取姓名段——执业编号、多人顿号列表在语料中未出现，不做超前泛化
_ANALYST_RE = re.compile(r"分析师[:：]\s*([\u4e00-\u9fa5]{2,4})")


def _as_date(y: str, m: str, d: str) -> date | None:
    """字符串转 date，非法日期（2026/13/45）返回 None 而不是抛错。"""
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def derive_org(title: str) -> str | None:
    """机构：标题第二段（``2026.08.17-国信证券-…`` → ``国信证券``）。

    语料实测 38/78 命中（19 家券商/机构）；首块机构词检索全为误报，不做回退。
    """
    m = _TITLE_ORG_RE.match(title or "")
    return m.group(4) if m else None


def derive_analysts(first_block: str | None) -> list[str]:
    """作者：首块 ``分析师：X`` 的姓名段（含执业编号的只取姓名）。实测 20/78。"""
    m = _ANALYST_RE.search(first_block or "")
    return [m.group(1)] if m else []


def derive_published(doc_id: str, title: str, first_block: str | None) -> date | None:
    """发布日期：doc_id 前缀 → 标题日期 → 首块正文日期，逐级回退。实测 59/78。"""
    m = _DOC_ID_DATE_RE.match(doc_id or "")
    if m and (d := _as_date(*m.groups())):
        return d
    m = _TITLE_ORG_RE.match(title or "")
    if m and (d := _as_date(m.group(1), m.group(2), m.group(3))):
        return d
    if first_block:
        # 扫到首个**合法**日期为止（2026/13/45 这类假日期跳过继续找）
        for m in _TEXT_DATE_RE.finditer(first_block):
            if d := _as_date(m.group(1), m.group(2), m.group(3)):
                return d
    return None


def derive_metadata(
    doc_id: str,
    title: str,
    texts: list[str],
    doc_kind_override: str | None = None,
) -> dict[str, Any]:
    """一份文档的元数据全集（§3.5 可得子集）。

    ``doc_kind`` 与 ``CorpusService.extract_claims`` 同口径：override 优先，
    否则零成本规则分类——物化只是把这套判定**落到列**，抽取链路行为不变。
    """
    kind = doc_kind_override if doc_kind_override in DOC_KINDS else classify_doc_kind(title, texts)
    # subject 只给 company（industry/macro 的主体编码在 metric 前缀里，
    # 给错的坐标比缺失更危险——与文档级标的兜底同一纪律）
    subject = document_ticker(title, texts) if kind == "company" else None
    return {
        "doc_kind": kind,
        "subject": subject,
        "org": derive_org(title),
        "analysts": derive_analysts(texts[0] if texts else None),
        "published": derive_published(doc_id, title, texts[0] if texts else None),
    }
