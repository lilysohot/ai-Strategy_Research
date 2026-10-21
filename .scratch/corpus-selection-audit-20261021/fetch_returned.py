"""Read original text for the saved actual outputs; no search or embedding calls."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from plugins.corpus.preparation.read_pg import fetch_verbatim
from plugins.corpus.retrieval.cli import pilot_dsn
from plugins.corpus.retrieval.embedding import VectorConfig


def main():
    load_dotenv(ROOT / ".env")
    config = VectorConfig.from_env()
    target = pilot_dsn(config)
    manifest = json.loads(
        (ROOT / ".scratch/corpus-vector-acceptance-20261020/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    cache = {}
    for case in manifest["cases"]:
        capture = json.loads((HERE / f"captures/{case['id']}.json").read_text(encoding="utf-8"))
        evidence = {}
        for hit in capture["public_hits"]:
            locators = [hit["locator"]]
            # Show existing labelled anchors only if actually in the returned scope.
            if hit["build_id"] == case.get("build_id"):
                locators.extend(
                    "chunk:" + chunk for chunk in case.get("gold_chunks", [])
                    if "chunk:" + chunk in hit["context_locators"]
                )
            for locator in dict.fromkeys(locators):
                key = (hit["doc_id"], locator)
                if key not in cache:
                    cache[key] = asdict(fetch_verbatim(
                        target, hit["doc_id"], locator, sandbox_db=config.target_db
                    ))
                value = cache[key]
                assert value["source_id"] == hit["source_id"]
                evidence[value["chunk_id"]] = value
        out = HERE / "returned-text" / (case["id"] + ".json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "case": case["id"],
            "manifest_sha256": capture["manifest_sha256"],
            "method": "fetch_verbatim(saved doc_id, saved locator); not a new retrieval",
            "chunks": evidence,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Read {len(cache)} unique original chunks for {len(manifest['cases'])} saved outputs")
    first = cache[next(key for key in cache if key[1] == "chunk:16a9a510ef9e405f:body:0001")]
    text = first["text"]
    pos = text.find("互连电容")
    print("p01 verified original excerpt:", text[max(0, pos-70):pos+150])


if __name__ == "__main__":
    main()
