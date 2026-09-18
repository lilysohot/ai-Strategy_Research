"""User-authorized six-PDF read-only annotation phase; never uses ingestion outputs."""
import hashlib
import io
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[2]
sys.path.insert(0, str(ROOT))
CONFIG = HERE / "annotation-guard.json"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_once(path, value):
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def main():
    if sys.argv[1] == "prepare":
        rows = [json.loads(s) for s in (BASE / "source-gold-frozen.jsonl").read_text().splitlines() if s]
        hashes = {r["source_sha256"]: r["source_id"] for r in rows}
        inventory = json.loads((BASE / "dev-manifest.json").read_text())
        sources = [{"source_id": hashes[r["source_id"]], "sha256": r["source_id"], "path": r["path"]}
                   for r in inventory["sources"] if r["source_id"] in hashes]
        assert len(sources) == 6 and len({s["sha256"] for s in sources}) == 6
        config = json.loads((BASE / "guards/i3.json").read_text())
        config["phase"] = "i3-2-agent-annotation-readonly"
        config["note"] = "用户明确授权六份冻结开发PDF只读补证；零网络/模型/PG，保留三份留出隔离；不改i3守卫。"
        config["sources"]["read_roots"] = ["data"]
        config["sources"]["allowed_source_paths"] = [s["path"] for s in sources]
        assert not set(config["sources"]["allowed_source_paths"]) & set(config["sources"]["forbidden_roots"])
        write_once(CONFIG, config)
        write_once(HERE / "authorized-sources.json", {"sources": sources,
            "guard_sha256": sha(CONFIG.read_bytes()),
            "source_gold_sha256": sha((BASE / "source-gold-frozen.jsonl").read_bytes()),
            "user_authorization": "允许六份开发 PDF 只读补证",
            "reviewer": "Codex AI-assisted, final human sign-off pending"})
        from plugins.corpus.preparation.guard import run_selfcheck
        report = run_selfcheck(CONFIG)
        write_once(HERE / "annotation-guard-selfcheck.json", report)
        print("guard selfcheck", report["passed"], len(report["cases"]))
        assert report["passed"]
        return
    assert sys.argv[1] == "extract"
    from plugins.corpus.preparation.guard import install
    install(CONFIG)
    # Explicit guarded Python read before the native renderer receives only memory bytes.
    import pymupdf
    import pdfplumber
    authorized = json.loads((HERE / "authorized-sources.json").read_text())
    assert sha(CONFIG.read_bytes()) == authorized["guard_sha256"]
    proof = json.loads((HERE / "annotation-guard-selfcheck.json").read_text())
    assert proof["passed"] and proof["config_sha256"] == authorized["guard_sha256"]
    output = HERE / "pages"
    output.mkdir(exist_ok=True)
    selected = {"2026-08-16_6f14cc14": [1, 3, 7], "2026-09-06_dddc7cd0": [1, 3, 7, 20],
                "2026-08-13_174b6462": [10], "2026-09-06_f8e31696": [1],
                "2026-09-06_cc03f55b": [1, 2], "2026-09-06_793b3967": [1]}
    records = []
    for source in authorized["sources"]:
        data = (ROOT / source["path"]).read_bytes()
        assert sha(data) == source["sha256"], "source drift"
        doc = pymupdf.open(stream=data, filetype="pdf")
        independent = pdfplumber.open(io.BytesIO(data))
        assert len(doc) == len(independent.pages)
        pages = []
        for number, page in enumerate(doc, 1):
            text = page.get_text()
            second_text = independent.pages[number - 1].extract_text() or ""
            pages.append({"page": number, "text": text, "independent_text": second_text,
                          "text_chars": len(text), "image_count": len(page.get_images()),
                          "drawing_count": len(page.get_drawings())})
            if number in selected[source["source_id"]]:
                destination = output / f"{source['source_id']}-p{number}.png"
                assert not destination.exists()
                destination.write_bytes(page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6)).tobytes("png"))
        write_once(output / (source["source_id"] + ".json"), {**source, "pages": pages})
        records.append({**source, "page_count": len(pages),
                        "sparse_pages": [p["page"] for p in pages if len(p["independent_text"].strip()) < 80],
                        "text_sha256": sha((output / (source["source_id"] + ".json")).read_bytes())})
        print(source["source_id"], len(pages), "pages", sum(len(p["text"]) for p in pages), "chars", flush=True)
        independent.close()
        doc.close()
    write_once(HERE / "source-read-audit.json", {"guard_sha256": authorized["guard_sha256"],
        "reader": "pymupdf + independent pdfplumber; not production ingestion parser", "sources": records,
        "model_calls": 0, "network_calls": 0, "pg_calls": 0, "human_signoff": False})


if __name__ == "__main__":
    main()
