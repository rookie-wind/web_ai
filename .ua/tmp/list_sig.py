"""列出批次的显著符号键（与 build-batch.mjs 的过滤规则一致）。

输出 `path::Name<TAB>kind<TAB>start-end<TAB>exported` 便于撰写语义表。
"""

import json
import sys
from pathlib import Path

ROOT = Path("e:/codeGIT/pca-mcp-server")


def main() -> None:
    idx = sys.argv[1]
    extract = json.loads(
        (ROOT / f".ua/tmp/ua-file-extract-results-{idx}.json").read_text("utf-8")
    )
    for res in extract["results"]:
        exported = {e["name"] for e in res.get("exports") or []}
        items = []
        for fn in res.get("functions") or []:
            lines = (fn.get("endLine") or 0) - (fn.get("startLine") or 0) + 1
            if lines >= 10 or fn["name"] in exported:
                items.append((fn["name"], "function", fn, fn["name"] in exported))
        for c in res.get("classes") or []:
            lines = (c.get("endLine") or 0) - (c.get("startLine") or 0) + 1
            if len(c.get("methods") or []) >= 2 or lines >= 20 or c["name"] in exported:
                items.append((c["name"], "class", c, c["name"] in exported))
        if items:
            print(f"# {res['path']}  ({len(items)} significant)")
        for name, kind, node, is_exp in sorted(items, key=lambda x: x[2]["startLine"]):
            print(
                f"{res['path']}::{name}\t{kind}\t"
                f"{node['startLine']}-{node['endLine']}\t"
                f"{'exported' if is_exp else 'private'}"
            )


if __name__ == "__main__":
    main()
