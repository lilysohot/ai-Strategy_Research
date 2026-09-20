import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from plugins.corpus.preparation import guard
config = conninfo_to_dict(dotenv_values(ROOT / ".env")["CORPUS_DSN"])
dsn = make_conninfo("", user=config.get("user"), password=config.get("password"),
                   host="127.0.0.1", port=543, dbname="i2_sandbox_corpus", connect_timeout=5)
guard.install(BASE / "guards/i3-e2e.json")
from plugins.corpus.preparation.repository_pg import PgStore
record = json.loads((BASE / "audits/20260920-i31-signed-release/review-dddc7cd0.json").read_text())
approved = json.loads((BASE / "i3-2/evidence-targets-approved.json").read_text())
quotes = sorted({t["quote"] for q in approved["questions"] for role in ("approved_required", "supplementary")
                 for t in q.get(role, []) if t["source_id"].endswith("_dddc7cd0") and "page:7" in t["locator"]})
with PgStore(dsn) as store:
    source = store.get_source(record["source_id"])
    units = [u for u in store.get_units(record["build_id"]) if u.location.page == 7]
    print(json.dumps({"archive_path": source.archive_path, "quotes": quotes,
                      "units": [{"id": u.unit_id, "status": u.status.value, "bbox": u.location.bbox,
                                  "text": u.raw_text} for u in units]}, ensure_ascii=False, indent=2))
