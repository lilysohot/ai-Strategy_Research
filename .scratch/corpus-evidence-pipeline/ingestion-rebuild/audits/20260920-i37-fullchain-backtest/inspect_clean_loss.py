"""只读核查：i37 桶 `doc_not_kept_clean_stage_loss` 的 2 条，究竟卡在哪一层。

问题：报告把它们记为"清洗剔除/NOISE"。需要确认是
  (a) 清洗 NOISE 判定（可能与本轮单元边界变化有关 = 我们的副作用），还是
  (b) admission scope 裁剪（OUT_OF_SCOPE，口径使然），还是
  (c) 单元 REVIEW_REQUIRED / NEEDS_OCR。
只读 PG，不写任何东西。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE
while not (ROOT / "plugins").is_dir():
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

from plugins.corpus.preparation import guard  # noqa: E402
from plugins.corpus.preparation.repository_pg import PgStore  # noqa: E402

WS = re.compile(r"\s+")
TARGETS = {("company-007", "e1"), ("company-008", "a-1")}


def norm(s: object) -> str:
    return WS.sub("", s) if isinstance(s, str) else ""


def connect() -> str:
    config = conninfo_to_dict(dotenv_values(ROOT / ".env")["CORPUS_DSN"])
    return make_conninfo(
        "",
        user=config.get("user"),
        password=config.get("password"),
        host="127.0.0.1",
        port=543,
        dbname="i2_sandbox_corpus",
        connect_timeout=5,
    )


def main() -> None:
    ident = json.loads((HERE / "source-identity-map.json").read_text())
    print("identity map 键:", list(ident))
    builds = ident.get("active_builds") or {}
    aliases = ident.get("aliases") or {}
    print("active_builds 样例:", list(builds)[:2])
    print("aliases 样例:", list(aliases.items())[:2])
    rows = json.loads((HERE / "diagnostics.json").read_text())
    need = [r for r in rows if (r["query_id"], r["target_id"]) in TARGETS]

    with PgStore(connect()) as store:
        for r in need:
            print("=" * 88)
            print(f"ITEM {r['query_id']} {r['target_id']} locator={r['locator']} src={r['source_id']}")
            qn = norm(r["quote"])
            key = r["source_id"]
            # aliases 是 sha -> 别名，这里要反向解析
            sha = next((s for s, alias in aliases.items() if alias == key), key)
            build = builds.get(sha) or builds.get(key)
            if build is None:
                cand = [b for k, b in builds.items() if k.startswith(key) or key.startswith(k[:12])]
                build = cand[0] if cand else None
            print("  build:", build)
            if build is None:
                continue
            units = store.get_units(build)
            page = int(str(r["locator"][0]).split(":")[1])
            on_page = [u for u in units if u.location.page == page]
            kept_text = norm("\n".join(u.raw_text for u in on_page if str(u.status).endswith("KEPT")))
            print(f"  该页单元数={len(on_page)}  引文是否在 kept 拼接中={qn in kept_text}")
            for u in on_page:
                mark = "  <<< 含引文片段" if any(
                    p and p in norm(u.raw_text) for p in (qn[:20], qn[-20:])
                ) else ""
                print(f"    ord={u.ordinal} status={u.status} reasons={u.reasons} "
                      f"len={len(u.raw_text)}{mark}")
                if mark:
                    print(f"        raw={u.raw_text[:200]!r}")


if __name__ == "__main__":
    main()
