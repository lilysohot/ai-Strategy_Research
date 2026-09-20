"""人工 gap-review 签字辅助：渲染被阻断 PDF 的相关页供 U 审阅签署。

对每份被阻断 build 的 PDF，导出被堵页面的 PNG 渲染与 kept 文本，供以人工逐页
核对的一侧签署 gap-review 凭证（`human-gap-review-1` page / `human-gap-review-2`
region 两 schema）。本脚本**只读**来源 PDF，不生成任何签名/引号。

用法(仓库根)::

    uv run python .scratch/.../20260920-i35-reingest-pdf5/review_aid.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
OUT = HERE / "review-aid"
SANDBOX_DB = "i2_sandbox_corpus"

BLOCKED = {
    # name -> (pdf path, blocked page numbers)
    "maotai-huachuang": ("data/corpus/2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张慧-公司研究-业绩点评-贵州茅台-600519-报表实质扎实-经营底部已过-贵州茅台-600519-2026年中报点评-e034bdac.pdf", [2]),
    "guangli-guoxin": ("data/corpus/2026-09-06_2026.09.06-国信证券-光力科技-300480-2026年中报点评-半导体划片机国内龙头-经营拐点向上-b6beb6ee.pdf", [7]),
    "changjiang-shiwenda": ("data/corpus/2026-08-13_2026.08.13-长江证券-国内研报-长江证券-化工专题-景气投资-十问十答-7463f4d0.pdf", [1, 2, 3, 12, 13, 17, 18, 21, 22, 24]),
    "guangda-feinong": ("data/corpus/2026-09-06_2026.09.06-光大证券-2026年8月美国非农数据点评-强非农降低了年内加息的门槛-6fc25e24.pdf", [6]),
}


def main() -> int:
    os.environ["CORPUS_DEV_LANE"] = "1"
    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation import guard  # noqa: PLC0415
    guard.install(str(ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json"))  # noqa: E501

    env = {l.split("=", 1)[0]: l.split("=", 1)[1] for l in open(ROOT / ".env", encoding="utf-8") if "=" in l and not l.strip().startswith("#")}  # noqa: E501
    cred = env["CORPUS_DSN"].split("://", 1)[1].rsplit("@", 1)[0]
    dsn = f"postgresql://{cred}@127.0.0.1:543/{SANDBOX_DB}"

    manifest = []
    OUT.mkdir(parents=True, exist_ok=True)
    import pymupdf  # noqa: PLC0415

    for name, (rel, pages) in BLOCKED.items():
        pdf_path = ROOT / rel
        raw = pdf_path.read_bytes()
        entry = {"name": name, "path": rel, "blocked_pages": pages}
        with pymupdf.open(stream=raw, filetype="pdf") as doc:
            for page_no in pages:
                page = doc[page_no - 1]
                img = page.get_pixmap(dpi=150)
                img_path = OUT / f"{name}-p{page_no}.png"
                img.save(img_path)
                text_path = OUT / f"{name}-p{page_no}.txt"
                text_path.write_text(page.get_text(), encoding="utf-8")
                entry["pages_" + str(page_no)] = {
                    "png": str(img_path.relative_to(ROOT)),
                    "native_text_len": len(page.get_text()),
                    "image_count": len(page.get_image_info()),
                }
        manifest.append(entry)
        print(json.dumps(entry, ensure_ascii=False, indent=2))
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("output dir:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())