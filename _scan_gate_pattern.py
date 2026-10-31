"""时间线分析：区分 login 僵尸确认（永久无效）与 write 的 TTL 过期反复。"""
import json

AUDIT = r"e:\codeGIT\pca-mcp-server\webchat\webchat_data\gate_audit.jsonl"
LOGIN_TOOLS = {"edge_get_token", "login"}
LOGIN_REASON = "webchat 会话已持凭据，禁用登录类工具"

rows = []
with open(AUDIT, encoding="utf-8") as fp:
    for line in fp:
        line = line.strip()
        if line:
            rows.append(json.loads(line))
rows.sort(key=lambda r: r.get("ts", 0))

# 按 (session, target) 分组打印时间线，标注相邻间隔
from collections import defaultdict

groups = defaultdict(list)
for r in rows:
    groups[(r.get("session_id", "")[:12], r.get("target", ""))].append(r)

print("===== login 类 target 的完整时间线（关键）=====")
for (sid, target), rs in groups.items():
    is_login = target in LOGIN_TOOLS or any(
        r.get("reason") == LOGIN_REASON for r in rs
    )
    if not is_login:
        continue
    print(f"\n[{sid}] target={target}")
    prev = None
    for r in rs:
        gap = "" if prev is None else f"(+{r['ts'] - prev:.0f}s)"
        print(f"  {r.get('decision'):<8} tool={r.get('tool_name','')!r:<18} "
              f"reason={r.get('reason','')}{gap}")
        prev = r["ts"]
    # 结论判定：confirm 之后是否出现过 allow
    decs = [r.get("decision") for r in rs]
    print(f"  => 含 allow? {'allow' in decs} | confirm 次数={decs.count('confirm')} "
          f"| deny 次数={decs.count('deny')}")

print("\n\n===== write 类 target 的 deny→confirm→allow 间隔（判 TTL）=====")
for (sid, target), rs in groups.items():
    is_login = target in LOGIN_TOOLS or any(
        r.get("reason") == LOGIN_REASON for r in rs
    )
    if is_login:
        continue
    decs = [r.get("decision") for r in rs]
    if "deny" in decs and "confirm" in decs:
        print(f"\n[{sid}] target={target}")
        prev = None
        for r in rs:
            gap = "" if prev is None else f"(+{r['ts'] - prev:.0f}s)"
            print(f"  {r.get('decision'):<8} tool={r.get('tool_name','')!r} "
                  f"{gap}")
            prev = r["ts"]
