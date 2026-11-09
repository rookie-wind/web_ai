# 网关扫描脚本（供 python 执行：python3 xlpa-output/scan_gateways.md.py 不适用，请内联执行）
```python
import json, os
src = r"C:\Users\song\AppData\Local\Temp\qoder-mcp-outputs\xlpa_edge_get_device_tree_3b7c22241d4c.txt"
out = r"E:\codeGIT\pca-mcp-server\webchat\webchat_data\workspaces\8280a1280e32bec8331a56b1a9dae553\xlpa-output\gateways.md"
d = json.load(open(src, encoding="utf-8"))

def desc(n):
    return sum(1 + desc(c) for c in n.get("children", []))

rows = []
def walk(n, depth):
    if depth == 0:
        rows.append(n)
    for c in n.get("children", []):
        walk(c, depth + 1)

lines = ["# 20.2.96.2 顶层设备（网关候选）", ""]
for node in d["data"]:
    lines.append(f"- name={node.get('name')} | id={node.get('id')} | identifier={node.get('identifier')} "
                 f"| deviceAddress={node.get('deviceAddress')} | deviceTypeId={node.get('deviceTypeId')} "
                 f"| deviceClassify={node.get('deviceClassify')} | direct_children={len(node.get('children', []))} "
                 f"| total_descendants={desc(node)}")
    for c in node.get("children", []):
        if desc(c) > 0:
            lines.append(f"  - 子树节点 name={c.get('name')} | id={c.get('id')} | deviceTypeId={c.get('deviceTypeId')} "
                         f"| descendants={desc(c)}")
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("top_level", len(d["data"]))
