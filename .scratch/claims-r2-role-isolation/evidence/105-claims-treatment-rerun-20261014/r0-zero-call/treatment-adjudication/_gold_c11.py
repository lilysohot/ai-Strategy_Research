import json

G = "/home/administrator/FrontierAgent/.scratch/claims-r2-role-isolation/evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json"
d = json.load(open(G))
for r in d["records"]:
    rid = r["record_id"]
    if rid.startswith("NT-C") and 11 <= int(rid[5:]) <= 20:
        sf = r["semantic_fields"]
        print(rid, "| critical=", r.get("critical"), "| factuality=", sf.get("factuality"))
        print("   quote:", r.get("quote"))
        print("   subject:", sf.get("subject"), "| metric:", sf.get("metric"))
        print("   value:", sf.get("value"), "| unit:", sf.get("unit"), "| period:", sf.get("period"))
        print()
