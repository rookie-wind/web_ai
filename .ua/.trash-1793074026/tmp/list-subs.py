"""列出各批次中满足显著性阈值的类与函数名，供人工撰写语义时对齐清单。"""

import io
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

FN_MIN = 25
root = Path(sys.argv[1])
want = [int(x) for x in sys.argv[2].split(",")]
out = io.StringIO()
batches = json.loads((root / ".ua/intermediate/batches.json").read_text(encoding="utf-8"))

for b in batches["batches"]:
    if b["batchIndex"] not in want:
        continue
    res = json.loads(
        (root / (".ua/tmp/ua-file-extract-results-%d.json" % b["batchIndex"])).read_text(encoding="utf-8")
    )
    by = {r["path"]: r for r in res["results"]}
    out.write("##### BATCH %d #####\n" % b["batchIndex"])
    for f in b["files"]:
        r = by.get(f["path"])
        if not r or r.get("language") not in ("python", "c"):
            continue
        all_cls = r.get("classes") or []
        cls = [
            (c["name"], c["endLine"] - c["startLine"] + 1, len(c.get("methods") or []), c.get("bases") or [])
            for c in all_cls
            if len(c.get("methods") or []) >= 2 or (c["endLine"] - c["startLine"] + 1) >= 20
        ]
        fns = [
            (x["name"], x["endLine"] - x["startLine"] + 1)
            for x in r.get("functions") or []
            if (x["endLine"] - x["startLine"] + 1) >= FN_MIN
        ]
        small_cls = [c["name"] for c in all_cls if c["name"] not in [x[0] for x in cls]]
        out.write("FILE %s (%s lines)\n" % (f["path"], r["totalLines"]))
        out.write("   CLASSES: %s\n" % json.dumps(cls, ensure_ascii=False))
        out.write("   FNS: %s\n" % json.dumps(fns, ensure_ascii=False))
        if small_cls:
            out.write("   (below-threshold classes: %s)\n" % ",".join(small_cls))

(root / ".ua/tmp/subs-report.txt").write_text(out.getvalue(), encoding="utf-8")
print("subs-report.txt written")
